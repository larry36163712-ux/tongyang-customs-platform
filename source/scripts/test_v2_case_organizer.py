from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from v2.core.models import CanonicalField, DocumentType, ParsedDocument, ParsedField
from v2.workflow.engine import DocumentWorkflowEngine
from v2.workflow.models import CaseStatus, CaseWorkflow, DocumentSegment
from v2.workflow.organizer import CustomsCaseOrganizer, CustomsSynonymDictionary


def _write(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    root = Path(tempfile.gettempdir()) / "ai_customs_case_organizer_test"
    root.mkdir(parents=True, exist_ok=True)

    invoice = root / "invoice.txt"
    packing = root / "packing.txt"
    arrival = root / "arrival_notice.txt"
    manifest = root / "manifest.txt"
    declaration = root / "ds2.txt"

    _write(
        invoice,
        [
            "Commercial Invoice",
            "Invoice No: INV-CASE-001",
            "B/L No: BL-CASE-001",
            "Consignee: TONG YANG CUSTOMER",
            "Shipper: TEST SUPPLIER",
            "Description: WOODEN CHAIR",
            "Package: 97 BALES",
            "Quantity: 97 PCS",
            "Unit: PCE",
            "Amount: USD 30277.35",
            "FOB: USD 30000.00",
            "CIF: USD 30277.35",
            "Currency: USD",
            "Incoterm: CIF",
        ],
    )
    _write(
        packing,
        [
            "Packing List",
            "Invoice No: INV-CASE-001",
            "B/L No: BL-CASE-001",
            "Package: 97 BALES",
            "Quantity: 97 PCE",
            "Gross Weight: 99,270 KGS",
            "Net Weight: 98,000 KGS",
            "CBM: 120.5",
        ],
    )
    _write(
        arrival,
        [
            "Arrival Notice",
            "B/L No: BL-CASE-001",
            "Vessel: WAN HAI",
            "Voyage: 293",
            "ETA: 2026/05/22",
            "Port of Discharge: KAOHSIUNG",
            "Container: TLLU1234567",
            "Seal: SEAL123",
        ],
    )
    _write(
        manifest,
        [
            "Cargo Manifest",
            "Manifest No: MF-CASE-001",
            "B/L No: BL-CASE-001",
            "Vessel Voyage: WAN HAI 293",
            "Container No: TLLU1234567",
            "Seal No: SEAL123",
            "Package: 97 BALES",
            "Gross Weight: 99,270 KGS",
            "Description: WOODEN CHAIR",
        ],
    )
    _write(
        declaration,
        [
            "海關進口報單 DS2",
            "報單號碼: AA1234567890",
            "B/L No: BL-CASE-001",
            "船名航次: WAN HAI 293",
            "Package: 97 BLE",
            "Quantity: 97 PCS",
            "毛重: 99,270 KG",
            "稅則: 4707.20",
            "統計方式: 02",
            "完稅價格 CIF: USD 30277.35",
            "稅率: 5%",
            "稅額: 1514",
            "推貿費: 12",
            "營業稅: 1589",
            "輸入規定: MP1",
            "MP1: Y",
            "BSMI: M3",
            "商檢: 需檢驗",
        ],
    )

    engine = DocumentWorkflowEngine(cache_root=root / "cache", rules_path=root / "config/customs_rules.json")
    result = engine.process_paths([str(invoice), str(packing), str(arrival), str(manifest), str(declaration)])
    if not result.cases:
        raise RuntimeError("case organizer test produced no workflow case")

    case = result.cases[0]
    organizer = case.case_organizer
    if organizer is None:
        raise RuntimeError("case organizer result was not attached to workflow case")
    if not organizer.shipment_summary:
        raise RuntimeError("shipment summary was empty")
    if not organizer.cargo_summary:
        raise RuntimeError("cargo summary was empty")
    if not organizer.customs_summary:
        raise RuntimeError("customs summary was empty")
    if not organizer.manifest_summary:
        raise RuntimeError("manifest summary was empty")

    report = organizer.human_text()
    detailed_report = organizer.human_text(detail=True)
    required_sections = ["一、案件摘要", "三、船務資料", "四、貨物資料", "五、金額 / 報關資料", "八、風險提醒"]
    for section in required_sections:
        if section not in report:
            raise RuntimeError(f"case organizer report missing section: {section}")
    for phrase in ["97 BALES", "PCE 視為 PCS", "推貿費", "營業稅", "輸入規定", "MP1", "BSMI", "商檢"]:
        if phrase not in report:
            raise RuntimeError(f"case organizer report missing customs phrase: {phrase}")
    if "艙單佐證" not in report:
        raise RuntimeError("case organizer report missing manifest evidence section")
    if "艙單已提供" not in report:
        raise RuntimeError("case organizer report missing manifest risk note")
    for forbidden in ["bl_no: exact", "invoice_no", "declaration_no", "closing_date", "WARNING_GLOBAL", "parser"]:
        if forbidden in report:
            raise RuntimeError(f"case organizer report leaked internal wording: {forbidden}")
    if "來源：" in report:
        raise RuntimeError("case organizer default report should hide source file names")
    if ".txt" in report:
        raise RuntimeError("case organizer default report should hide raw source filenames")
    if "來源：" not in detailed_report:
        raise RuntimeError("case organizer detail report should show source file names")
    if "航次待確認" not in report:
        raise RuntimeError("vessel/voyage partial match should be shown as pending confirmation")
    if "船名航次 不一致" in report:
        raise RuntimeError("vessel/voyage partial match should not be shown as direct mismatch")

    dictionary = CustomsSynonymDictionary()
    same_package, _ = dictionary.equivalent(CanonicalField.PACKAGE_COUNT, "97 BLE", "97 BALES")
    same_unit, _ = dictionary.equivalent(CanonicalField.UNIT, "PCS", "PCE")
    if not same_package:
        raise RuntimeError("BLE / BALES synonym rule failed")
    if not same_unit:
        raise RuntimeError("PCS / PCE synonym rule failed")

    arrival_doc = ParsedDocument(
        document_type=DocumentType.ARRIVAL_NOTICE,
        customer="",
        supplier="",
        template_id="test",
        source_name="arrival_notice_only.txt",
        fields=[
            ParsedField(CanonicalField.BL_NO, "B/L No", "BL-CASE-002", 0.9),
            ParsedField(CanonicalField.VESSEL, "Vessel", "WAN HAI", 0.9),
            ParsedField(CanonicalField.ETA, "ETA", "2026/05/22", 0.9),
        ],
    )
    arrival_segment = DocumentSegment(
        source_path=root / "arrival_notice_only.txt",
        source_name="arrival_notice_only.txt",
        page_start=1,
        page_end=1,
        text="Arrival Notice\nB/L No: BL-CASE-002\nVessel: WAN HAI\nETA: 2026/05/22",
        detected_type=DocumentType.ARRIVAL_NOTICE,
        confidence=0.9,
    )
    arrival_segment.parser_result = type(
        "ParserResultStub",
        (),
        {"document": arrival_doc, "confidence": 0.9, "parser_name": "test", "debug": {}},
    )()
    arrival_case = CaseWorkflow(
        case_id="BL-CASE-002",
        status=CaseStatus.MISSING_DOCUMENTS,
        documents=[arrival_segment],
        match_keys={"bl_no": "BL-CASE-002"},
        missing_documents=[DocumentType.BILL_OF_LADING.value],
    )
    arrival_result = CustomsCaseOrganizer().organize_case(arrival_case)
    arrival_report = arrival_result.human_text()
    if "未取得正式 B/L，目前以到貨通知作為船務佐證" not in arrival_report:
        raise RuntimeError("Arrival Notice substitute B/L rule failed")

    print(
        "case organizer ok: "
        f"cases={len(result.cases)} "
        f"shipment_fields={len(organizer.shipment_summary)} "
        f"cargo_fields={len(organizer.cargo_summary)} "
        f"customs_fields={len(organizer.customs_summary)} "
        f"risks={len(organizer.risk_notes)}"
    )


if __name__ == "__main__":
    main()
