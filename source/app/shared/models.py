from __future__ import annotations

from dataclasses import dataclass


STATUS_SYMBOLS = {
    "match": "✓",
    "warning": "⚠",
    "mismatch": "✗",
}


@dataclass(frozen=True)
class CheckItem:
    status: str
    field: str
    message: str
    expected: str = ""
    actual: str = ""

    @property
    def symbol(self) -> str:
        return STATUS_SYMBOLS[self.status]

    @classmethod
    def match(cls, field: str, message: str, expected: str = "", actual: str = "") -> "CheckItem":
        return cls("match", field, message, expected, actual)

    @classmethod
    def warning(cls, field: str, message: str, expected: str = "", actual: str = "") -> "CheckItem":
        return cls("warning", field, message, expected, actual)

    @classmethod
    def mismatch(cls, field: str, message: str, expected: str = "", actual: str = "") -> "CheckItem":
        return cls("mismatch", field, message, expected, actual)


@dataclass(frozen=True)
class CheckReport:
    items: list[CheckItem]

    @property
    def summary(self) -> str:
        mismatches = sum(1 for item in self.items if item.status == "mismatch")
        warnings = sum(1 for item in self.items if item.status == "warning")
        matches = sum(1 for item in self.items if item.status == "match")
        return f"✓ {matches}　⚠ {warnings}　✗ {mismatches}"
