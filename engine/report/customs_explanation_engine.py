from __future__ import annotations

from engine.report.formula_reasoning_engine import FormulaReasoningEngine
from engine.report.semantic_explanation_engine import SemanticExplanationEngine


class CustomsExplanationEngine:
    def __init__(
        self,
        semantic: SemanticExplanationEngine | None = None,
        formula: FormulaReasoningEngine | None = None,
    ) -> None:
        self.semantic = semantic or SemanticExplanationEngine()
        self.formula = formula or FormulaReasoningEngine()

    def semantic_explanation(self, values: list[str]) -> str:
        return self.semantic.explain(values)

    def formula_explanation(self, title: str, values: list[str]) -> str:
        return self.formula.explain(title, values)

    def practical_explanation(self, title: str) -> str:
        return {
            "船名航次": "船名航次應以 SO、B/L 與報單交叉核對，重點是同一船名與同一航次，不是單純字串完全相同。",
            "件數": "報關件數以實際包裝單位為準；Bale 件數不等於櫃數，不能把 40HC 櫃數當成件數。",
            "重量": "重量需同時確認單位換算與毛重、淨重欄位位置，避免把毛重誤打成淨重。",
            "金額": "金額需回到 INV 單價、數量、幣別與報單申報基礎，不能只看總額字串一致。",
            "CIF / FOB": "CIF 應由 FOB、FRT、INS 組成；缺少運費或保險費來源時需人工確認。",
            "稅則": "稅則合理性需結合品名、材質、用途與輸入規定判斷，不應只比對代碼。",
            "櫃號封條": "櫃號封條屬高風險欄位，需以 B/L、裝箱明細與報單交叉確認。",
        }.get(title, "")

    def explain_section(self, title: str, values: list[str], hint: str = "") -> str:
        notes = [
            self.semantic_explanation(values),
            self.practical_explanation(title),
            hint,
        ]
        return " ".join(note for note in notes if note).strip()
