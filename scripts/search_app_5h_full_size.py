#!/usr/bin/env python3
"""Search causal app-parity 5H candidates on the local hourly cache.

This is research-only: it does not alter the Android active profile. It uses
full balance, AustralianSuper brokerage, 2bp slippage, one position, and
completed 5H candles built from the same six-hour ASX session convention.
"""
from __future__ import annotations

import json, math, random, sqlite3, statistics
from datetime import datetime
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from australian_super_fees import australian_super_member_direct_fee

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/asx_hourly_yfinance_42d.sqlite3"
OUT = ROOT / "reports/app_5h_full_size_search.json"
CAPITAL = 200_000.0

def aggregate(symbol):
    db = sqlite3.connect(DB)
    rows = db.execute("SELECT timestamp_local,open,high,low,close,volume FROM hourly_candles WHERE symbol=? ORDER BY timestamp_local", (symbol,)).fetchall()
    by = {}
    for stamp, op, hi, lo, cl, vol in rows:
        dt = datetime.fromisoformat(stamp); by.setdefault(dt.date(), {})[dt.hour] = (op, hi, lo, cl, vol)
    result = []
    for date, bars in sorted(by.items()):
        start = 10 if all(h in bars for h in range(10, 15)) else (9 if all(h in bars for h in range(9, 14)) else None)
        if start is None: continue
        selected = [bars[h] for h in range(start, start + 5)]
        result.append({"date": str(date), "open": selected[0][0], "high": max(x[1] for x in selected), "low": min(x[2] for x in selected), "close": selected[-1][3], "volume": sum(x[4] for x in selected)})
    return result

def ema(values, period):
    alpha = 2 / (period + 1); result = [values[0]]
    for value in values[1:]: result.append(alpha * value + (1 - alpha) * result[-1])
    return result

def evaluate(candles, p):
    close = [x["close"] for x in candles]; high = [x["high"] for x in candles]; low = [x["low"] for x in candles]; volume = [x["volume"] for x in candles]
    fast, slow = ema(close, p["fast"]), ema(close, p["slow"])
    atr = []
    for i in range(len(candles)):
        trs = []
        for j in range(max(0, i - 13), i + 1):
            prev = close[j - 1] if j else close[j]
            trs.append(max(high[j] - low[j], abs(high[j] - prev), abs(low[j] - prev)))
        atr.append(sum(trs) / len(trs))
    cash = CAPITAL; position = None; equity = []; trades = []; peak = CAPITAL
    for i, bar in enumerate(candles):
        price = close[i]
        if position:
            position["peak"] = max(position["peak"], price)
            if price >= position["entry"] * (1 + p["be"]): position["be"] = True
            if position["peak"] >= position["entry"] * (1 + p["pl_trigger"]): position["pl"] = True
            stop = position["entry"] * (1 - p["stop"])
            if position["be"]: stop = max(stop, position["entry"] * (1 + p["be_lock"]))
            if position["pl"]: stop = max(stop, position["entry"] * (1 + p["pl_lock"]))
            if position["peak"] >= position["entry"] * (1 + p["trail_trigger"]): stop = max(stop, position["peak"] * (1 - p["trail_pct"]))
            red = price < slow[i]
            yellow = price < fast[i] and price >= slow[i] and fast[i] > slow[i]
            exit_rule = (red if p["exit"] == "slow_break" else (red or yellow) if p["exit"] == "fast_or_slow" else fast[i] < slow[i])
            reason = "TP" if price >= position["entry"] * (1 + p["tp"]) else "STOP" if price <= stop else "RULE" if exit_rule else None
            if reason:
                exit_price = price * (1 - .0002); fee = australian_super_member_direct_fee(position["qty"] * exit_price)
                net = (exit_price - position["entry"]) * position["qty"] - position["entry_fee"] - fee
                cash += position["qty"] * exit_price - fee; trades.append(net); position = None
        prior = max(high[max(0, i - p["lookback"]):i]) if i >= p["lookback"] else None
        breakout = prior is not None and price > prior
        trend = fast[i] > slow[i] and price > slow[i]
        cross = i > 0 and fast[i - 1] <= slow[i - 1] and trend
        entry = {"breakout": breakout, "breakout_trend": breakout and trend, "ema_cross": cross, "breakout_or_cross": (breakout and trend) or cross}[p["entry"]]
        filter_ok = True
        if p["filter"] == "atr": filter_ok = prior is not None and price > prior + p["atr_buffer"] * atr[i]
        elif p["filter"] == "slope": filter_ok = i > 0 and fast[i] > fast[i - 1] and slow[i] > slow[i - 1]
        elif p["filter"] == "volume": filter_ok = i >= 20 and volume[i] > statistics.median(volume[i - 20:i])
        if position is None and entry and filter_ok:
            entry_price = price * (1 + .0002); qty = math.floor(cash / entry_price)
            if qty > 0:
                fee = australian_super_member_direct_fee(qty * entry_price); cash -= qty * entry_price + fee
                position = {"entry": entry_price, "qty": qty, "entry_fee": fee, "peak": entry_price, "be": False, "pl": False}
        mark = cash + (position["qty"] * price if position else 0); peak = max(peak, mark); equity.append(mark)
    if position:
        exit_price = close[-1] * (1 - .0002); fee = australian_super_member_direct_fee(position["qty"] * exit_price)
        trades.append((exit_price - position["entry"]) * position["qty"] - position["entry_fee"] - fee); cash += position["qty"] * exit_price - fee; equity[-1] = cash
    dd = min((v / max(equity[:i + 1]) - 1) for i, v in enumerate(equity)) if equity else 0.0
    return {"pnl_aud": round(cash - CAPITAL, 2), "drawdown_pct": round(dd * 100, 2), "trades": len(trades), "eligible": len(trades) >= 1 and abs(dd * 100) <= 6.0}

def search(symbol, seed=20261115, candidates=20000):
    rng = random.Random(seed); candles = aggregate(symbol); results = []
    for _ in range(candidates):
        fast = rng.randint(3, 35); slow = rng.randint(fast + 2, 140)
        p = {"lookback": rng.randint(5, min(35, max(5, len(candles) - 1))), "fast": fast, "slow": slow,
             "entry": rng.choice(("breakout", "breakout_trend", "ema_cross", "breakout_or_cross")),
             "exit": rng.choice(("fast_or_slow", "slow_break", "trend_cross")), "filter": rng.choice(("none", "atr", "slope", "volume")),
             "atr_buffer": rng.choice((.05, .10, .15, .20, .25)), "tp": rng.uniform(.02, .20), "stop": rng.uniform(.01, .10),
             "be": rng.uniform(.005, .05), "be_lock": rng.uniform(0, .005), "pl_trigger": rng.uniform(.03, .15), "pl_lock": rng.uniform(0, .03),
             "trail_trigger": rng.uniform(.02, .12), "trail_pct": rng.uniform(.005, .05)}
        stats = evaluate(candles, p); results.append({"params": p, "stats": stats})
    results.sort(key=lambda x: (x["stats"]["eligible"], x["stats"]["pnl_aud"] - 5000 * abs(min(x["stats"]["drawdown_pct"], 0)) ), reverse=True)
    return {"symbol": symbol, "candles": len(candles), "candidates": candidates, "top": results[:25], "eligible_count": sum(x["stats"]["eligible"] for x in results)}

if __name__ == "__main__":
    report = {"capital_aud": CAPITAL, "allocation": 1.0, "slippage_bps": 2, "fees": "AustralianSuper Member Direct brokerage; no admin fee", "results": [search("CSL"), search("TWE", seed=20261116)]}
    OUT.parent.mkdir(parents=True, exist_ok=True); OUT.write_text(json.dumps(report, indent=2))
    for item in report["results"]:
        print(item["symbol"], item["candles"], "candles", "eligible", item["eligible_count"])
        for candidate in item["top"][:5]: print(candidate["stats"], candidate["params"])
