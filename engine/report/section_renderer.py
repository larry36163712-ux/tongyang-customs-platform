from __future__ import annotations

class SectionRenderer:
    def render(self, index: int, section) -> list[str]:
        lines = [f"{self._number(index)}、{section.title}"]
        if section.declaration_value:
            lines.extend(["", "報單：", section.declaration_value])
        for source, value in section.document_values.items():
            if value:
                lines.extend(["", f"{source}：", value])
        if section.calculation:
            lines.extend(["", "換算：" if self._is_conversion(section.calculation) else "驗算：", section.calculation])
        lines.extend(["", "結果：", section.result])
        if section.explanation:
            lines.extend(["", "說明：", section.explanation])
        if section.risk:
            lines.extend(["", "風險：", section.risk])
        return lines

    def _is_conversion(self, calculation: str) -> bool:
        return "MTS" in calculation and "KG" in calculation

    def _number(self, value: int) -> str:
        labels = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
        return labels[value - 1] if 1 <= value <= len(labels) else str(value)
