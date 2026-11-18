#!/usr/bin/env python3
"""AI mutation loop for the US.APP 10-minute paper strategy.

AI agents propose bounded strategy mutations. The local deterministic
evaluator owns all P/L, and every accepted out-of-sample candidate is published
to the root paper bot's SIMULATE strategy file immediately.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import os
import random
import sqlite3
import sys
import time
import uuid
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
blind_session_walk_forward = root_strategy.blind_session_walk_forward
aggregate_candles = root_strategy.aggregate_candles
RESEARCH_INTERVALS = root_strategy.RESEARCH_INTERVALS
from model_client import MCPClient
from agent_workers import AntigravityOptimizer


# Explicit research hypotheses ensure every round tests whether the current
# exit is giving up too much of a sustained move. These focus on profit
# capture: target size, break-even protection, profit locks, and trailing
# stops. They are evaluated locally alongside agent proposals; none is
# promoted without the normal holdout gate.
PROFIT_EXIT_RESEARCH_VARIANTS = (
    {"tp": 0.08, "break_even_trigger": 0.02, "profit_lock_trigger": 0.06, "profit_lock": 0.01, "trail_trigger": 0.05, "trail_pct": 0.02},
    {"tp": 0.1069, "break_even_trigger": 0.02, "profit_lock_trigger": 0.08, "profit_lock": 0.01, "trail_trigger": 0.06, "trail_pct": 0.02},
    {"tp": 0.15, "break_even_trigger": 0.03, "profit_lock_trigger": 0.08, "profit_lock": 0.02, "trail_trigger": 0.08, "trail_pct": 0.025},
    {"tp": 0.20, "break_even_trigger": 0.03, "profit_lock_trigger": 0.10, "profit_lock": 0.03, "trail_trigger": 0.10, "trail_pct": 0.03},
    {"tp": 0.30, "break_even_trigger": 0.04, "profit_lock_trigger": 0.12, "profit_lock": 0.04, "trail_trigger": 0.12, "trail_pct": 0.04},
    {"tp": 0.50, "break_even_trigger": 0.05, "profit_lock_trigger": 0.15, "profit_lock": 0.05, "trail_trigger": 0.15, "trail_pct": 0.05},
    {"exit_mode": "slow_break", "tp": 0.15, "break_even_trigger": 0.03, "profit_lock_trigger": 0.08, "profit_lock": 0.02, "trail_trigger": 0.08, "trail_pct": 0.025},
    {"exit_mode": "slow_break", "tp": 0.30, "break_even_trigger": 0.04, "profit_lock_trigger": 0.12, "profit_lock": 0.04, "trail_trigger": 0.12, "trail_pct": 0.04},
    {"exit_mode": "trend_cross", "tp": 0.20, "break_even_trigger": 0.03, "profit_lock_trigger": 0.10, "profit_lock": 0.03, "trail_trigger": 0.10, "trail_pct": 0.03},
    {"exit_mode": "slow_break", "profit_exit_mode": "atr_peak_retrace", "tp": 0.50, "profit_arm_return": 0.08, "profit_lock_return": 0.02, "profit_atr_multiple": 2.5, "profit_min_retrace": 0.03},
    {"exit_mode": "slow_break", "profit_exit_mode": "atr_peak_retrace", "tp": 0.50, "profit_arm_return": 0.12, "profit_lock_return": 0.04, "profit_atr_multiple": 3.0, "profit_min_retrace": 0.04},
)
MIN_PROMOTION_TRADES = 3
MAX_PROMOTION_DRAWDOWN_DEGRADATION_PCT = 1.0
TRAIN_SESSIONS = 21


def init_agent_bus(db_path: Path) -> None:
    """Create the durable agent-to-agent message ledger."""
    with sqlite3.connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS agent_messages (
            message_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            run_id TEXT NOT NULL,
            round_number INTEGER NOT NULL,
            sender TEXT NOT NULL,
            recipient TEXT NOT NULL,
            message_type TEXT NOT NULL,
            correlation_id TEXT,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'DELIVERED'
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_agent_messages_run_round ON agent_messages(run_id, round_number, created_at)")
        db.commit()


def send_agent_message(db_path: Path, run_id: str, round_number: int,
                       sender: str, recipient: str, message_type: str,
                       payload: dict, correlation_id: str | None = None) -> str:
    message_id = str(uuid.uuid4())
    with sqlite3.connect(db_path) as db:
        db.execute(
            """INSERT INTO agent_messages
            (message_id, created_at, run_id, round_number, sender, recipient,
             message_type, correlation_id, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (message_id, pd.Timestamp.now(tz="UTC").isoformat(), run_id,
             int(round_number), sender, recipient, message_type,
             correlation_id, json.dumps(payload, default=str, sort_keys=True)),
        )
        db.commit()
    return message_id


def write_live_strategy(symbol: str, interval: int, params: dict, run_id: str) -> dict:
    path = ROOT / "paper_bot_live_strategy.json"
    payload = {"symbol": symbol, "interval": int(interval), "params": dict(params),
               "run_id": run_id, "updated_at": pd.Timestamp.now(tz="UTC").isoformat(),
               "mode": "SIMULATE"}
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)
    return payload


def load_frame(db_path: Path, start: str | None = None,
               end: str | None = None) -> pd.DataFrame:
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
    if end is not None:
        end_stamp = pd.Timestamp(end)
        frame = frame.loc[frame.index <= end_stamp]
    if frame.empty:
        raise RuntimeError("No candles remain after the requested end timestamp")
    if start is not None:
        frame = frame.loc[frame.index >= pd.Timestamp(start)]
    if frame.empty:
        raise RuntimeError("No candles remain after the requested date window")
    return frame[["open", "high", "low", "close", "volume"]].astype(float)


def persist_interval_frames(db_path: Path, frame: pd.DataFrame) -> None:
    """Persist source and derived research candles in the run database."""
    with sqlite3.connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS candles (
            symbol TEXT NOT NULL, interval_minutes INTEGER NOT NULL, time_key TEXT NOT NULL,
            open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
            volume REAL, turnover REAL, source TEXT NOT NULL DEFAULT 'research',
            PRIMARY KEY (symbol, interval_minutes, time_key))""")
        db.execute("DELETE FROM candles WHERE time_key < ?", ("2026-01-01T00:00:00",))
        for interval in RESEARCH_INTERVALS:
            derived = aggregate_candles(frame, interval)
            db.executemany(
                """INSERT OR REPLACE INTO candles
                (symbol, interval_minutes, time_key, open, high, low, close, volume, source)
                VALUES ('US.APP', ?, ?, ?, ?, ?, ?, ?, 'derived_research')""",
                [(interval, pd.Timestamp(stamp).isoformat(), float(row.open), float(row.high),
                  float(row.low), float(row.close), float(row.volume)) for stamp, row in derived.iterrows()],
            )
        db.commit()


def evaluate(frame: pd.DataFrame, params: dict) -> dict:
    effective = {**BASELINE, **params}
    interval_results = {}
    for interval in RESEARCH_INTERVALS:
        interval_frame = aggregate_candles(frame, interval)
        interval_results[str(interval)] = blind_session_walk_forward(
            interval_frame, [effective], min_train_sessions=TRAIN_SESSIONS
        )
    ranked_intervals = []
    for interval, item in interval_results.items():
        aggregate = item.get("aggregate", {})
        score = float(aggregate.get("total_return_pct", 0.0)) - 0.35 * abs(float(aggregate.get("max_drawdown_pct", 0.0)))
        ranked_intervals.append((score, int(interval), item))
    _, selected_interval, replay = max(ranked_intervals, key=lambda row: row[0]) if ranked_intervals else (0.0, 10, {"aggregate": {}})
    # Every candidate gets a fresh 10m baseline replay on the identical
    # continuous train-then-test sequence.
    baseline_replay = blind_session_walk_forward(frame, [dict(BASELINE)], min_train_sessions=TRAIN_SESSIONS)
    result = dict(replay.get("aggregate", {"total_return_pct": 0.0, "max_drawdown_pct": 0.0, "trades": 0}))
    result["selection_score"] = round(float(result.get("total_return_pct", 0.0)) - 0.35 * abs(float(result.get("max_drawdown_pct", 0.0))), 4)
    result["selected_interval"] = selected_interval
    result["base_comparison_interval"] = 10
    result["research_intervals"] = list(RESEARCH_INTERVALS)
    return {"params": effective, "stats": result, "selected_interval": selected_interval, "interval_results": interval_results, "baseline_replay": baseline_replay}


def mutate(rng: random.Random, parent: dict | None = None) -> dict:
    base = dict(BASELINE) if parent is None else {**BASELINE, **parent}
    params = dict(base)
    params["lookback"] = max(5, min(120, int(round(base["lookback"] + rng.gauss(0, 8)))))
    params["fast"] = max(2, min(30, int(round(base["fast"] + rng.gauss(0, 3)))))
    params["slow"] = max(params["fast"] + 2, min(200, int(round(base["slow"] + rng.gauss(0, 12)))))
    params["tp"] = round(max(.02, min(.50, base["tp"] + rng.gauss(0, .03))), 4)
    params["stop"] = round(max(.01, min(.25, base["stop"] + rng.gauss(0, .02))), 4)
    if rng.random() < .30:
        params["exit_mode"] = rng.choice(("fast_or_slow", "slow_break", "trend_cross"))
    if rng.random() < .35:
        params["entry_filter"] = rng.choice(("none", "atr", "slope", "volume"))
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
                allowed = {"lookback", "fast", "slow", "tp", "stop", "break_even_trigger", "break_even_lock", "profit_lock_trigger", "profit_lock", "trail_trigger", "trail_pct", "entry_filter", "atr_buffer", "volume_median_period", "exit_mode", "profit_exit_mode", "profit_arm_return", "profit_lock_return", "profit_atr_multiple", "profit_min_retrace"}
                if isinstance(item, dict) and any(key in item for key in allowed):
                    try:
                        result = {}
                        if "lookback" in item: result["lookback"] = max(5, min(120, int(item["lookback"])))
                        if "fast" in item: result["fast"] = max(2, min(30, int(item["fast"])))
                        if "slow" in item: result["slow"] = max(result.get("fast", int(BASELINE["fast"])) + 2, min(200, int(item["slow"])))
                        for key, low, high in (("tp", .02, .50), ("stop", .01, .25), ("break_even_trigger", .0, .20), ("break_even_lock", .0, .10), ("profit_lock_trigger", .0, .50), ("profit_lock", .0, .20), ("trail_trigger", .0, .50), ("trail_pct", .0, .30), ("atr_buffer", .0, 2.0)):
                            if key in item: result[key] = round(max(low, min(high, float(item[key]))), 4)
                        if item.get("entry_filter") in {"none", "atr", "slope", "volume"}: result["entry_filter"] = item["entry_filter"]
                        if "volume_median_period" in item: result["volume_median_period"] = max(2, min(120, int(item["volume_median_period"])))
                        if item.get("exit_mode") in {"fast_or_slow", "slow_break", "trend_cross"}: result["exit_mode"] = item["exit_mode"]
                        if item.get("profit_exit_mode") in {"legacy_target_lock", "atr_peak_retrace"}: result["profit_exit_mode"] = item["profit_exit_mode"]
                        for key, low, high in (("profit_arm_return", 0.01, 0.50), ("profit_lock_return", 0.0, 0.30), ("profit_atr_multiple", 0.25, 10.0), ("profit_min_retrace", 0.005, 0.50)):
                            if key in item: result[key] = round(max(low, min(high, float(item[key]))), 4)
                        return result
                    except (TypeError, ValueError):
                        return None
    return None


def ask_agent(client: MCPClient | None, antigravity: AntigravityOptimizer | None, provider: str, profile: dict, parents: list[dict], role: str, nvidia_proposals: list[dict] | None = None) -> dict | None:
    role_instruction = {
        "explorer": "Generate a falsifiable strategy hypothesis and identify what evidence would disprove it.",
        "critic": "Actively attack the premise: look for benchmark mismatch, leakage, regime dependence, overfitting, and exits that merely harvest one lucky move.",
        "risk reviewer": "Prioritize drawdown, profit protection, slippage, execution timing, position limits, and whether the exit can actually be implemented causally.",
        "true controller: choose, constrain, and configure one NVIDIA proposal for local deterministic testing": "Challenge every proposal before configuring it. Reject unsupported performance claims, unmatched buy-and-hold comparisons, time-based substitutes for profit capture, and candidates that only win in-sample.",
    }.get(role, "State the hypothesis, its failure mode, and the evidence required to accept it.")
    prompt = (
        "You are an independent mutation agent for the US.APP Moomoo paper bot. "
        "The active strategy is a causal US.APP 10-minute Donchian breakout with EMA trend filtering and close-based execution. "
        "Propose exactly one bounded JSON strategy mutation. You may change "
        "lookback (integer 5-120), fast EMA (2-30), slow EMA (10-200), tp (0.02-0.50), "
        "stop (0.01-0.25), break-even/profit-lock/trailing-stop thresholds, "
        "entry_filter (none, atr, slope, volume), or exit_mode "
        "(fast_or_slow, slow_break, trend_cross). You may also select the "
        "timeframe-independent atr_peak_retrace profit-capture indicator with "
        "profit_arm_return, profit_lock_return, profit_atr_multiple, and "
        "profit_min_retrace. Explicitly consider whether "
        "the exit captures a large profit while protecting an already-profitable "
        "position; do not use time-based exits as a substitute for profit capture. "
        "Keep entries signal-driven. Buy-and-hold is a benchmark only and must "
        "not be presented as a matched-entry strategy result. "
        "These are the only safe strategy configuration keys. "
        f"Your assigned role is: {role_instruction} "
        "Before returning a candidate, challenge: (1) is the entry still signal-driven, "
        "(2) is the benchmark matched to the same entry, (3) does the exit protect a "
        "realized profit without future data, (4) does it survive the unseen final test "
        "and final test, and (5) is the sample large enough to support the claim? "
        "Use only the supplied DATA PROFILE and locally testable hypotheses as evidence; "
        "do not invent candle behavior, trades, or performance. Cite the relevant profile "
        "fact in your internal reasoning before returning JSON. "
        "NVIDIA may suggest; "
        "Antigravity is the only authority allowed to turn a suggestion into a "
        "locally tested configuration. Do not invent performance claims. "
        f"Role: {role}. DATA PROFILE: {json.dumps(profile)} "
        f"PARENTS: {json.dumps(parents[:5])} "
        f"NVIDIA_PROPOSALS_FOR_CONTROLLER: {json.dumps(nvidia_proposals or [])} "
        "Return JSON only, for example {\"lookback\": 40, \"fast\": 12, \"slow\": 30}."
    )
    try:
        if provider == "antigravity":
            return parse_proposal(antigravity.ask(prompt)) if antigravity else None
        return parse_proposal(client.ask(prompt, provider=provider, max_tokens=120)) if client else None
    except Exception:
        if provider == "antigravity":
            raise
        return None


def write_status(path: Path, payload: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    temporary.replace(path)


def mcp_server_path() -> Path:
    configured = os.environ.get("MULTI_MODEL_MCP_SERVER")
    candidates = [
        Path(configured) if configured else None,
        LAB_ROOT.parent / "multi-model-ai-gateway" / "ai" / "mcp_server.py",
        LAB_ROOT.parent / "TradingSystem" / "multi-model-ai-gateway" / "ai" / "mcp_server.py",
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
    raise FileNotFoundError("MCP server not found; set MULTI_MODEL_MCP_SERVER")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "quant_dashboard.sqlite3")
    ap.add_argument("--run-dir", type=Path, default=LAB_ROOT / "strategy_lab_runs")
    ap.add_argument("--rounds", type=int, default=20)
    ap.add_argument("--agents", type=int, default=2)
    ap.add_argument("--candidates", type=int, default=100)
    ap.add_argument("--start", help="inclusive candle timestamp, preferably ISO 8601 without timezone")
    ap.add_argument("--end", help="inclusive candle timestamp, preferably ISO 8601 without timezone")
    ap.add_argument("--providers", default="antigravity")
    ap.add_argument("--continuous", action="store_true")
    args = ap.parse_args()
    providers = [x.strip() for x in args.providers.split(",") if x.strip()]
    frame = load_frame(args.db, args.start, args.end)
    persist_interval_frames(args.db, frame)
    baseline_evidence = {
        "current_window_10m": blind_session_walk_forward(frame, [dict(BASELINE)], min_train_sessions=TRAIN_SESSIONS)["aggregate"]
    }
    blind_candidates = [dict(BASELINE)] + [{**BASELINE, **variant} for variant in PROFIT_EXIT_RESEARCH_VARIANTS]
    blind_evidence = blind_session_walk_forward(frame, blind_candidates, min_train_sessions=TRAIN_SESSIONS)
    profile = {
        "symbol": "US.APP", "interval": "10m", "rows": len(frame),
        "start": str(frame.index.min()), "end": str(frame.index.max()),
        "data_window_policy": "all_available_candles_or_explicit_start_end", "training_sessions": TRAIN_SESSIONS, "requested_start": args.start,
        "requested_end": args.end, "rows_available_for_continuous_replay": len(frame),
        "sessions": int(frame.index.normalize().nunique()),
        "close_start": round(float(frame["close"].iloc[0]), 6),
        "close_end": round(float(frame["close"].iloc[-1]), 6),
        "raw_close_to_close_return_pct": round(float((frame["close"].iloc[-1] / frame["close"].iloc[0] - 1) * 100), 3),
        "baseline_evidence": baseline_evidence,
        "blind_session_walk_forward": {
            "status": blind_evidence["status"],
            "train_sessions": blind_evidence.get("train_sessions"),
            "replayed_sessions": blind_evidence.get("replayed_sessions"),
            "test_start": blind_evidence.get("test_start"),
            "test_end": blind_evidence.get("test_end"),
            "aggregate": blind_evidence.get("aggregate"),
            "ending_capital": blind_evidence.get("ending_capital"),
        },
    }
    run_dir = args.run_dir / ("APP-" + time.strftime("%Y%m%d-%H%M%S"))
    run_dir.mkdir(parents=True, exist_ok=True)
    init_agent_bus(args.db)
    run_id = run_dir.name
    (run_dir / "blind_session_walk_forward.json").write_text(
        json.dumps(blind_evidence, indent=2, default=str) + "\n"
    )
    stop_file = run_dir / "STOP"
    status_file = args.run_dir / "app_runtime_status.json"
    client = None
    antigravity = None
    if any(provider in {"local", "nvidia"} for provider in providers):
        try:
            client = MCPClient(mcp_server_path(), os.environ.get("MULTI_MODEL_GATEWAY_URL", "http://127.0.0.1:8788"))
        except Exception:
            pass
    if "antigravity" in providers:
        try:
            antigravity = AntigravityOptimizer(timeout_seconds=60)
        except Exception as exc:
            raise RuntimeError(f"required Antigravity controller unavailable: {exc}") from exc
    else:
        raise RuntimeError("Antigravity is required as the strategy-lab controller; include antigravity in --providers")
    parents = [dict(BASELINE)]
    round_number = 0
    try:
        while args.continuous or round_number < args.rounds:
            if stop_file.exists():
                break
            round_number += 1
            write_status(status_file, {"state": "RUNNING", "symbol": "US.APP", "interval": "10m", "round": round_number, "run_dir": str(run_dir), "profile": profile})
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.agents)) as pool:
                jobs = [pool.submit(lambda seed: [evaluate(frame, mutate(random.Random(seed), random.choice(parents))) for _ in range(args.candidates)], 900000 + round_number * 100 + i) for i in range(args.agents)]
                candidates = [item for job in jobs for item in job.result()]
            candidates.extend(evaluate(frame, {**BASELINE, **variant}) for variant in PROFIT_EXIT_RESEARCH_VARIANTS)
            nvidia_proposals = []
            message_ids = []
            if client:
                for agent in range(max(1, args.agents)):
                    proposal = ask_agent(client, None, "nvidia", profile, parents, ["explorer", "critic", "risk reviewer"][agent % 3])
                    if proposal:
                        nvidia_proposals.append(proposal)
                        message_ids.append(send_agent_message(
                            args.db, run_id, round_number, "nvidia", "antigravity",
                            "strategy_proposal", {"role": ["explorer", "critic", "risk reviewer"][agent % 3], "proposal": proposal},
                        ))
            if antigravity:
                configured_parents = parents + nvidia_proposals
                if nvidia_proposals:
                    message_ids.append(send_agent_message(
                        args.db, run_id, round_number, "research_lab", "antigravity",
                        "controller_review_request", {"parents": parents, "nvidia_proposals": nvidia_proposals},
                    ))
                for agent in range(max(1, args.agents)):
                    proposal = ask_agent(None, antigravity, "antigravity", profile, configured_parents, "true controller: choose, constrain, and configure one NVIDIA proposal for local deterministic testing", nvidia_proposals)
                    if proposal:
                        candidates.append(evaluate(frame, proposal))
                        message_ids.append(send_agent_message(
                            args.db, run_id, round_number, "antigravity", "deterministic_evaluator",
                            "configured_candidate", {"proposal": proposal},
                        ))
            candidates.append(evaluate(frame, dict(BASELINE)))
            candidates.sort(key=lambda item: item["stats"]["selection_score"], reverse=True)
            parents = [item["params"] for item in candidates[:max(2, args.agents)]]
            selected = candidates[0]
            selected_interval = int(selected.get("selected_interval", 10))
            selected_frame = aggregate_candles(frame, selected_interval)
            candidate_blind = blind_session_walk_forward(selected_frame, [selected["params"]], min_train_sessions=TRAIN_SESSIONS)
            baseline_blind = blind_session_walk_forward(frame, [dict(BASELINE)], min_train_sessions=TRAIN_SESSIONS)
            final = {"params": selected["params"], "stats": candidate_blind["aggregate"]}
            baseline_final_test = {"params": dict(BASELINE), "stats": baseline_blind["aggregate"]}
            baseline_current_window = evaluate(frame, dict(BASELINE))
            promotion_reasons = []
            if final["stats"].get("trades", 0) < MIN_PROMOTION_TRADES:
                promotion_reasons.append(f"blind_replay_trades<{MIN_PROMOTION_TRADES}")
            if final["stats"]["total_return_pct"] <= baseline_final_test["stats"]["total_return_pct"]:
                promotion_reasons.append("blind_replay_return_not_above_current_baseline")
            if final["stats"]["max_drawdown_pct"] < baseline_final_test["stats"]["max_drawdown_pct"] - MAX_PROMOTION_DRAWDOWN_DEGRADATION_PCT:
                promotion_reasons.append("final_test_drawdown_too_deep")
            if promotion_reasons:
                promoted = {"status": "REJECTED", "params": dict(BASELINE), "reasons": promotion_reasons, "decision_basis": "continuous_unseen_replay_from_session_22_vs_fresh_10m_baseline", "baseline_final_test": baseline_final_test["stats"], "baseline_current_window": baseline_current_window["stats"]}
            else:
                promoted = write_live_strategy("US.APP", selected_interval, selected["params"], f"APP-{run_dir.name}-r{round_number:03d}")
            result = {"round": round_number, "profile": profile, "train_best": candidates[0], "selected_train": selected, "candidate_blind_replay": candidate_blind, "baseline_blind_replay": baseline_blind, "baseline_final_test": baseline_final_test, "baseline_current_window": baseline_current_window, "final_test": final, "promotion_gate": {"hard_rule": "first_21_complete_sessions_train_then_one_continuous_unseen_replay_to_latest_candle", "decision_basis": "continuous_unseen_replay_from_session_22_vs_fresh_10m_baseline", "train_sessions": TRAIN_SESSIONS, "test_step_sessions": "continuous_to_latest", "min_trades": MIN_PROMOTION_TRADES, "max_drawdown_degradation_pct": MAX_PROMOTION_DRAWDOWN_DEGRADATION_PCT}, "promoted": promoted, "agent_mutation": bool(client or antigravity), "proposal_provider": "nvidia" if client else None, "configuration_provider": "antigravity" if antigravity else None, "nvidia_proposals": nvidia_proposals}
            message_ids.append(send_agent_message(
                args.db, run_id, round_number, "deterministic_evaluator", "antigravity",
                "evaluation_result", {"candidate": final, "baseline": baseline_final_test, "promoted": promoted},
            ))
            message_ids.append(send_agent_message(
                args.db, run_id, round_number, "research_lab", "mlx_learner",
                "learning_record", {"selected": selected, "final_test": final, "baseline": baseline_final_test, "promoted": promoted},
            ))
            result["agent_to_agent"] = {"protocol": "sqlite_agent_messages", "message_ids": message_ids, "acknowledged_by": ["deterministic_evaluator", "antigravity", "mlx_learner"]}
            (run_dir / f"round-{round_number:03d}.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
            write_status(status_file, {"state": "RUNNING", **result, "run_dir": str(run_dir)})
            print(json.dumps({"round": round_number, "train": candidates[0]["stats"], "final_test": final["stats"], "promoted": promoted}), flush=True)
    finally:
        if client:
            client.close()
        write_status(status_file, {"state": "STOPPED", "round": round_number, "run_dir": str(run_dir), "profile": profile})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
