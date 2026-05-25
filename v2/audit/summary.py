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
    missing_documents: list[str] = field(default_factory=list)
    differences: list[str] = field(default_factory=list)
    high_risk_fields: list[str] = field(default_factory=list)
    rule_warnings: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    def human_text(self) -> str:
        lines = [
            f"案件 {self.case_id}: {self.headline}",
            f"是否可報: {'可報' if self.can_declare else '不可報'}",
        ]
        if self.missing_documents:
            lines.append("缺件: " + ", ".join(self.missing_documents))
        if self.differences:
            lines.append("差異: " + " | ".join(self.differences))
        if self.high_risk_fields:
            lines.append("高風險: " + " | ".join(self.high_risk_fields))
        if self.rule_warnings:
            lines.append("規則提示: " + " | ".join(self.rule_warnings))
        if self.next_actions:
            lines.append("下一步: " + " | ".join(self.next_actions))
        return "\n".join(lines)


class AIAuditSummaryEngine:
    """Turns parser/audit/rule output into customs-broker review decisions."""

    def summarize_case(self, case: CaseWorkflow) -> AuditSummary:
        report = case.audit_report
        missing_documents = list(case.missing_documents)
        differences = self._differences(report)
        high_risk = self._high_risk(report)
        rule_warnings = list(case.rule_findings)
        can_declare = not missing_documents and not differences and not high_risk
        headline = self._headline(can_declare, missing_documents, differences, high_risk, rule_warnings)
        next_actions = self._next_actions(missing_documents, differences, high_risk, rule_warnings)
        summary = AuditSummary(
            case_id=case.case_id,
            status=case.status.value,
            can_declare=can_declare,
            headline=headline,
            missing_documents=missing_documents,
            differences=differences,
            high_risk_fields=high_risk,
            rule_warnings=rule_warnings,
            next_actions=next_actions,
        )
        case.audit_summary = summary
        return summary

    def _differences(self, report: DocumentCheckReport | None) -> list[str]:
        if not report:
            return ["尚未產生核對報告"]
        return [
            result.message
            for result in report.results
            if result.status in {CheckStatus.MISMATCH, CheckStatus.MISSING}
        ]

    def _high_risk(self, report: DocumentCheckReport | None) -> list[str]:
        if not report:
            return []
        warnings = list(report.high_risk_warnings)
        warnings.extend(result.message for result in report.results if result.status == CheckStatus.HIGH_RISK or result.risk_level == "high")
        return warnings

    def _headline(
        self,
        can_declare: bool,
        missing_documents: list[str],
        differences: list[str],
        high_risk: list[str],
        rule_warnings: list[str],
    ) -> str:
        if can_declare:
            return "文件齊全且未發現阻擋報關的差異"
        if missing_documents:
            return f"缺少 {len(missing_documents)} 份必要文件"
        if high_risk:
            return f"存在 {len(high_risk)} 個高風險核對項目"
        if differences:
            return f"存在 {len(differences)} 個欄位差異需複核"
        if rule_warnings:
            return "存在規則提示需人工確認"
        return "尚需完成案件核對"

    def _next_actions(
        self,
        missing_documents: list[str],
        differences: list[str],
        high_risk: list[str],
        rule_warnings: list[str],
    ) -> list[str]:
        actions: list[str] = []
        if missing_documents:
            actions.append("補齊缺少文件後再報關")
        if differences:
            actions.append("逐項確認差異欄位並修正報單或來源文件")
        if high_risk:
            actions.append("先處理高風險欄位，必要時升級主管複核")
        if rule_warnings:
            actions.append("依公司/客戶/航線規則確認是否需額外計算或註記")
        if not actions:
            actions.append("可進入報關送件流程")
        return actions
