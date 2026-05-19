from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from v2.core.models import CanonicalField, CheckResult, CheckStatus, DocumentCheckReport, ParsedDocument
from v2.core.parser_engine import SemanticParserEngine


CHECK_FIELDS = (
    CanonicalField.QUANTITY,
    CanonicalField.PACKAGE_COUNT,
    CanonicalField.NET_WEIGHT,
    CanonicalField.GROSS_WEIGHT,
    CanonicalField.AMOUNT,
    CanonicalField.CURRENCY,
    CanonicalField.DESCRIPTION,
)


class InvoicePackingChecker:
    def __init__(self, parser: SemanticParserEngine | None = None) -> None:
        self.parser = parser or SemanticParserEngine()

    def check_texts(self, invoice_text: str, packing_text: str) -> DocumentCheckReport:
        invoice = self.parser.parse_document(invoice_text)
        packing = self.parser.parse_document(packing_text)
        return self.check(invoice, packing)

    def check(self, invoice: ParsedDocument, packing: ParsedDocument) -> DocumentCheckReport:
        results = [self._compare_field(field, invoice, packing) for field in CHECK_FIELDS]
        if any(result.status == CheckStatus.MISMATCH for result in results):
            status = CheckStatus.MISMATCH
            summary = "核對失敗：INV vs PKG 有差異。"
        elif any(result.status == CheckStatus.MISSING for result in results):
            status = CheckStatus.MISSING
            summary = "核對未完成：有必要欄位缺少。"
        else:
            status = CheckStatus.MATCH
            summary = "核對成功：INV vs PKG 主要欄位一致。"
        return DocumentCheckReport(status=status, summary=summary, invoice=invoice, packing=packing, results=results)

    def _compare_field(self, field: CanonicalField, invoice: ParsedDocument, packing: ParsedDocument) -> CheckResult:
        inv = _field_value(invoice, field)
        pkg = _field_value(packing, field)
        if not inv or not pkg:
            return CheckResult(field, CheckStatus.MISSING, inv, pkg, f"{_label(field)} 缺少欄位")

        if field in {
            CanonicalField.QUANTITY,
            CanonicalField.PACKAGE_COUNT,
            CanonicalField.NET_WEIGHT,
            CanonicalField.GROSS_WEIGHT,
            CanonicalField.AMOUNT,
        }:
            inv_num = _number(inv)
            pkg_num = _number(pkg)
            if inv_num is None or pkg_num is None:
                same = _normalize_text(inv) == _normalize_text(pkg)
            else:
                same = inv_num == pkg_num
        else:
            same = _normalize_text(inv) == _normalize_text(pkg)

        if same:
            return CheckResult(field, CheckStatus.MATCH, inv, pkg, f"{_label(field)} 一致")
        return CheckResult(field, CheckStatus.MISMATCH, inv, pkg, f"{_label(field)} 不同")


def _field_value(document: ParsedDocument, field: CanonicalField) -> str:
    for parsed in document.fields:
        if parsed.canonical == field:
            return parsed.value
    return ""


def _number(value: str) -> Decimal | None:
    match = re.search(r"-?\d+(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?", value)
    if not match:
        return None
    try:
        return Decimal(match.group(0).replace(",", ""))
    except InvalidOperation:
        return None


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _label(field: CanonicalField) -> str:
    return {
        CanonicalField.QUANTITY: "數量",
        CanonicalField.PACKAGE_COUNT: "件數",
        CanonicalField.NET_WEIGHT: "淨重",
        CanonicalField.GROSS_WEIGHT: "毛重",
        CanonicalField.AMOUNT: "金額",
        CanonicalField.CURRENCY: "幣別",
        CanonicalField.DESCRIPTION: "品名",
    }.get(field, field.value)
