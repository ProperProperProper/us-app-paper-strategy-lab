#!/usr/bin/env python3
"""AI mutation loop for the US.APP 10-minute paper strategy.

AI agents propose bounded grid-lookback mutations. The local deterministic
evaluator owns all P/L, and every selected validation candidate is published
to the root paper bot's SIMULATE strategy file immediately.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import random
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LAB_ROOT = ROOT
sys.path.insert(0, str(ROOT / "scripts"))


def load_root_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


root_strategy = load_root_module("root_strategy_57pct", ROOT / "scripts" / "strategy_57pct.py")
BASELINE, run, stats = root_strategy.BASELINE, root_strategy.run, root_strategy.stats
from model_client import MCPClient
from agent_workers import AntigravityOptimizer


def write_live_strategy(symbol: str, interval: int, params: dict, run_id: str) -> dict:
    path = ROOT / "paper_bot_live_strategy.json"
    payload = {"symbol": symbol, "interval": int(interval), "params": dict(params),
               "run_id": run_id, "updated_at": pd.Timestamp.now(tz="UTC").isoformat(),
               "mode": "SIMULATE"}
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)
    return payload


def load_frame(db_path: Path) -> pd.DataFrame:
    with sqlite3.connect(db_path) as db:
        frame = pd.read_sql_query(
            """SELECT time_key, open, high, low, close, volume
               FROM candles WHERE symbol='US.APP' AND interval_minutes=10
               ORDER BY time_key""",
            db, parse_dates=["time_key"],
        )
    if frame.empty:
        raise RuntimeError("No US.APP 10-minute candles in the Moomoo cache")
    frame = frame.drop_duplicates("time_key").set_index("time_key").sort_index()
    frame = frame.loc[frame.index >= frame.index.max() - pd.Timedelta(days=30)]
    return frame[["open", "high", "low", "close", "volume"]].astype(float)


def evaluate(frame: pd.DataFrame, params: dict) -> dict:
    _, trades, data = run(frame, params, 100_000.0, 1.0, 2.0, 0.0)
    result = stats(trades, data, 100_000.0)
    result["selection_score"] = round(result["total_return_pct"] - 0.35 * abs(result["max_drawdown_pct"]), 4)
    return {"params": dict(params), "stats": result}


def mutate(rng: random.Random, parent: dict | None = None) -> dict:
    base = dict(BASELINE) if parent is None else {**BASELINE, **parent}
    params = {
        "grid_lookback": max(5, min(120, int(round(base["grid_lookback"] + rng.gauss(0, 8))))),
        "grid_intervals": 4,
        "entry_mode": base.get("entry_mode", "any_grid_cross"),
        "exit_mode": base.get("exit_mode", "any_grid_cross_down"),
    }
    if rng.random() < .35:
        params["entry_mode"] = rng.choice(("any_grid_cross", "top_breakout", "upper_half_cross", "lower_half_cross"))
    if rng.random() < .35:
        params["exit_mode"] = rng.choice(("any_grid_cross_down", "top_breakdown", "bottom_breakdown", "lower_half_breakdown"))
    return params


def parse_proposal(text: str) -> dict | None:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text or ""):
        if char not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            value = [value]
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and ("grid_lookback" in item or "entry_mode" in item or "exit_mode" in item):
                    try:
                        result = {"grid_intervals": 4}
                        if "grid_lookback" in item:
                            result["grid_lookback"] = max(5, min(120, int(item["grid_lookback"])))
                        if item.get("entry_mode") in {"any_grid_cross", "top_breakout", "upper_half_cross", "lower_half_cross"}:
                            result["entry_mode"] = item["entry_mode"]
                        if item.get("exit_mode") in {"any_grid_cross_down", "top_breakdown", "bottom_breakdown", "lower_half_breakdown"}:
                            result["exit_mode"] = item["exit_mode"]
                        return result
                    except (TypeError, ValueError):
                        return None
    return None


def ask_agent(client: MCPClient | None, antigravity: AntigravityOptimizer | None, provider: str, profile: dict, parents: list[dict], role: str, nvidia_proposals: list[dict] | None = None) -> dict | None:
    prompt = (
        "You are an independent mutation agent for the US.APP Moomoo paper bot. "
        "The active strategy is a causal 10-minute candle-open price grid. "
        "Propose exactly one bounded JSON strategy mutation. You may change "
        "grid_lookback (integer 5-120), entry_mode (any_grid_cross, top_breakout, "
        "upper_half_cross, lower_half_cross), or exit_mode (any_grid_cross_down, "
        "top_breakdown, bottom_breakdown, lower_half_breakdown). "
        "These are the only safe strategy configuration keys. NVIDIA may suggest; "
        "Antigravity is the only authority allowed to turn a suggestion into a "
        "locally tested configuration. Do not invent performance claims. "
        f"Role: {role}. DATA PROFILE: {json.dumps(profile)} "
        f"PARENTS: {json.dumps(parents[:5])} "
        f"NVIDIA_PROPOSALS_FOR_CONTROLLER: {json.dumps(nvidia_proposals or [])} "
        "Return JSON only, for example {\"grid_lookback\": 45}."
    )
    try:
        if provider == "antigravity":
            return parse_proposal(antigravity.ask(prompt)) if antigravity else None
        return parse_proposal(client.ask(prompt, provider=provider, max_tokens=120)) if client else None
    except Exception:
        return None


def write_status(path: Path, payload: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    temporary.replace(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "quant_dashboard.sqlite3")
    ap.add_argument("--run-dir", type=Path, default=LAB_ROOT / "strategy_lab_runs")
    ap.add_argument("--rounds", type=int, default=20)
    ap.add_argument("--agents", type=int, default=2)
    ap.add_argument("--candidates", type=int, default=100)
    ap.add_argument("--providers", default="antigravity")
    ap.add_argument("--continuous", action="store_true")
    args = ap.parse_args()
    providers = [x.strip() for x in args.providers.split(",") if x.strip()]
    frame = load_frame(args.db)
    train_end, validation_end = int(len(frame) * .60), int(len(frame) * .80)
    train, validation, test = frame.iloc[:train_end], frame.iloc[train_end:validation_end], frame.iloc[validation_end:]
    profile = {"symbol": "US.APP", "interval": "10m", "rows": len(frame), "start": str(frame.index.min()), "end": str(frame.index.max()), "train_rows": len(train), "validation_rows": len(validation), "test_rows": len(test)}
    run_dir = args.run_dir / ("APP-" + time.strftime("%Y%m%d-%H%M%S"))
    run_dir.mkdir(parents=True, exist_ok=True)
    stop_file = run_dir / "STOP"
    status_file = args.run_dir / "app_runtime_status.json"
    client = None
    antigravity = None
    if any(provider in {"local", "nvidia"} for provider in providers):
        try:
            client = MCPClient(LAB_ROOT.parent / "multi-model-ai-gateway/ai/mcp_server.py", "http://127.0.0.1:8788")
        except Exception:
            pass
    if "antigravity" in providers:
        try:
            antigravity = AntigravityOptimizer(timeout_seconds=60)
        except Exception:
            pass
    parents = [dict(BASELINE)]
    round_number = 0
    try:
        while args.continuous or round_number < args.rounds:
            if stop_file.exists():
                break
            round_number += 1
            write_status(status_file, {"state": "RUNNING", "symbol": "US.APP", "interval": "10m", "round": round_number, "run_dir": str(run_dir), "profile": profile})
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.agents)) as pool:
                jobs = [pool.submit(lambda seed: [evaluate(train, mutate(random.Random(seed), random.choice(parents))) for _ in range(args.candidates)], 900000 + round_number * 100 + i) for i in range(args.agents)]
                candidates = [item for job in jobs for item in job.result()]
            nvidia_proposals = []
            if client:
                for agent in range(max(1, args.agents)):
                    proposal = ask_agent(client, None, "nvidia", profile, parents, ["explorer", "critic", "risk reviewer"][agent % 3])
                    if proposal:
                        nvidia_proposals.append(proposal)
            if antigravity:
                configured_parents = parents + nvidia_proposals
                for agent in range(max(1, args.agents)):
                    proposal = ask_agent(None, antigravity, "antigravity", profile, configured_parents, "true controller: choose, constrain, and configure one NVIDIA proposal for local deterministic testing", nvidia_proposals)
                    if proposal:
                        candidates.append(evaluate(train, proposal))
            candidates.append(evaluate(train, dict(BASELINE)))
            candidates.sort(key=lambda item: item["stats"]["selection_score"], reverse=True)
            parents = [item["params"] for item in candidates[:max(2, args.agents)]]
            validation_candidates = [evaluate(validation, item["params"]) for item in candidates[:25]]
            validation_candidates.sort(key=lambda item: item["stats"]["selection_score"], reverse=True)
            selected = validation_candidates[0]
            final = evaluate(test, selected["params"])
            promoted = write_live_strategy("US.APP", 10, selected["params"], f"APP-{run_dir.name}-r{round_number:03d}")
            result = {"round": round_number, "profile": profile, "train_best": candidates[0], "selected_validation": selected, "final_test": final, "promoted": promoted, "agent_mutation": bool(client or antigravity), "proposal_provider": "nvidia" if client else None, "configuration_provider": "antigravity" if antigravity else None, "nvidia_proposals": nvidia_proposals}
            (run_dir / f"round-{round_number:03d}.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
            write_status(status_file, {"state": "RUNNING", **result, "run_dir": str(run_dir)})
            print(json.dumps({"round": round_number, "train": candidates[0]["stats"], "validation": selected["stats"], "test": final["stats"], "promoted": promoted}), flush=True)
    finally:
        if client:
            client.close()
        write_status(status_file, {"state": "STOPPED", "round": round_number, "run_dir": str(run_dir), "profile": profile})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
