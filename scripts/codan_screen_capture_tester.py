#!/usr/bin/env python3
"""Run the local paper-trading tester against the stitched Codan screenshots.

This adapter deliberately reads the stitched SQLite view rather than the
Moomoo/OpenD cache. It is local research data, and every run records which
quality-filtered view was used.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strategy_57pct import BASELINE, optimize, run, stats
from australian_super_fees import australian_super_member_direct_fee
from scan_codan_intervals import aggregate


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "data" / "codan_screen_capture.sqlite3"
VIEWS = {"stitched_backtest_candles", "backtest_candles", "stitched_candles"}


def load_source(path: Path, view: str) -> tuple[pd.DataFrame, dict]:
    if view not in VIEWS:
        raise ValueError(f"unsupported view: {view}")
    with sqlite3.connect(path) as db:
        tables = {r[0] for r in db.execute("select name from sqlite_master where type in ('table','view')")}
        if view not in tables:
            raise ValueError(f"missing view {view!r} in {path}")
        columns = {r[1] for r in db.execute(f"pragma table_info({view})")}
        volume_sql = "volume" if "volume" in columns else "NULL AS volume"
        method_sql = "method" if "method" in columns else "'stitched' AS method"
        confidence_sql = "confidence" if "confidence" in columns else "'unknown' AS confidence"
        provenance_sql = "provenance" if "provenance" in columns else "'screen-capture reconstruction' AS provenance"
        frame = pd.read_sql_query(
            f"""select timestamp_local, open, high, low, close, {volume_sql}, {method_sql},
                       {confidence_sql}, {provenance_sql}
                from {view} order by timestamp_local""", db,
            parse_dates=["timestamp_local"],
        )
        integrity = db.execute("pragma integrity_check").fetchone()[0]
    if integrity != "ok":
        raise ValueError(f"source database integrity check failed: {integrity}")
    if frame.empty:
        raise ValueError("source view contains no candles")
    if frame["timestamp_local"].duplicated().any():
        dupes = frame.loc[frame["timestamp_local"].duplicated(), "timestamp_local"].astype(str).tolist()
        raise ValueError(f"duplicate candle timestamps are not allowed: {dupes[:5]}")
    frame = frame.set_index("timestamp_local")
    frame.index.name = "time_key"
    numeric = ["open", "high", "low", "close"]
    frame[numeric] = frame[numeric].astype(float)
    invalid = frame[(frame.high < frame[["open", "close"]].max(axis=1)) |
                    (frame.low > frame[["open", "close"]].min(axis=1)) |
                    (frame.low > frame.high)]
    if not invalid.empty:
        raise ValueError(f"source contains {len(invalid)} invalid OHLC rows")
    meta = {
        "source_db": str(path), "source_view": view,
        "rows": int(len(frame)), "start": str(frame.index.min()),
        "end": str(frame.index.max()),
        "methods": frame.method.value_counts().to_dict(),
        "confidence": frame.confidence.value_counts().to_dict(),
    }
    return frame, meta


def main() -> None:
    p = argparse.ArgumentParser(description="Backtest CDA candles built from 1h screen-capture data")
    p.add_argument("--source-db", type=Path, default=DEFAULT_SOURCE)
    p.add_argument("--view", choices=sorted(VIEWS), default="stitched_backtest_candles")
    p.add_argument("--bars", type=int, choices=range(1, 8), default=5,
                   help="1h bars per aggregate candle; default 5 uses the first five bars of each session and ignores the remaining hour")
    p.add_argument("--capital", type=float, default=200_000.0)
    p.add_argument("--allocation", type=float, default=.95)
    p.add_argument("--slippage-bps", type=float, default=2.0)
    p.add_argument("--trials", type=int, default=500)
    p.add_argument("--optimize", action="store_true")
    p.add_argument("--report-dir", type=Path, default=ROOT / "reports")
    args = p.parse_args()

    raw_candles, source_meta = load_source(args.source_db, args.view)
    candles = aggregate(raw_candles, args.bars)
    if candles.empty:
        raise ValueError("aggregation produced no candles")
    source_meta.update({
        "raw_rows": source_meta["rows"],
        "rows": int(len(candles)),
        "base_interval": "1h",
        "aggregation_bars": args.bars,
        "effective_interval": f"{args.bars}h",
        "discarded_remainder_hours_per_session": max(0, 6 - args.bars),
    })
    params = dict(BASELINE)
    optimization = []
    if args.optimize:
        optimization = optimize(candles, params, args.capital, args.allocation,
                                args.slippage_bps, 0.0, trials=args.trials,
                                fee_model=australian_super_member_direct_fee)
        if optimization:
            params.update(optimization[0]["params"])
    _, trades, data = run(candles, params, args.capital, args.allocation,
                          args.slippage_bps, 0.0, fee_model=australian_super_member_direct_fee)
    stats_result = stats(trades, data, args.capital)
    result = {
        "source": source_meta,
        "interval": f"{args.bars}h", "symbol": "ASX:CDA",
        "params": params,
        "stats": stats_result,
        "trades": [t.__dict__ for t in trades],
        "optimization_top": optimization[:10],
        "warning": "Screen-reconstructed candles are estimates; use for research only.",
        "fee_model": "AustralianSuper Member Direct transaction brokerage only: A$10 first A$12,500; 0.08% next A$37,500; 0.04% above A$50,000; no account administration fee",
    }
    args.report_dir.mkdir(parents=True, exist_ok=True)
    stem = f"cda_{args.bars}h_{args.view}"
    (args.report_dir / f"{stem}.json").write_text(json.dumps(result, indent=2, default=str))
    candles.index.name = "time_key"
    export = candles.reset_index()
    for column, default in (("method", "aggregated"), ("confidence", "inherited"),
                            ("provenance", "causal 1h aggregation")):
        if column not in export:
            export[column] = default
    export = export[["time_key", "open", "high", "low", "close", "method", "confidence", "provenance"]]
    export.to_csv(args.report_dir / f"{stem}.csv", index=False)
    print(json.dumps({"source": source_meta, "params": params, "stats": result["stats"],
                      "report": str(args.report_dir / f"{stem}.json")}, indent=2, default=str))


if __name__ == "__main__":
    main()
