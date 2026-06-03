from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.rules.condition_matcher import ConditionMatcher
from engine.rules.rule_loader import RuleLoader, RuleObject
from v2.rules import RuleEngine, RuleFinding
from v2.workflow.models import CaseWorkflow


@dataclass(frozen=True)
class RuleExecutionResult:
    case_id: str
    findings: list[RuleFinding] = field(default_factory=list)

    @property
    def human_messages(self) -> list[str]:
        return [finding.human_text() for finding in self.findings]


class RuleExecutor:
    """Rule engine façade used by the ERP architecture layer."""

    def __init__(self, rules_path: str | Path) -> None:
        self.rules_path = Path(rules_path)
        self.loader = RuleLoader(self.rules_path)
        self.matcher = ConditionMatcher()
        self.runtime = RuleEngine(self.rules_path)

    def load_rules(self) -> list[RuleObject]:
        return self.loader.load()

    def matching_rules(self, context: dict[str, Any]) -> list[RuleObject]:
        return [
            rule
            for rule in self.load_rules()
            if rule.enabled and self.matcher.matches(rule.applies_when, context)
        ]

    def execute_case(self, case: CaseWorkflow) -> RuleExecutionResult:
        findings = self.runtime.evaluate(case)
        case.rule_findings = [finding.human_text() for finding in findings]
        return RuleExecutionResult(case_id=case.case_id, findings=findings)

