from __future__ import annotations

from v2.audit.summary import AuditSummary


class HumanReadableSummary:
    """Renders audit summary content for customs-broker decision workflows."""

    def render(self, summary: AuditSummary | None) -> str:
        if summary is None:
            return "尚未完成核對。"
        return summary.human_text()

