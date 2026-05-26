from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re


class FormulaReasoningEngine:
    def explain(self, title: str, values: list[str]) -> str:
        if title in {"重量", "毛重", "淨重"}:
            return self.weight_conversion(values)
        if title in {"CIF / FOB", "金額"}:
            return self.cif_formula(values) or self.unit_price_formula(values)
        return self.cif_formula(values) or self.unit_price_formula(values) or self.weight_conversion(values)

    def weight_conversion(self, values: list[str]) -> str:
        parsed = [self._quantity_unit(value) for value in values]
        weights = [(qty, unit) for qty, unit in parsed if qty is not None and unit in {"MT", "MTS", "KG", "KGS"}]
        if len(weights) < 2:
            return ""
        kg_values = [self._to_kg(qty, unit) for qty, unit in weights]
        if len(set(kg_values)) == 1:
            mt_qty = next((qty for qty, unit in weights if unit in {"MT", "MTS"}), None)
            if mt_qty is not None:
                return f"{mt_qty} MTS = {self._format_decimal(kg_values[0])} KG"
        return ""

    def cif_formula(self, values: list[str]) -> str:
        text = " ".join(values).upper()
        fob = self._amount_after_label(text, "FOB")
        freight = self._amount_after_label(text, "FRT") or self._amount_after_label(text, "FREIGHT")
        insurance = self._amount_after_label(text, "INS") or self._amount_after_label(text, "INSURANCE")
        cif = self._amount_after_label(text, "CIF")
        if None in {fob, freight, insurance, cif}:
            return ""
        total = fob + freight + insurance
        status = "正確" if total == cif else f"不一致，差額 {cif - total}"
        return f"{self._format_decimal(fob)} + {self._format_decimal(freight)} + {self._format_decimal(insurance)} = {self._format_decimal(total)}，CIF {status}"

    def unit_price_formula(self, values: list[str]) -> str:
        text = " ".join(values).upper()
        unit_price = self._amount_after_pattern(text, r"USD\s*([0-9,.]+)\s*/\s*MT")
        weight = self._amount_after_pattern(text, r"([0-9,.]+)\s*MTS?\b")
        amount = self._amount_after_label(text, "AMOUNT") or self._amount_after_label(text, "FOB")
        if None in {unit_price, weight, amount}:
            return ""
        total = unit_price * weight
        status = "完全正確" if total == amount else f"需確認，差額 {amount - total}"
        return f"{self._format_decimal(weight)} x {self._format_decimal(unit_price)} = {self._format_decimal(total)}，單價驗算 {status}"

    def _quantity_unit(self, value: str) -> tuple[Decimal | None, str]:
        match = re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*([A-Z]{2,5})\b", value.upper())
        if not match:
            return None, ""
        return self._to_decimal(match.group(1)), match.group(2)

    def _to_kg(self, qty: Decimal, unit: str) -> Decimal:
        return qty * Decimal("1000") if unit in {"MT", "MTS"} else qty

    def _amount_after_label(self, text: str, label: str) -> Decimal | None:
        return self._amount_after_pattern(text, rf"\b{re.escape(label)}\b\s*[:=]?\s*(?:USD)?\s*([0-9,.]+)")

    def _amount_after_pattern(self, text: str, pattern: str) -> Decimal | None:
        match = re.search(pattern, text)
        if not match:
            return None
        return self._to_decimal(match.group(1))

    def _to_decimal(self, value: str) -> Decimal | None:
        try:
            return Decimal(re.sub(r"[^0-9.\-]", "", value))
        except (InvalidOperation, ValueError):
            return None

    def _format_decimal(self, value: Decimal) -> str:
        return f"{value:,.3f}".rstrip("0").rstrip(".")
