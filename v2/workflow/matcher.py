from __future__ import annotations

import hashlib
import re
from collections import defaultdict

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


class WorkflowMatcher:
    def group_cases(self, segments: list[DocumentSegment], direction: str = "import") -> list[CaseWorkflow]:
        buckets: dict[str, list[DocumentSegment]] = defaultdict(list)
        keys_by_bucket: dict[str, dict[str, str]] = {}
        for segment in segments:
            document = segment.parsed
            keys = self.match_keys(document, segment.text)
            bucket = self._bucket_key(keys, segment)
            buckets[bucket].append(segment)
            keys_by_bucket.setdefault(bucket, {}).update({k: v for k, v in keys.items() if v})

        cases: list[CaseWorkflow] = []
        for bucket, docs in buckets.items():
            case_id = self._case_id(keys_by_bucket.get(bucket, {}), docs)
            missing = self._missing_documents(docs, direction)
            status = CaseStatus.MISSING_DOCUMENTS if missing else CaseStatus.PENDING
            cases.append(
                CaseWorkflow(
                    case_id=case_id,
                    status=status,
                    direction=direction,
                    documents=docs,
                    match_keys=keys_by_bucket.get(bucket, {}),
                    missing_documents=missing,
                )
            )
        return cases

    def match_keys(self, document: ParsedDocument | None, text: str) -> dict[str, str]:
        keys = {
            "invoice_no": self._first_match(text, r"\b(?:invoice|inv)\s*(?:no\.?|#)?\s*[:\-]?\s*([A-Z0-9\-\/]+)"),
            "bl_no": self._first_match(text, r"\b(?:b/l|bl|bill of lading)\s*(?:no\.?|#)?\s*[:\-]?\s*([A-Z0-9\-\/]+)"),
            "booking_no": self._first_match(text, r"\b(?:booking)\s*(?:no\.?|number|#)?\s*[:\-]?\s*([A-Z0-9\-\/]+)"),
            "shipping_order_no": self._first_match(text, r"\b(?:s/o|so|shipping order)\s*(?:no\.?|#)?\s*[:\-]?\s*([A-Z0-9\-\/]+)"),
            "container_no": self._first_match(text, r"\b([A-Z]{4}\d{7})\b"),
            "vessel_voyage": self._first_match(text, r"\b(?:vessel\s*/\s*voyage|vessel voyage)\s*[:\-]?\s*([A-Z0-9 .\-\/]+)"),
            "date": self._first_match(text, r"\b(20\d{2}[-/]\d{1,2}[-/]\d{1,2})\b"),
        }
        if document:
            keys["consignee"] = self._field(document, CanonicalField.CUSTOMER)
            keys["shipper"] = self._field(document, CanonicalField.SUPPLIER)
            keys["amount"] = self._field(document, CanonicalField.AMOUNT)
            keys["booking_no"] = keys.get("booking_no") or self._field(document, CanonicalField.BOOKING_NO)
            keys["shipping_order_no"] = keys.get("shipping_order_no") or self._field(document, CanonicalField.SHIPPING_ORDER_NO)
            keys["vessel_voyage"] = keys.get("vessel_voyage") or self._field(document, CanonicalField.VESSEL_VOYAGE)
        return {key: value for key, value in keys.items() if value}

    def _bucket_key(self, keys: dict[str, str], segment: DocumentSegment) -> str:
        for key in ("booking_no", "shipping_order_no", "bl_no", "container_no", "vessel_voyage", "invoice_no"):
            if keys.get(key):
                return f"{key}:{keys[key].casefold()}"
        return f"source:{segment.source_path.name}"

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
        match = re.search(pattern, text, flags=re.IGNORECASE)
        return match.group(1).strip() if match else ""
