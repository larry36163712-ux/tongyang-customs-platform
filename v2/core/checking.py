from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from v2.core.models import CanonicalField, CheckResult, CheckStatus, DocumentCheckReport, DocumentType, ParsedDocument
from v2.core.parser_engine import SemanticParserEngine


CHECK_FIELDS = (
    CanonicalField.QUANTITY,
    CanonicalField.PACKAGE_COUNT,
    CanonicalField.NET_WEIGHT,
    CanonicalField.GROSS_WEIGHT,
    CanonicalField.AMOUNT,
    CanonicalField.CURRENCY,
    CanonicalField.DESCRIPTION,
    CanonicalField.HS_CODE,
    CanonicalField.PORT,
    CanonicalField.CONTAINER_NO,
    CanonicalField.SEAL_NO,
    CanonicalField.VESSEL_VOYAGE,
)

HIGH_RISK_FIELDS = {
    CanonicalField.HS_CODE,
    CanonicalField.CONTAINER_NO,
    CanonicalField.SEAL_NO,
    CanonicalField.VESSEL_VOYAGE,
}


class DeclarationDocumentChecker:
    def __init__(self, parser: SemanticParserEngine | None = None) -> None:
        self.parser = parser or SemanticParserEngine()

    def check_documents(self, documents: list[ParsedDocument]) -> DocumentCheckReport:
        declaration = self._find_declaration(documents)
        if declaration is None:
            return DocumentCheckReport(
                status=CheckStatus.HIGH_RISK,
                summary="缺少 DS2 報單，無法進行核心核對。",
                declaration=None,
                documents=documents,
                high_risk_warnings=["未上傳 DS2 報單 PDF 或匯出檔。"],
            )

        supporting = [document for document in documents if document is not declaration]
        results = [self._compare_field(field, declaration, supporting) for field in CHECK_FIELDS]
        warnings = self._high_risk_warnings(results, declaration, supporting)

        if warnings:
            status = CheckStatus.HIGH_RISK
            summary = "核對完成：存在高風險 warning。"
        elif any(result.status == CheckStatus.MISMATCH for result in results):
            status = CheckStatus.MISMATCH
            summary = "核對失敗：DS2 報單與文件有差異。"
        elif any(result.status == CheckStatus.MISSING for result in results):
            status = CheckStatus.MISSING
            summary = "核對未完成：有欄位缺少。"
        else:
            status = CheckStatus.MATCH
            summary = "核對成功：DS2 報單與文件主要欄位一致。"

        return DocumentCheckReport(
            status=status,
            summary=summary,
            declaration=declaration,
            documents=documents,
            results=results,
            high_risk_warnings=warnings,
        )

    def check_texts(self, declaration_text: str, *supporting_texts: str) -> DocumentCheckReport:
        documents = [self.parser.parse_document(declaration_text, source_name="DS2")]
        documents.extend(self.parser.parse_document(text, source_name=f"文件 {index}") for index, text in enumerate(supporting_texts, 1))
        return self.check_documents(documents)

    def _find_declaration(self, documents: list[ParsedDocument]) -> ParsedDocument | None:
        for document in documents:
            if document.document_type == DocumentType.DS2_DECLARATION:
                return document
        return None

    def _compare_field(
        self,
        field: CanonicalField,
        declaration: ParsedDocument,
        supporting: list[ParsedDocument],
    ) -> CheckResult:
        declaration_value = _field_value(declaration, field)
        document_values = {
            document.source_name or document.document_type.value: value
            for document in supporting
            if (value := _field_value(document, field))
        }

        if not declaration_value:
            return CheckResult(field, CheckStatus.MISSING, "", document_values, f"{_label(field)}：DS2 報單缺少欄位")
        if not document_values:
            risk = "high" if field in HIGH_RISK_FIELDS else "normal"
            return CheckResult(field, CheckStatus.MISSING, declaration_value, {}, f"{_label(field)}：所有佐證文件缺少欄位", risk)

        mismatches = {
            name: value
            for name, value in document_values.items()
            if not _same_value(field, declaration_value, value)
        }
        if mismatches:
            risk = "high" if field in HIGH_RISK_FIELDS else "normal"
            return CheckResult(
                field,
                CheckStatus.MISMATCH,
                declaration_value,
                document_values,
                f"{_label(field)}：DS2 與 {', '.join(mismatches)} 不一致",
                risk,
            )

        return CheckResult(field, CheckStatus.MATCH, declaration_value, document_values, f"{_label(field)}：一致")

    def _high_risk_warnings(
        self,
        results: list[CheckResult],
        declaration: ParsedDocument,
        supporting: list[ParsedDocument],
    ) -> list[str]:
        warnings: list[str] = []
        if not supporting:
            warnings.append("只有 DS2 報單，缺少 INV / PKG / B/L / 到貨通知等佐證文件。")
        present_types = {document.document_type for document in supporting}
        if DocumentType.INVOICE not in present_types:
            warnings.append("缺少 INV，金額、幣別與品名核對風險高。")
        if DocumentType.PACKING_LIST not in present_types:
            warnings.append("缺少 PKG，數量、件數、淨重、毛重核對風險高。")
        if DocumentType.BILL_OF_LADING not in present_types:
            warnings.append("缺少 B/L，櫃號、封條、船名航次核對風險高。")
        warnings.extend(result.message for result in results if result.risk_level == "high" and result.status != CheckStatus.MATCH)
        return warnings


class InvoicePackingChecker(DeclarationDocumentChecker):
    """Backward compatible alias for older tests and callers."""


def _field_value(document: ParsedDocument, field: CanonicalField) -> str:
    for parsed in document.fields:
        if parsed.canonical == field:
            return parsed.value
    return ""


def _same_value(field: CanonicalField, left: str, right: str) -> bool:
    if field in {
        CanonicalField.QUANTITY,
        CanonicalField.PACKAGE_COUNT,
        CanonicalField.NET_WEIGHT,
        CanonicalField.GROSS_WEIGHT,
        CanonicalField.AMOUNT,
    }:
        left_num = _number(left)
        right_num = _number(right)
        if left_num is not None and right_num is not None:
            return left_num == right_num
    return _normalize_text(left) == _normalize_text(right)


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
        CanonicalField.HS_CODE: "稅則",
        CanonicalField.PORT: "港口",
        CanonicalField.CONTAINER_NO: "櫃號",
        CanonicalField.SEAL_NO: "封條",
        CanonicalField.VESSEL_VOYAGE: "船名航次",
    }.get(field, field.value)
