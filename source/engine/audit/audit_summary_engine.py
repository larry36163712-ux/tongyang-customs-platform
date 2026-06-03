from __future__ import annotations

from engine.audit.compare_formatter import CompareFormatter, CompareRow
from engine.audit.human_readable_summary import HumanReadableSummary
from v2.audit.summary import AIAuditSummaryEngine, AuditSummary
from v2.workflow.models import CaseWorkflow


class AuditSummaryEngine:
    """ERP audit-summary façade over the active V2 audit summary engine."""

    def __init__(self) -> None:
        self.runtime = AIAuditSummaryEngine()
        self.formatter = CompareFormatter()
        self.renderer = HumanReadableSummary()

    def summarize(self, case: CaseWorkflow) -> AuditSummary:
        return self.runtime.summarize_case(case)

    def compare_rows(self, case: CaseWorkflow) -> list[CompareRow]:
        return self.formatter.format_report(case.audit_report)

    def human_text(self, case: CaseWorkflow) -> str:
        return self.renderer.render(case.audit_summary)

