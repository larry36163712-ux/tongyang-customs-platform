from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from v2.audit.normalization import SemanticNormalizationEngine
from v2.audit.validation import AuditValidationEngine
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
    CanonicalField.DECLARATION_NO,
    CanonicalField.INVOICE_NO,
    CanonicalField.BL_NO,
    CanonicalField.BOOKING_NO,
    CanonicalField.INCOTERM,
    CanonicalField.CIF,
    CanonicalField.FOB,
    CanonicalField.FREIGHT,
    CanonicalField.INSURANCE,
    CanonicalField.EXCHANGE_RATE,
    CanonicalField.STATISTICAL_METHOD,
    CanonicalField.DUTY_AMOUNT,
    CanonicalField.CLOSING_DATE,
)

HIGH_RISK_FIELDS = {
    CanonicalField.HS_CODE,
    CanonicalField.CONTAINER_NO,
    CanonicalField.SEAL_NO,
    CanonicalField.VESSEL_VOYAGE,
    CanonicalField.HS_CODE,
    CanonicalField.EXCHANGE_RATE,
}

OPTIONAL_REPORT_FIELDS = {
    CanonicalField.DECLARATION_NO,
    CanonicalField.INVOICE_NO,
    CanonicalField.BL_NO,
    CanonicalField.BOOKING_NO,
    CanonicalField.INCOTERM,
    CanonicalField.CIF,
    CanonicalField.FOB,
    CanonicalField.FREIGHT,
    CanonicalField.INSURANCE,
    CanonicalField.EXCHANGE_RATE,
    CanonicalField.STATISTICAL_METHOD,
    CanonicalField.DUTY_AMOUNT,
    CanonicalField.CLOSING_DATE,
}


class DeclarationDocumentChecker:
    def __init__(
        self,
        parser: SemanticParserEngine | None = None,
        normalizer: SemanticNormalizationEngine | None = None,
        validator: AuditValidationEngine | None = None,
    ) -> None:
        self.parser = parser or SemanticParserEngine()
        self.normalizer = normalizer or SemanticNormalizationEngine()
        self.validator = validator or AuditValidationEngine(self.normalizer)

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
        validation_findings = self.validator.validate(declaration, supporting, results)
        warnings = self._high_risk_warnings(results, declaration, supporting)
        warnings.extend(
            f"{finding.title}: {finding.risk}"
            for finding in validation_findings
            if finding.risk and finding.status == CheckStatus.MISMATCH
        )

        blocking_results = [
            result
            for result in results
            if not (result.field in OPTIONAL_REPORT_FIELDS and result.status == CheckStatus.MISSING)
        ]
        if warnings:
            status = CheckStatus.HIGH_RISK
            summary = "核對完成：存在高風險 warning。"
        elif any(result.status == CheckStatus.MISMATCH for result in blocking_results):
            status = CheckStatus.MISMATCH
            summary = "核對失敗：DS2 報單與文件有差異。"
        elif any(result.status == CheckStatus.MISSING for result in blocking_results):
            status = CheckStatus.MISSING
            summary = "核對未完成：有欄位缺少。"
        else:
            status = CheckStatus.MATCH
            summary = "核對成功：DS2 報單與文件主要欄位一致。"

        report = DocumentCheckReport(
            status=status,
            summary=summary,
            declaration=declaration,
            documents=documents,
            results=results,
            high_risk_warnings=warnings,
        )
        report.raw_validations = validation_findings  # type: ignore[attr-defined]
        return report

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
            if not self._same_value(field, declaration_value, value)
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

    def _same_value(self, field: CanonicalField, left: str, right: str) -> bool:
        same, _reason = self.normalizer.equivalent(field, left, right)
        return same

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
        warnings.extend(
            result.message
            for result in results
            if result.risk_level == "high"
            and result.status != CheckStatus.MATCH
            and not (result.field in OPTIONAL_REPORT_FIELDS and result.status == CheckStatus.MISSING)
        )
        return warnings


class InvoicePackingChecker(DeclarationDocumentChecker):
    """Backward compatible alias for older tests and callers."""


def _field_value(document: ParsedDocument, field: CanonicalField) -> str:
    for parsed in document.fields:
        if parsed.canonical == field:
            return parsed.value
    if field == CanonicalField.PACKAGE_COUNT:
        for parsed in document.fields:
            if parsed.canonical == CanonicalField.QUANTITY and re.search(r"\b(BLE|BALE|BALES|CTN|CTNS|PKG|PKGS)\b", parsed.value.upper()):
                return parsed.value
    return ""


def _same_value(field: CanonicalField, left: str, right: str) -> bool:
    if field in {
        CanonicalField.QUANTITY,
        CanonicalField.PACKAGE_COUNT,
        CanonicalField.NET_WEIGHT,
        CanonicalField.GROSS_WEIGHT,
        CanonicalField.AMOUNT,
        CanonicalField.CIF,
        CanonicalField.FOB,
        CanonicalField.FREIGHT,
        CanonicalField.INSURANCE,
        CanonicalField.EXCHANGE_RATE,
        CanonicalField.DUTY_AMOUNT,
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
        CanonicalField.DECLARATION_NO: "報單號碼",
        CanonicalField.INVOICE_NO: "INV NO",
        CanonicalField.BL_NO: "BL NO",
        CanonicalField.BOOKING_NO: "Booking NO",
        CanonicalField.INCOTERM: "Incoterm",
        CanonicalField.CIF: "CIF",
        CanonicalField.FOB: "FOB",
        CanonicalField.FREIGHT: "運費",
        CanonicalField.INSURANCE: "保費",
        CanonicalField.EXCHANGE_RATE: "匯率",
        CanonicalField.STATISTICAL_METHOD: "統計方式",
        CanonicalField.DUTY_AMOUNT: "稅額",
        CanonicalField.CLOSING_DATE: "結關日",
    }.get(field, field.value)
