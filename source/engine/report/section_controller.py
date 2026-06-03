from __future__ import annotations

from dataclasses import dataclass
import re

from v2.core.models import CheckStatus
from v2.workflow.models import CaseWorkflow
from engine.report.report_formatter import AuditNarrativeReport, AuditReportSection, ReportFormatter
from engine.report.section_builder import SectionBuilder
from engine.report.section_state_manager import SectionState, SectionStateManager
from engine.report.section_templates import SECTION_BY_KEY, SECTION_BY_NAV_LABEL, SECTION_TEMPLATES, SectionTemplate


@dataclass(frozen=True)
class RenderedSection:
    key: str
    label: str
    state: SectionState
    text: str


class SectionController:
    def __init__(
        self,
        section_builder: SectionBuilder | None = None,
        formatter: ReportFormatter | None = None,
        state_manager: SectionStateManager | None = None,
    ) -> None:
        self.section_builder = section_builder or SectionBuilder()
        self.formatter = formatter or ReportFormatter()
        self.state_manager = state_manager or SectionStateManager()

    def navigation_labels(self) -> list[str]:
        return [template.nav_label for template in SECTION_TEMPLATES]

    def section_key_for_label(self, label: str) -> str:
        return SECTION_BY_NAV_LABEL.get(label, SECTION_TEMPLATES[0]).key

    def render(self, case: CaseWorkflow, section_key: str) -> RenderedSection:
        template = SECTION_BY_KEY.get(section_key, SECTION_TEMPLATES[0])
        state = self.state_manager.states_for_case(case)[template.key]
        section = self._build_section(case, template)
        report = AuditNarrativeReport(case.case_id, self._headline(template, state.status), [section], self._problems(case, template))
        return RenderedSection(template.key, template.nav_label, state, self.formatter.format(report))

    def states(self, case: CaseWorkflow) -> dict[str, SectionState]:
        return self.state_manager.states_for_case(case)

    def _build_section(self, case: CaseWorkflow, template: SectionTemplate) -> AuditReportSection:
        if template.key == "document_completeness":
            return self._document_completeness_section(case, template)
        if template.key == "vessel_voyage":
            return self._vessel_voyage_section(case)
        if template.key == "risk":
            return self._risk_section(case, template)
        if template.key == "final_review":
            return self._final_review_section(case, template)
        results = list(case.audit_report.results) if case.audit_report else []
        grouped = [result for result in results if result.field.value in template.fields]
        if grouped:
            return self.section_builder.build_from_template(template, grouped)
        return AuditReportSection(
            title=template.title,
            result="⚠ 未核對",
            explanation=f"目前沒有可用欄位可執行「{template.nav_label}」。{template.explanation_hint}",
            risk="若此段為本案必要核對項目，需補齊文件或 parser 欄位。",
        )

    def _vessel_voyage_section(self, case: CaseWorkflow) -> AuditReportSection:
        results = list(case.audit_report.results) if case.audit_report else []
        vessel_results = [result for result in results if result.field.value in {"vessel_voyage", "vessel", "voyage"}]
        if not vessel_results:
            return AuditReportSection(
                title="船名航次",
                result="⚠ 未核對",
                explanation="目前沒有從報單、SO 或 B/L 擷取到船名航次欄位，需補文件或人工確認。",
                risk="船名航次未核對時，不應視為可放行。",
            )

        declaration_value = self._join_values(result.declaration_value for result in vessel_results)
        document_values: dict[str, str] = {}
        for result in vessel_results:
            for source, value in result.document_values.items():
                if value:
                    document_values[self._source_label(source)] = value

        normalized_declaration = self._normalize_vessel_voyage(declaration_value)
        normalized_documents = {
            source: self._normalize_vessel_voyage(value)
            for source, value in document_values.items()
            if value
        }
        semantic_match = bool(
            normalized_declaration
            and normalized_documents
            and all(value == normalized_declaration for value in normalized_documents.values())
        )
        raw_match = declaration_value in set(document_values.values())
        has_engine_issue = any(
            result.status in {CheckStatus.MISMATCH, CheckStatus.MISSING, CheckStatus.HIGH_RISK}
            for result in vessel_results
        )

        if semantic_match:
            result_text = "✅ 一致"
            explanation = "報單與文件船名航次完全一致。" if raw_match else "船名航次存在空格、標點或欄位格式差異，但正規化後屬同一船名航次。"
            risk = ""
        elif has_engine_issue:
            result_text = "❌ 不一致"
            explanation = "報單與文件的船名航次正規化後仍不一致，需人工確認是否同一航次。"
            risk = self._join_values(result.message for result in vessel_results if result.message)
        else:
            result_text = "⚠ 需人工確認"
            explanation = "系統已找到船名航次資料，但無法以目前正規化規則確認是否一致。"
            risk = "請人工比對船名、航次、空格、斜線與 OCR 可能誤判字元。"

        return AuditReportSection(
            title="船名航次",
            declaration_value=declaration_value or "-",
            document_values=document_values,
            result=result_text,
            explanation=explanation,
            risk=risk,
        )

    def _normalize_vessel_voyage(self, value: str) -> str:
        normalized = value.upper()
        normalized = re.sub(r"\b(VESSEL|VOYAGE|VOY|VSL)\b", "", normalized)
        normalized = normalized.replace("船名", "").replace("航次", "")
        normalized = normalized.replace("／", "/")
        return re.sub(r"[^A-Z0-9]", "", normalized)

    def _join_values(self, values) -> str:
        clean = [str(value).strip() for value in values if str(value).strip()]
        return " / ".join(dict.fromkeys(clean))

    def _source_label(self, source: str) -> str:
        upper = source.upper()
        if "BOOK" in upper or "S/O" in upper or "SO" in upper:
            return "SO"
        if "B/L" in upper or "BL" in upper:
            return "B/L"
        if "DECL" in upper or "DS2" in upper:
            return "報單"
        return source

    def _document_completeness_section(self, case: CaseWorkflow, template: SectionTemplate) -> AuditReportSection:
        found = sorted({
            (segment.parsed.document_type.value if segment.parsed else segment.detected_type.value)
            for segment in case.documents
        })
        missing = list(case.missing_documents)
        return AuditReportSection(
            title=template.title,
            document_values={"已收到": "、".join(found) or "-"},
            result="⚠ 待補件" if missing else "✅ 已完成",
            explanation=("缺少文件: " + "、".join(missing)) if missing else "必要文件已納入本案 workflow，可進入逐段核對。",
        )

    def _risk_section(self, case: CaseWorkflow, template: SectionTemplate) -> AuditReportSection:
        risks = self._problems(case, template)
        return AuditReportSection(
            title=template.title,
            result="⚠ 需人工確認" if risks else "✅ 未發現高風險",
            explanation="；".join(risks) if risks else "目前未發現不一致、缺欄位或規則警示。",
        )

    def _final_review_section(self, case: CaseWorkflow, template: SectionTemplate) -> AuditReportSection:
        problems = self._problems(case, template)
        return AuditReportSection(
            title=template.title,
            result="⚠ 需人工確認" if problems or case.missing_documents else "✅ 可進入申報確認",
            explanation="；".join(problems or ["文件與欄位核對未發現阻擋申報的問題。"]),
            risk="送件前仍需依公司流程確認紙本、電子資料與申報系統一致。",
        )

    def _headline(self, template: SectionTemplate, status: str) -> str:
        return f"{template.nav_label} - {status}"

    def _problems(self, case: CaseWorkflow, template: SectionTemplate) -> list[str]:
        results = list(case.audit_report.results) if case.audit_report else []
        if template.fields:
            results = [result for result in results if result.field.value in template.fields]
        problems = [
            result.message or f"{result.field.value} 需人工確認"
            for result in results
            if result.status in {CheckStatus.MISMATCH, CheckStatus.MISSING, CheckStatus.HIGH_RISK}
        ]
        if template.key in {"document_completeness", "risk", "final_review"}:
            problems.extend(f"缺少 {name}" for name in case.missing_documents)
            problems.extend(case.rule_findings)
        return list(dict.fromkeys(problem for problem in problems if problem))
