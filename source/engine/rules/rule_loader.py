from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


RULE_FILES = (
    "global_rules.json",
    "company_rules.json",
    "customer_rules.json",
    "route_rules.json",
    "case_rules.json",
    "document_rules.json",
)


@dataclass(frozen=True)
class RuleObject:
    rule_id: str
    scope: str
    enabled: bool
    applies_when: dict[str, Any]
    priority: int
    description: str
    calculation: dict[str, Any]
    source: str
    warning_level: str
    path: Path


class RuleLoader:
    """Loads modular customs rule config from config/rules."""

    def __init__(self, rules_path: str | Path) -> None:
        self.rules_path = Path(rules_path)

    def load(self) -> list[RuleObject]:
        rules: list[RuleObject] = []
        for path in self._rule_paths():
            rules.extend(self._load_file(path))
        return sorted(rules, key=lambda rule: rule.priority)

    def _rule_paths(self) -> list[Path]:
        if self.rules_path.is_file():
            return [self.rules_path]
        if not self.rules_path.exists():
            return []
        return [self.rules_path / name for name in RULE_FILES if (self.rules_path / name).exists()]

    def _load_file(self, path: Path) -> list[RuleObject]:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        raw_rules = data.get("rules", []) if isinstance(data, dict) else []
        rules: list[RuleObject] = []
        for item in raw_rules:
            if not isinstance(item, dict):
                continue
            rule = self._to_rule(item, path)
            if rule:
                rules.append(rule)
        return rules

    def _to_rule(self, item: dict[str, Any], path: Path) -> RuleObject | None:
        rule_id = str(item.get("rule_id", "")).strip()
        if not rule_id:
            return None
        return RuleObject(
            rule_id=rule_id,
            scope=str(item.get("scope", "global")).strip().lower(),
            enabled=bool(item.get("enabled", True)),
            applies_when=dict(item.get("applies_when") or {}),
            priority=int(item.get("priority", 100)),
            description=str(item.get("description", "")).strip(),
            calculation=dict(item.get("calculation") or {}),
            source=str(item.get("source", "")).strip(),
            warning_level=str(item.get("warning_level", "warning")).strip().lower(),
            path=path,
        )

