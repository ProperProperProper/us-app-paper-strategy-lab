#!/usr/bin/env python3
"""Download ASX daily candles from Yahoo Finance into a local SQLite store.

This is deliberately separate from the reconstructed screen-capture database.
Rows are keyed by (symbol, session_date), so repeated runs update existing
observations rather than creating duplicates.
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf


DEFAULT_SYMBOLS = "CDA,BHP,CBA,CSL,WES,RIO,FMG,GMG,WOW,ALL,AMC,ANZ,NAB,WBC, MQG,"
DEFAULT_SYMBOLS += "TCL,CPU,REA,WTC,XRO,CAR,SEK,RMD,MIN,NXT,STO,S32,QAN,COL,TWE"


def parse_symbols(value: str) -> list[str]:
    result: list[str] = []
    for raw in value.replace("\n", ",").split(","):
        symbol = raw.strip().upper().replace(".AX", "")
        if symbol and symbol not in result:
            result.append(symbol)
    return result


def init_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS daily_candles (
            symbol TEXT NOT NULL,
            session_date TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            adj_close REAL,
            volume REAL,
            dividends REAL DEFAULT 0,
            stock_splits REAL DEFAULT 0,
            source TEXT NOT NULL DEFAULT 'yfinance',
            downloaded_at TEXT NOT NULL,
            PRIMARY KEY (symbol, session_date)
        );
        CREATE INDEX IF NOT EXISTS idx_daily_candles_symbol_date
            ON daily_candles(symbol, session_date);
        CREATE TABLE IF NOT EXISTS download_runs (
            run_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            period TEXT NOT NULL,
            interval TEXT NOT NULL,
            symbols_requested INTEGER NOT NULL,
            symbols_succeeded INTEGER NOT NULL DEFAULT 0,
            rows_written INTEGER NOT NULL DEFAULT 0,
            notes TEXT
        );
        CREATE TABLE IF NOT EXISTS download_symbols (
            run_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            yahoo_ticker TEXT NOT NULL,
            status TEXT NOT NULL,
            rows_received INTEGER NOT NULL DEFAULT 0,
            first_date TEXT,
            last_date TEXT,
            error TEXT,
            PRIMARY KEY (run_id, symbol)
        );
        """
    )
    con.commit()
    return con


def scalar(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def download_one(symbol: str, period: str) -> pd.DataFrame:
    ticker = f"{symbol}.AX"
    frame = yf.download(
        ticker,
        period=period,
        interval="1d",
        auto_adjust=False,
        actions=True,
        progress=False,
        threads=False,
        group_by="column",
    )
    if frame is None or frame.empty:
        return pd.DataFrame()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = [col[0] for col in frame.columns]
    frame = frame.reset_index()
    frame.columns = [str(col).lower().replace(" ", "_") for col in frame.columns]
    if "date" not in frame:
        return pd.DataFrame()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return frame.dropna(subset=["date", "open", "high", "low", "close"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/asx_daily_yfinance.sqlite3"))
    parser.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    parser.add_argument("--period", default="max", help="Yahoo Finance period, normally max")
    args = parser.parse_args()

    symbols = parse_symbols(args.symbols)
    con = init_db(args.db)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    started = datetime.now(timezone.utc).isoformat()
    con.execute(
        "INSERT INTO download_runs(run_id,started_at,period,interval,symbols_requested) VALUES(?,?,?,?,?)",
        (run_id, started, args.period, "1d", len(symbols)),
    )
    con.commit()

    succeeded = 0
    total_written = 0
    for symbol in symbols:
        ticker = f"{symbol}.AX"
        try:
            frame = download_one(symbol, args.period)
            now = datetime.now(timezone.utc).isoformat()
            rows = 0
            for row in frame.itertuples(index=False):
                values = {str(k): getattr(row, str(k)) for k in frame.columns}
                # Reject malformed bars before they can enter the research store.
                o, h, low, close = (scalar(values.get(k)) for k in ("open", "high", "low", "close"))
                if None in (o, h, low, close) or low > min(o, close) or h < max(o, close):
                    continue
                con.execute(
                    """
                    INSERT INTO daily_candles
                    (symbol,session_date,open,high,low,close,adj_close,volume,dividends,stock_splits,source,downloaded_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(symbol,session_date) DO UPDATE SET
                      open=excluded.open, high=excluded.high, low=excluded.low,
                      close=excluded.close, adj_close=excluded.adj_close,
                      volume=excluded.volume, dividends=excluded.dividends,
                      stock_splits=excluded.stock_splits, downloaded_at=excluded.downloaded_at
                    """,
                    (symbol, values["date"], o, h, low, close,
                     scalar(values.get("adj_close")), scalar(values.get("volume")),
                     scalar(values.get("dividends")) or 0.0, scalar(values.get("stock_splits")) or 0.0,
                     "yfinance", now),
                )
                rows += 1
            first = frame["date"].min() if rows else None
            last = frame["date"].max() if rows else None
            con.execute(
                "INSERT INTO download_symbols VALUES(?,?,?,?,?,?,?,?)",
                (run_id, symbol, ticker, "ok" if rows else "empty", rows, first, last, None),
            )
            succeeded += bool(rows)
            total_written += rows
            print(f"{symbol:5s} {rows:5d} rows {first or '-'} .. {last or '-'}", flush=True)
        except Exception as exc:  # keep the batch moving when one Yahoo symbol fails
            con.execute(
                "INSERT INTO download_symbols VALUES(?,?,?,?,?,?,?,?)",
                (run_id, symbol, ticker, "error", 0, None, None, str(exc)[:500]),
            )
            print(f"{symbol:5s} ERROR {exc}", flush=True)
        con.commit()

    completed = datetime.now(timezone.utc).isoformat()
    con.execute(
        "UPDATE download_runs SET completed_at=?,symbols_succeeded=?,rows_written=? WHERE run_id=?",
        (completed, succeeded, total_written, run_id),
    )
    con.commit()
    count, distinct_symbols, first_date, last_date = con.execute(
        "SELECT count(*),count(DISTINCT symbol),min(session_date),max(session_date) FROM daily_candles"
    ).fetchone()
    print(f"\nDatabase: {args.db}")
    print(f"Stored: {count:,} rows across {distinct_symbols} symbols, {first_date} .. {last_date}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
