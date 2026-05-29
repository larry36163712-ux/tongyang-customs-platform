from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

from v2.core.models import CanonicalField


@dataclass(frozen=True)
class NormalizedValue:
    raw: str
    value: str
    numeric: Decimal | None = None
    unit: str = ""
    currency: str = ""
    note: str = ""


class SemanticNormalizationEngine:
    """Normalizes customs values the way a broker compares them in practice."""

    PACKAGE_UNITS = {
        "BLE": "BALES",
        "BALE": "BALES",
        "BALES": "BALES",
        "CTN": "CTNS",
        "CTNS": "CTNS",
        "CARTON": "CTNS",
        "CARTONS": "CTNS",
        "PKG": "PKGS",
        "PKGS": "PKGS",
        "PACKAGE": "PKGS",
        "PACKAGES": "PKGS",
        "PCS": "PCS",
        "PCE": "PCS",
        "PC": "PCS",
    }
    WEIGHT_UNITS = {"KG", "KGS", "KGM", "MT", "MTS", "TON", "TONS"}
    MONEY_FIELDS = {
        CanonicalField.AMOUNT,
        CanonicalField.CIF,
        CanonicalField.FOB,
        CanonicalField.FREIGHT,
        CanonicalField.INSURANCE,
        CanonicalField.DUTY_AMOUNT,
        CanonicalField.CUSTOMS_VALUE,
        CanonicalField.TRADE_PROMOTION_FEE,
        CanonicalField.BUSINESS_TAX,
    }

    def normalize(self, field: CanonicalField, value: str) -> NormalizedValue:
        raw = value or ""
        if field in {CanonicalField.PACKAGE_COUNT, CanonicalField.QUANTITY}:
            return self._quantity(raw, package=True)
        if field in {CanonicalField.NET_WEIGHT, CanonicalField.GROSS_WEIGHT}:
            return self._weight(raw)
        if field in self.MONEY_FIELDS:
            return self._money(raw)
        if field == CanonicalField.EXCHANGE_RATE:
            return self._decimal_value(raw, "exchange rate")
        if field in {CanonicalField.INVOICE_NO, CanonicalField.BL_NO, CanonicalField.BOOKING_NO, CanonicalField.SHIPPING_ORDER_NO, CanonicalField.CONTAINER_NO, CanonicalField.SEAL_NO}:
            normalized = re.sub(r"[^A-Z0-9]", "", raw.upper())
            return NormalizedValue(raw, self._repair_ocr_identifier(normalized), note="identifier normalized")
        if field == CanonicalField.HS_CODE:
            return NormalizedValue(raw, re.sub(r"[^0-9]", "", raw), note="tariff digits normalized")
        if field in {CanonicalField.VESSEL_VOYAGE, CanonicalField.VESSEL, CanonicalField.VOYAGE, CanonicalField.PORT, CanonicalField.POL, CanonicalField.POD}:
            return NormalizedValue(raw, re.sub(r"[^A-Z0-9]", "", raw.upper()), note="shipping text normalized")
        if field == CanonicalField.INCOTERM:
            match = re.search(r"\b(FOB|CIF|CFR|CNF|EXW|DAP|DDP)\b", raw.upper())
            return NormalizedValue(raw, match.group(1) if match else raw.strip().upper())
        return NormalizedValue(raw, re.sub(r"\s+", " ", raw).strip().casefold())

    def equivalent(self, field: CanonicalField, left: str, right: str) -> tuple[bool, str]:
        left_norm = self.normalize(field, left)
        right_norm = self.normalize(field, right)
        if left_norm.numeric is not None and right_norm.numeric is not None:
            if left_norm.numeric == right_norm.numeric and left_norm.unit == right_norm.unit:
                return True, self._note(left_norm, right_norm)
            if field in self.MONEY_FIELDS | {CanonicalField.EXCHANGE_RATE} and left_norm.numeric == right_norm.numeric:
                return True, self._note(left_norm, right_norm)
            return False, f"{left_norm.raw} normalized to {left_norm.numeric} {left_norm.unit}; {right_norm.raw} normalized to {right_norm.numeric} {right_norm.unit}"
        if left_norm.value == right_norm.value:
            return True, self._note(left_norm, right_norm)
        return False, f"{left_norm.raw} normalized to {left_norm.value}; {right_norm.raw} normalized to {right_norm.value}"

    def _quantity(self, raw: str, package: bool) -> NormalizedValue:
        match = re.search(r"(-?[0-9][0-9,]*(?:\.[0-9]+)?)\s*([A-Z]{2,10})?", raw.upper())
        if not match:
            return NormalizedValue(raw, re.sub(r"\s+", " ", raw).strip().upper())
        qty = self._to_decimal(match.group(1))
        unit = match.group(2) or ""
        normalized_unit = self.PACKAGE_UNITS.get(unit, unit) if package else unit
        value = f"{self._format(qty)} {normalized_unit}".strip() if qty is not None else raw.strip().upper()
        note = f"{unit} treated as {normalized_unit}" if unit and unit != normalized_unit else "quantity normalized"
        return NormalizedValue(raw, value, qty, normalized_unit, note=note)

    def _weight(self, raw: str) -> NormalizedValue:
        match = re.search(r"(-?[0-9][0-9,]*(?:\.[0-9]+)?)\s*([A-Z]{2,5})?", raw.upper())
        if not match:
            return NormalizedValue(raw, re.sub(r"\s+", " ", raw).strip().upper())
        qty = self._to_decimal(match.group(1))
        unit = match.group(2) or "KGS"
        if qty is None:
            return NormalizedValue(raw, raw.strip().upper())
        if unit in {"MT", "MTS", "TON", "TONS"}:
            kg = qty * Decimal("1000")
            return NormalizedValue(raw, f"{self._format(kg)} KGS", kg, "KGS", note=f"{self._format(qty)} {unit} = {self._format(kg)} KGS")
        if unit in {"KG", "KGS", "KGM"}:
            return NormalizedValue(raw, f"{self._format(qty)} KGS", qty, "KGS", note=f"{unit} treated as KGS")
        return NormalizedValue(raw, f"{self._format(qty)} {unit}", qty, unit)

    def _money(self, raw: str) -> NormalizedValue:
        currency = ""
        match_currency = re.search(r"\b(USD|TWD|NTD|EUR|JPY|CNY|RMB|GBP|HKD)\b", raw.upper())
        if match_currency:
            currency = "CNY" if match_currency.group(1) == "RMB" else match_currency.group(1)
        compact_currency = re.match(r"^(USD|TWD|NTD|EUR|JPY|CNY|RMB|GBP|HKD)\s*([0-9,.]+)", raw.strip().upper())
        amount_text = compact_currency.group(2) if compact_currency else raw
        amount = self._to_decimal(amount_text)
        value = f"{currency} {self._format(amount)}".strip() if amount is not None else raw.strip().upper()
        return NormalizedValue(raw, value, amount, currency=currency, note="currency and thousands separators normalized")

    def _decimal_value(self, raw: str, note: str) -> NormalizedValue:
        value = self._to_decimal(raw)
        return NormalizedValue(raw, self._format(value) if value is not None else raw.strip(), value, note=note)

    def _to_decimal(self, value: str) -> Decimal | None:
        match = re.search(r"-?[0-9][0-9,]*(?:\.[0-9]+)?|-?[0-9]+(?:\.[0-9]+)?", value)
        if not match:
            return None
        try:
            return Decimal(match.group(0).replace(",", ""))
        except (InvalidOperation, ValueError):
            return None

    def _repair_ocr_identifier(self, value: str) -> str:
        chars = list(value)
        for index, char in enumerate(chars):
            before = chars[index - 1] if index > 0 else ""
            after = chars[index + 1] if index + 1 < len(chars) else ""
            near_digit = before.isdigit() or after.isdigit()
            if near_digit and char == "O":
                chars[index] = "0"
            elif near_digit and char in {"I", "L"}:
                chars[index] = "1"
        return "".join(chars)

    def _format(self, value: Decimal | None) -> str:
        if value is None:
            return ""
        return f"{value:,.6f}".rstrip("0").rstrip(".")

    def _note(self, left: NormalizedValue, right: NormalizedValue) -> str:
        notes = [note for note in (left.note, right.note) if note]
        return "；".join(dict.fromkeys(notes))
