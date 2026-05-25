from __future__ import annotations

from enum import Enum

from v2.core.models import CheckStatus
from v2.workflow.models import CaseWorkflow


class WorkflowState(str, Enum):
    WAITING_BL = "WAITING_BL"
    WAITING_DECLARATION = "WAITING_DECLARATION"
    PARTIAL_WORKFLOW = "PARTIAL_WORKFLOW"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    PENDING_MATCH = "PENDING_MATCH"
    READY_FOR_AUDIT = "READY_FOR_AUDIT"
    AUDIT_COMPLETED = "AUDIT_COMPLETED"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"


class WorkflowStateMachine:
    """Maps document completeness and audit output into formal workflow states."""

    def resolve(self, case: CaseWorkflow, low_confidence: bool = False) -> WorkflowState:
        if low_confidence:
            return WorkflowState.LOW_CONFIDENCE
        missing = {item.upper() for item in case.missing_documents}
        if "B/L" in missing:
            return WorkflowState.WAITING_BL
        if {"DS2報單", "出口報單"} & missing:
            return WorkflowState.WAITING_DECLARATION
        if case.missing_documents:
            return WorkflowState.PARTIAL_WORKFLOW
        if not case.audit_report:
            return WorkflowState.PENDING_MATCH
        if case.audit_report.status == CheckStatus.MATCH and not case.rule_findings:
            return WorkflowState.AUDIT_COMPLETED
        if case.audit_report.status == CheckStatus.MATCH:
            return WorkflowState.READY_FOR_AUDIT
        return WorkflowState.NEEDS_HUMAN_REVIEW

