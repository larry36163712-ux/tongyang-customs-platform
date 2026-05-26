from __future__ import annotations

from dataclasses import dataclass, field

from engine.report.section_renderer import SectionRenderer


@dataclass(frozen=True)
class AuditReportSection:
    title: str
    declaration_value: str = ""
    document_values: dict[str, str] = field(default_factory=dict)
    calculation: str = ""
    result: str = ""
    explanation: str = ""
    risk: str = ""


@dataclass(frozen=True)
class AuditNarrativeReport:
    case_id: str
    headline: str
    sections: list[AuditReportSection]
    problems: list[str] = field(default_factory=list)


class ReportFormatter:
    def __init__(self, section_renderer: SectionRenderer | None = None) -> None:
        self.section_renderer = section_renderer or SectionRenderer()

    def format(self, report: AuditNarrativeReport) -> str:
        lines = [f"AI Customs Audit Report - {report.case_id}", report.headline, ""]
        for index, section in enumerate(report.sections, 1):
            lines.extend(self.section_renderer.render(index, section))
            lines.append("")
        if report.problems:
            lines.append("問題與人工確認事項")
            for index, problem in enumerate(report.problems, 1):
                lines.append(f"{index}. {problem}")
        return "\n".join(lines).strip()
