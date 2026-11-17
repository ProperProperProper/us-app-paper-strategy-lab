"""Safe, causal custom-indicator and strategy engine for agent experiments."""
from __future__ import annotations

import math
from dataclasses import asdict
from typing import Any

import numpy as np
import pandas as pd

from australian_super_fees import australian_super_member_direct_fee
from strategy_57pct import Trade, _validate_candles, _validate_trades, stats


def _feature(frame: pd.DataFrame, spec: dict[str, Any]) -> pd.Series:
    name = spec["name"]; w = max(2, int(spec.get("window", 20))); close = frame["close"].astype(float)
    if name == "sma": return close.rolling(w).mean()
    if name == "ema": return close.ewm(span=w, adjust=False).mean()
    if name == "atr":
        tr = pd.concat([frame.high-frame.low, (frame.high-close.shift()).abs(), (frame.low-close.shift()).abs()], axis=1).max(axis=1)
        return tr.rolling(w).mean()
    if name == "roc": return close.pct_change(w)
    if name == "volatility": return close.pct_change().rolling(w).std() * np.sqrt(w)
    if name == "efficiency_ratio":
        direction=(close-close.shift(w)).abs(); noise=close.diff().abs().rolling(w).sum()
        return direction / noise.replace(0,np.nan)
    if name == "slope":
        return close.rolling(w).apply(lambda x: np.polyfit(np.arange(len(x)), x, 1)[0] / max(abs(x[-1]),1e-12), raw=True)
    if name == "range_position":
        lo=frame.low.rolling(w).min(); hi=frame.high.rolling(w).max()
        return (close-lo)/(hi-lo).replace(0,np.nan)
    if name == "volume_ratio":
        if "volume" not in frame: return pd.Series(np.nan,index=frame.index)
        return frame.volume / frame.volume.rolling(w).mean()
    raise ValueError(f"unsupported indicator: {name}")


def compile_features(frame: pd.DataFrame, specs: list[dict[str, Any]]) -> pd.DataFrame:
    x=frame.copy()
    for spec in specs: x[spec["id"]]=_feature(x,spec)
    return x


def _condition(x: pd.DataFrame, c: dict[str, Any]) -> pd.Series:
    op=c["op"]; left=x[c["left"]] if c["left"] in x else float(c["left"]); right=x[c["right"]] if c.get("right") in x else float(c.get("right",0))
    if op == "gt": return left > right
    if op == "gte": return left >= right
    if op == "lt": return left < right
    if op == "lte": return left <= right
    left_prev = left.shift(1) if isinstance(left, pd.Series) else left
    right_prev = right.shift(1) if isinstance(right, pd.Series) else right
    if op == "cross_up": return (left > right) & (left_prev <= right_prev)
    if op == "cross_down": return (left < right) & (left_prev >= right_prev)
    raise ValueError(f"unsupported condition: {op}")


def run_custom(frame: pd.DataFrame, spec: dict[str, Any], capital=200000.0, allocation=.95, slippage_bps=2.0):
    _validate_candles(frame); x=compile_features(frame,spec["features"])
    entry=_condition(x,spec["entry"]); exit_signal=_condition(x,spec["exit"])
    rows=list(x.iterrows()); slip=slippage_bps/10000; cash=float(capital); position=None; trades=[]; equity=[]
    for i,(stamp,bar) in enumerate(rows[:-1]):
        next_stamp,next_bar=rows[i+1]
        equity.append({"date":stamp,"equity":cash+(position["qty"]*float(bar.close) if position else 0)})
        if position:
            price=float(bar.close); stop=position["entry"]*(1-float(spec.get("stop",.05))); target=position["entry"]*(1+float(spec.get("take_profit",.20)))
            reason="TP" if price>=target else "STOP" if price<=stop else "SIGNAL_EXIT" if bool(exit_signal.iloc[i]) else None
            if reason:
                out=float(next_bar.open)*(1-slip); exit_fee=australian_super_member_direct_fee(position["qty"]*out); gross=(out-position["entry"])*position["qty"]; costs=position["entry_fee"]+exit_fee
                trades.append(Trade(position["signal_time"].isoformat(),position["entry_time"].isoformat(),position["entry"],position["qty"],next_stamp.isoformat(),out,gross,costs,gross-costs,(gross-costs)/(position["entry"]*position["qty"])*100,reason)); cash+=position["qty"]*out-exit_fee; position=None; continue
            # Never overwrite an open position with a second signal.
            continue
        if bool(entry.iloc[i]):
            px=float(next_bar.open)*(1+slip); qty=math.floor(cash*allocation/px); fee=australian_super_member_direct_fee(qty*px) if qty>0 else 0
            if qty>0 and qty*px+fee <= cash:
                cash-=qty*px+fee; position={"entry":px,"qty":qty,"entry_time":next_stamp,"signal_time":stamp,"entry_fee":fee}
    if position:
        stamp,bar=rows[-1]; out=float(bar.close)*(1-slip); fee=australian_super_member_direct_fee(position["qty"]*out); gross=(out-position["entry"])*position["qty"]; costs=position["entry_fee"]+fee; trades.append(Trade(position["signal_time"].isoformat(),position["entry_time"].isoformat(),position["entry"],position["qty"],stamp.isoformat(),out,gross,costs,gross-costs,(gross-costs)/(position["entry"]*position["qty"])*100,"MARK_TO_MARKET")); cash+=position["qty"]*out-fee
    _validate_trades(trades)
    if rows:
        last_stamp=rows[-1][0]
        equity.append({"date":last_stamp,"equity":cash})
    eq=pd.DataFrame(equity).set_index("date") if equity else pd.DataFrame(columns=["equity"])
    return x,trades,{"equity":eq,"ending_cash":cash}


def candidate_specs() -> list[dict[str, Any]]:
    """Documented seed families; agents may mutate windows, thresholds, and combinations."""
    return [
      {"name":"donchian_ema_efficiency","features":[{"id":"ema_fast","name":"ema","window":12},{"id":"ema_slow","name":"ema","window":48},{"id":"eff","name":"efficiency_ratio","window":20},{"id":"hi","name":"sma","window":20}],"entry":{"op":"gt","left":"ema_fast","right":"ema_slow"},"exit":{"op":"lt","left":"ema_fast","right":"ema_slow"},"stop":.05,"take_profit":.25},
      {"name":"roc_atr_trend","features":[{"id":"roc","name":"roc","window":20},{"id":"slope","name":"slope","window":30},{"id":"atr","name":"atr","window":20},{"id":"ema","name":"ema","window":30}],"entry":{"op":"gt","left":"roc","right":0.0},"exit":{"op":"cross_down","left":"roc","right":0.0},"stop":.06,"take_profit":.30},
    ]
