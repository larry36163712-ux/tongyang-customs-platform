from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from v2.workflow.models import CaseWorkflow


@dataclass(frozen=True)
class RuleDefinition:
    code: str
    description: str
    severity: str
    keywords: tuple[str, ...]


class RuleEngine:
    def __init__(self, rules_path: Path) -> None:
        self.rules_path = rules_path
        self.rules = self._load_rules()

    def apply(self, case: CaseWorkflow) -> list[str]:
        text = "\n".join(segment.text for segment in case.documents).casefold()
        findings: list[str] = []
        for rule in self.rules:
            if all(keyword.casefold() in text for keyword in rule.keywords):
                findings.append(f"{rule.severity.upper()} {rule.code}: {rule.description}")
        case.rule_findings = findings
        return findings

    def _load_rules(self) -> list[RuleDefinition]:
        if not self.rules_path.exists():
            return []
        data = json.loads(self.rules_path.read_text(encoding="utf-8-sig"))
        rules = data.get("rules", []) if isinstance(data, dict) else []
        return [
            RuleDefinition(
                code=str(item.get("code", "")),
                description=str(item.get("description", "")),
                severity=str(item.get("severity", "warning")),
                keywords=tuple(str(keyword) for keyword in item.get("keywords", [])),
            )
            for item in rules
            if isinstance(item, dict) and item.get("code")
        ]
