"""Generic transaction fee model for local paper-trading research."""
from __future__ import annotations


def transaction_fee(order_value: float) -> float:
    """Progressive transaction brokerage, rounded to cents.

    The model is deliberately account-provider neutral: it represents only
    transaction brokerage and does not include an account administration fee.
    """
    value = float(order_value)
    if value < 0:
        raise ValueError("transaction value cannot be negative")
    if value == 0:
        return 0.0
    fee = 10.0
    fee += min(max(value - 12_500.0, 0.0), 37_500.0) * 0.0008
    fee += max(value - 50_000.0, 0.0) * 0.0004
    return round(fee + 1e-9, 2)
