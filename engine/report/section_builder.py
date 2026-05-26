from __future__ import annotations

from v2.core.models import CheckResult, CheckStatus
from engine.report.customs_explanation_engine import CustomsExplanationEngine
from engine.report.report_formatter import AuditReportSection
from engine.report.section_templates import SectionTemplate


FIELD_LABELS = {
    "quantity": "數量",
    "package_count": "件數",
    "unit": "單位",
    "item_no": "項次",
    "description": "品名",
    "gross_weight": "毛重",
    "net_weight": "淨重",
    "amount": "金額",
    "currency": "幣別",
    "hs_code": "稅則",
    "port": "港口",
    "container_no": "櫃號",
    "seal_no": "封條",
    "vessel_voyage": "船名航次",
    "origin": "產地",
    "customer": "客戶",
    "supplier": "供應商",
}


class SectionBuilder:
    def __init__(self, explanation_engine: CustomsExplanationEngine | None = None) -> None:
        self.explanation = explanation_engine or CustomsExplanationEngine()

    def build_from_template(self, template: SectionTemplate, results: list[CheckResult]) -> AuditReportSection:
        declaration_value = self._join_unique(result.declaration_value for result in results)
        document_values = self._merge_document_values(results)
        values = [declaration_value, *document_values.values()]
        calculation = self.explanation.formula_explanation(template.title, values)
        explanation = self.explanation.explain_section(template.title, values, template.explanation_hint)
        return AuditReportSection(
            title=template.title,
            declaration_value=declaration_value or "-",
            document_values=document_values,
            calculation=calculation,
            result=self._aggregate_result(results, calculation),
            explanation=explanation,
            risk=self._aggregate_risk(results),
        )

    def build_from_check(self, result: CheckResult) -> AuditReportSection:
        title = FIELD_LABELS.get(result.field.value, result.field.value)
        document_values = {self._source_label(source): value for source, value in result.document_values.items()}
        values = [result.declaration_value, *document_values.values()]
        return AuditReportSection(
            title=title,
            declaration_value=result.declaration_value or "-",
            document_values=document_values,
            calculation=self.explanation.formula_explanation(title, values),
            result=self._result_text(result),
            explanation=self.explanation.explain_section(title, values),
            risk=self._risk_text(result),
        )

    def build_missing_document(self, document_name: str) -> AuditReportSection:
        return AuditReportSection(
            title=f"{document_name} 文件狀態",
            result="⚠ 待補件",
            explanation=f"缺少 {document_name}，相關欄位不能完成正式核對，需補件或人工確認。",
            risk="缺件可能導致船名航次、櫃號封條、金額或申報基礎無法確認。",
        )

    def build_practical_judgment(self, results: list[CheckResult]) -> AuditReportSection | None:
        values: list[str] = []
        for result in results:
            values.append(result.declaration_value)
            values.extend(result.document_values.values())
        combined = " ".join(value for value in values if value).upper()
        if "CONTAINER" in combined and ("BLE" in combined or "BALES" in combined):
            return AuditReportSection(
                title="AI 實務判斷",
                document_values={"文件描述": combined[:300]},
                result="✅ 合理",
                explanation="雖然文件可能出現 40HC CONTAINERS，但出口件數通常以 Bale 等包裝單位申報；件數需看 BLE / BALES，不應誤以櫃數替代件數。",
            )
        return None

    def _aggregate_result(self, results: list[CheckResult], calculation: str = "") -> str:
        statuses = {result.status for result in results}
        if CheckStatus.MISMATCH in statuses:
            return "❌ 不一致"
        if CheckStatus.HIGH_RISK in statuses:
            return "⚠ 高風險"
        if CheckStatus.MISSING in statuses:
            return "⚠ 無法確認"
        if calculation and ("正確" in calculation or "=" in calculation):
            return "✅ 正確"
        return "✅ 一致"

    def _aggregate_risk(self, results: list[CheckResult]) -> str:
        risks = [result.message for result in results if result.status != CheckStatus.MATCH and result.message]
        return "；".join(dict.fromkeys(risks))

    def _result_text(self, result: CheckResult) -> str:
        if result.status == CheckStatus.MATCH:
            return "✅ 一致"
        if result.status == CheckStatus.MISMATCH:
            return "❌ 不一致"
        if result.status == CheckStatus.MISSING:
            return "⚠ 無法確認"
        if result.status == CheckStatus.HIGH_RISK:
            return "⚠ 高風險"
        return result.status.value

    def _risk_text(self, result: CheckResult) -> str:
        if result.status == CheckStatus.MATCH and result.risk_level != "high":
            return ""
        return result.message

    def _merge_document_values(self, results: list[CheckResult]) -> dict[str, str]:
        merged: dict[str, list[str]] = {}
        for result in results:
            label = FIELD_LABELS.get(result.field.value, result.field.value)
            for source, value in result.document_values.items():
                merged.setdefault(self._source_label(source), []).append(f"{label}: {value}")
        return {source: self._join_unique(values) for source, values in merged.items()}

    def _source_label(self, source: str) -> str:
        upper = source.upper()
        if "INVOICE" in upper or "INV" in upper:
            return "INV"
        if "PACK" in upper or "PKG" in upper or "PL" in upper:
            return "PL"
        if "B/L" in upper or "BL" in upper:
            return "B/L"
        if "BOOK" in upper or "S/O" in upper or "SO" in upper:
            return "SO"
        return source

    def _join_unique(self, values) -> str:
        clean = [str(value).strip() for value in values if str(value).strip()]
        return " / ".join(dict.fromkeys(clean))
