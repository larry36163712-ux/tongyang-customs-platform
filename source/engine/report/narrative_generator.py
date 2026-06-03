from __future__ import annotations

from v2.core.models import CheckResult, CheckStatus
from v2.workflow.models import CaseWorkflow
from engine.report.compare_to_report import CompareToReportTransformer
from engine.report.report_formatter import AuditNarrativeReport, AuditReportSection
from engine.report.section_builder import SectionBuilder
from engine.report.section_templates import SECTION_TEMPLATES


class NarrativeGenerator:
    def __init__(
        self,
        section_builder: SectionBuilder | None = None,
        transformer: CompareToReportTransformer | None = None,
    ) -> None:
        self.sections = section_builder or SectionBuilder()
        self.transformer = transformer or CompareToReportTransformer(self.sections)

    def generate(self, case: CaseWorkflow) -> AuditNarrativeReport:
        sections: list[AuditReportSection] = []
        problems: list[str] = []

        results = list(case.audit_report.results) if case.audit_report else []
        validations = getattr(case.audit_report, "raw_validations", []) if case.audit_report else []
        for template in SECTION_TEMPLATES:
            if template.key == "document_identity":
                sections.append(self._document_identity(case, results))
                continue
            if template.key == "risk":
                sections.append(self._risk_section(case, results, validations))
                continue
            if template.key == "final_review":
                sections.append(self._final_section(case, results, validations))
                continue
            section_results = [result for result in results if result.field.value in template.fields]
            section = self.sections.build_from_template(template, section_results)
            section = self._attach_validations(section, template.title, validations)
            sections.append(section)

        problems.extend(f"缺少 {missing_document}" for missing_document in case.missing_documents)
        problems.extend(self._problems(results))
        problems.extend(case.rule_findings)
        return AuditNarrativeReport(
            case_id=case.case_id,
            headline=self._headline(case, problems),
            sections=sections,
            problems=self._dedupe(problems),
        )

    def _headline(self, case: CaseWorkflow, problems: list[str]) -> str:
        problem_count = len(self._dedupe(problems))
        if problem_count:
            return f"本案發現 {problem_count} 項需確認事項，以下依報關核對順序列出原因與風險。"
        if case.audit_report and case.audit_report.status == CheckStatus.MATCH:
            return "本案主要欄位核對一致，未發現阻擋申報的差異。"
        return "本案已產生核對報告，請依各段說明確認是否可申報。"

    def _document_identity(self, case: CaseWorkflow, results: list[CheckResult]) -> AuditReportSection:
        found = []
        for segment in case.documents:
            parsed = segment.parsed
            document_type = parsed.document_type.value if parsed else segment.detected_type.value
            found.append(f"{document_type}: {segment.source_name}")
        missing = "、".join(case.missing_documents) if case.missing_documents else "無"
        section_results = [result for result in results if result.field.value in {"declaration_no", "invoice_no", "bl_no", "booking_no", "shipping_order_no", "container_no", "seal_no"}]
        document_values = {"已收到文件": "；".join(found) if found else "-"}
        for result in section_results:
            document_values.update(result.document_values)
        mismatches = [result.message for result in section_results if result.status != CheckStatus.MATCH]
        return AuditReportSection(
            title="文件完整度與單號",
            document_values=document_values,
            declaration_value="報單已收到" if case.audit_report and case.audit_report.declaration else "報單未確認",
            calculation=f"必要文件缺漏：{missing}；單號差異：{'；'.join(mismatches) if mismatches else '未發現'}",
            result="✅ 文件與單號可進入核對" if not case.missing_documents and not mismatches else "⚠ 文件或單號需確認",
            explanation="本段先確認文件是否齊全，再核對報單號碼、INV NO、BL NO、Booking NO、櫃號與封條是否屬於同一票。",
            risk="缺件或單號差異會造成後續船名、件數、重量、金額與稅則核對失準。" if case.missing_documents or mismatches else "未發現缺件或單號風險。",
        )

    def _risk_section(self, case: CaseWorkflow, results: list[CheckResult], validations) -> AuditReportSection:
        risks = list(case.rule_findings)
        if case.audit_report:
            risks.extend(case.audit_report.high_risk_warnings)
        risks.extend(result.message for result in results if result.status != CheckStatus.MATCH and result.message)
        risks.extend(f"{finding.title}: {finding.risk}" for finding in validations if getattr(finding, "risk", ""))
        risks.extend(f"缺少 {name}" for name in case.missing_documents)
        unique = self._dedupe(risks)
        return AuditReportSection(
            title="風險提醒",
            declaration_value=case.audit_report.summary if case.audit_report else "-",
            document_values={"風險項目": "；".join(unique) if unique else "未發現阻擋申報的異常"},
            calculation="已依缺件、欄位差異、高風險欄位與規則提醒彙整。",
            result="⚠ 需人工確認" if unique else "✅ 未見重大風險",
            explanation="此段以資深報關核對角度彙整，不列工程 parser confidence 或 debug 資訊。",
            risk="；".join(unique) if unique else "未發現明確異常。",
        )

    def _final_section(self, case: CaseWorkflow, results: list[CheckResult], validations) -> AuditReportSection:
        has_problem = bool(
            case.missing_documents
            or case.rule_findings
            or any(result.status != CheckStatus.MATCH for result in results)
            or any(getattr(finding, "status", CheckStatus.MATCH) != CheckStatus.MATCH for finding in validations)
        )
        if has_problem:
            result = "⚠ 暫不建議直接申報"
            explanation = "本案仍有缺件、欄位不一致或高風險欄位，建議先補件或由報關人員確認後再送件。"
            risk = "未處理前可能造成申報錯誤、退件或後續補正。"
        else:
            result = "✅ 可進入申報前確認"
            explanation = "主要文件與報單欄位目前核對一致，可進入申報前最後人工確認。"
            risk = "仍需依實際貨況與最新法規完成最終責任確認。"
        return AuditReportSection(
            title="最後結論",
            declaration_value=case.status.value,
            document_values={"案件狀態": case.workflow_state, "同票配對": case.grouping_confidence},
            calculation="綜合文件完整度、報單核對、清表核對、稅額與風險提醒後判斷。",
            result=result,
            explanation=explanation,
            risk=risk,
        )

    def _attach_validations(self, section: AuditReportSection, title: str, validations) -> AuditReportSection:
        related = [finding for finding in validations if self._validation_belongs(title, getattr(finding, "title", ""))]
        if not related:
            return section
        processes = [finding.process for finding in related if finding.process]
        explanations = [finding.explanation for finding in related if finding.explanation]
        risks = [finding.risk for finding in related if finding.risk]
        result = section.result
        if any(finding.status == CheckStatus.MISMATCH for finding in related):
            result = "❌ 不一致"
        elif any(finding.status == CheckStatus.MISSING for finding in related) and "不一致" not in result:
            result = "⚠ 無法確認"
        return AuditReportSection(
            title=section.title,
            declaration_value=section.declaration_value,
            document_values=section.document_values,
            calculation="；".join(dict.fromkeys([section.calculation, *processes])) if section.calculation or processes else "",
            result=result,
            explanation=" ".join(dict.fromkeys([section.explanation, *explanations])).strip(),
            risk="；".join(dict.fromkeys([section.risk, *risks])) if section.risk or risks else "",
        )

    def _validation_belongs(self, section_title: str, validation_title: str) -> bool:
        mapping = {
            "運費保費": ("CIF",),
            "單價": ("單價",),
            "重量": ("重量",),
            "匯率": ("匯率",),
            "件數": ("件數",),
            "稅則": ("稅則",),
            "統計方式": ("統計方式",),
        }
        return any(token in validation_title for token in mapping.get(section_title, ()))

    def _problems(self, results: list[CheckResult]) -> list[str]:
        return [
            result.message or f"{result.field.value} 需人工確認"
            for result in results
            if result.status in {CheckStatus.MISMATCH, CheckStatus.MISSING, CheckStatus.HIGH_RISK}
        ]

    def _dedupe(self, values: list[str]) -> list[str]:
        seen = set()
        result = []
        for value in values:
            if value and value not in seen:
                seen.add(value)
                result.append(value)
        return result
