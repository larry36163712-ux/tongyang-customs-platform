from __future__ import annotations

from v2.workflow.models import CaseWorkflow
from engine.report.narrative_generator import NarrativeGenerator
from engine.report.report_formatter import AuditNarrativeReport, ReportFormatter


class AuditReportEngine:
    """Builds a customs-broker style narrative report from workflow audit results."""

    def __init__(
        self,
        narrative_generator: NarrativeGenerator | None = None,
        formatter: ReportFormatter | None = None,
    ) -> None:
        self.narrative = narrative_generator or NarrativeGenerator()
        self.formatter = formatter or ReportFormatter()

    def build(self, case: CaseWorkflow) -> AuditNarrativeReport:
        return self.narrative.generate(case)

    def build_text(self, case: CaseWorkflow) -> str:
        return self.formatter.format(self.build(case))
