from __future__ import annotations

from dataclasses import dataclass

from v2.core.models import CheckStatus, DocumentCheckReport


@dataclass(frozen=True)
class CompareRow:
    field: str
    document_value: str
    declaration_value: str
    status: str
    warning_level: str
    message: str


class CompareFormatter:
    """Formats raw compare results into human-readable audit rows."""

    def format_report(self, report: DocumentCheckReport | None) -> list[CompareRow]:
        if report is None:
            return []
        rows: list[CompareRow] = []
        for result in report.results:
            rows.append(
                CompareRow(
                    field=result.field.value,
                    document_value="; ".join(f"{name}: {value}" for name, value in result.document_values.items()),
                    declaration_value=result.declaration_value,
                    status=self._status_label(result.status),
                    warning_level=result.risk_level,
                    message=result.message,
                )
            )
        return rows

    def _status_label(self, status: CheckStatus) -> str:
        return {
            CheckStatus.MATCH: "正常",
            CheckStatus.MISSING: "可疑",
            CheckStatus.MISMATCH: "錯誤",
            CheckStatus.HIGH_RISK: "錯誤",
        }.get(status, status.value)

