from __future__ import annotations

from app.parser.document import ParsedDocument, UploadedDocument
from app.shared.checking import (
    compare_ds2_with_documents,
    compare_formal_documents,
    document_items,
    parsed_field_items,
    parsed_document_fields,
    resolved_fields,
)
from app.shared.models import CheckItem, CheckReport


IMPORT_FIELDS = [
    "進口商",
    "國別",
    "船名航次",
    "貨櫃場",
    "倉號",
    "稅則",
    "稅率",
    "稅金",
    "納稅辦法",
    "件數",
    "毛重",
    "淨重",
    "CIF",
    "FOB",
    "品名",
]

REQUIRED_DOCUMENTS = ["INV", "PKG", "B/L", "倉單", "DS2報單"]
FORMAL_COMPARE_FIELDS = ["船名航次", "貨櫃號", "港口", "件數", "毛重", "淨重", "FOB", "CIF", "品名"]
DS2_COMPARE_FIELDS = [
    "船名航次",
    "貨櫃號",
    "港口",
    "件數",
    "毛重",
    "淨重",
    "FOB",
    "CIF",
    "品名",
    "稅則",
    "稅率",
    "稅金",
    "納稅辦法",
]


class ImportChecker:
    """Import checker: formal documents first, then DS2 comparison."""

    def check(
        self,
        documents: dict[str, list[UploadedDocument]],
        parsed_documents: dict[str, list[ParsedDocument]] | None = None,
        freight_inputs: dict[str, str] | None = None,
    ) -> CheckReport:
        parsed_documents = parsed_documents or {}
        items: list[CheckItem] = []

        items.extend(document_items(REQUIRED_DOCUMENTS, documents))
        items.extend(parsed_field_items(parsed_documents))
        items.extend(compare_formal_documents(parsed_documents, FORMAL_COMPARE_FIELDS))
        items.extend(compare_ds2_with_documents(parsed_documents, DS2_COMPARE_FIELDS))

        handled = resolved_fields(items) | parsed_document_fields(parsed_documents)
        for field in IMPORT_FIELDS:
            if field not in handled:
                items.append(
                    CheckItem.warning(
                        field,
                        "已建立核對欄位，等待文件解析或人工確認。",
                        expected="文件彼此一致，且 DS2 與文件一致",
                        actual="尚未取得足夠資料",
                    )
                )

        return CheckReport(items=items)
