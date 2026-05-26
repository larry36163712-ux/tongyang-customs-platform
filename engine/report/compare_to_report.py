from __future__ import annotations

from v2.core.models import CheckResult, CheckStatus
from engine.report.report_formatter import AuditReportSection
from engine.report.section_builder import SectionBuilder
from engine.report.section_templates import SECTION_TEMPLATES


class CompareToReportTransformer:
    def __init__(self, section_builder: SectionBuilder | None = None) -> None:
        self.section_builder = section_builder or SectionBuilder()

    def transform(self, results: list[CheckResult]) -> list[AuditReportSection]:
        sections: list[AuditReportSection] = []
        used_fields: set[str] = set()

        for template in SECTION_TEMPLATES:
            grouped = [result for result in results if result.field.value in template.fields]
            if grouped:
                sections.append(self.section_builder.build_from_template(template, grouped))
                used_fields.update(result.field.value for result in grouped)

        for result in sorted(results, key=self._result_priority):
            if result.field.value not in used_fields:
                sections.append(self.section_builder.build_from_check(result))
        return sections

    def _result_priority(self, result: CheckResult) -> int:
        return {
            CheckStatus.MISMATCH: 0,
            CheckStatus.HIGH_RISK: 1,
            CheckStatus.MISSING: 2,
            CheckStatus.MATCH: 3,
        }.get(result.status, 4)
