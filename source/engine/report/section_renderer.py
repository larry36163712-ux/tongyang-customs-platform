from __future__ import annotations

class SectionRenderer:
    def render(self, index: int, section) -> list[str]:
        lines = [f"{self._number(index)}、{section.title}"]
        if section.declaration_value:
            lines.extend(["", "報單值：", section.declaration_value])
        if not section.document_values:
            lines.extend(["", "文件值：", "-"])
        for source, value in section.document_values.items():
            if value:
                lines.extend(["", f"文件值（{source}）：", value])
        lines.extend(["", "AI 判斷：", section.result or "-"])
        lines.extend(["", "是否一致：", self._consistency(section.result)])
        if section.calculation:
            lines.extend(["", "換算：" if self._is_conversion(section.calculation) else "驗算：", section.calculation])
        else:
            lines.extend(["", "驗算：", "-"])
        lines.extend(["", "風險：", section.risk or "未發現明確異常。"])
        if section.explanation:
            lines.extend(["", "白話說明：", section.explanation])
        else:
            lines.extend(["", "白話說明：", "此段資料不足，需由報關人員依原始文件確認。"])
        return lines

    def _is_conversion(self, calculation: str) -> bool:
        return "MTS" in calculation and "KG" in calculation

    def _number(self, value: int) -> str:
        labels = [
            "一",
            "二",
            "三",
            "四",
            "五",
            "六",
            "七",
            "八",
            "九",
            "十",
            "十一",
            "十二",
            "十三",
            "十四",
            "十五",
            "十六",
            "十七",
        ]
        return labels[value - 1] if 1 <= value <= len(labels) else str(value)

    def _consistency(self, result: str) -> str:
        if not result:
            return "無法確認"
        if "不一致" in result:
            return "否"
        if "高風險" in result or "無法確認" in result or "待補" in result or "暫不建議" in result:
            return "需人工確認"
        if "一致" in result or "正確" in result or "可進入" in result or "未見" in result:
            return "是"
        return "需人工確認"
