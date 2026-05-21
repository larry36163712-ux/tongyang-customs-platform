from __future__ import annotations

import re

from v2.core.models import CanonicalField, DocumentType, ParsedDocument, ParsedField
from v2.parsers.base import ParserContext, ParserResult


BOOKING_TERMS = ("booking", "booking confirmation", "shipping order", "s/o", "訂艙", "定倉")

FIELD_PATTERNS: tuple[tuple[CanonicalField, tuple[str, ...]], ...] = (
    (CanonicalField.BOOKING_NO, (r"booking\s*(?:no\.?|number|#)?\s*[:\-]?\s*([A-Z0-9\-\/]+)", r"訂艙號碼\s*[:：]?\s*([A-Z0-9\-\/]+)", r"定倉號碼\s*[:：]?\s*([A-Z0-9\-\/]+)")),
    (CanonicalField.SHIPPING_ORDER_NO, (r"(?:s/o|so|shipping order)\s*(?:no\.?|#)?\s*[:\-]?\s*([A-Z0-9\-\/]+)",)),
    (CanonicalField.VESSEL, (r"vessel(?: name)?\s*[:\-]?\s*([A-Z0-9 .\-]+)", r"船名\s*[:：]?\s*([A-Z0-9 .\-]+)")),
    (CanonicalField.VOYAGE, (r"(?:voyage|voy\.?)\s*[:\-]?\s*([A-Z0-9 .\-]+)", r"航次\s*[:：]?\s*([A-Z0-9 .\-]+)")),
    (CanonicalField.VESSEL_VOYAGE, (r"vessel\s*/\s*voyage\s*[:\-]?\s*([A-Z0-9 .\-\/]+)", r"船名航次\s*[:：]?\s*([A-Z0-9 .\-\/]+)")),
    (CanonicalField.POL, (r"(?:pol|port of loading)\s*[:\-]?\s*([A-Z0-9 .\-]+)", r"起運港\s*[:：]?\s*([A-Z0-9 .\-]+)")),
    (CanonicalField.POD, (r"(?:pod|port of discharge)\s*[:\-]?\s*([A-Z0-9 .\-]+)", r"目的港\s*[:：]?\s*([A-Z0-9 .\-]+)")),
    (CanonicalField.ETD, (r"etd\s*[:\-]?\s*([0-9]{4}[-/][0-9]{1,2}[-/][0-9]{1,2}|[0-9]{1,2}[-/][0-9]{1,2}[-/][0-9]{2,4})",)),
    (CanonicalField.ETA, (r"eta\s*[:\-]?\s*([0-9]{4}[-/][0-9]{1,2}[-/][0-9]{1,2}|[0-9]{1,2}[-/][0-9]{1,2}[-/][0-9]{2,4})",)),
    (CanonicalField.CUSTOMER, (r"consignee\s*[:\-]?\s*(.+)",)),
    (CanonicalField.SUPPLIER, (r"shipper\s*[:\-]?\s*(.+)",)),
    (CanonicalField.NOTIFY, (r"notify(?: party)?\s*[:\-]?\s*(.+)",)),
    (CanonicalField.CONTAINER_NO, (r"\b([A-Z]{4}\d{7})\b", r"container\s*(?:no\.?)?\s*[:\-]?\s*([A-Z]{4}\d{7})")),
    (CanonicalField.SEAL_NO, (r"seal\s*(?:no\.?)?\s*[:\-]?\s*([A-Z0-9\-\/]+)",)),
    (CanonicalField.PACKAGE_COUNT, (r"(?:package|packages|pkg|ctn)\s*[:\-]?\s*([0-9,]+)",)),
    (CanonicalField.GROSS_WEIGHT, (r"(?:gross weight|g\.?w\.?)\s*[:\-]?\s*([0-9,.]+ ?(?:kg|kgs)?)",)),
    (CanonicalField.CBM, (r"(?:cbm|measurement|m3)\s*[:\-]?\s*([0-9,.]+)",)),
    (CanonicalField.CARRIER, (r"carrier\s*[:\-]?\s*(.+)",)),
    (CanonicalField.FORWARDER, (r"forwarder\s*[:\-]?\s*(.+)",)),
)


class BookingParser:
    name = "booking-so-parser"

    def supports(self, text: str, context: ParserContext) -> bool:
        normalized = text.casefold()
        return any(term in normalized for term in BOOKING_TERMS)

    def parse(self, text: str, context: ParserContext) -> ParserResult:
        normalized = text.casefold()
        if "booking confirmation" in normalized:
            document_type = DocumentType.BOOKING_CONFIRMATION
        elif "shipping order" in normalized or "s/o" in normalized:
            document_type = DocumentType.SHIPPING_ORDER
        else:
            document_type = DocumentType.BOOKING

        fields: list[ParsedField] = []
        seen: set[CanonicalField] = set()
        for canonical, patterns in FIELD_PATTERNS:
            for pattern in patterns:
                match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
                if not match:
                    continue
                value = match.group(1).strip(" \t:-：")
                if value and canonical not in seen:
                    fields.append(ParsedField(canonical, canonical.value, value, 0.86, match.group(0)))
                    seen.add(canonical)
                break

        missing = [
            field.value
            for field in (
                CanonicalField.BOOKING_NO,
                CanonicalField.VESSEL,
                CanonicalField.VOYAGE,
                CanonicalField.POL,
                CanonicalField.POD,
                CanonicalField.ETD,
                CanonicalField.CONTAINER_NO,
            )
            if field not in seen
        ]
        document = ParsedDocument(
            document_type=document_type,
            customer="",
            supplier="",
            template_id=self.name,
            source_name=context.source_name,
            fields=fields,
            warnings=[f"missing booking fields: {', '.join(missing)}"] if missing else [],
            raw_metadata={"parser": self.name, "missing_fields": missing},
        )
        confidence = 0.55 + min(0.4, len(fields) * 0.04)
        return ParserResult(document, min(confidence, 0.95), self.name, {"missing_fields": missing, "field_count": len(fields)})
