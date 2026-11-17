"""Exact local implementation of the GitHub 10-minute winner.

Source model: the local Donchian/EMA baseline research implementation.
Winner: lookback 33, EMA 17/26, TP 2.74%, stop 13.24%.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, asdict
from datetime import time

import numpy as np
import pandas as pd


BASELINE = {
    "lookback": 33, "fast": 17, "slow": 26,
    # Exact Moomoo Quant exit defaults.
    "tp": 0.1069, "stop": 0.0354,
    "break_even_trigger": 0.02, "break_even_lock": 0.002,
    "profit_lock_trigger": 0.08, "profit_lock": 0.01,
    "trail_trigger": 0.06, "trail_pct": 0.02,
    "entry_filter": "none", "atr_buffer": 0.10, "volume_median_period": 20,
}
ALLOCATION = 1.0
SESSION_END = time(15, 45)
EMA_WARMUP_MULTIPLIER = 1


def required_warmup_candles(params: dict = BASELINE) -> int:
    """Return the minimum causal history before this imitation may signal.

    The local strategy is an imitation of the frozen research rule, not a
    claim about any proprietary system.  EMA values are technically defined
    from the first row, but signals are withheld until the largest strategy
    lookback exists.  This is the operational minimum; it avoids making a
    short sample look tradable without requiring multiple years of history.
    """
    slow = int(params.get("slow", BASELINE["slow"]))
    regime = int(params.get("regime_ema", 89))
    lookback = int(params.get("lookback", BASELINE["lookback"]))
    slope_window = int(params.get("regime_window", 18))
    slope_lag = int(params.get("regime_lag", 12))
    return max(
        EMA_WARMUP_MULTIPLIER * slow,
        EMA_WARMUP_MULTIPLIER * regime,
        lookback + 1,
        slope_window * 2 + slope_lag,
    )


@dataclass
class Trade:
    signal_time: str
    entry_time: str
    entry_price: float
    qty: int
    exit_time: str
    exit_price: float
    gross_pnl: float
    costs: float
    net_pnl: float
    return_pct: float
    reason: str


def add_features(candles: pd.DataFrame, params: dict = BASELINE) -> pd.DataFrame:
    x = candles.copy().sort_index()
    close = x["close"].astype(float)
    x["ema_fast"] = close.ewm(span=int(params["fast"]), adjust=False).mean()
    x["ema_slow"] = close.ewm(span=int(params["slow"]), adjust=False).mean()
    x["prior_high"] = x["high"].shift(1).rolling(int(params["lookback"])).max()
    breakout = close > x["prior_high"]
    trend_up = (x["ema_fast"] > x["ema_slow"]) & (close > x["ema_slow"])
    previous_cross_up = (x["ema_fast"].shift(1) <= x["ema_slow"].shift(1)) & trend_up
    entry_mode = params.get("entry_mode", "breakout_trend")
    x["entry_signal"] = {
        "breakout": breakout,
        "breakout_trend": breakout & trend_up,
        "ema_cross": previous_cross_up,
        "breakout_or_cross": (breakout & trend_up) | previous_cross_up,
    }.get(entry_mode, breakout & trend_up).fillna(False)
    x["breakout"] = breakout.fillna(False)
    previous_close = close.shift(1).fillna(close)
    true_range = pd.concat([
        x["high"] - x["low"],
        (x["high"] - previous_close).abs(),
        (x["low"] - previous_close).abs(),
    ], axis=1).max(axis=1)
    x["atr14"] = true_range.rolling(14, min_periods=1).mean()
    volume_period = int(params.get("volume_median_period", 20))
    entry_filter = {
        "none": True,
        "atr": close > x["prior_high"] + float(params.get("atr_buffer", 0.10)) * x["atr14"],
        "slope": (x["ema_fast"] > x["ema_fast"].shift(1)) & (x["ema_slow"] > x["ema_slow"].shift(1)),
        "volume": x["volume"] > x["volume"].shift(1).rolling(volume_period).median(),
    }.get(params.get("entry_filter", "none"), True)
    x["entry_signal"] = (x["entry_signal"] & entry_filter).fillna(False)
    x["yellow_exit"] = ((close < x["ema_fast"]) & (close >= x["ema_slow"]) & (x["ema_fast"] > x["ema_slow"])).fillna(False)
    x["red_exit"] = (close < x["ema_slow"]).fillna(False)
    x["trend_exit"] = (x["red_exit"] & (x["ema_fast"] < x["ema_slow"])).fillna(False)
    x["exit_signal"] = {
        "fast_or_slow": x["yellow_exit"] | x["red_exit"],
        "slow_break": x["red_exit"],
        "trend_cross": x["ema_fast"] < x["ema_slow"],
    }.get(params.get("exit_mode", "fast_or_slow"), x["yellow_exit"] | x["red_exit"]).fillna(False)
    # Causal downtrend gate: every input is known at the completed signal bar.
    # It requires agreement between slow-EMA drift, log-price regression drift,
    # and distance from the recent peak, so a normal pullback does not get
    # blocked by one noisy candle.
    slope_window = int(params.get("regime_window", 18))
    slope_lag = int(params.get("regime_lag", 12))
    log_close = np.log(close.clip(lower=1e-12))
    x["slow_drift"] = x["ema_slow"].pct_change(slope_lag)
    x["regime_ema"] = close.ewm(span=int(params.get("regime_ema", 89)), adjust=False).mean()
    x["regime_drift"] = x["regime_ema"].pct_change(slope_lag)
    x["log_slope"] = log_close.rolling(slope_window).apply(
        lambda v: float(np.polyfit(np.arange(len(v)), v, 1)[0]), raw=True
    )
    x["recent_peak"] = close.shift(1).rolling(slope_window * 2).max()
    x["peak_distance"] = close / x["recent_peak"] - 1.0
    x["downtrend_blocked"] = (
        (x["slow_drift"] <= -0.002)
        & (x["log_slope"] <= -0.001)
        & (x["peak_distance"] <= -0.015)
        | ((x["regime_drift"] <= -0.001) & (close < x["regime_ema"]))
    ).fillna(False)
    required = required_warmup_candles(params)
    # The app is intentionally confined to its locally cached history.  Use
    # all available history as the operational seed when the full theoretical
    # warm-up is unavailable, while reporting that limitation to the lab.
    effective_warmup = min(required, len(x))
    x["warmup_ready"] = np.arange(len(x)) >= effective_warmup - 1
    x.attrs["fast"] = int(params["fast"]); x.attrs["slow"] = int(params["slow"])
    x.attrs["required_warmup_candles"] = required
    x.attrs["effective_warmup_candles"] = effective_warmup
    x.attrs["params"] = dict(params)
    return x.dropna(subset=["prior_high"])


def strategy_signal(frame: pd.DataFrame, params: dict = BASELINE) -> dict:
    data = frame.copy()
    if "time_key" in data.columns:
        data["time_key"] = pd.to_datetime(data["time_key"])
        data = data.set_index("time_key")
    x = add_features(data, params)
    if len(x) < 2:
        raise ValueError("not enough completed candles")
    bar = x.iloc[-2]
    bar_time = pd.Timestamp(x.index[-2]).time()
    warmup_ready = bool(bar.warmup_ready)
    return {"bar": str(x.index[-2]), "close": float(bar.close), "ema_fast": float(bar.ema_fast), "ema_slow": float(bar.ema_slow), "raw_long_signal": bool(bar.entry_signal), "downtrend_blocked": bool(bar.downtrend_blocked), "long_signal": warmup_ready and bool(bar.entry_signal) and not bool(bar.downtrend_blocked), "yellow_exit": warmup_ready and bool(bar.yellow_exit), "red_exit": warmup_ready and bool(bar.red_exit), "trend_exit": warmup_ready and bool(bar.trend_exit), "entry_allowed": warmup_ready and bar_time < time(15, 40), "session_exit": bar_time >= time(15, 40), "warmup_ready": warmup_ready, "warmup_status": "FULL" if len(x) >= int(x.attrs["required_warmup_candles"]) else "LIMITED_CACHE", "required_warmup_candles": int(x.attrs["required_warmup_candles"]), "effective_warmup_candles": int(x.attrs["effective_warmup_candles"])}


def _validate_candles(candles: pd.DataFrame) -> None:
    if not candles.index.is_monotonic_increasing:
        raise ValueError("candles must be sorted chronologically")
    if candles.index.has_duplicates:
        raise ValueError("duplicate candle timestamps are not allowed")
    required = {"open", "high", "low", "close"}
    missing = required.difference(candles.columns)
    if missing:
        raise ValueError(f"missing candle columns: {sorted(missing)}")


def _validate_trades(trades) -> None:
    previous_exit = None
    seen = set()
    for trade in trades:
        key = (trade.signal_time, trade.entry_time, trade.exit_time)
        if key in seen:
            raise ValueError("duplicate trade detected")
        seen.add(key)
        if not (trade.signal_time <= trade.entry_time <= trade.exit_time):
            raise ValueError("look-ahead or invalid trade chronology detected")
        if previous_exit is not None and trade.entry_time < previous_exit:
            raise ValueError("overlapping trades detected")
        previous_exit = trade.exit_time


def run(candles: pd.DataFrame, params: dict = BASELINE, capital: float = 100000.0, allocation: float = ALLOCATION, slippage_bps: float = 2.0, commission: float = 0.0, evaluation_start=None, fee_model=None):
    """Run the causal imitation with signal-candle-close execution.

    A completed 5H candle produces its signal at the close; the unused final
    session hour is the execution window. No next-candle data is consulted.
    """
    _validate_candles(candles)
    x = add_features(candles, params)
    rows = list(x.iterrows()); cash = float(capital); position = None; trades = []; equity_rows = []; slip = slippage_bps / 10000.0
    for row_index, (stamp, bar) in enumerate(rows):
        if evaluation_start is not None and stamp < pd.Timestamp(evaluation_start): continue
        if not bool(bar.warmup_ready):
            continue
        mark = cash + (position["qty"] * float(bar.close) if position else 0.0)
        equity_rows.append({"date": stamp, "equity": mark})
        if position:
            entry = position["entry"]
            price = float(bar.close)
            position["peak_price"] = max(position["peak_price"], price, entry)
            if price >= entry * float(params.get("break_even_trigger", 0.02)) + entry:
                position["break_even_armed"] = True
            if position["peak_price"] >= entry * (1 + float(params.get("profit_lock_trigger", 0.08))):
                position["profit_lock_armed"] = True
            stop = entry * (1 - float(params.get("stop", 0.0354)))
            if position["break_even_armed"]:
                stop = max(stop, entry * (1 + float(params.get("break_even_lock", 0.002))))
            if position["profit_lock_armed"]:
                stop = max(stop, entry * (1 + float(params.get("profit_lock", 0.01))))
            if position["peak_price"] >= entry * (1 + float(params.get("trail_trigger", 0.06))):
                stop = max(stop, position["peak_price"] * (1 - float(params.get("trail_pct", 0.02))))
            target = entry * (1 + float(params.get("tp", 0.1069)))
            take_profit = price >= target
            stop_loss = price <= stop
            reason = None; exit_raw = None; exit_time = stamp
            if take_profit: exit_raw, reason = float(bar.close), "TP"
            elif stop_loss: exit_raw, reason = float(bar.close), "STOP"
            max_holding = int(params.get("max_holding_bars", 0))
            time_stop = max_holding > 0 and (row_index - position["entry_index"]) >= max_holding
            if reason is None and time_stop: exit_raw, reason = float(bar.close), "TIME_STOP"
            elif bool(bar.exit_signal): exit_raw, reason = float(bar.close), "RULE_EXIT"
            if reason:
                exit_price = exit_raw * (1 - slip); gross = (exit_price - entry) * position["qty"]
                exit_fee = fee_model(position["qty"] * exit_price) if fee_model else commission
                costs = position["entry_fee"] + exit_fee; net = gross - costs; cash += position["qty"] * exit_price - exit_fee
                trades.append(Trade(position["signal_time"].isoformat(), position["entry_time"].isoformat(), entry, position["qty"], exit_time.isoformat(), exit_price, gross, costs, net, net / (entry * position["qty"]) * 100, reason)); position = None; continue
        gate_on = bool(params.get("downtrend_filter", True))
        # The five-hour candle is complete at this close.  The strategy is
        # allowed to act in the remaining ASX session hour, so execution is
        # the signal candle close, never the next session's open.
        if position is None and bool(bar.entry_signal) and (not gate_on or not bool(bar.downtrend_blocked)):
            entry = float(bar.close) * (1 + slip); qty = math.floor(cash * allocation / entry)
            if qty > 0:
                entry_fee = fee_model(qty * entry) if fee_model else commission
                cash -= qty * entry + entry_fee
                position = {"signal_time": stamp, "entry_time": stamp, "entry": entry, "qty": qty, "entry_fee": entry_fee, "peak_price": entry, "break_even_armed": False, "profit_lock_armed": False, "entry_index": row_index}
    if position and rows:
        stamp, bar = rows[-1]; exit_price = float(bar.close) * (1 - slip); gross = (exit_price - position["entry"]) * position["qty"]
        exit_fee = fee_model(position["qty"] * exit_price) if fee_model else commission
        costs = position["entry_fee"] + exit_fee; net = gross - costs; cash += position["qty"] * exit_price - exit_fee
        trades.append(Trade(position["signal_time"].isoformat(), position["entry_time"].isoformat(), position["entry"], position["qty"], stamp.isoformat(), exit_price, gross, costs, net, net / (position["entry"] * position["qty"]) * 100, "MARK_TO_MARKET"))
        position = None
    equity = pd.DataFrame(equity_rows).set_index("date") if equity_rows else pd.DataFrame(columns=["equity"])
    if position is None and rows and (equity.empty or equity.index[-1] != rows[-1][0]):
        equity.loc[rows[-1][0], "equity"] = cash
    if not equity.empty: equity["drawdown"] = equity.equity / equity.equity.cummax() - 1
    _validate_trades(trades)
    return x, trades, {"equity": equity, "ending_cash": cash}


def _stats(trades, equity, capital):
    returns = np.array([t.net_pnl / (t.entry_price * t.qty) for t in trades]) if trades else np.array([])
    compounded = np.cumprod(1 + returns) if len(returns) else np.array([1.0])
    ending = capital * float(compounded[-1])
    gains = returns[returns > 0].sum() if len(returns) else 0; losses = -returns[returns < 0].sum() if len(returns) else 0
    dd = compounded / np.maximum.accumulate(compounded) - 1
    daily = equity["equity"].resample("1D").last().pct_change(fill_method=None).dropna() if not equity.empty else pd.Series(dtype=float)
    return {
        "starting_capital": round(float(capital), 2),
        "ending_equity": round(ending, 2),
        "total_return_pct": round((ending / capital - 1) * 100, 3),
        "max_drawdown_pct": round(float(dd.min() * 100), 3) if len(dd) else 0,
        "trades": len(trades), "wins": int((returns > 0).sum()),
        "win_rate_pct": round(float((returns > 0).mean() * 100), 2) if len(returns) else 0,
        "profit_factor": round(float(gains / losses), 3) if losses else None,
        "average_trade_pct": round(float(returns.mean() * 100), 3) if len(returns) else 0,
        "sharpe_approx": round(float(daily.mean() / daily.std() * np.sqrt(252)), 3) if len(daily) > 1 and daily.std() else 0,
    }


def stats(trades, data, capital):
    """Dashboard-compatible metrics using the GitHub winner's compounding rule."""
    return _stats(trades, data["equity"] if isinstance(data, dict) else data, capital)


def optimize(candles, base=BASELINE, capital=100000.0, allocation=ALLOCATION, slippage_bps=2.0, commission=0.0, progress=None, trials=12000, seed=20261112, fee_model=None):
    """Same random ranges as the GitHub interval optimizer."""
    rng = random.Random(seed); rows = []
    for done in range(1, int(trials) + 1):
        p = {"lookback": rng.randint(5, 120), "fast": rng.randint(2, 30), "slow": rng.randint(10, 200), "tp": round(rng.uniform(.02, .50), 4), "stop": round(rng.uniform(.01, .25), 4)}
        if p["fast"] >= p["slow"]: continue
        _, trades, data = run(candles, p, capital, allocation, slippage_bps, commission, fee_model=fee_model)
        stats = _stats(trades, data["equity"], capital)
        if stats["trades"] >= 3: rows.append({"params": p, "stats": stats})
        if progress and (done % 100 == 0 or done == trials): progress(done, int(trials), f"GitHub 57% random trial {done:,}/{int(trials):,}")
    for row in rows:
        row["stats"]["selection_score"] = round(row["stats"]["total_return_pct"] - 0.35 * abs(row["stats"]["max_drawdown_pct"]), 3)
    return sorted(rows, key=lambda r: r["stats"]["selection_score"], reverse=True)[:25]


def walk_forward_optimize(candles, base=BASELINE, capital=100000.0, allocation=ALLOCATION, slippage_bps=2.0, commission=0.0, progress=None, trials=12000, seed=20261112, folds=3, fee_model=None):
    """Select parameters on each past window and score only the next unseen window."""
    frame = candles.sort_index(); n = len(frame); per_fold = max(1, int(trials) // folds); results = []
    for fold in range(folds):
        train_end = int(n * (0.50 + fold * (0.50 / folds)))
        test_end = int(n * (0.50 + (fold + 1) * (0.50 / folds)))
        if test_end > n: continue
        train = frame.iloc[:train_end]
        local_progress = (lambda done, total, msg, f=fold: progress(f * per_fold + done, trials, f"Walk-forward fold {f + 1}/{folds} · {msg}") if progress else None)
        candidates = optimize(train, base, capital, allocation, slippage_bps, commission, local_progress, per_fold, seed + fold, fee_model=fee_model)
        if not candidates: continue
        p = candidates[0]["params"]; test_start = frame.index[train_end]
        _, trades, data = run(frame.iloc[:test_end], p, capital, allocation, slippage_bps, commission, evaluation_start=test_start, fee_model=fee_model)
        result = _stats(trades, data["equity"], capital); result.update({"fold": fold + 1, "test_start": str(test_start), "test_end": str(frame.index[test_end - 1])})
        results.append({"params": p, "stats": result})
    if progress: progress(trials, trials, f"Walk-forward complete · {len(results)} unseen folds")
    return results


def walk_forward_replay(candles, fold_results, capital=100000.0, allocation=ALLOCATION,
                        slippage_bps=2.0, commission=0.0, fee_model=None):
    """Replay only the already-selected unseen folds, in chronological order."""
    frame = candles.sort_index(); all_trades = []; equity_parts = []; fold_capital = float(capital)
    for row in fold_results:
        p = row["params"]
        start = pd.Timestamp(row["stats"]["test_start"])
        end = pd.Timestamp(row["stats"]["test_end"])
        test_frame = frame.loc[:end]
        x, trades, data = run(test_frame, p, fold_capital, allocation, slippage_bps, commission, evaluation_start=start, fee_model=fee_model)
        all_trades.extend(trades)
        if not data["equity"].empty:
            equity_parts.append(data["equity"])
        fold_returns = np.array([t.net_pnl / (t.entry_price * t.qty) for t in trades])
        if len(fold_returns): fold_capital *= float(np.prod(1 + fold_returns))
    equity = pd.concat(equity_parts).sort_index() if equity_parts else pd.DataFrame(columns=["equity", "drawdown"])
    if not equity.empty:
        equity = equity[~equity.index.duplicated(keep="last")]
        equity["drawdown"] = equity.equity / equity.equity.cummax() - 1
    return add_features(frame, BASELINE), all_trades, {"equity": equity, "ending_cash": fold_capital}
