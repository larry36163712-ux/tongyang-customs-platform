from __future__ import annotations

from decimal import Decimal

from app.export_checker.freight_insurance import calculate_tong_ying_vietnam_cfs, parse_decimal
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


EXPORT_FIELDS = [
    "貨櫃號",
    "船名航次",
    "件數",
    "毛重",
    "淨重",
    "FOB",
    "運費",
    "保費",
    "CIF",
    "港口",
    "結關日",
    "開船日",
    "品名",
]

REQUIRED_DOCUMENTS = ["INV", "PKG", "訂艙單 / SO", "DS2報單"]
FORMAL_COMPARE_FIELDS = ["貨櫃號", "船名航次", "件數", "毛重", "淨重", "FOB", "CIF", "港口", "結關日", "開船日", "品名"]
DS2_COMPARE_FIELDS = ["貨櫃號", "船名航次", "件數", "毛重", "淨重", "FOB", "運費", "保費", "CIF", "港口", "品名"]


class ExportChecker:
    """Export checker: formal documents first, then DS2 comparison."""

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
        items.extend(self._check_freight_insurance(freight_inputs or {}))

        handled = resolved_fields(items) | parsed_document_fields(parsed_documents)
        for field in EXPORT_FIELDS:
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

    def _check_freight_insurance(self, values: dict[str, str]) -> list[CheckItem]:
        try:
            expected = calculate_tong_ying_vietnam_cfs(
                cbm=values.get("cbm", "0"),
                invoice_amount=values.get("invoice_amount", "0"),
                insurance_rate=values.get("insurance_rate", "0"),
            )
            declared_freight = parse_decimal(values.get("declared_freight", "0")).quantize(Decimal("0.01"))
            declared_insurance = parse_decimal(values.get("declared_insurance", "0")).quantize(Decimal("0.01"))
            declared_cif = parse_decimal(values.get("declared_cif", "0")).quantize(Decimal("0.01"))
        except ValueError as exc:
            return [CheckItem.warning("運保費驗算", str(exc), expected="有效數字", actual="輸入格式錯誤")]

        checks = [
            ("運費", expected.expected_freight, declared_freight),
            ("保費", expected.expected_insurance, declared_insurance),
            ("CIF", expected.expected_cif, declared_cif),
        ]
        items: list[CheckItem] = []
        for field, expected_value, actual_value in checks:
            if expected_value == actual_value:
                items.append(CheckItem.match(field, "通盈出口越南 CFS 規則驗算一致。"))
            else:
                items.append(
                    CheckItem.mismatch(
                        field,
                        "通盈出口越南 CFS 規則驗算不一致。",
                        expected=f"TWD {expected_value}",
                        actual=f"TWD {actual_value}",
                    )
                )
        return items
