from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class ConditionMatcher:
    """Matches rule applies_when clauses against runtime context."""

    def matches(self, applies_when: Mapping[str, Any] | None, context: Mapping[str, Any]) -> bool:
        if not applies_when:
            return True
        for key, expected in applies_when.items():
            if not self._match_value(context.get(key), expected):
                return False
        return True

    def _match_value(self, actual: Any, expected: Any) -> bool:
        if isinstance(expected, Mapping):
            return self._match_operator(actual, expected)
        if isinstance(expected, list):
            return any(self._match_value(actual, item) for item in expected)
        if isinstance(actual, list):
            return any(self._normalize(item) == self._normalize(expected) for item in actual)
        return self._normalize(actual) == self._normalize(expected)

    def _match_operator(self, actual: Any, expected: Mapping[str, Any]) -> bool:
        if "in" in expected:
            return self._match_value(actual, list(expected["in"]))
        if "not_in" in expected:
            return not self._match_value(actual, list(expected["not_in"]))
        if "exists" in expected:
            exists = actual not in (None, "", [])
            return exists is bool(expected["exists"])
        if "contains" in expected:
            actual_values = actual if isinstance(actual, list) else [actual]
            return any(self._normalize(item) == self._normalize(expected["contains"]) for item in actual_values)
        return False

    def _normalize(self, value: Any) -> str:
        if value is None:
            return ""
        return " ".join(str(value).strip().casefold().split())

