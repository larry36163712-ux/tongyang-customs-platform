from __future__ import annotations

from dataclasses import dataclass

from v2.core.models import CheckStatus
from v2.workflow.models import CaseWorkflow
from engine.report.section_templates import SECTION_TEMPLATES, SectionTemplate


@dataclass(frozen=True)
class SectionState:
    key: str
    label: str
    status: str


class SectionStateManager:
    def states_for_case(self, case: CaseWorkflow) -> dict[str, SectionState]:
        results = list(case.audit_report.results) if case.audit_report else []
        states: dict[str, SectionState] = {}
        for template in SECTION_TEMPLATES:
            if template.key == "document_completeness":
                status = "異常" if case.missing_documents else "已完成"
            elif template.key == "risk":
                status = "異常" if self._has_issue(results) or case.rule_findings else "已完成"
            elif template.key == "final_review":
                status = "需人工確認" if case.missing_documents or self._has_issue(results) else "已完成"
            else:
                grouped = [result for result in results if result.field.value in template.fields]
                status = self._status_from_results(grouped)
            states[template.key] = SectionState(template.key, template.nav_label, status)
        return states

    def _status_from_results(self, results) -> str:
        if not results:
            return "未核對"
        statuses = {result.status for result in results}
        if CheckStatus.MISMATCH in statuses or CheckStatus.HIGH_RISK in statuses:
            return "異常"
        if CheckStatus.MISSING in statuses:
            return "需人工確認"
        return "已完成"

    def _has_issue(self, results) -> bool:
        return any(result.status in {CheckStatus.MISMATCH, CheckStatus.MISSING, CheckStatus.HIGH_RISK} for result in results)
