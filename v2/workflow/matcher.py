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
        if document:
            keys["consignee"] = self._field(document, CanonicalField.CUSTOMER)
            keys["shipper"] = self._field(document, CanonicalField.SUPPLIER)
            keys["amount"] = self._field(document, CanonicalField.AMOUNT)
            keys["booking_no"] = keys.get("booking_no") or self._field(document, CanonicalField.BOOKING_NO)
            keys["shipping_order_no"] = keys.get("shipping_order_no") or self._field(document, CanonicalField.SHIPPING_ORDER_NO)
            keys["vessel_voyage"] = keys.get("vessel_voyage") or self._field(document, CanonicalField.VESSEL_VOYAGE)
        return {key: _normalize_key(key, value) for key, value in keys.items() if value}

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
            elif similarity >= 0.72 and key in {"invoice_no", "bl_no", "booking_no", "shipping_order_no", "container_no"}:
                reasons.append(f"{key}: partial")
                score = max(score, weight * 0.72)

        if left_segment.source_path == right_segment.source_path and score < 0.68:
            score = max(score, 0.68)
            reasons.append("same source file")

        confidence = self._confidence_label(score, 2)
        return MatchDecision(score=score, confidence=confidence, reasons=self._dedupe(reasons))

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
        present = {doc.parsed.document_type for doc in docs if doc.parsed}
        required = EXPORT_REQUIRED_TYPES if direction == "export" else IMPORT_REQUIRED_TYPES
        if direction == "export" and DocumentType.SHIPPING_ORDER in present:
            required = set(required)
            required.discard(DocumentType.BOOKING)
        return [document_type.value for document_type in required if document_type not in present]

    def _field(self, document: ParsedDocument, field: CanonicalField) -> str:
        for parsed in document.fields:
            if parsed.canonical == field:
                return parsed.value
        return ""

    def _first_match(self, text: str, pattern: str) -> str:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = match.group(1).strip()
            if value.upper() not in {"INV", "INVOICE", "NO", "NUMBER", "BL", "B/L"}:
                return value
        return ""

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
    if key in {"invoice_no", "bl_no", "booking_no", "shipping_order_no", "container_no"}:
        value = _repair_ocr_identifier(value)
    if key == "vessel_voyage":
        value = _normalize_vessel_alias(value)
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
