from __future__ import annotations

import re


class SemanticExplanationEngine:
    UNIT_ALIASES = {
        "BLE": ("BALES", "Bale 單位"),
        "BALE": ("BALES", "Bale 單位"),
        "BALES": ("BALES", "Bale 單位"),
        "PCS": ("PCE", "Piece 單位"),
        "PCE": ("PCE", "Piece 單位"),
        "MT": ("MTS", "Metric Ton 單位"),
        "MTS": ("MTS", "Metric Ton 單位"),
        "KG": ("KGS", "Kilogram 單位"),
        "KGS": ("KGS", "Kilogram 單位"),
        "LICENCE": ("LICENSE", "英文拼字差異"),
        "LICENSE": ("LICENSE", "英文拼字差異"),
    }

    def explain(self, values: list[str]) -> str:
        groups: dict[str, set[str]] = {}
        descriptions: dict[str, str] = {}
        for unit in self._extract_alias_tokens(values):
            normalized, description = self.UNIT_ALIASES[unit]
            groups.setdefault(normalized, set()).add(unit)
            descriptions[normalized] = description
        notes = []
        for normalized, raw_values in groups.items():
            if len(raw_values) > 1:
                raw = " / ".join(sorted(raw_values))
                notes.append(f"{raw} 屬相同 {descriptions[normalized]}，可視為同一報關語意。")
        return " ".join(notes)

    def _extract_alias_tokens(self, values: list[str]) -> list[str]:
        tokens: list[str] = []
        for value in values:
            for token in re.findall(r"\b[A-Z]{2,8}\b", value.upper()):
                if token in self.UNIT_ALIASES:
                    tokens.append(token)
        return tokens
