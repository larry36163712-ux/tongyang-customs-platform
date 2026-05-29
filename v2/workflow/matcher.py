from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass

from v2.core.models import CanonicalField, DocumentType, ParsedDocument
from v2.workflow.models import CaseStatus, CaseWorkflow, DocumentSegment


IMPORT_REQUIRED_TYPES = {DocumentType.DS2_DECLARATION, DocumentType.INVOICE, DocumentType.PACKING_LIST, DocumentType.BILL_OF_LADING}
EXPORT_REQUIRED_TYPES = {
    DocumentType.EXPORT_DECLARATION,
    DocumentType.INVOICE,
    DocumentType.PACKING_LIST,
    DocumentType.BILL_OF_LADING,
    DocumentType.BOOKING,
}


KEY_WEIGHTS = {
    "booking_no": 1.0,
    "shipping_order_no": 1.0,
    "bl_no": 0.95,
    "invoice_no": 0.9,
    "container_no": 0.9,
    "container_suffix": 0.72,
    "vessel_voyage": 0.7,
    "amount": 0.55,
    "date": 0.45,
    "consignee": 0.35,
    "shipper": 0.35,
}


@dataclass(frozen=True)
class MatchDecision:
    score: float
    confidence: str
    reasons: list[str]


class WorkflowMatcher:
    def group_cases(self, segments: list[DocumentSegment], direction: str = "import") -> list[CaseWorkflow]:
        segment_keys = [self.match_keys(segment.parsed, segment.text) for segment in segments]
        parent = list(range(len(segments)))

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left: int, right: int) -> None:
            left_root = find(left)
            right_root = find(right)
            if left_root != right_root:
                parent[right_root] = left_root

        for left in range(len(segments)):
            for right in range(left + 1, len(segments)):
                decision = self._match_decision(segment_keys[left], segment_keys[right], segments[left], segments[right])
                if decision.confidence in {"exact_match", "high_confidence", "partial_match"}:
                    union(left, right)

        buckets: dict[int, list[DocumentSegment]] = defaultdict(list)
        keys_by_bucket: dict[int, dict[str, str]] = defaultdict(dict)
        reasons_by_bucket: dict[int, list[str]] = defaultdict(list)
        scores_by_bucket: dict[int, list[float]] = defaultdict(list)
        for index, segment in enumerate(segments):
            bucket = find(index)
            keys = segment_keys[index]
            buckets[bucket].append(segment)
            keys_by_bucket[bucket].update({key: value for key, value in keys.items() if value})

        for bucket, docs in buckets.items():
            indexes = [index for index, segment in enumerate(segments) if segment in docs]
            for left_pos, left in enumerate(indexes):
                for right in indexes[left_pos + 1 :]:
                    decision = self._match_decision(segment_keys[left], segment_keys[right], segments[left], segments[right])
                    scores_by_bucket[bucket].append(decision.score)
                    reasons_by_bucket[bucket].extend(decision.reasons)

        cases: list[CaseWorkflow] = []
        for bucket, docs in buckets.items():
            case_id = self._case_id(keys_by_bucket.get(bucket, {}), docs)
            missing = self._missing_documents(docs, direction)
            candidates = self._fallback_candidates(docs, direction)
            manual_queue = self._manual_confirm_queue(docs, candidates)
            status = CaseStatus.MISSING_DOCUMENTS if missing else CaseStatus.PENDING
            score = max(scores_by_bucket.get(bucket, [0.0]))
            confidence = self._confidence_label(score, len(docs))
            cases.append(
                CaseWorkflow(
                    case_id=case_id,
                    status=status,
                    direction=direction,
                    documents=docs,
                    match_keys=keys_by_bucket.get(bucket, {}),
                    missing_documents=missing,
                    manual_confirm_queue=manual_queue,
                    fallback_document_candidates=candidates,
                    grouping_confidence=confidence,
                    grouping_score=score,
                    grouping_reasons=self._dedupe(reasons_by_bucket.get(bucket, []))[:8],
                    unresolved_fields=self._unresolved_fields(keys_by_bucket.get(bucket, {}), docs),
                )
            )
        return cases

    def match_keys(self, document: ParsedDocument | None, text: str) -> dict[str, str]:
        normalized_text = _normalize_ocr_text(text)
        keys = {
            "invoice_no": self._first_match(normalized_text, r"\b(?:invoice\s*(?:no\.?|number|#)|inv\b\s*(?:no\.?|number|#)?)\s*[:\-]?\s*([A-Z0-9\-\/]+)"),
            "bl_no": self._first_match(normalized_text, r"\b(?:b/l|bl|bill of lading)\s*(?:no\.?|number|#)?\s*[:\-]?\s*([A-Z0-9\-\/]+)"),
            "booking_no": self._first_match(normalized_text, r"\b(?:booking|bkg)\s*(?:no\.?|number|#)?\s*[:\-]?\s*([A-Z0-9\-\/]+)"),
            "shipping_order_no": self._first_match(normalized_text, r"\b(?:s/o|so|shipping order)\s*(?:no\.?|number|#)?\s*[:\-]?\s*([A-Z0-9\-\/]+)"),
            "container_no": self._first_match(normalized_text, r"\b([A-Z]{4}\s*\d{7})\b"),
            "vessel_voyage": self._first_match(normalized_text, r"\b(?:vessel\s*/\s*voyage|vessel voyage|vsl\s*/?\s*voy)\s*[:\-]?\s*([A-Z0-9 .\-\/]+)"),
            "date": self._first_match(normalized_text, r"\b(20\d{2}[-/]\d{1,2}[-/]\d{1,2})\b"),
        }
        text_vessel = self._vessel_voyage_from_text(normalized_text)
        if text_vessel and (not keys.get("vessel_voyage") or self._is_generic_vessel_value(keys["vessel_voyage"])):
            keys["vessel_voyage"] = text_vessel
        if not keys.get("container_no"):
            keys["container_no"] = self._container_from_text(normalized_text)
        keys["container_suffix"] = self._container_suffix(keys.get("container_no", "")) or self._container_suffix_from_text(normalized_text)
        if document:
            keys["consignee"] = self._field(document, CanonicalField.CUSTOMER)
            keys["shipper"] = self._field(document, CanonicalField.SUPPLIER)
            keys["amount"] = self._field(document, CanonicalField.AMOUNT)
            keys["invoice_no"] = keys.get("invoice_no") or self._field(document, CanonicalField.INVOICE_NO)
            keys["bl_no"] = keys.get("bl_no") or self._field(document, CanonicalField.BL_NO)
            keys["booking_no"] = keys.get("booking_no") or self._field(document, CanonicalField.BOOKING_NO)
            keys["shipping_order_no"] = keys.get("shipping_order_no") or self._field(document, CanonicalField.SHIPPING_ORDER_NO)
            parsed_vessel = self._field(document, CanonicalField.VESSEL_VOYAGE) or self._field(document, CanonicalField.VOYAGE)
            keys["vessel_voyage"] = keys.get("vessel_voyage") or parsed_vessel
            keys["container_no"] = keys.get("container_no") or self._field(document, CanonicalField.CONTAINER_NO)
            keys["container_suffix"] = keys.get("container_suffix") or self._container_suffix(keys.get("container_no", ""))
        normalized = {key: _normalize_key(key, value) for key, value in keys.items() if value}
        return {key: value for key, value in normalized.items() if self._valid_match_key(key, value)}

    def _bucket_key(self, keys: dict[str, str], segment: DocumentSegment) -> str:
        for key in ("booking_no", "shipping_order_no", "bl_no", "container_no", "vessel_voyage", "invoice_no"):
            if keys.get(key):
                return f"{key}:{keys[key].casefold()}"
        return f"source:{segment.source_path.name}"

    def _match_decision(
        self,
        left: dict[str, str],
        right: dict[str, str],
        left_segment: DocumentSegment,
        right_segment: DocumentSegment,
    ) -> MatchDecision:
        reasons: list[str] = []
        if self._source_context_conflict(left_segment, right_segment):
            return MatchDecision(score=0.0, confidence="pending_review", reasons=["source anti-mix guard"])
        if self._anti_mix_conflict(left, right):
            return MatchDecision(score=0.0, confidence="pending_review", reasons=["anti-mix guard"])
        score = 0.0
        for key, weight in KEY_WEIGHTS.items():
            left_value = left.get(key, "")
            right_value = right.get(key, "")
            if not left_value or not right_value:
                continue
            similarity = _key_similarity(left_value, right_value)
            if similarity >= 1.0:
                reasons.append(f"{key}: exact")
                score = max(score, weight)
            elif similarity >= 0.88:
                reasons.append(f"{key}: OCR-normalized")
                score = max(score, weight * 0.92)
            elif similarity >= 0.72 and key in {"invoice_no", "bl_no", "booking_no", "shipping_order_no", "container_no", "container_suffix"}:
                reasons.append(f"{key}: partial")
                score = max(score, weight * 0.72)

        if left_segment.source_path == right_segment.source_path and score < 0.68:
            score = max(score, 0.68)
            reasons.append("same source file")

        if score < 0.6 and self._bridge_context_match(left, right, left_segment, right_segment):
            score = max(score, 0.64)
            reasons.append("shipment bridge candidate")

        if (
            score < 0.6
            and self._complementary_customs_documents(left_segment, right_segment)
            and (self._has_soft_context_overlap(left, right) or self._lacks_conflicting_context(left, right))
        ):
            score = max(score, 0.62)
            reasons.append("customs document set candidate")

        confidence = self._confidence_label(score, 2)
        return MatchDecision(score=score, confidence=confidence, reasons=self._dedupe(reasons))

    def _anti_mix_conflict(self, left: dict[str, str], right: dict[str, str]) -> bool:
        hard_keys = ("invoice_no", "bl_no", "booking_no", "shipping_order_no", "container_no")
        for key in hard_keys:
            left_value = left.get(key, "")
            right_value = right.get(key, "")
            if left_value and right_value and _key_similarity(left_value, right_value) < 0.72:
                return True
        for key in ("consignee", "shipper"):
            left_value = left.get(key, "")
            right_value = right.get(key, "")
            if left_value and right_value and _key_similarity(left_value, right_value) < 0.58:
                return True
        return False

    def _bridge_context_match(
        self,
        left: dict[str, str],
        right: dict[str, str],
        left_segment: DocumentSegment,
        right_segment: DocumentSegment,
    ) -> bool:
        left_type = self._effective_document_type(left_segment)
        right_type = self._effective_document_type(right_segment)
        bridge_types = {DocumentType.BILL_OF_LADING, DocumentType.ARRIVAL_NOTICE, DocumentType.DELIVERY_ORDER, DocumentType.MANIFEST}
        core_types = {DocumentType.INVOICE, DocumentType.PACKING_LIST, DocumentType.DS2_DECLARATION, DocumentType.EXPORT_DECLARATION}
        if not ((left_type in bridge_types and right_type in core_types) or (right_type in bridge_types and left_type in core_types)):
            return False
        container_overlap = self._context_similarity(left, right, "container_no", 0.72) or self._context_similarity(left, right, "container_suffix", 0.92)
        vessel_overlap = self._context_similarity(left, right, "vessel_voyage", 0.78)
        party_overlap = self._context_similarity(left, right, "consignee", 0.62) or self._context_similarity(left, right, "shipper", 0.62)
        reference_overlap = any(self._context_similarity(left, right, key, 0.72) for key in ("booking_no", "bl_no", "invoice_no"))
        return bool(reference_overlap or container_overlap or (vessel_overlap and (container_overlap or party_overlap)))

    def _context_similarity(self, left: dict[str, str], right: dict[str, str], key: str, threshold: float) -> bool:
        left_value = left.get(key, "")
        right_value = right.get(key, "")
        return bool(left_value and right_value and _key_similarity(left_value, right_value) >= threshold)

    def _has_soft_context_overlap(self, left: dict[str, str], right: dict[str, str]) -> bool:
        for key in ("consignee", "shipper", "vessel_voyage", "date"):
            left_value = left.get(key, "")
            right_value = right.get(key, "")
            if left_value and right_value and _key_similarity(left_value, right_value) >= 0.72:
                return True
        return False

    def _lacks_conflicting_context(self, left: dict[str, str], right: dict[str, str]) -> bool:
        context_keys = (
            "invoice_no",
            "bl_no",
            "booking_no",
            "shipping_order_no",
            "container_no",
            "container_suffix",
            "consignee",
            "shipper",
            "vessel_voyage",
            "date",
        )
        return not any(left.get(key) and right.get(key) for key in context_keys)

    def _confidence_label(self, score: float, document_count: int) -> str:
        if document_count <= 1 and score <= 0:
            return "pending_review"
        if score >= 0.95:
            return "exact_match"
        if score >= 0.8:
            return "high_confidence"
        if score >= 0.6:
            return "partial_match"
        if score > 0:
            return "low_confidence"
        return "pending_review"

    def _case_id(self, keys: dict[str, str], docs: list[DocumentSegment]) -> str:
        label = keys.get("booking_no") or keys.get("shipping_order_no") or keys.get("bl_no") or keys.get("invoice_no") or keys.get("container_no")
        if label:
            return label
        digest = hashlib.sha1("|".join(doc.source_name for doc in docs).encode("utf-8", errors="ignore")).hexdigest()[:8]
        return f"CASE-{digest.upper()}"

    def _missing_documents(self, docs: list[DocumentSegment], direction: str) -> list[str]:
        present = {self._effective_document_type(doc) for doc in docs if self._effective_document_type(doc) != DocumentType.UNKNOWN}
        required = EXPORT_REQUIRED_TYPES if direction == "export" else IMPORT_REQUIRED_TYPES
        if direction == "export" and DocumentType.SHIPPING_ORDER in present:
            required = set(required)
            required.discard(DocumentType.BOOKING)
        candidate_present = {
            candidate.document_type
            for doc in docs
            for candidate in doc.candidates
            if candidate.document_type != DocumentType.UNKNOWN
            and candidate.confidence >= self._candidate_missing_threshold(candidate.document_type)
        }
        return [document_type.value for document_type in required if document_type not in present and document_type not in candidate_present]

    def _fallback_candidates(self, docs: list[DocumentSegment], direction: str) -> dict[str, list[str]]:
        required = EXPORT_REQUIRED_TYPES if direction == "export" else IMPORT_REQUIRED_TYPES
        result: dict[str, list[str]] = {}
        for document_type in required:
            names = [
                f"{doc.source_name} ({int(candidate.confidence * 100)}%)"
                for doc in docs
                for candidate in doc.candidates
                if candidate.document_type == document_type
                and candidate.confidence >= self._candidate_missing_threshold(document_type)
                and candidate.needs_manual_confirm
            ]
            if names:
                result[document_type.value] = names
        return result

    def _manual_confirm_queue(self, docs: list[DocumentSegment], candidates: dict[str, list[str]]) -> list[str]:
        queue: list[str] = []
        for document_label, names in candidates.items():
            queue.append(f"待人工確認 {document_label}: {', '.join(names)}")
        for doc in docs:
            if doc.manual_confirm_reason:
                best = doc.candidates[0] if doc.candidates else None
                label = best.document_type.value if best else doc.detected_type.value
                queue.append(f"待人工確認 {label}: {doc.source_name}，{doc.manual_confirm_reason}")
        return self._dedupe(queue)

    def _effective_document_type(self, doc: DocumentSegment) -> DocumentType:
        if doc.parsed and doc.parsed.document_type != DocumentType.UNKNOWN:
            return doc.parsed.document_type
        if doc.detected_type != DocumentType.UNKNOWN:
            return doc.detected_type
        if doc.candidates:
            best = doc.candidates[0]
            if best.confidence >= self._candidate_missing_threshold(best.document_type):
                return best.document_type
        return DocumentType.UNKNOWN

    def _candidate_missing_threshold(self, document_type: DocumentType) -> float:
        if document_type in {DocumentType.DS2_DECLARATION, DocumentType.EXPORT_DECLARATION}:
            return 0.30
        if document_type in {
            DocumentType.ARRIVAL_NOTICE,
            DocumentType.DELIVERY_ORDER,
            DocumentType.TAX_SHEET,
            DocumentType.CLEARANCE_LIST,
            DocumentType.MATERIAL_CLEARANCE,
            DocumentType.DRAWBACK_CLEARANCE,
        }:
            return 0.36
        return 0.42

    def _complementary_customs_documents(self, left: DocumentSegment, right: DocumentSegment) -> bool:
        left_type = self._effective_document_type(left)
        right_type = self._effective_document_type(right)
        useful = {
            DocumentType.INVOICE,
            DocumentType.PACKING_LIST,
            DocumentType.BILL_OF_LADING,
            DocumentType.MANIFEST,
            DocumentType.DS2_DECLARATION,
            DocumentType.EXPORT_DECLARATION,
            DocumentType.BOOKING,
            DocumentType.SHIPPING_ORDER,
            DocumentType.DELIVERY_ORDER,
        }
        return left_type in useful and right_type in useful and left_type != right_type

    def _field(self, document: ParsedDocument, field: CanonicalField) -> str:
        for parsed in document.fields:
            if parsed.canonical == field:
                return parsed.value
        return ""

    def _first_match(self, text: str, pattern: str) -> str:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = match.group(1).strip()
            if value.upper() not in {"INV", "INVOICE", "NO", "NUMBER", "BL", "B/L", "CONFIRMATION", "SHIPPING", "ORDER"}:
                return value
        return ""

    def _valid_match_key(self, key: str, value: str) -> bool:
        if not value:
            return False
        generic = {"TO", "NG", "L", "LID", "SHIPPER", "CONSIGNEE", "NOTIFY", "ADDRESS", "PRECARRYING", "ONCARRYING"}
        if value in generic:
            return False
        if key in {"invoice_no", "bl_no", "booking_no", "shipping_order_no"}:
            return len(value) >= 4 and not value.isalpha()
        if key == "container_no":
            return len(value) >= 8 and bool(re.search(r"[0-9]", value))
        if key == "container_suffix":
            return len(value) >= 6 and value.isdigit()
        if key == "vessel_voyage":
            return len(value) >= 6 and not self._is_generic_vessel_value(value)
        if key == "amount":
            return any(char.isdigit() for char in value)
        return True

    def _source_context_conflict(self, left: DocumentSegment, right: DocumentSegment) -> bool:
        if left.source_path == right.source_path:
            return False
        left_hint = self._source_customer_hint(left)
        right_hint = self._source_customer_hint(right)
        return bool(left_hint and right_hint and left_hint != right_hint)

    def _source_customer_hint(self, segment: DocumentSegment) -> str:
        stem = segment.source_path.stem
        stem = re.sub(r"^\d+[_\-\s]*", "", stem)
        stem = re.sub(
            r"(DS2|INV|IV|PKG|PL|B_L|BL|B/L|報單|發票|包裝單|裝箱單|提單|艙單|倉單|到貨|D[/-]?O|SO|BOOKING|PDF|\d+)",
            "",
            stem,
            flags=re.IGNORECASE,
        )
        cjk = "".join(re.findall(r"[\u4e00-\u9fff]+", stem))
        return cjk if len(cjk) >= 2 else ""

    def _is_generic_vessel_value(self, value: str) -> bool:
        normalized = _normalize_key("vessel_voyage", value)
        return normalized in {"PRECARRYING", "ONCARRYING", "VESSEL", "VOYAGE"}

    def _vessel_voyage_from_text(self, text: str) -> str:
        match = re.search(r"\b(?:WAN\s+)?HAI\s+([0-9A-Z]{2,4})\s+([A-Z0-9]{2,5})\b", text, flags=re.IGNORECASE)
        if match:
            voyage = _repair_ocr_identifier(match.group(2).upper())
            return f"WAN HAI {match.group(1)} {voyage}"
        return ""

    def _container_from_text(self, text: str) -> str:
        patterns = (
            r"\b([A-Z]{4})\s*([0-9?OILSG]{2,4})\s*([0-9?OILSG]{2,4})\b",
            r"\b([A-Z]{2,4}SU)\s*([0-9?OILSG]{2,5})\s*([0-9?OILSG]{2,5})\b",
        )
        for pattern in patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                owner = match.group(1).upper()
                number = self._repair_container_digits(match.group(2) + match.group(3))
                if len(number) >= 7:
                    return f"{owner}{number[-7:]}"
        return ""

    def _container_suffix_from_text(self, text: str) -> str:
        container = self._container_from_text(text)
        if container:
            return self._container_suffix(container)
        for match in re.finditer(r"(?:CONTAINER|CONT|SEAL|SEA-L)[^A-Z0-9]{0,8}([0-9?OILSG]{6,8})", text, flags=re.IGNORECASE):
            suffix = self._repair_container_digits(match.group(1))
            if len(suffix) >= 6:
                return suffix[-7:]
        return ""

    def _container_suffix(self, value: str) -> str:
        digits = "".join(char for char in _repair_ocr_identifier(value) if char.isdigit())
        return digits[-7:] if len(digits) >= 7 else ""

    def _repair_container_digits(self, value: str) -> str:
        table = str.maketrans({"?": "7", "O": "0", "I": "1", "L": "1", "S": "5", "G": "8"})
        return re.sub(r"[^0-9]", "", value.upper().translate(table))

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if value and value not in seen:
                seen.add(value)
                result.append(value)
        return result

    def _unresolved_fields(self, keys: dict[str, str], docs: list[DocumentSegment]) -> list[str]:
        required = ["invoice_no", "bl_no", "booking_no", "container_no"]
        unresolved = [key for key in required if not keys.get(key)]
        if len(docs) == 1:
            unresolved.append("cross_document_match")
        return unresolved


def _normalize_ocr_text(text: str) -> str:
    normalized = text.replace("\u3000", " ")
    normalized = normalized.replace("：", ":").replace("－", "-").replace("–", "-").replace("—", "-")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\s*/\s*", "/", normalized)
    normalized = re.sub(r"\s*-\s*", "-", normalized)
    return normalized.casefold().upper()


def _normalize_key(key: str, value: str) -> str:
    value = _normalize_ocr_text(value)
    value = re.sub(r"[^A-Z0-9/\-.]", "", value)
    if key in {"invoice_no", "bl_no", "booking_no", "shipping_order_no", "container_no", "container_suffix"}:
        value = _repair_ocr_identifier(value)
    if key == "vessel_voyage":
        value = _normalize_vessel_alias(_repair_ocr_identifier(value))
    return value


def _repair_ocr_identifier(value: str) -> str:
    chars = list(value)
    for index, char in enumerate(chars):
        before = chars[index - 1] if index > 0 else ""
        after = chars[index + 1] if index + 1 < len(chars) else ""
        near_digit = before.isdigit() or after.isdigit()
        if near_digit and char == "O":
            chars[index] = "0"
        elif near_digit and char in {"I", "L"}:
            chars[index] = "1"
    return "".join(chars)


def _normalize_vessel_alias(value: str) -> str:
    aliases = {
        "VOYAGE": "VOY",
        "VOY.": "VOY",
        "V.": "VOY",
        "VSL": "VESSEL",
    }
    for source, target in aliases.items():
        value = value.replace(source, target)
    return value


def _key_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    left_variants = _identifier_variants(left)
    right_variants = _identifier_variants(right)
    if left_variants & right_variants:
        return 0.92
    shorter, longer = sorted((left, right), key=len)
    if len(shorter) >= 5 and shorter in longer:
        return len(shorter) / len(longer)
    return _sequence_similarity(left, right)


def _identifier_variants(value: str) -> set[str]:
    variants = {value}
    variants.add(value.replace("O", "0"))
    variants.add(value.replace("0", "O"))
    variants.add(value.replace("I", "1").replace("L", "1"))
    variants.add(value.replace("1", "I"))
    return variants


def _sequence_similarity(left: str, right: str) -> float:
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, 1):
        current = [i]
        for j, right_char in enumerate(right, 1):
            cost = 0 if left_char == right_char else 1
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + cost))
        previous = current
    distance = previous[-1]
    return 1.0 - (distance / max(len(left), len(right), 1))
