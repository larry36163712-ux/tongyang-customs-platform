from __future__ import annotations

from v2.workflow.matcher import WorkflowMatcher
from v2.workflow.models import CaseWorkflow, DocumentSegment


class GroupingEngine:
    """Workflow grouping façade over the active V2 matcher."""

    def __init__(self) -> None:
        self.matcher = WorkflowMatcher()

    def group(self, segments: list[DocumentSegment], direction: str = "import") -> list[CaseWorkflow]:
        return self.matcher.group_cases(segments, direction=direction)

