#!/usr/bin/env python3
"""Persist causal higher-interval candles aggregated from CDA 1-hour bars."""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from scan_codan_intervals import aggregate, load


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-db", type=Path, default=Path("data/codan_screen_capture.sqlite3"))
    ap.add_argument("--source-view", default="stitched_candles")
    ap.add_argument("--bars", type=int, default=5)
    ap.add_argument("--output", type=Path, default=Path("data/codan_5h_aggregated.sqlite3"))
    args = ap.parse_args()
    if args.bars < 2:
        ap.error("--bars must be at least 2 for an aggregated interval")

    raw = load(args.source_db, args.source_view)
    candles = aggregate(raw, args.bars)
    if candles.empty:
        ap.error("aggregation produced no candles")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(args.output)
    con.executescript(
        """
        DROP TABLE IF EXISTS candles;
        CREATE TABLE candles (
            symbol TEXT NOT NULL,
            source_view TEXT NOT NULL,
            base_interval TEXT NOT NULL,
            interval TEXT NOT NULL,
            timestamp_local TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            PRIMARY KEY(symbol, interval, timestamp_local)
        );
        """
    )
    con.executemany(
        "INSERT INTO candles VALUES(?,?,?,?,?,?,?,?,?)",
        [
            ("CDA", args.source_view, "1h", f"{args.bars}h", stamp.isoformat(sep=" "),
             float(row.open), float(row.high), float(row.low), float(row.close))
            for stamp, row in candles.iterrows()
        ],
    )
    con.commit()
    print(f"Wrote {len(candles)} CDA {args.bars}h candles to {args.output}")
    print(f"Range: {candles.index.min()} .. {candles.index.max()}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
