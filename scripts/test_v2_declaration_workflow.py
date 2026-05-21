from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from v2.core.checking import DeclarationDocumentChecker
from v2.core.document_loader import DocumentLoader
from v2.core.models import CheckStatus


def write_doc(root: Path, name: str, text: str) -> str:
    path = root / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def main() -> None:
    work = Path(tempfile.gettempdir()) / "ai_customs_v2_declaration_workflow"
    work.mkdir(parents=True, exist_ok=True)
    loader = DocumentLoader()
    checker = DeclarationDocumentChecker()

    ds2 = write_doc(
        work,
        "ds2.txt",
        "\n".join(
            [
                "DS2 進口報單",
                "Quantity: 100 PCS",
                "Packages: 10 CTN",
                "Net Weight: 500",
                "Gross Weight: 560",
                "Amount: 12000",
                "Currency: USD",
                "Description: Sofa",
                "HS Code: 940161",
                "Port: KEELUNG",
                "Container No: TGHU1234567",
                "Seal No: S12345",
                "Vessel Voyage: YM WELLNESS 123E",
            ]
        ),
    )
    inv = write_doc(
        work,
        "invoice.txt",
        "\n".join(
            [
                "Commercial Invoice",
                "QTY: 100 PCS",
                "Amount: 12000",
                "Currency: USD",
                "Goods: Sofa",
                "HS Code: 940161",
            ]
        ),
    )
    pkg = write_doc(
        work,
        "packing.txt",
        "\n".join(
            [
                "Packing List",
                "Quantity: 100 PCS",
                "Carton: 10 CTN",
                "NW: 500",
                "GW: 560",
                "Goods: Sofa",
            ]
        ),
    )
    bl = write_doc(
        work,
        "bl.txt",
        "\n".join(
            [
                "Bill of Lading",
                "Port: KEELUNG",
                "Container No: TGHU1234567",
                "Seal No: S12345",
                "Vessel Voyage: YM WELLNESS 123E",
            ]
        ),
    )
    loaded = loader.load_paths([ds2, inv, pkg, bl])
    report = checker.check_documents([item.parsed for item in loaded])
    if report.status != CheckStatus.MATCH:
        raise RuntimeError(f"expected match, got {report.status}: {report.summary}")

    bad_bl = write_doc(
        work,
        "bad-bl.txt",
        "\n".join(
            [
                "Bill of Lading",
                "Port: TAICHUNG",
                "Container No: TGHU9999999",
                "Seal No: BAD999",
                "Vessel Voyage: YM OTHER 999W",
            ]
        ),
    )
    bad_loaded = loader.load_paths([ds2, inv, pkg, bad_bl])
    bad_report = checker.check_documents([item.parsed for item in bad_loaded])
    if bad_report.status != CheckStatus.HIGH_RISK:
        raise RuntimeError(f"expected high risk, got {bad_report.status}")
    if not bad_report.high_risk_warnings:
        raise RuntimeError("expected high risk warnings")

    missing_report = checker.check_documents([item.parsed for item in loader.load_paths([inv, pkg])])
    if missing_report.status != CheckStatus.HIGH_RISK:
        raise RuntimeError("missing DS2 should be high risk")

    print("declaration workflow ok")


if __name__ == "__main__":
    main()

