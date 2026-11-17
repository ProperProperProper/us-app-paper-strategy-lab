"""Causal machine-learning strategy experiments.

Models are refit on expanding historical data before each signal bar. No
future labels, indicators, or scaling statistics are allowed into a signal.
This is an experimental research family, not an app promotion mechanism.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from australian_super_fees import australian_super_member_direct_fee
from strategy_57pct import Trade, _validate_candles, _validate_trades, stats
from advanced_research_engine import advanced_feature_frame, advanced_seed_params, causal_triple_barrier_labels


FEATURES = ("ret1", "ret3", "ret6", "range_pct", "ema_gap", "volume_ratio")
ADVANCED_FEATURES = FEATURES + ("kalman_gap", "kalman_slope", "ewma_vol", "garch_vol", "leverage_effect", "ou_z", "frac_diff", "drawdown", "range_z", "volume_z", "event_intensity", "direction_entropy")


def feature_frame(frame: pd.DataFrame, window: int = 12) -> pd.DataFrame:
    close = frame.close.astype(float)
    x = pd.DataFrame(index=frame.index)
    x["ret1"] = close.pct_change()
    x["ret3"] = close.pct_change(3)
    x["ret6"] = close.pct_change(6)
    x["range_pct"] = (frame.high - frame.low) / close
    x["ema_gap"] = close.ewm(span=max(2, window), adjust=False).mean() / close.ewm(span=max(4, window * 3), adjust=False).mean() - 1
    x["volume_ratio"] = frame.volume / frame.volume.rolling(max(3, window)).median()
    return x.replace([np.inf, -np.inf], np.nan)


def _model(kind: str, seed: int):
    if kind == "mlp":
        return make_pipeline(StandardScaler(), MLPClassifier(hidden_layer_sizes=(8,), alpha=0.05, max_iter=250, random_state=seed, early_stopping=False))
    if kind == "random_forest":
        return RandomForestClassifier(n_estimators=32, max_depth=4, min_samples_leaf=3, random_state=seed, n_jobs=1)
    if kind == "gradient_boosting":
        return GradientBoostingClassifier(n_estimators=32, max_depth=2, learning_rate=.05, random_state=seed)
    return make_pipeline(StandardScaler(), LogisticRegression(C=0.15, solver="liblinear", max_iter=200, random_state=seed))


def probabilities(frame: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    use_advanced = params.get("feature_set") == "advanced"
    if use_advanced:
        basic = feature_frame(frame, int(params.get("feature_window", 12)))
        advanced = advanced_feature_frame(frame, int(params.get("feature_window", 12)))
        x = pd.concat([basic, advanced], axis=1).loc[:, ~pd.concat([basic, advanced], axis=1).columns.duplicated()]
        model_features = list(ADVANCED_FEATURES)
    else:
        x = feature_frame(frame, int(params.get("feature_window", 12)))
        model_features = list(FEATURES)
    x = x[model_features]
    if params.get("model") == "formula":
        window = max(5, int(params.get("normalization_window", 20)))
        normalized = (x - x.rolling(window).mean()) / x.rolling(window).std().replace(0, np.nan)
        weights = params.get("weights", {})
        score = sum(float(weights.get(name, 0.0)) * normalized[name] for name in FEATURES)
        scale = max(0.05, float(params.get("score_scale", 1.0)))
        return 1.0 / (1.0 + np.exp(-score / scale))
    close = frame.close.astype(float)
    horizon = max(1, int(params.get("label_horizon", 1)))
    if params.get("model") == "triple_barrier_meta":
        labels = causal_triple_barrier_labels(frame, horizon=max(2, horizon), upper=float(params.get("upper_barrier", .04)), lower=float(params.get("lower_barrier", .03)))
    else:
        labels = (close.shift(-horizon) / close - 1 > float(params.get("label_threshold", 0.0))).astype(float)
    output = pd.Series(np.nan, index=frame.index, dtype=float)
    min_train = max(20, int(params.get("min_train", 30)))
    for i in range(len(frame)):
        # At bar i, labels through i-1 are known. The current row is never
        # included in fitting because its forward label is not yet known.
        end = i - horizon
        if end < min_train:
            continue
        train = x.iloc[:end].copy()
        y = labels.iloc[:end]
        valid = train.notna().all(axis=1) & y.notna()
        train, y = train.loc[valid], y.loc[valid].astype(int)
        if len(train) < min_train or y.nunique() < 2 or x.iloc[i].isna().any():
            continue
        kind = str(params.get("model", "logistic"))
        if kind == "kalman_regime":
            row = x.iloc[i]
            score = 3.0 * float(row.get("kalman_slope", 0.0)) + 1.5 * float(row.get("kalman_gap", 0.0)) - .5 * float(row.get("garch_vol", 0.0))
            output.iloc[i] = 1.0 / (1.0 + np.exp(-score * 100.0))
            continue
        kinds = ["logistic", "random_forest"] if kind == "mixture_of_experts" else (["mlp", "random_forest", "gradient_boosting"] if kind == "deep_ensemble" else [kind])
        probabilities_at_bar = []
        for offset, model_kind in enumerate(kinds):
            model = _model(model_kind, int(params.get("seed", 7)) + i + offset * 1000)
            model.fit(train, y)
            probabilities_at_bar.append(float(model.predict_proba(x.iloc[[i]])[0, 1]))
        output.iloc[i] = float(np.mean(probabilities_at_bar))
    return output


def run_ml(frame: pd.DataFrame, params: dict[str, Any], capital: float = 200_000.0, allocation: float = 1.0, slippage_bps: float = 2.0):
    _validate_candles(frame)
    prob = probabilities(frame, params)
    buy_threshold = float(params.get("buy_threshold", 0.58))
    sell_threshold = float(params.get("sell_threshold", 0.45))
    stop = float(params.get("stop", 0.08))
    target = float(params.get("take_profit", 0.16))
    slip = slippage_bps / 10000.0
    cash = float(capital); position = None; trades = []; equity_rows = []
    rows = list(frame.iterrows())
    for i, (stamp, bar) in enumerate(rows):
        price = float(bar.close)
        equity_rows.append({"date": stamp, "equity": cash + (position["qty"] * price if position else 0.0)})
        if position:
            exit_reason = None
            if price <= position["entry"] * (1 - stop): exit_reason = "ML_STOP"
            elif price >= position["entry"] * (1 + target): exit_reason = "ML_TP"
            elif pd.notna(prob.iloc[i]) and float(prob.iloc[i]) <= sell_threshold: exit_reason = "ML_EXIT"
            if exit_reason:
                out = price * (1 - slip); fee = australian_super_member_direct_fee(position["qty"] * out)
                gross = (out - position["entry"]) * position["qty"]; costs = position["entry_fee"] + fee
                trades.append(Trade(position["signal_time"], position["entry_time"], position["entry"], position["qty"], stamp.isoformat(), out, gross, costs, gross - costs, (gross - costs) / (position["entry"] * position["qty"]) * 100, exit_reason))
                cash += position["qty"] * out - fee; position = None
                continue
        if position is None and pd.notna(prob.iloc[i]) and float(prob.iloc[i]) >= buy_threshold:
            entry = price * (1 + slip); qty = math.floor(cash * allocation / entry); fee = australian_super_member_direct_fee(qty * entry) if qty else 0.0
            if qty and qty * entry + fee <= cash:
                cash -= qty * entry + fee
                position = {"signal_time": stamp.isoformat(), "entry_time": stamp.isoformat(), "entry": entry, "qty": qty, "entry_fee": fee}
    if position and rows:
        stamp, bar = rows[-1]; out = float(bar.close) * (1 - slip); fee = australian_super_member_direct_fee(position["qty"] * out)
        gross = (out - position["entry"]) * position["qty"]; costs = position["entry_fee"] + fee
        trades.append(Trade(position["signal_time"], position["entry_time"], position["entry"], position["qty"], stamp.isoformat(), out, gross, costs, gross - costs, (gross - costs) / (position["entry"] * position["qty"]) * 100, "ML_MARK_TO_MARKET"))
        cash += position["qty"] * out - fee
    equity = pd.DataFrame(equity_rows).set_index("date") if equity_rows else pd.DataFrame(columns=["equity"])
    _validate_trades(trades)
    return trades, {"equity": equity, "ending_cash": cash}, stats(trades, {"equity": equity}, capital)


def ml_seed_params() -> list[dict[str, Any]]:
    return [
        {"model": "formula", "feature_window": 8, "normalization_window": 18, "score_scale": 1.0, "weights": {"ret1": 0.35, "ret3": 0.30, "ret6": 0.20, "range_pct": -0.10, "ema_gap": 0.40, "volume_ratio": 0.15}, "buy_threshold": 0.58, "sell_threshold": 0.45, "stop": 0.08, "take_profit": 0.16, "seed": 3},
        {"model": "formula", "feature_window": 12, "normalization_window": 24, "score_scale": 0.8, "weights": {"ret1": 0.15, "ret3": 0.40, "ret6": 0.35, "range_pct": -0.15, "ema_gap": 0.45, "volume_ratio": 0.20}, "buy_threshold": 0.60, "sell_threshold": 0.42, "stop": 0.10, "take_profit": 0.20, "seed": 5},
        {"model": "logistic", "feature_window": 8, "label_horizon": 1, "label_threshold": 0.0, "min_train": 20, "buy_threshold": 0.55, "sell_threshold": 0.45, "stop": 0.08, "take_profit": 0.16, "seed": 7},
        {"model": "logistic", "feature_window": 12, "label_horizon": 2, "label_threshold": 0.005, "min_train": 30, "buy_threshold": 0.60, "sell_threshold": 0.42, "stop": 0.10, "take_profit": 0.20, "seed": 11},
        {"model": "mlp", "feature_window": 8, "label_horizon": 1, "label_threshold": 0.0, "min_train": 30, "buy_threshold": 0.60, "sell_threshold": 0.40, "stop": 0.08, "take_profit": 0.16, "seed": 17},
        *advanced_seed_params(),
    ]
