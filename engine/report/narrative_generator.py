from __future__ import annotations

from v2.core.models import CheckResult, CheckStatus
from v2.workflow.models import CaseWorkflow
from engine.report.compare_to_report import CompareToReportTransformer
from engine.report.report_formatter import AuditNarrativeReport, AuditReportSection
from engine.report.section_builder import SectionBuilder


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

        for missing_document in case.missing_documents:
            sections.append(self.sections.build_missing_document(missing_document))
            problems.append(f"缺少 {missing_document}")

        results = list(case.audit_report.results) if case.audit_report else []
        sections.extend(self.transformer.transform(results))

        practical = self.sections.build_practical_judgment(results)
        if practical:
            sections.append(practical)

        problems.extend(self._problems(results))
        problems.extend(case.rule_findings)
        if not sections:
            sections.append(
                AuditReportSection(
                    title="核對狀態",
                    result="⚠ 尚未產生正式核對報告",
                    explanation="目前文件不足或尚未完成欄位解析，需補文件後重新核對。",
                )
            )
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
