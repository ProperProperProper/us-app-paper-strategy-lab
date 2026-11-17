"""AustralianSuper Member Direct fee model used by local research."""
from __future__ import annotations

from datetime import datetime
from typing import Any


ANNUAL_ADMIN_FEE_AUD = 150.00


def australian_super_member_direct_fee(order_value_aud: float) -> float:
    """Progressive brokerage per transaction, rounded to cents."""
    value = float(order_value_aud)
    if value < 0:
        raise ValueError("transaction value cannot be negative")
    if value == 0:
        return 0.0
    fee = 10.0
    fee += min(max(value - 12_500.0, 0.0), 37_500.0) * 0.0008
    fee += max(value - 50_000.0, 0.0) * 0.0004
    return round(fee + 1e-9, 2)


def australian_super_admin_fee(candles: Any) -> float:
    """Prorate the A$150 annual administration fee over the test window."""
    if candles is None or len(candles) < 2:
        return 0.0
    index = candles.index
    days = max(0, (index[-1] - index[0]).days)
    return round(ANNUAL_ADMIN_FEE_AUD * days / 365.0, 2)


def apply_australian_super_admin_fee(result: dict, candles: Any) -> dict:
    """Return stats after subtracting the separately charged admin fee."""
    output = dict(result)
    fee = australian_super_admin_fee(candles)
    output["administration_fee_aud"] = fee
    output["ending_equity"] = round(float(output["ending_equity"]) - fee, 2)
    output["total_return_pct"] = round((output["ending_equity"] / output["starting_capital"] - 1.0) * 100.0, 3)
    output["fee_model"] = "AustralianSuper Member Direct"
    return output
