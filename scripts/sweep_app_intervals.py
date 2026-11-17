#!/usr/bin/env python3
"""Swarm-search causal ASX session intervals from the app's hourly cache.

Each interval is built from complete Sydney-local ASX session bars only. The
last partial chunk of a session is ignored (except a 6H interval, which uses
all six session hours). Returns are always calculated by the local evaluator;
MCP/NVIDIA workers only propose parameter mutations.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import random
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from multi_symbol_strategy_lab import (  # noqa: E402
    APP_IMITATION,
    BASELINE,
    CAPITAL,
    MAX_DRAWDOWN_PCT,
    MIN_TRADES,
    ONE_HOUR_WINNER,
    SLIPPAGE_BPS,
    UNIVERSE,
    evaluate,
    nvidia_search,
    search,
)
from mcp_strategy_lab import MCPClient  # noqa: E402
from ml_strategy_engine import ml_seed_params, run_ml  # noqa: E402
from causal_formula_engine import random_formula, run_formula, validate_formula  # noqa: E402
from advanced_research_engine import ADVANCED_FAMILIES, advanced_seed_params  # noqa: E402

REFERENCE_5H_CANDLES = 42
REFERENCE_HOURLY_BARS = REFERENCE_5H_CANDLES * 5
NVIDIA_MODELS = [
    "nvidia/nemotron-3.5-bolt-e4b",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "deepseek-ai/deepseek-v4.1-flash",
    "z-ai/glm-5.3-flash",
    "minimaxai/minimax-m3.1-flash",
    "meta/muse-glimmer-30b",
    "nvidia/nemotron-3.5-super-vl-120b-a12b",
    "mistralai/mistral-large-4-1t-a52b",
    "stepfun-ai/step-5-preview",
]


def candle_limit_for_interval(bars: int) -> int:
    """Keep the same 210-hour history represented by 42 five-hour candles."""
    return REFERENCE_HOURLY_BARS // bars


def load_hourly(db_path: Path, symbol: str) -> pd.DataFrame:
    with sqlite3.connect(db_path) as db:
        frame = pd.read_sql_query(
            "SELECT timestamp_local, open, high, low, close, volume "
            "FROM hourly_candles WHERE symbol=? ORDER BY timestamp_local",
            db, params=(symbol,), parse_dates=["timestamp_local"],
        )
    return frame


def symbols_from_db(db_path: Path) -> list[str]:
    with sqlite3.connect(db_path) as db:
        symbols = [row[0] for row in db.execute("SELECT DISTINCT symbol FROM hourly_candles ORDER BY symbol")]
    return [symbol for symbol in symbols if symbol != "ALL"]


def aggregate_session(frame: pd.DataFrame, bars: int) -> pd.DataFrame:
    """Aggregate 10:00-16:00 Sydney sessions into 1H..6H bars."""
    if bars < 1 or bars > 6:
        raise ValueError("bars must be between 1 and 6")
    rows = []
    frame = frame.copy()
    frame["session_date"] = frame["timestamp_local"].dt.date
    for date, group in frame.groupby("session_date"):
        group = group[group["timestamp_local"].dt.hour.isin(range(10, 16))]
        group = group.sort_values("timestamp_local").drop_duplicates("timestamp_local")
        if len(group) != 6 or list(group["timestamp_local"].dt.hour) != list(range(10, 16)):
            continue
        for start in range(0, 6 - bars + 1, bars):
            part = group.iloc[start:start + bars]
            rows.append({
                "time_key": part["timestamp_local"].iloc[-1] + pd.Timedelta(hours=1),
                "open": float(part["open"].iloc[0]),
                "high": float(part["high"].max()),
                "low": float(part["low"].min()),
                "close": float(part["close"].iloc[-1]),
                "volume": float(part["volume"].sum()),
            })
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    result = pd.DataFrame(rows).set_index("time_key").sort_index()
    if result.index.duplicated().any():
        raise ValueError("duplicate aggregated timestamps")
    return result


def evaluate_ml(frame: pd.DataFrame, params: dict) -> dict:
    trades, data, result = run_ml(frame, params, capital=CAPITAL, allocation=1.0, slippage_bps=SLIPPAGE_BPS)
    result.update({
        "strategy_family": "causal_ml",
        "available_candles": len(frame),
        "selection_score": round(result["total_return_pct"] - 0.35 * abs(result["max_drawdown_pct"]), 4),
        "drawdown_limit_pct": MAX_DRAWDOWN_PCT,
        "minimum_trades": MIN_TRADES,
    })
    result["risk_eligible"] = abs(float(result["max_drawdown_pct"])) <= MAX_DRAWDOWN_PCT and int(result["trades"]) >= MIN_TRADES
    return {"kind": "ml", "params": params, "stats": result}


def evaluate_formula_candidate(frame: pd.DataFrame, spec: dict) -> dict:
    """Evaluate a whitelisted expression tree with the same causal ledger."""
    try:
        validate_formula(spec["entry"])
        validate_formula(spec["exit"])
        trades, data, result = run_formula(
            frame, spec, capital=CAPITAL, allocation=1.0, slippage_bps=SLIPPAGE_BPS
        )
    except Exception:
        return {"kind": "formula", "params": spec, "stats": {
            "trades": 0, "total_pnl_aud": -1e12, "total_return_pct": -1e12,
            "max_drawdown_pct": 1e12, "selection_score": -1e12,
            "risk_eligible": False, "strategy_family": "causal_formula_invalid",
        }}
    result.update({
        "strategy_family": "causal_formula_tree",
        "available_candles": len(frame),
        "selection_score": round(result["total_return_pct"] - 0.35 * abs(result["max_drawdown_pct"]), 4),
        "drawdown_limit_pct": MAX_DRAWDOWN_PCT,
        "minimum_trades": MIN_TRADES,
        "brokerage": "AustralianSuper Member Direct",
        "administration_fee_included": False,
    })
    result["risk_eligible"] = (
        abs(float(result["max_drawdown_pct"])) <= MAX_DRAWDOWN_PCT
        and int(result["trades"]) >= MIN_TRADES
    )
    return {"kind": "formula", "params": spec, "stats": result}


def evaluate_candidate(frame: pd.DataFrame, candidate: dict) -> dict:
    if candidate.get("kind") == "ml":
        return evaluate_ml(frame, candidate["params"])
    if candidate.get("kind") == "formula":
        return evaluate_formula_candidate(frame, candidate["params"])
    return evaluate(frame, candidate["params"])


def formula_spec(rng: random.Random) -> dict:
    """Generate one causal indicator/entry/exit tree without executable code."""
    left = random_formula(rng)
    right = random_formula(rng)
    entry = {"op": rng.choice(("gt", "cross_up")), "args": [left, right]}
    left2 = random_formula(rng)
    right2 = random_formula(rng)
    exit_signal = {"op": rng.choice(("lt", "cross_down")), "args": [left2, right2]}
    return {"entry": entry, "exit": exit_signal,
            "stop": round(rng.uniform(.03, .20), 4),
            "take_profit": round(rng.uniform(.04, .35), 4),
            "generator": "bounded_random_composition"}


def run_interval(frame: pd.DataFrame, symbol: str, interval: int, candidates: int, clients_by_model: dict[str, list[MCPClient]], agents_per_model: int) -> dict:
    n = len(frame)
    train_end, validation_end = int(n * .60), int(n * .80)
    train, validation, test = frame.iloc[:train_end], frame.iloc[train_end:validation_end], frame.iloc[validation_end:]
    parents = [dict(BASELINE), dict(ONE_HOUR_WINNER), {**BASELINE, **APP_IMITATION}]
    local_candidates = search(train, 910000 + interval, candidates, parents)
    local_candidates += [evaluate(train, dict(BASELINE)), evaluate(train, {**BASELINE, **APP_IMITATION})]
    ml_candidates = []
    ml_rng = random.Random(440000 + interval)
    for seed_params in ml_seed_params():
        for _ in range(4):
            params = dict(seed_params)
            params["buy_threshold"] = round(max(0.51, min(0.80, params["buy_threshold"] + ml_rng.uniform(-0.04, 0.08))), 3)
            params["sell_threshold"] = round(max(0.20, min(0.49, params["sell_threshold"] + ml_rng.uniform(-0.05, 0.04))), 3)
            params["feature_window"] = max(5, min(24, int(round(params["feature_window"] + ml_rng.gauss(0, 2)))))
            params["min_train"] = max(20, min(80, int(round(params["min_train"] + ml_rng.gauss(0, 5)))))
            if params.get("model") == "formula":
                params["weights"] = {name: round(float(weight) + ml_rng.gauss(0, 0.15), 3) for name, weight in params["weights"].items()}
                params["normalization_window"] = max(8, min(40, int(round(params["normalization_window"] + ml_rng.gauss(0, 3)))))
            ml_candidates.append(evaluate_ml(train, params))
    formula_candidates = []
    formula_rng = random.Random(970000 + interval + n)
    # This is deliberately independent of the fixed-parameter population. A
    # continuous run changes the seed each cycle, so the search space keeps
    # expanding while the expression grammar remains auditable and causal.
    for _ in range(96):
        formula_candidates.append(evaluate_formula_candidate(train, formula_spec(formula_rng)))
    nvidia_proposals = []
    nvidia_proposals_by_model = {}
    if clients_by_model and agents_per_model:
        profile = {
            "symbol": symbol, "interval": f"{interval}H", "rows": n,
            "train_rows": len(train), "validation_rows": len(validation), "test_rows": len(test),
            "session_hours": "10:00-16:00 Australia/Sydney",
        }
        defaults = {**BASELINE, "entry_mode": "breakout_trend", "exit_mode": "fast_or_slow", "downtrend_filter": True, "regime_ema": 89, "max_holding_bars": 0}
        parent_params = [item["params"] for item in local_candidates[:5]]
        total_agents = sum(len(clients) for clients in clients_by_model.values())
        with concurrent.futures.ThreadPoolExecutor(max_workers=total_agents) as pool:
            futures = {
                pool.submit(nvidia_search, clients_by_model[model][agent_id - 1], symbol, profile, parent_params, agent_id, model=model): model
                for model in clients_by_model
                for agent_id in range(1, agents_per_model + 1)
            }
            for future, model in futures.items():
                raw_candidates = future.result()
                nvidia_proposals_by_model[model] = nvidia_proposals_by_model.get(model, 0) + len(raw_candidates)
                for raw in raw_candidates:
                    params = dict(defaults)
                    params.update(raw)
                    nvidia_proposals.append(evaluate(train, params))
                    if isinstance(raw.get("formula"), dict):
                        try:
                            formula_candidates.append(evaluate_formula_candidate(train, raw["formula"]))
                        except (KeyError, TypeError, ValueError):
                            pass
    all_candidates = local_candidates + nvidia_proposals + ml_candidates + formula_candidates
    all_candidates.sort(key=lambda item: item["stats"]["selection_score"], reverse=True)
    traded_profitable = [item for item in all_candidates if item["stats"]["trades"] >= MIN_TRADES and item["stats"]["total_pnl_aud"] > 0]
    traded_profitable.sort(key=lambda item: (item["stats"]["total_pnl_aud"], item["stats"]["selection_score"]), reverse=True)
    traded_low_drawdown = [item for item in all_candidates if item["stats"]["trades"] >= MIN_TRADES]
    traded_low_drawdown.sort(key=lambda item: (abs(item["stats"]["max_drawdown_pct"]), -item["stats"]["total_pnl_aud"]))
    candidates_all = [item for item in all_candidates if item["stats"]["risk_eligible"]]
    candidates_all.sort(key=lambda item: item["stats"]["selection_score"], reverse=True)
    validation_ranked = []
    for item in candidates_all[:25]:
        result = evaluate_candidate(validation, item)
        if result["stats"]["risk_eligible"]:
            validation_ranked.append(result)
    validation_ranked.sort(key=lambda item: item["stats"]["selection_score"], reverse=True)
    selected = validation_ranked[0] if validation_ranked else None
    final = evaluate(test, selected["params"]) if selected else None
    def compact(item):
        if not item:
            return None
        stats = item["stats"]
        return {"params": item["params"], "stats": stats}

    best_any = all_candidates[0] if all_candidates else None
    best_profitable = traded_profitable[0] if traded_profitable else None
    best_low_drawdown = traded_low_drawdown[0] if traded_low_drawdown else None
    return {
        "symbol": symbol, "interval": f"{interval}H", "rows": n,
        "train_rows": len(train), "validation_rows": len(validation), "test_rows": len(test),
        "start": str(frame.index.min()), "end": str(frame.index.max()),
        "local_candidates": candidates, "ml_candidates": len(ml_candidates),
        "formula_candidates": len(formula_candidates), "advanced_ml_seeds": len(advanced_seed_params()), "nvidia_proposals": len(nvidia_proposals),
        "advanced_families": ADVANCED_FAMILIES,
        "nvidia_proposals_by_model": nvidia_proposals_by_model,
        "baseline": evaluate(frame, dict(BASELINE)),
        "best_train": candidates_all[0] if candidates_all else None,
        "train_eligible_count": len(candidates_all),
        "best_train_any": compact(best_any),
        "best_train_profitable_traded": compact(best_profitable),
        "best_train_low_drawdown_traded": compact(best_low_drawdown),
        "profitable_traded_near_misses": [compact(item) for item in traded_profitable[:100]],
        "selected_validation": selected, "final_test": final,
        "risk_gate": {"max_drawdown_pct": MAX_DRAWDOWN_PCT, "minimum_trades": MIN_TRADES},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=ROOT / "data/asx_hourly_yfinance_42d.sqlite3")
    parser.add_argument("--candidates", type=int, default=10000)
    parser.add_argument("--agents-per-model", type=int, default=3)
    parser.add_argument("--continuous", action="store_true")
    parser.add_argument("--stop-file", type=Path)
    parser.add_argument("--symbols", default="")
    parser.add_argument("--run-dir", type=Path, default=ROOT / "strategy_lab_runs")
    args = parser.parse_args()
    run_dir = args.run_dir / time.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    stop_file = args.stop_file or run_dir / "STOP"
    requested_symbols = [item.strip().upper() for item in args.symbols.replace(",", " ").split() if item.strip()]
    symbols = requested_symbols or symbols_from_db(args.db)
    clients_by_model: dict[str, list[MCPClient]] = {}
    try:
        for model in NVIDIA_MODELS:
            clients_by_model[model] = [MCPClient(ROOT.parent / "multi-model-ai-gateway/ai/mcp_server.py", "http://127.0.0.1:8788") for _ in range(args.agents_per_model)]
    except Exception as exc:
        print(f"MCP unavailable: {exc}", file=sys.stderr)
    results = []
    results_by_key = {}
    cycle = 0
    interrupted = False
    try:
        while True:
            cycle += 1
            for symbol in symbols:
                if stop_file.exists():
                    break
                hourly = load_hourly(args.db, symbol)
                for interval in range(1, 7):
                    if stop_file.exists():
                        break
                    frame = aggregate_session(hourly, interval).tail(candle_limit_for_interval(interval))
                    result = run_interval(frame, symbol, interval, args.candidates, clients_by_model, args.agents_per_model)
                    result["cycle"] = cycle
                    interval_dir = run_dir / "interval_results" / f"cycle-{cycle:04d}"
                    interval_dir.mkdir(parents=True, exist_ok=True)
                    (interval_dir / f"{symbol}_{interval}H.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
                    results_by_key[f"{symbol}:{interval}H"] = result
                    results = list(results_by_key.values())
                    compact = [{"symbol": item["symbol"], "interval": item["interval"], "cycle": item["cycle"], "rows": item["rows"], "nvidia_proposals": item["nvidia_proposals"], "nvidia_proposals_by_model": item["nvidia_proposals_by_model"], "train_eligible_count": item["train_eligible_count"], "eligible": bool(item["selected_validation"]), "final_test": item["final_test"]["stats"] if item["final_test"] else None, "best_profitable_traded": item["best_train_profitable_traded"]["stats"] if item["best_train_profitable_traded"] else None, "best_low_drawdown_traded": item["best_train_low_drawdown_traded"]["stats"] if item["best_train_low_drawdown_traded"] else None} for item in results]
                    (run_dir / "progress.json").write_text(json.dumps({"cycle": cycle, "symbols": symbols, "interval_results": compact}, indent=2, default=str) + "\n")
                    print(f"cycle={cycle} {symbol} {interval}H rows={len(frame)} nvidia={result['nvidia_proposals']} eligible={'yes' if result['selected_validation'] else 'no'}", flush=True)
            if not args.continuous or stop_file.exists():
                break
    except KeyboardInterrupt:
        interrupted = True
    finally:
        for clients in clients_by_model.values():
            for client in clients:
                client.close()
    summary = {
        "status": "stopped" if interrupted or stop_file.exists() else "completed", "data_interval": "hourly cache aggregated per ASX session",
        "symbols": symbols, "intervals": ["1H", "2H", "3H", "4H", "5H", "6H"],
        "candidates_per_local_worker": args.candidates, "local_workers": 1,
        "nvidia_models": NVIDIA_MODELS, "nvidia_agents_per_model": args.agents_per_model,
        "nvidia_concurrent_agents_per_interval": len(NVIDIA_MODELS) * args.agents_per_model,
        "reference_history": "42 five-hour candles = 210 hourly bars",
        "max_candles_by_interval": {f"{n}H": candle_limit_for_interval(n) for n in range(1, 7)},
        "capital": CAPITAL, "slippage_bps_per_side": SLIPPAGE_BPS,
        "brokerage": "AustralianSuper Member Direct", "administration_fee_included": False,
        "results": results,
    }
    output = run_dir / "summary.json"
    output.write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(f"Saved {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
