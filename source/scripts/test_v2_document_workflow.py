from __future__ import annotations

import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from v2.workflow.engine import DocumentWorkflowEngine


def main() -> None:
    root = Path(tempfile.gettempdir()) / "ai_customs_workflow_test"
    root.mkdir(parents=True, exist_ok=True)
    sample = root / "case.txt"
    sample.write_text(
        "\n".join(
            [
                "DS2 declaration",
                "invoice no: INV-001",
                "b/l no: BL-001",
                "container: ABCD1234567",
                "quantity: 10",
                "gross weight: 100",
                "net weight: 90",
                "amount: 1000",
                "currency: USD",
                "hs code: 9403.60",
                "",
                "commercial invoice",
                "invoice no: INV-001",
                "quantity: 10",
                "amount: 1000",
                "currency: USD",
            ]
        ),
        encoding="utf-8",
    )

    engine = DocumentWorkflowEngine(cache_root=root / "cache", rules_path=root / "config/customs_rules.json")
    result = engine.process_paths([str(sample)])
    if not result.intake_files:
        raise RuntimeError("intake failed")
    if not result.segments:
        raise RuntimeError("splitter produced no segments")
    if not result.cases:
        raise RuntimeError("matcher produced no cases")
    case = result.cases[0]
    if not case.audit_report:
        raise RuntimeError("audit did not run")
    if "parser_count" not in result.debug:
        raise RuntimeError("debug metadata missing")

    export_sample = root / "export.txt"
    export_sample.write_text(
        "\n".join(
            [
                "Booking Confirmation",
                "Booking No: BK-001",
                "S/O No: SO-001",
                "Vessel: YM TEST",
                "Voyage: 001E",
                "POL: KAOHSIUNG",
                "POD: LOS ANGELES",
                "ETD: 2026-06-01",
                "ETA: 2026-06-15",
                "Shipper: TONG YANG",
                "Consignee: ACME",
                "Notify: ACME",
                "Container: ABCD1234567",
                "Seal: S12345",
                "Package: 10",
                "Gross Weight: 100 KG",
                "CBM: 12.5",
                "Carrier: YM",
                "Forwarder: TEST FWD",
                "",
                "Bill of Lading",
                "Booking No: BK-001",
                "Vessel: YM TEST",
                "Voyage: 001E",
                "POL: KAOHSIUNG",
                "POD: LOS ANGELES",
                "Container: ABCD1234567",
                "Seal: S12345",
                "Package: 10",
                "Gross Weight: 100 KG",
                "CBM: 12.5",
            ]
        ),
        encoding="utf-8",
    )
    export_result = engine.process_paths([str(export_sample)], direction="export")
    if not export_result.cases:
        raise RuntimeError("export matcher produced no cases")
    export_case = export_result.cases[0]
    if "booking_no" not in export_case.match_keys:
        raise RuntimeError("booking key was not extracted")
    if not any(segment.parsed and segment.parsed.document_type.value in {"BOOKING", "BOOKING_CONFIRMATION", "S/O"} for segment in export_case.documents):
        raise RuntimeError("booking parser did not classify export booking document")
    print(
        f"document workflow ok: import_cases={len(result.cases)} export_cases={len(export_result.cases)} "
        f"export_status={export_case.status.value}"
    )


if __name__ == "__main__":
    main()
