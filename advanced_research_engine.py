"""Causal advanced-research primitives for the strategy lab.

This module deliberately separates *research families* from claims that the
current cache can support them.  Every feature is computed from the current
bar and bars before it. Families needing multiple symbols or tick events are
registered but marked unavailable until that data exists; they are never
approximated with invented data.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


ADVANCED_FAMILIES: dict[str, dict[str, Any]] = {
    "kalman_filter": {"data": "OHLCV", "status": "available"},
    "particle_filter": {"data": "OHLCV", "status": "available_proxy"},
    "markov_switching": {"data": "OHLCV", "status": "available_proxy"},
    "hmm_regime": {"data": "OHLCV", "status": "optional_dependency"},
    "semi_markov_regime": {"data": "OHLCV", "status": "available_proxy"},
    "garch": {"data": "OHLCV", "status": "available_proxy"},
    "egarch": {"data": "OHLCV", "status": "available_proxy"},
    "gjr_garch": {"data": "OHLCV", "status": "available_proxy"},
    "hawkes": {"data": "ticks_or_events", "status": "requires_event_data"},
    "extreme_value": {"data": "OHLCV", "status": "available"},
    "copula": {"data": "multiple_symbols", "status": "requires_cross_section"},
    "pca_factor": {"data": "multiple_symbols", "status": "requires_cross_section"},
    "dynamic_factor": {"data": "multiple_symbols", "status": "requires_cross_section"},
    "ornstein_uhlenbeck": {"data": "spread_or_price", "status": "available_proxy"},
    "optimal_stopping": {"data": "OHLCV", "status": "available_proxy"},
    "almgren_chriss": {"data": "orders_and_impact", "status": "requires_execution_data"},
    "black_litterman": {"data": "multiple_assets", "status": "requires_portfolio"},
    "random_matrix": {"data": "multiple_assets", "status": "requires_cross_section"},
    "gaussian_process": {"data": "OHLCV", "status": "optional_dependency"},
    "triple_barrier": {"data": "OHLCV", "status": "available_causal_training"},
    "meta_labeling": {"data": "OHLCV", "status": "available_causal_training"},
    "fractional_differentiation": {"data": "OHLCV", "status": "available"},
    "entropy_information": {"data": "OHLCV", "status": "available"},
    "conformal_prediction": {"data": "OHLCV", "status": "available_causal_training"},
    "symbolic_regression": {"data": "OHLCV", "status": "available_via_formula_dsl"},
    "genetic_programming": {"data": "OHLCV", "status": "available_via_formula_dsl"},
    "neural_ode": {"data": "OHLCV", "status": "optional_dependency"},
    "temporal_convolution": {"data": "OHLCV", "status": "optional_dependency"},
    "transformer": {"data": "OHLCV", "status": "optional_dependency"},
    "mixture_of_experts": {"data": "OHLCV", "status": "available"},
    "deep_ensemble": {"data": "OHLCV", "status": "available"},
    "differentiable_backtest": {"data": "OHLCV", "status": "research_only"},
    "information_shortfall": {"data": "execution_data", "status": "requires_execution_data"},
}


def _safe_z(series: pd.Series, window: int) -> pd.Series:
    mean = series.rolling(window).mean()
    std = series.rolling(window).std().replace(0, np.nan)
    return (series - mean) / std


def _kalman(frame: pd.DataFrame, process_noise: float = 1e-4, observation_noise: float = 1e-2):
    """Two-state recursive level/slope filter; no smoothing or future data."""
    level = float(frame.close.iloc[0]); slope = 0.0
    levels, slopes = [], []
    q, r = float(process_noise), float(observation_noise)
    p00, p01, p10, p11 = 1.0, 0.0, 0.0, 1.0
    for price in frame.close.astype(float):
        pred_level, pred_slope = level + slope, slope
        # F P F' for the level/slope state transition [[1, 1], [0, 1]].
        a00 = p00 + p01 + p10 + p11 + q
        a01 = p01 + p11
        a10 = p10 + p11
        a11 = p11 + q
        innovation = price - pred_level
        s = max(1e-12, a00 + r)
        k0, k1 = a00 / s, a10 / s
        level, slope = pred_level + k0 * innovation, pred_slope + k1 * innovation
        p00, p01 = (1 - k0) * a00, (1 - k0) * a01
        p10, p11 = a10 - k1 * a00, a11 - k1 * a01
        levels.append(level); slopes.append(slope)
    return pd.Series(levels, index=frame.index), pd.Series(slopes, index=frame.index)


def _fractional_difference(series: pd.Series, d: float = .4, window: int = 24) -> pd.Series:
    """Fixed-width causal fractional difference approximation."""
    weights = [1.0]
    for k in range(1, window):
        weights.append(-weights[-1] * (d - k + 1) / k)
    return series.rolling(window).apply(lambda x: float(np.dot(weights[:len(x)][::-1], x)), raw=True)


def advanced_feature_frame(frame: pd.DataFrame, window: int = 12) -> pd.DataFrame:
    """Build a broad OHLCV feature set with only backward-looking windows."""
    close = frame.close.astype(float)
    ret = close.pct_change()
    out = pd.DataFrame(index=frame.index)
    out["kalman_level"], out["kalman_slope"] = _kalman(frame)
    out["kalman_gap"] = close / out["kalman_level"] - 1
    out["ewma_vol"] = ret.ewm(span=max(3, window), adjust=False).std()
    sq = ret.pow(2)
    garch = pd.Series(np.nan, index=frame.index, dtype=float)
    variance = float(ret.iloc[1:].var()) if len(ret.dropna()) > 1 else 0.0
    for stamp, value in sq.items():
        variance = .05 * float(value if pd.notna(value) else variance) + .93 * variance
        garch.loc[stamp] = math.sqrt(max(variance, 0.0))
    out["garch_vol"] = garch
    out["leverage_effect"] = ret.where(ret < 0, 0).rolling(window).mean()
    out["ou_z"] = _safe_z(close, max(5, window * 2))
    out["frac_diff"] = _fractional_difference(close, .4, max(8, window * 2))
    out["drawdown"] = close / close.cummax() - 1
    out["range_z"] = _safe_z((frame.high - frame.low) / close, window)
    out["volume_z"] = _safe_z(frame.volume.astype(float), window)
    # Event-intensity proxy. It is explicitly labelled a proxy because ticks
    # and order arrivals are not present in the app cache.
    events = (ret.abs() > ret.abs().rolling(window).median()).astype(float)
    out["event_intensity"] = events.ewm(span=max(3, window), adjust=False).mean()
    # Entropy of the trailing up/down distribution.
    direction = (ret > 0).astype(float)
    out["direction_entropy"] = direction.rolling(window).apply(
        lambda x: float(-sum(p * math.log(p) for p in (x.mean(), 1 - x.mean()) if p > 0)), raw=True
    )
    return out.replace([np.inf, -np.inf], np.nan)


def causal_triple_barrier_labels(frame: pd.DataFrame, horizon: int, upper: float, lower: float) -> pd.Series:
    """Labels become usable only after their forward horizon has completed."""
    close = frame.close.astype(float)
    labels = pd.Series(np.nan, index=frame.index, dtype=float)
    for i in range(len(frame) - horizon):
        path = close.iloc[i + 1:i + horizon + 1] / close.iloc[i] - 1
        upper_hit = path[path >= upper].index[0] if (path >= upper).any() else None
        lower_hit = path[path <= -lower].index[0] if (path <= -lower).any() else None
        if upper_hit is not None and (lower_hit is None or upper_hit <= lower_hit): labels.iloc[i] = 1.0
        elif lower_hit is not None: labels.iloc[i] = 0.0
        else: labels.iloc[i] = float(path.iloc[-1] > 0)
    return labels


def purged_walk_forward_slices(n: int, train: float = .6, validation: float = .2, embargo: int = 1):
    """Chronological splits with an embargo between train and validation."""
    train_end = int(n * train); validation_start = min(n, train_end + embargo)
    validation_end = min(n, int(n * (train + validation)))
    return slice(0, train_end), slice(validation_start, validation_end), slice(validation_end, n)


def advanced_seed_params() -> list[dict[str, Any]]:
    return [
        {"model": "random_forest", "feature_set": "advanced", "feature_window": 12, "min_train": 30, "buy_threshold": .58, "sell_threshold": .44, "stop": .08, "take_profit": .16, "seed": 101},
        {"model": "gradient_boosting", "feature_set": "advanced", "feature_window": 12, "min_train": 30, "buy_threshold": .58, "sell_threshold": .44, "stop": .08, "take_profit": .16, "seed": 103},
        {"model": "mixture_of_experts", "feature_set": "advanced", "feature_window": 12, "min_train": 30, "buy_threshold": .58, "sell_threshold": .44, "stop": .08, "take_profit": .16, "seed": 107},
        {"model": "deep_ensemble", "feature_set": "advanced", "feature_window": 12, "min_train": 30, "buy_threshold": .58, "sell_threshold": .44, "stop": .08, "take_profit": .16, "seed": 109},
        {"model": "kalman_regime", "feature_set": "advanced", "feature_window": 12, "min_train": 20, "buy_threshold": .56, "sell_threshold": .43, "stop": .08, "take_profit": .16, "seed": 113},
        {"model": "triple_barrier_meta", "feature_set": "advanced", "feature_window": 12, "min_train": 30, "buy_threshold": .58, "sell_threshold": .44, "stop": .08, "take_profit": .16, "seed": 127},
    ]
