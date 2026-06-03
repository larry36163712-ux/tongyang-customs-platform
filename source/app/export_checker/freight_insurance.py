from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


TWOPLACES = Decimal("0.01")


@dataclass(frozen=True)
class FreightInsuranceResult:
    expected_freight: Decimal
    expected_insurance: Decimal
    expected_cif: Decimal
    invoice_amount: Decimal


def parse_decimal(value: str | int | float | Decimal) -> Decimal:
    try:
        return Decimal(str(value).strip() or "0")
    except (InvalidOperation, AttributeError):
        raise ValueError(f"無法轉換數字：{value}") from None


def calculate_tong_ying_vietnam_cfs(
    cbm: str | int | float | Decimal,
    invoice_amount: str | int | float | Decimal,
    insurance_rate: str | int | float | Decimal,
    rule_config: dict[str, Any] | None = None,
) -> FreightInsuranceResult:
    rule_config = rule_config or {}
    freight_rule = rule_config.get("freight_rule", {})
    insurance_rule = rule_config.get("insurance_rule", {})
    cbm_value = parse_decimal(cbm)
    amount = parse_decimal(invoice_amount)
    rate = parse_decimal(insurance_rate)

    threshold = parse_decimal(freight_rule.get("cbm_threshold", "5"))
    lte_threshold = parse_decimal(freight_rule.get("freight_lte_threshold", "6000"))
    gt_threshold = parse_decimal(freight_rule.get("freight_gt_threshold", "8000"))
    multiplier = parse_decimal(insurance_rule.get("multiplier", "1.1"))
    minimum_premium = parse_decimal(insurance_rule.get("minimum_premium_twd", "400"))

    expected_freight = lte_threshold if cbm_value <= threshold else gt_threshold
    raw_insurance = amount * multiplier * rate
    expected_insurance = max(raw_insurance, minimum_premium).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    expected_cif = (amount + expected_freight + expected_insurance).quantize(TWOPLACES, rounding=ROUND_HALF_UP)

    return FreightInsuranceResult(
        expected_freight=expected_freight.quantize(TWOPLACES),
        expected_insurance=expected_insurance,
        expected_cif=expected_cif,
        invoice_amount=amount.quantize(TWOPLACES, rounding=ROUND_HALF_UP),
    )
