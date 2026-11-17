#!/usr/bin/env python3
"""Export a sanitized, deterministic candle snapshot for reproducible research."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from pathlib import Path


FIELDS = ("time_key", "open", "high", "low", "close", "volume")


def export_snapshot(db_path: Path, output: Path, symbol: str, interval: int,
                    start: str, end: str) -> dict:
    with sqlite3.connect(db_path) as db:
        rows = db.execute(
            """SELECT time_key, open, high, low, close, volume
               FROM candles
               WHERE symbol = ? AND interval_minutes = ?
                 AND datetime(time_key) >= datetime(?)
                 AND datetime(time_key) <= datetime(?)
               ORDER BY time_key""",
            (symbol, interval, start, end),
        ).fetchall()
    if not rows:
        raise RuntimeError("no candles matched the requested snapshot")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(FIELDS)
        writer.writerows(rows)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    manifest = {
        "symbol": symbol,
        "interval_minutes": interval,
        "start": rows[0][0],
        "end": rows[-1][0],
        "rows": len(rows),
        "columns": list(FIELDS),
        "source": "Moomoo OpenD cache; user-exported snapshot",
        "sha256": digest,
        "execution_note": "Use completed candles; this snapshot contains no credentials or account data.",
    }
    output.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("quant_dashboard.sqlite3"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--symbol", default="US.APP")
    parser.add_argument("--interval", type=int, default=10)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    args = parser.parse_args()
    print(json.dumps(export_snapshot(args.db, args.output, args.symbol, args.interval, args.start, args.end), indent=2))
