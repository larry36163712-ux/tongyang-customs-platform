from __future__ import annotations

__all__ = ["CustomsAuditEngine", "AIAuditSummaryEngine", "AuditSummary"]


def __getattr__(name: str):
    if name == "CustomsAuditEngine":
        from v2.audit.engine import CustomsAuditEngine

        return CustomsAuditEngine
    if name in {"AIAuditSummaryEngine", "AuditSummary"}:
        from v2.audit.summary import AIAuditSummaryEngine, AuditSummary

        return {"AIAuditSummaryEngine": AIAuditSummaryEngine, "AuditSummary": AuditSummary}[name]
    raise AttributeError(name)
