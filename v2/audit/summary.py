from __future__ import annotations

from dataclasses import dataclass, field

from v2.core.models import CheckStatus, DocumentCheckReport
from v2.workflow.models import CaseWorkflow


@dataclass(frozen=True)
class AuditSummary:
    case_id: str
    status: str
    can_declare: bool
    headline: str
    workflow_state: str = "PENDING_MATCH"
    grouping_confidence: str = "pending_review"
    found_documents: list[str] = field(default_factory=list)
    missing_documents: list[str] = field(default_factory=list)
    differences: list[str] = field(default_factory=list)
    high_risk_fields: list[str] = field(default_factory=list)
    unresolved_fields: list[str] = field(default_factory=list)
    grouping_reasons: list[str] = field(default_factory=list)
    rule_warnings: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    def human_text(self) -> str:
        lines = ["【核對摘要】", f"案件 {self.case_id}: {self.headline}"]
        lines.append(f"案件狀態: {self._human_status()}")
        if self.found_documents:
            lines.append("已找到文件: " + ", ".join(self.found_documents))
        if self.missing_documents:
            lines.append("缺少文件: " + ", ".join(self.missing_documents))
        matched = self._matched_items()
        if matched:
            lines.append("已確認一致項目: " + ", ".join(matched))
        if self.high_risk_fields:
            lines.append("風險: " + " | ".join(self.high_risk_fields[:6]))
        if self.differences:
            lines.append("異常欄位: " + " | ".join(self.differences[:8]))
        if self.unresolved_fields:
            lines.append("無法確認項目: " + ", ".join(self.unresolved_fields))
        if self.rule_warnings:
            lines.append("規則提醒: " + " | ".join(self.rule_warnings[:4]))
        if self.next_actions:
            lines.append("建議下一步: " + " | ".join(self.next_actions))
        return "\n".join(lines)

    def _human_status(self) -> str:
        if self.can_declare:
            return "可核對"
        if self.workflow_state in {"WAITING_BL", "WAITING_DECLARATION", "PARTIAL_WORKFLOW"}:
            return "待補件"
        if self.workflow_state == "AUDIT_COMPLETED":
            return "核對完成"
        return "需人工確認"

    def _matched_items(self) -> list[str]:
        if self.missing_documents or self.differences or self.high_risk_fields:
            return []
        if self.found_documents:
            return ["必要文件已建立關聯", "目前未發現差異"]
        return []


class AIAuditSummaryEngine:
    """Turns parser/audit/rule output into customs-broker review decisions."""

    def summarize_case(self, case: CaseWorkflow) -> AuditSummary:
        report = case.audit_report
        found_documents = self._found_documents(case)
        missing_documents = list(case.missing_documents)
        differences = self._differences(report)
        high_risk = self._high_risk(report)
        unresolved_fields = list(case.unresolved_fields)
        rule_warnings = list(case.rule_findings)
        can_declare = (
            case.workflow_state in {"READY_FOR_AUDIT", "AUDIT_COMPLETED"}
            and not missing_documents
            and not differences
            and not high_risk
            and case.grouping_confidence in {"exact_match", "high_confidence"}
        )
        headline = self._headline(case, can_declare, missing_documents, differences, high_risk, rule_warnings)
        next_actions = self._next_actions(case, missing_documents, differences, high_risk, rule_warnings, unresolved_fields)
        summary = AuditSummary(
            case_id=case.case_id,
            status=case.status.value,
            can_declare=can_declare,
            headline=headline,
            workflow_state=case.workflow_state,
            grouping_confidence=case.grouping_confidence,
            found_documents=found_documents,
            missing_documents=missing_documents,
            differences=differences,
            high_risk_fields=high_risk,
            unresolved_fields=unresolved_fields,
            grouping_reasons=list(case.grouping_reasons),
            rule_warnings=rule_warnings,
            next_actions=next_actions,
        )
        case.audit_summary = summary
        return summary

    def _found_documents(self, case: CaseWorkflow) -> list[str]:
        found: list[str] = []
        for segment in case.documents:
            document_type = segment.parsed.document_type.value if segment.parsed else segment.detected_type.value
            found.append(f"{document_type}({segment.source_name}, p.{segment.page_start}-{segment.page_end})")
        return found

    def _differences(self, report: DocumentCheckReport | None) -> list[str]:
        if not report:
            return ["尚未完成欄位核對"]
        return [
            result.message
            for result in report.results
            if result.status in {CheckStatus.MISMATCH, CheckStatus.MISSING}
        ]

    def _high_risk(self, report: DocumentCheckReport | None) -> list[str]:
        if not report:
            return []
        warnings = list(report.high_risk_warnings)
        warnings.extend(
            result.message
            for result in report.results
            if result.status == CheckStatus.HIGH_RISK or result.risk_level == "high"
        )
        return warnings

    def _headline(
        self,
        case: CaseWorkflow,
        can_declare: bool,
        missing_documents: list[str],
        differences: list[str],
        high_risk: list[str],
        rule_warnings: list[str],
    ) -> str:
        if can_declare:
            return "文件齊全且未發現阻擋報關的差異"
        if case.workflow_state == "LOW_CONFIDENCE":
            return "文件關聯信心不足，需要人工確認是否同一票"
        if case.workflow_state == "WAITING_BL":
            return "缺少 B/L，暫時不能完成核對"
        if case.workflow_state == "WAITING_DECLARATION":
            return "缺少報單，等待報單後才能進入完整 audit"
        if case.workflow_state == "PARTIAL_WORKFLOW":
            return "文件尚未齊全，已建立部分 workflow"
        if missing_documents:
            return f"缺少 {len(missing_documents)} 份必要文件"
        if high_risk:
            return f"發現 {len(high_risk)} 個高風險核對問題"
        if differences:
            return f"發現 {len(differences)} 個差異，需人工判斷"
        if rule_warnings:
            return "發現規則提醒，需確認是否適用本案"
        return "已建立案件 workflow，等待進一步核對"

    def _next_actions(
        self,
        case: CaseWorkflow,
        missing_documents: list[str],
        differences: list[str],
        high_risk: list[str],
        rule_warnings: list[str],
        unresolved_fields: list[str],
    ) -> list[str]:
        actions: list[str] = []
        if case.grouping_confidence in {"low_confidence", "pending_review"}:
            actions.append("請人工確認 INV / PKG / B/L 是否屬於同一票案件")
        if missing_documents:
            actions.append("補齊缺少的正式文件")
        if unresolved_fields:
            actions.append("補確認關鍵欄位: " + ", ".join(unresolved_fields))
        if differences:
            actions.append("逐項核對差異欄位，確認是否需要更正報單或文件")
        if high_risk:
            actions.append("先處理高風險欄位，再決定是否可報")
        if rule_warnings:
            actions.append("確認公司、客戶、航線或案件規則是否適用")
        if not actions:
            actions.append("可進入報關送件流程")
        return actions
