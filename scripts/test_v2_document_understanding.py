from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from v2.core.document_understanding import SemanticDocumentClassifier
from v2.core.models import DocumentType
from v2.workflow.matcher import WorkflowMatcher
from v2.workflow.models import DocumentSegment


def _segment(name: str, text: str) -> DocumentSegment:
    classifier = SemanticDocumentClassifier()
    candidates = classifier.classify(text, name)
    return DocumentSegment(
        source_path=Path(name),
        source_name=name,
        page_start=1,
        page_end=1,
        text=text,
        detected_type=DocumentType.UNKNOWN,
        confidence=0.0,
        document_confidence=candidates[0].confidence if candidates else 0.0,
        candidates=candidates,
        manual_confirm_reason="版面解析不完整或辨識信心不足，需人工確認" if candidates and candidates[0].needs_manual_confirm else "",
    )


def main() -> None:
    invoice_text = "\n".join(
        [
            "Commercial Invoice",
            "Invoice No: IV-001",
            "Seller: TONG YANG",
            "Buyer: ACME",
            "Amount USD 30,277.35",
            "Unit Price USD 10 CIF",
        ]
    )
    packing_text = "\n".join(
        [
            "Packing List",
            "Package 97 BALES",
            "Gross Weight 99,270 KGS",
            "Net Weight 98,000 KGS",
            "Measurement 70 CBM",
        ]
    )
    bl_text = "\n".join(
        [
            "B/L No: BL-001",
            "Vessel EVER TEST Voyage 001E",
        ]
    )
    declaration_text = "\n".join(
        [
            "\u7a05\u5247 94036090",
            "\u7d71\u8a08\u65b9\u5f0f 02",
        ]
    )
    full_bl_text = "\n".join(
        [
            "BILL OF LADING",
            "ORIGINAL",
            "B/L NO BL123",
            "SHIPPER ABC",
            "CONSIGNEE XYZ",
            "PLACE OF RECEIPT TAIPEI",
            "PORT OF LOADING KAOHSIUNG",
            "NO OF ORIGINAL B/L THREE",
        ]
    )
    arrival_notice_text = "\n".join(
        [
            "ARRIVAL NOTICE",
            "NOTICE NO AN123",
            "VESSEL TEST VOYAGE 123",
            "ETA 2026-06-01",
            "FREE TIME 7 DAYS",
            "DELIVERY ORDER RELEASE",
        ]
    )
    noisy_bl_text = "\n".join(
        [
            "BILL 0F LAD1NG",
            "0RIGINAL",
            "B L NO BL123",
            "SHIPPER ABC",
            "CONSIGNEE XYZ",
            "PLACE 0F RECEIPT TAIPEI",
            "N0 OF 0RIGINAL B L THREE",
        ]
    )

    docs = [
        _segment("scan001.pdf", invoice_text),
        _segment("IMG_8821.jpg", packing_text),
        _segment("export_final.pdf", bl_text),
        _segment("file-unknown.pdf", declaration_text),
    ]
    best_types = {doc.candidates[0].document_type for doc in docs}
    expected = {
        DocumentType.INVOICE,
        DocumentType.PACKING_LIST,
        DocumentType.BILL_OF_LADING,
        DocumentType.DS2_DECLARATION,
    }
    if best_types != expected:
        raise RuntimeError(f"semantic classifier mismatch: {best_types}")
    if docs[0].candidates[0].confidence < 0.9:
        raise RuntimeError("invoice semantic confidence too low")
    if docs[1].candidates[0].confidence < 0.8:
        raise RuntimeError("packing semantic confidence too low")
    if not docs[2].candidates[0].needs_manual_confirm:
        raise RuntimeError("partial B/L should be queued for manual confirmation")
    if not docs[3].candidates[0].needs_manual_confirm:
        raise RuntimeError("partial DS2 declaration should be queued for manual confirmation")

    filename_trap = SemanticDocumentClassifier().best(packing_text, "invoice-final-v9.pdf")
    if filename_trap.document_type != DocumentType.PACKING_LIST:
        raise RuntimeError("classification must not trust misleading filenames")
    classifier = SemanticDocumentClassifier()
    full_bl = classifier.best(full_bl_text, "arrival_notice.pdf")
    if full_bl.document_type != DocumentType.BILL_OF_LADING or full_bl.confidence < 0.85:
        raise RuntimeError(f"B/L fingerprint failed: {full_bl}")
    arrival_notice = classifier.best(arrival_notice_text, "bl.pdf")
    if arrival_notice.document_type != DocumentType.ARRIVAL_NOTICE or arrival_notice.confidence < 0.75:
        raise RuntimeError(f"arrival notice fingerprint failed: {arrival_notice}")
    noisy_bl = classifier.best(noisy_bl_text, "scan001.pdf")
    if noisy_bl.document_type != DocumentType.BILL_OF_LADING:
        raise RuntimeError(f"OCR similarity matching failed for noisy B/L: {noisy_bl}")
    if "document_similarity" not in noisy_bl.score_breakdown:
        raise RuntimeError("noisy B/L did not use document similarity scoring")

    cases = WorkflowMatcher().group_cases(docs, direction="import")
    if len(cases) != 1:
        raise RuntimeError(f"expected one fuzzy-matched case, got {len(cases)}")
    case = cases[0]
    if case.missing_documents:
        raise RuntimeError(f"candidate documents must not be marked missing: {case.missing_documents}")
    if DocumentType.BILL_OF_LADING.value not in case.fallback_document_candidates:
        raise RuntimeError("low-confidence B/L candidate was not queued for manual confirmation")
    if DocumentType.DS2_DECLARATION.value not in case.fallback_document_candidates:
        raise RuntimeError("low-confidence DS2 declaration candidate was not queued for manual confirmation")
    if not case.manual_confirm_queue:
        raise RuntimeError("manual confirmation queue was not populated")

    print("document understanding ok: fuzzy candidates are not missing")


if __name__ == "__main__":
    main()
