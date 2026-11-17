"""Bounded, compositional causal formula strategies.

Agents may generate expression trees, never executable source code. Every
operator is explicitly whitelisted and only reads the current or historical
completed-bar frame.
"""
from __future__ import annotations

import math
import random
from typing import Any

import numpy as np
import pandas as pd

from moomoo_fees import transaction_fee
from strategy_57pct import Trade, _validate_candles, _validate_trades, stats

FIELDS = {"open", "high", "low", "close", "volume"}
OPS = {"add", "sub", "mul", "div", "abs", "neg", "min", "max", "ema", "sma", "std", "minroll", "maxroll", "lag", "roc", "zscore", "gt", "gte", "lt", "lte", "and", "or", "not", "cross_up", "cross_down"}


def _series(frame, node):
    if not isinstance(node, dict) or "op" not in node:
        raise ValueError("invalid formula node")
    op = node["op"]
    if op == "field":
        if node.get("name") not in FIELDS:
            raise ValueError("unsupported field")
        return frame[node["name"]].astype(float)
    if op == "const":
        return pd.Series(float(node.get("value", 0.0)), index=frame.index)
    if op not in OPS:
        raise ValueError("unsupported formula operation")
    args = [_series(frame, item) for item in node.get("args", [])]
    if op == "not": return ~args[0].astype(bool)
    if op == "abs": return args[0].astype(float).abs()
    if op == "neg": return -args[0].astype(float)
    if op == "add": return args[0].astype(float) + args[1].astype(float)
    if op == "sub": return args[0].astype(float) - args[1].astype(float)
    if op == "mul": return args[0].astype(float) * args[1].astype(float)
    if op == "div": return args[0].astype(float) / args[1].astype(float).replace(0, np.nan)
    if op == "min": return pd.concat([item.astype(float) for item in args], axis=1).min(axis=1)
    if op == "max": return pd.concat([item.astype(float) for item in args], axis=1).max(axis=1)
    window = max(2, min(120, int(node.get("window", 12))))
    if op == "ema": return args[0].ewm(span=window, adjust=False).mean()
    if op == "sma": return args[0].rolling(window).mean()
    if op == "std": return args[0].rolling(window).std()
    if op == "minroll": return args[0].rolling(window).min()
    if op == "maxroll": return args[0].rolling(window).max()
    if op == "lag": return args[0].shift(window)
    if op == "roc": return args[0].pct_change(window)
    if op == "zscore": return (args[0] - args[0].rolling(window).mean()) / args[0].rolling(window).std().replace(0, np.nan)
    if op in {"gt", "gte", "lt", "lte"}:
        return {"gt": args[0] > args[1], "gte": args[0] >= args[1], "lt": args[0] < args[1], "lte": args[0] <= args[1]}[op]
    if op == "and": return args[0].astype(bool) & args[1].astype(bool)
    if op == "or": return args[0].astype(bool) | args[1].astype(bool)
    if op in {"cross_up", "cross_down"}:
        return ((args[0] > args[1]) & (args[0].shift(1) <= args[1].shift(1))) if op == "cross_up" else ((args[0] < args[1]) & (args[0].shift(1) >= args[1].shift(1)))
    raise ValueError("unhandled formula operation")


def validate_formula(node, depth=0):
    if depth > 8:
        raise ValueError("formula depth exceeded")
    if not isinstance(node, dict) or node.get("op") not in {"field", "const"} | OPS:
        raise ValueError("invalid formula tree")
    if node["op"] == "field":
        if node.get("name") not in FIELDS: raise ValueError("invalid field")
        return
    if node["op"] == "const":
        value = float(node.get("value", 0.0))
        if not math.isfinite(value) or abs(value) > 1e6: raise ValueError("invalid constant")
        return
    unary_ops = {"abs", "neg", "not", "ema", "sma", "std", "minroll", "maxroll", "lag", "roc", "zscore"}
    expected = 1 if node["op"] in unary_ops else 2
    if len(node.get("args", [])) != expected: raise ValueError("invalid arity")
    for child in node["args"]: validate_formula(child, depth + 1)


def run_formula(frame, spec, capital=200000.0, allocation=1.0, slippage_bps=2.0):
    _validate_candles(frame); validate_formula(spec["entry"]); validate_formula(spec["exit"])
    entry = _series(frame, spec["entry"]).fillna(False).astype(bool)
    exit_signal = _series(frame, spec["exit"]).fillna(False).astype(bool)
    slip = slippage_bps / 10000.0; cash = float(capital); position = None; trades = []; equity_rows = []
    for stamp, bar in frame.iterrows():
        price = float(bar.close); equity_rows.append({"date": stamp, "equity": cash + (position["qty"] * price if position else 0.0)})
        if position:
            reason = "FORMULA_EXIT" if bool(exit_signal.loc[stamp]) else None
            if price <= position["entry"] * (1 - float(spec.get("stop", .08))): reason = "FORMULA_STOP"
            elif price >= position["entry"] * (1 + float(spec.get("take_profit", .16))): reason = "FORMULA_TP"
            if reason:
                out = price * (1 - slip); fee = transaction_fee(position["qty"] * out); gross = (out - position["entry"]) * position["qty"]; costs = position["entry_fee"] + fee; net = gross - costs
                trades.append(Trade(position["time"], position["time"], position["entry"], position["qty"], stamp.isoformat(), out, gross, costs, net, net / (position["entry"] * position["qty"]) * 100, reason)); cash += position["qty"] * out - fee; position = None; continue
        if position is None and bool(entry.loc[stamp]):
            px = price * (1 + slip); qty = math.floor(cash * allocation / px); fee = transaction_fee(qty * px) if qty else 0.0
            if qty and qty * px + fee <= cash: cash -= qty * px + fee; position = {"time": stamp.isoformat(), "entry": px, "qty": qty, "entry_fee": fee}
    if position:
        stamp = frame.index[-1]; out = float(frame.iloc[-1].close) * (1 - slip); fee = transaction_fee(position["qty"] * out); gross = (out - position["entry"]) * position["qty"]; costs = position["entry_fee"] + fee; net = gross - costs
        trades.append(Trade(position["time"], position["time"], position["entry"], position["qty"], stamp.isoformat(), out, gross, costs, net, net / (position["entry"] * position["qty"]) * 100, "FORMULA_MARK_TO_MARKET"))
    equity = pd.DataFrame(equity_rows).set_index("date")
    _validate_trades(trades)
    return trades, {"equity": equity, "ending_cash": cash}, stats(trades, {"equity": equity}, capital)


def random_formula(rng: random.Random, depth=0):
    if depth >= 3 or rng.random() < .28:
        if rng.random() < .7: return {"op": "field", "name": rng.choice(sorted(FIELDS))}
        return {"op": "const", "value": round(rng.uniform(-1.0, 1.0), 4)}
    op = rng.choice(["add", "sub", "mul", "div", "ema", "sma", "std", "roc", "zscore", "gt", "lt", "cross_up", "cross_down"])
    if op in {"ema", "sma", "std", "roc", "zscore"}:
        return {"op": op, "window": rng.randint(3, 36), "args": [random_formula(rng, depth + 1)]}
    return {"op": op, "args": [random_formula(rng, depth + 1), random_formula(rng, depth + 1)]}
