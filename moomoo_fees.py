"""Compatibility alias for the former fee module name."""
from __future__ import annotations

from australian_super_fees import australian_super_member_direct_fee


def moomoo_au_asx_fee(order_value_aud: float) -> float:
    """Deprecated name; retained for old imports while using AustralianSuper fees."""
    return australian_super_member_direct_fee(order_value_aud)
