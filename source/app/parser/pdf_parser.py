from __future__ import annotations

import re
from pathlib import Path

from app.parser.document import ParsedDocument, UploadedDocument
from app.parser.templates import parse_with_customer_template


COMMON_LABELS = {
    "FOB": ["FOB", "F.O.B"],
    "CIF": ["CIF", "C.I.F"],
    "品名": ["Description", "Commodity", "Goods", "Product", "品名", "貨名"],
    "件數": ["Packages", "Package", "PCS", "CTNS", "Quantity", "Qty", "件數", "箱數"],
    "毛重": ["Gross Weight", "G.W.", "GW", "毛重"],
    "淨重": ["Net Weight", "N.W.", "NW", "淨重"],
    "船名航次": ["Vessel Voyage", "Vessel/Voyage", "Vessel", "Voyage", "船名航次", "船名", "航次"],
    "貨櫃號": ["Container No", "Container Number", "Container", "CNTR", "貨櫃號", "櫃號"],
    "港口": ["Port of Loading", "Port of Discharge", "POL", "POD", "Port", "港口"],
}

FIELD_LABELS: dict[str, dict[str, list[str]]] = {
    "INV": {
        "發票號碼": ["Invoice No", "Invoice Number", "Inv No", "發票號碼", "發票編號"],
        **{key: COMMON_LABELS[key] for key in ["FOB", "CIF", "品名", "件數", "毛重", "淨重"]},
    },
    "PKG": {
        **{key: COMMON_LABELS[key] for key in ["品名", "件數", "毛重", "淨重"]},
    },
    "B/L": {
        **{key: COMMON_LABELS[key] for key in ["船名航次", "貨櫃號", "港口", "件數", "毛重", "淨重"]},
    },
    "倉單": {
        "貨櫃場": ["Container Yard", "CY", "貨櫃場"],
        "倉號": ["Warehouse No", "Warehouse", "倉號", "倉庫"],
        **{key: COMMON_LABELS[key] for key in ["船名航次", "貨櫃號", "港口", "件數", "毛重", "淨重"]},
    },
    "訂艙單 / SO": {
        "結關日": ["Closing Date", "Cut Off", "CY Cut", "結關日"],
        "開船日": ["ETD", "Sailing Date", "Departure Date", "開船日"],
        **{key: COMMON_LABELS[key] for key in ["船名航次", "貨櫃號", "港口", "件數", "毛重", "淨重"]},
    },
    "DS2報單": {
        "稅則": ["HS Code", "Tariff", "Commodity Code", "稅則", "稅則號別"],
        "稅率": ["Tax Rate", "Duty Rate", "Rate", "稅率"],
        "稅金": ["Tax", "Duty", "稅金", "進口稅"],
        "納稅辦法": ["Tax Payment", "Payment Method", "納稅辦法", "納稅方式"],
        "運費": ["Freight", "運費"],
        "保費": ["Insurance", "保費"],
        **COMMON_LABELS,
    },
}

ALIASES = {
    "DS2報單": {"DS2報單", "DS2"},
    "訂艙單 / SO": {"訂艙單 / SO", "訂艙單", "SO", "S/O"},
}


def parse_uploaded_documents(
    documents: dict[str, list[UploadedDocument]],
) -> dict[str, list[ParsedDocument]]:
    parsed: dict[str, list[ParsedDocument]] = {}
    for doc_type, doc_list in documents.items():
        parser_key = _parser_key(doc_type)
        parsed[doc_type] = [parse_uploaded_document(document, parser_key) for document in doc_list]
    return parsed


def parse_uploaded_document(document: UploadedDocument, parser_key: str | None = None) -> ParsedDocument:
    key = parser_key or _parser_key(document.doc_type)
    try:
        text = extract_text(document.stored_path)
    except RuntimeError as exc:
        return ParsedDocument(doc_type=document.doc_type, source_name=document.display_name, fields={}, error=str(exc))

    fields = parse_fields(key, text, document.display_name)
    return ParsedDocument(doc_type=document.doc_type, source_name=document.display_name, fields=fields, text=text)


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf_text(path)
    if suffix in {".txt", ".csv"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    raise RuntimeError(f"目前 parser 先支援 PDF/TXT/CSV，尚未支援：{path.suffix}")


def parse_fields(doc_type: str, text: str, source_name: str = "") -> dict[str, str]:
    normalized = _normalize_text(text)
    definitions = FIELD_LABELS.get(_parser_key(doc_type), {})
    parsed: dict[str, str] = {}
    for field, labels in definitions.items():
        value = _extract_by_labels(normalized, labels)
        if value:
            parsed[field] = value
    template_fields = parse_with_customer_template(_parser_key(doc_type), text, source_name)
    parsed.update({field: value for field, value in template_fields.items() if value})
    return parsed


def _extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError("缺少 pypdf，請先執行：pip install -r requirements.txt") from None

    reader = PdfReader(str(path))
    chunks: list[str] = []
    for page in reader.pages:
        chunks.append(page.extract_text() or "")
    return "\n".join(chunks)


def _parser_key(doc_type: str) -> str:
    for canonical, aliases in ALIASES.items():
        if doc_type in aliases:
            return canonical
    return doc_type


def _normalize_text(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.replace("\r", "\n").split("\n")]
    return "\n".join(line for line in lines if line)


def _extract_by_labels(text: str, labels: list[str]) -> str:
    for label in sorted(labels, key=len, reverse=True):
        escaped = re.escape(label)
        patterns = [
            rf"(?im)^\s*{escaped}\s*[:：#]\s*(.+)$",
            rf"(?im)^\s*{escaped}\s{{2,}}(.+)$",
            rf"(?im){escaped}\s*[:：#]\s*([^\n]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                value = _clean_value(match.group(1))
                if value:
                    return value
    return ""


def _clean_value(value: str) -> str:
    value = re.sub(r"\s{2,}", " ", value).strip(" \t:：")
    return value[:160]
