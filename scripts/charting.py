"""Small chart renderer used by the US.APP dashboard."""
from __future__ import annotations

import base64
import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _png():
    buffer = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buffer, format="png", dpi=120)
    plt.close()
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def charts(frame, trades, equity):
    output = {}
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(frame.index, frame["close"], color="#2563eb", label="close")
    for trade in trades:
        ax.axvline(trade.entry_time, color="#16a34a", alpha=.35)
        ax.axvline(trade.exit_time, color="#dc2626", alpha=.35)
    ax.set_title("US.APP price and trades")
    output["price"] = _png()

    fig, ax = plt.subplots(figsize=(10, 4))
    if not equity.empty:
        ax.plot(equity.index, equity["equity"], color="#16a34a")
    ax.set_title("Equity")
    output["equity"] = _png()

    fig, ax = plt.subplots(figsize=(10, 4))
    if not equity.empty:
        monthly = equity["equity"].resample("M").last().pct_change().dropna()
        ax.bar(monthly.index.astype(str), monthly * 100, color="#64748b")
        ax.tick_params(axis="x", rotation=45)
    ax.set_title("Monthly returns (%)")
    output["monthly"] = _png()
    return output
