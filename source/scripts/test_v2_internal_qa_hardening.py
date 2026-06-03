from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from v2.core.models import CanonicalField, DocumentType, ParsedDocument, ParsedField
from v2.workflow.matcher import WorkflowMatcher
from v2.workflow.models import DocumentSegment


class ParserResultStub:
    def __init__(self, document: ParsedDocument) -> None:
        self.document = document
        self.confidence = 0.9
        self.parser_name = "test"
        self.debug = {}


def _doc(document_type: DocumentType, source: str, fields: list[ParsedField]) -> DocumentSegment:
    parsed = ParsedDocument(document_type, "", "", "test", source, fields)
    text = "\n".join(f"{field.source_label}: {field.value}" for field in fields)
    segment = DocumentSegment(
        source_path=Path(source),
        source_name=source,
        page_start=1,
        page_end=1,
        text=text,
        detected_type=document_type,
        confidence=0.9,
        document_confidence=0.9,
    )
    segment.parser_result = ParserResultStub(parsed)  # type: ignore[assignment]
    return segment


def _field(field: CanonicalField, label: str, value: str) -> ParsedField:
    return ParsedField(field, label, value, 0.9)


def main() -> None:
    matcher = WorkflowMatcher()
    tong_yang_segments = [
        _doc(
            DocumentType.INVOICE,
            "台暉IV.pdf",
            [
                _field(CanonicalField.INVOICE_NO, "Invoice No", "TH-INV-001"),
                _field(CanonicalField.VESSEL_VOYAGE, "Vessel Voyage", "WAN HAI 293"),
                _field(CanonicalField.AMOUNT, "Amount", "1000"),
            ],
        ),
        _doc(
            DocumentType.PACKING_LIST,
            "台暉PL.pdf",
            [
                _field(CanonicalField.INVOICE_NO, "Invoice No", "TH-INV-001"),
                _field(CanonicalField.PACKAGE_COUNT, "Package", "97 BALES"),
            ],
        ),
        _doc(
            DocumentType.DS2_DECLARATION,
            "台暉報單.pdf",
            [
                _field(CanonicalField.INVOICE_NO, "Invoice No", "TH-INV-001"),
                _field(CanonicalField.VESSEL_VOYAGE, "Vessel Voyage", "WAN HAI 293"),
                _field(CanonicalField.HS_CODE, "HS Code", "4707.20"),
            ],
        ),
        _doc(
            DocumentType.BILL_OF_LADING,
            "台暉BL.pdf",
            [
                _field(CanonicalField.VESSEL_VOYAGE, "Vessel Voyage", "WAN HAI 293"),
                _field(CanonicalField.BL_NO, "B/L No", "BL-TONG-YANG-001"),
            ],
        ),
    ]
    cases = matcher.group_cases(tong_yang_segments, direction="import")
    if len(cases) != 1:
        raise RuntimeError(f"safe bridge should keep same-customer vessel-linked documents together, got {len(cases)}")

    mixed_segments = tong_yang_segments + [
        _doc(
            DocumentType.INVOICE,
            "詩肯IV.pdf",
            [
                _field(CanonicalField.INVOICE_NO, "Invoice No", "SK-INV-999"),
                _field(CanonicalField.VESSEL_VOYAGE, "Vessel Voyage", "WAN HAI 293"),
                _field(CanonicalField.AMOUNT, "Amount", "1000"),
            ],
        )
    ]
    mixed_cases = matcher.group_cases(mixed_segments, direction="import")
    if len(mixed_cases) < 2:
        raise RuntimeError("anti-mix guard should not merge different customer filename contexts")

    print("internal_qa_hardening=ok")


if __name__ == "__main__":
    main()
