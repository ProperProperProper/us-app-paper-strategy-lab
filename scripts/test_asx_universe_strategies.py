#!/usr/bin/env python3
"""Run fixed local strategies across the cached ASX research universe.

This is deliberately a comparison harness, not an optimiser. It uses only
completed daily candles from the local SQLite cache, the causal local strategy
engine, A$200,000 per-symbol starting capital, 95% allocation, 2 bps slippage,
and AustralianSuper Member Direct brokerage. The annual administration fee is
not included, matching the research configuration.

Daily candles are not equivalent to the Android app's five-hour session
candles. The app-style row is therefore labelled as a daily proxy.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))

from australian_super_fees import australian_super_member_direct_fee
from strategy_57pct import BASELINE, run, stats


ORIGINAL_UNIVERSE = (
    "CDA BHP CBA CSL WES RIO FMG GMG WOW ALL AMC ANZ NAB WBC MQG "
    "TCL CPU REA WTC XRO CAR SEK RMD MIN NXT STO S32 QAN COL TWE"
).split()

APP_DAILY_PROXY = {
    **BASELINE,
    "lookback": 10,
    "fast": 30,
    "slow": 137,
    "regime_ema": 89,
}


def load_daily(db_path: Path, symbol: str) -> pd.DataFrame:
    with sqlite3.connect(db_path) as db:
        frame = pd.read_sql_query(
            """SELECT session_date, open, high, low, close, volume
               FROM daily_candles WHERE symbol = ? ORDER BY session_date""",
            db,
            params=(symbol,),
            parse_dates=["session_date"],
        )
    if frame.empty:
        raise ValueError(f"no cached candles for {symbol}")
    frame = frame.set_index("session_date")
    frame.index = frame.index.tz_localize(None)
    frame.index.name = "time_key"
    required = ["open", "high", "low", "close"]
    frame[required] = frame[required].astype(float)
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError(f"invalid date sequence for {symbol}")
    invalid = frame[(frame.high < frame[["open", "close"]].max(axis=1)) |
                    (frame.low > frame[["open", "close"]].min(axis=1)) |
                    (frame.low > frame.high)]
    if not invalid.empty:
        raise ValueError(f"invalid OHLC rows for {symbol}: {len(invalid)}")
    return frame


def test_one(frame: pd.DataFrame, params: dict, capital: float) -> dict:
    _, trades, data = run(
        frame,
        params,
        capital=capital,
        allocation=0.95,
        slippage_bps=2.0,
        fee_model=australian_super_member_direct_fee,
    )
    result = stats(trades, data, capital)
    result["brokerage_model"] = "AustralianSuper Member Direct"
    result["administration_fee_included"] = False
    result["slippage_bps_per_side"] = 2.0
    result["allocation"] = 0.95
    result["params"] = params
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "data/asx_daily_yfinance.sqlite3")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/asx_universe_fixed_strategy_results.json")
    parser.add_argument("--capital", type=float, default=200_000.0)
    parser.add_argument("--days", type=int, default=42, help="latest calendar-day window to test")
    parser.add_argument("--exclude", default="", help="space/comma separated symbols to omit from local research")
    args = parser.parse_args()

    excluded = {x.strip().upper() for x in args.exclude.replace(",", " ").split() if x.strip()}
    symbols = [symbol for symbol in ORIGINAL_UNIVERSE if symbol not in excluded]
    results = []
    for symbol in symbols:
        frame = load_daily(args.db, symbol)
        window_start = frame.index.max() - timedelta(days=args.days - 1)
        frame = frame.loc[frame.index >= window_start]
        results.append({
            "symbol": symbol,
            "rows": len(frame),
            "start": str(frame.index.min().date()),
            "end": str(frame.index.max().date()),
            "research_baseline": test_one(frame, BASELINE, args.capital),
            "app_style_daily_proxy": test_one(frame, APP_DAILY_PROXY, args.capital),
        })
        print(
            f"{symbol:4s} rows={len(frame):5d} "
            f"baseline={results[-1]['research_baseline']['total_return_pct']:8.2f}% "
            f"proxy={results[-1]['app_style_daily_proxy']['total_return_pct']:8.2f}%",
            flush=True,
        )

    def ranking(key: str) -> list[dict]:
        return sorted(
            results,
            key=lambda row: (
                row[key]["total_return_pct"],
                row[key]["max_drawdown_pct"],
                row[key]["trades"],
            ),
            reverse=True,
        )

    report = {
        "source_db": str(args.db),
        "symbols_requested": symbols,
        "symbols_tested": len(results),
        "starting_capital_per_symbol": args.capital,
        "data_interval": "1D",
        "window_calendar_days": args.days,
        "execution": "signal on completed daily bar; entry at next available daily open",
        "costs": {
            "brokerage": "AustralianSuper Member Direct progressive brokerage",
            "administration_fee_included": False,
            "slippage_bps_per_side": 2.0,
        },
        "warning": "The app-style daily proxy is not equivalent to the Android 5H CDA strategy.",
        "results": results,
        "rankings": {
            "research_baseline": [row["symbol"] for row in ranking("research_baseline")],
            "app_style_daily_proxy": [row["symbol"] for row in ranking("app_style_daily_proxy")],
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"\nSaved {args.output}")
    for label, key in (("research baseline", "research_baseline"), ("app-style daily proxy", "app_style_daily_proxy")):
        print(f"\nTop {label}:")
        for row in ranking(key)[:10]:
            metric = row[key]
            print(f"{row['symbol']:4s} return={metric['total_return_pct']:8.2f}% DD={metric['max_drawdown_pct']:8.2f}% trades={metric['trades']:3d} win={metric['win_rate_pct']:6.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
