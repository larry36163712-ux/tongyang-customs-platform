from v2.workflow.models import CaseWorkflow, DocumentSegment, IntakeFile, WorkflowResult

__all__ = ["CaseWorkflow", "DocumentSegment", "DocumentWorkflowEngine", "IntakeFile", "WorkflowResult"]


def __getattr__(name: str):
    if name == "DocumentWorkflowEngine":
        from v2.workflow.engine import DocumentWorkflowEngine

        return DocumentWorkflowEngine
    raise AttributeError(name)
