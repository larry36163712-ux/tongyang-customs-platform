from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


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
) -> FreightInsuranceResult:
    cbm_value = parse_decimal(cbm)
    amount = parse_decimal(invoice_amount)
    rate = parse_decimal(insurance_rate)

    expected_freight = Decimal("6000") if cbm_value <= Decimal("5") else Decimal("8000")
    raw_insurance = amount * Decimal("1.1") * rate
    expected_insurance = max(raw_insurance, Decimal("400")).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    expected_cif = (amount + expected_freight + expected_insurance).quantize(TWOPLACES, rounding=ROUND_HALF_UP)

    return FreightInsuranceResult(
        expected_freight=expected_freight.quantize(TWOPLACES),
        expected_insurance=expected_insurance,
        expected_cif=expected_cif,
        invoice_amount=amount.quantize(TWOPLACES, rounding=ROUND_HALF_UP),
    )
