#!/usr/bin/env python3
"""Download the 42-day hourly ASX universe and test fixed 5H strategies.

The downloader is intentionally capped at 42 calendar days. The test keeps
the first five completed ASX session hours and discards the final session
hours, matching the app's five-hour aggregation convention. BHP is included
only in this local research universe; it is not part of the Android app.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "asx-cda-5h-breakout-backtester"))
from moomoo_fees import moomoo_au_asx_fee
from strategy_57pct import BASELINE, run, stats

SYMBOLS = "CDA BHP CBA CSL WES RIO FMG GMG WOW ALL AMC ANZ NAB WBC MQG TCL CPU REA WTC XRO CAR SEK RMD MIN NXT STO S32 QAN COL TWE".split()
APP_PARAMS = {
    **BASELINE,
    "lookback": 10,
    "fast": 30,
    "slow": 137,
    "tp": 0.2205,
    "stop": 0.1609,
    "break_even_trigger": 0.0484,
    "break_even_lock": 0.0099,
    "profit_lock_trigger": 0.0758,
    "profit_lock": 0.0292,
    "trail_trigger": 0.2,
    "trail_pct": 0.0623,
}


def init_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS hourly_candles (
        symbol TEXT NOT NULL, timestamp_local TEXT NOT NULL,
        open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL,
        close REAL NOT NULL, volume REAL NOT NULL, source TEXT NOT NULL,
        downloaded_at TEXT NOT NULL, PRIMARY KEY(symbol, timestamp_local))""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_hourly_symbol_time ON hourly_candles(symbol, timestamp_local)")
    db.commit()
    return db


def download(symbol: str, days: int) -> pd.DataFrame:
    frame = yf.download(
        f"{symbol}.AX", period=f"{days}d", interval="1h", auto_adjust=False,
        actions=False, progress=False, threads=False, group_by="column",
    )
    if frame is None or frame.empty:
        return pd.DataFrame()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = [col[0].lower() for col in frame.columns]
    else:
        frame.columns = [str(col).lower() for col in frame.columns]
    frame = frame.reset_index()
    time_col = next(col for col in frame.columns if str(col).lower() in {"datetime", "date"})
    frame[time_col] = pd.to_datetime(frame[time_col], utc=True).dt.tz_convert("Australia/Sydney").dt.tz_localize(None)
    frame = frame.rename(columns={time_col: "timestamp_local"})
    frame = frame.dropna(subset=["timestamp_local", "open", "high", "low", "close"])
    return frame[["timestamp_local", "open", "high", "low", "close", "volume"]].sort_values("timestamp_local")


def aggregate(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    frame = frame.copy()
    frame["session_date"] = frame["timestamp_local"].dt.date
    for _, group in frame.groupby("session_date"):
        group = group[(group.timestamp_local.dt.hour >= 10) & (group.timestamp_local.dt.hour <= 15)].sort_values("timestamp_local")
        hours = group.drop_duplicates("timestamp_local").iloc[:6]
        if len(hours) < 6:
            continue
        bars = hours.iloc[:5]
        rows.append({
            # The last included bar is 14:00-15:00.  Timestamp the aggregate
            # at its close so consumers can act only after the 5H candle is
            # complete, during the remaining 15:00-16:00 session hour.
            "timestamp_local": bars.timestamp_local.iloc[-1] + pd.Timedelta(hours=1),
            "open": float(bars.open.iloc[0]), "high": float(bars.high.max()),
            "low": float(bars.low.min()), "close": float(bars.close.iloc[-1]),
            "volume": float(bars.volume.sum()),
        })
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    return pd.DataFrame(rows).set_index("timestamp_local").sort_index()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=42)
    ap.add_argument("--db", type=Path, default=ROOT / "data/asx_hourly_yfinance_42d.sqlite3")
    ap.add_argument("--output", type=Path, default=ROOT / "reports/asx_42d_hourly_5h_strategy_results.json")
    ap.add_argument("--exclude", default="")
    args = ap.parse_args()
    if args.days > 42:
        raise SystemExit("--days cannot exceed the 42-day provider limit")
    excluded = {x.strip().upper() for x in args.exclude.replace(",", " ").split() if x.strip()}
    symbols = [s for s in SYMBOLS if s not in excluded]
    db = init_db(args.db)
    report_rows = []
    now = datetime.now(timezone.utc).isoformat()
    for symbol in symbols:
        raw = download(symbol, args.days)
        for row in raw.itertuples(index=False):
            db.execute("""INSERT INTO hourly_candles VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(symbol,timestamp_local) DO UPDATE SET
                open=excluded.open, high=excluded.high, low=excluded.low,
                close=excluded.close, volume=excluded.volume, downloaded_at=excluded.downloaded_at""",
                (symbol, row.timestamp_local.isoformat(), float(row.open), float(row.high), float(row.low), float(row.close), float(row.volume or 0), "yfinance", now))
        db.commit()
        five = aggregate(raw)
        if len(five) < 2:
            print(f"{symbol:4s} hourly={len(raw):4d} 5h={len(five):3d} insufficient")
            continue
        _, trades_base, data_base = run(five, dict(BASELINE), 200_000, .95, 2, 0, fee_model=moomoo_au_asx_fee)
        _, trades_app, data_app = run(five, dict(APP_PARAMS), 200_000, .95, 2, 0, fee_model=moomoo_au_asx_fee)
        row = {"symbol": symbol, "hourly_rows": len(raw), "five_hour_rows": len(five), "start": str(five.index.min()), "end": str(five.index.max()), "research_baseline": stats(trades_base, data_base, 200_000), "app_cda_parameters": stats(trades_app, data_app, 200_000)}
        report_rows.append(row)
        print(f"{symbol:4s} hourly={len(raw):4d} 5h={len(five):3d} baseline={row['research_baseline']['total_return_pct']:7.2f}% app={row['app_cda_parameters']['total_return_pct']:7.2f}% trades={row['app_cda_parameters']['trades']}", flush=True)
    db.close()
    report = {"source": "Yahoo Finance chart endpoint via yfinance", "window_days": args.days, "symbols_tested": len(report_rows), "symbols": symbols, "base_interval": "1h", "effective_interval": "5h", "session_hours_used": "10:00-14:00 Australia/Sydney", "final_session_hours_discarded": "15:00-16:00", "starting_capital_per_symbol": 200_000, "allocation": .95, "slippage_bps_per_side": 2, "brokerage": "Moomoo AU ASX transaction brokerage", "annual_admin_fee_included": False, "warning": "42-day limited-cache run; the app-style strategy is not fully warmed when 137 five-hour bars are unavailable.", "results": report_rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(f"\nSaved {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
