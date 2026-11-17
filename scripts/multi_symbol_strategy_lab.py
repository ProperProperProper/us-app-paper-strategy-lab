#!/usr/bin/env python3
"""Per-symbol mutation lab over the local ASX daily-candle universe.

This is the daily research variant of the MCP Strategy Lab. It keeps symbols
isolated, evaluates candidates locally, and selects parameters chronologically:
train -> validation -> untouched test. AI reviews can suggest directions, but
they never supply performance numbers or execute code.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import random
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from australian_super_fees import australian_super_member_direct_fee
from strategy_57pct import BASELINE, required_warmup_candles, run, stats
from mcp_strategy_lab import MCPClient, ONE_HOUR_WINNER, APP_IMITATION, safe_agent_review

# Active universe after the <=6% final-test drawdown screen. The full cached
# 30-symbol universe remains available in SQLite for audit/reproducibility.
UNIVERSE = "CSL TWE".split()
CAPITAL = 200_000.0
ALLOCATION = 1.0
SLIPPAGE_BPS = 2.0
MAX_DRAWDOWN_PCT = 6.0
MIN_TRADES = 1
NVIDIA_MODELS = [
    "nvidia/nemotron-3.5-bolt-e4b",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "deepseek-ai/deepseek-v4.1-flash",
]
NVIDIA_MIN_INTERVAL_SECONDS = 30.0
NVIDIA_JITTER_SECONDS = 2.0
ANTIGRAVITY_BIN = os.environ.get("ANTIGRAVITY_BIN", "/Applications/Gemini.app/Contents/Helpers/agy")
ANTIGRAVITY_MODEL = os.environ.get("ANTIGRAVITY_MODEL", "gemini-3.8-flash-low")


class NvidiaRequestGate:
    """Serialize hosted calls and adaptively back off after upstream failures."""
    def __init__(self):
        self.lock = threading.Lock()
        self.next_request_at = 0.0
        self.global_cooldown_until = 0.0
        self.cooldown_until: dict[str, float] = {}
        self.failures: dict[str, int] = {}
        self.health: dict[str, dict] = {}

    def _entry(self, model: str) -> dict:
        return self.health.setdefault(model, {"requests": 0, "successes": 0,
            "failures": 0, "local_fallbacks": 0, "empty_responses": 0,
            "invalid_responses": 0,
            "last_route": None, "last_error": None, "last_response_excerpt": None,
            "last_latency_ms": None,
            "cooldown_seconds": 0})

    def acquire(self, model: str | None) -> bool:
        model = model or "auto"
        while True:
            with self.lock:
                now = time.monotonic()
                wait_until = max(self.next_request_at, self.global_cooldown_until, self.cooldown_until.get(model, 0.0))
                if wait_until <= now:
                    self.next_request_at = now + NVIDIA_MIN_INTERVAL_SECONDS + random.uniform(0, NVIDIA_JITTER_SECONDS)
                    self._entry(model)["requests"] += 1
                    return True
                wait = wait_until - now
            time.sleep(min(wait, 1.0))

    def success(self, model: str | None, route: str | None = None, latency_ms: float | None = None, empty: bool = False):
        with self.lock:
            if model:
                self.failures[model] = 0
                self.cooldown_until.pop(model, None)
                item = self._entry(model)
                item["successes"] += 1
                item["last_route"] = route or "nvidia"
                item["last_latency_ms"] = round(latency_ms, 1) if latency_ms is not None else None
                if empty:
                    item["empty_responses"] += 1

    def failure(self, model: str | None, error: str | None = None):
        if not model:
            return
        with self.lock:
            count = self.failures.get(model, 0) + 1
            self.failures[model] = count
            cooldown = min(600.0, 90.0 * (2 ** min(count - 1, 3)))
            self.cooldown_until[model] = time.monotonic() + cooldown
            self.global_cooldown_until = max(self.global_cooldown_until, time.monotonic() + min(60.0, 15.0 * count))
            item = self._entry(model)
            item["failures"] += 1
            item["last_error"] = (error or "upstream failure")[:240]
            item["cooldown_seconds"] = int(cooldown)

    def fallback(self, model: str | None, reason: str | None = None):
        if not model:
            return
        with self.lock:
            item = self._entry(model)
            item["local_fallbacks"] += 1
            item["last_route"] = "local_fallback"
            if reason:
                item["last_error"] = reason[:240]

    def empty(self, model: str | None, response: str):
        if not model:
            return
        with self.lock:
            self._entry(model)["last_response_excerpt"] = "<empty or non-parseable response>"

    def invalid(self, model: str | None, response: str | None = None):
        if not model:
            return
        with self.lock:
            item = self._entry(model)
            item["invalid_responses"] += 1
            if response:
                item["last_response_excerpt"] = response[:240]

    def snapshot(self) -> dict:
        with self.lock:
            return {name: dict(value) for name, value in self.health.items()}


NVIDIA_GATE = NvidiaRequestGate()
CONTROLLER_HEALTH = {
    "requests": 0,
    "successes": 0,
    "failures": 0,
    "fallbacks": 0,
    "antigravity_fallbacks": 0,
    "antigravity_fallback_successes": 0,
    "antigravity_fallback_failures": 0,
    "last_route": None,
    "last_error": None,
    "last_latency_ms": None,
}
ANTIGRAVITY_HEALTH = {
    "model": ANTIGRAVITY_MODEL,
    "requests": 0,
    "successes": 0,
    "failures": 0,
    "invalid_responses": 0,
    "last_error": None,
    "last_latency_ms": None,
}


class AntigravityOptimizer:
    """Bounded local Antigravity proposal worker.

    Antigravity may propose mutations only. It runs in plan mode, receives the
    measured profile in the prompt, and never writes code or computes metrics.
    The deterministic evaluator remains the authority.
    """

    def __init__(self, timeout_seconds: int = 60):
        binary = shutil.which(ANTIGRAVITY_BIN) or (ANTIGRAVITY_BIN if Path(ANTIGRAVITY_BIN).exists() else None)
        if not binary:
            raise FileNotFoundError(f"Antigravity CLI not found: {ANTIGRAVITY_BIN}")
        self.binary = binary
        self.timeout_seconds = max(10, int(timeout_seconds))

    def ask(self, prompt: str) -> str:
        started = time.monotonic()
        ANTIGRAVITY_HEALTH["requests"] += 1
        command = [
            self.binary, "--model", ANTIGRAVITY_MODEL, "--effort", "low", "--mode", "plan",
            "--disable-slash-commands", "--output-format", "json",
            "--print-timeout", f"{self.timeout_seconds}s", "--print", prompt,
        ]
        try:
            completed = subprocess.run(
                command, cwd=ROOT.parent, capture_output=True, text=True,
                timeout=self.timeout_seconds + 10, check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError((completed.stderr or completed.stdout or f"exit={completed.returncode}").strip()[:240])
            envelope = json.loads(completed.stdout)
            response = envelope.get("response", "") if isinstance(envelope, dict) else ""
            if not isinstance(response, str) or not response.strip():
                raise RuntimeError("Antigravity returned an empty response")
            ANTIGRAVITY_HEALTH["successes"] += 1
            ANTIGRAVITY_HEALTH["last_latency_ms"] = round((time.monotonic() - started) * 1000, 1)
            return response
        except Exception as exc:
            ANTIGRAVITY_HEALTH["failures"] += 1
            ANTIGRAVITY_HEALTH["last_error"] = str(exc)[:240]
            ANTIGRAVITY_HEALTH["last_latency_ms"] = round((time.monotonic() - started) * 1000, 1)
            raise


def load_frame(db_path: Path, symbol: str) -> pd.DataFrame:
    with sqlite3.connect(db_path) as db:
        frame = pd.read_sql_query(
            "SELECT session_date, open, high, low, close, volume FROM daily_candles WHERE symbol=? AND source='yfinance' ORDER BY session_date",
            db, params=(symbol,), parse_dates=["session_date"],
        ).set_index("session_date")
    frame.index = frame.index.tz_localize(None)
    frame.index.name = "time_key"
    return frame[["open", "high", "low", "close", "volume"]].astype(float)


def load_app_5h_frame(db_path: Path, symbol: str) -> pd.DataFrame:
    """Build exactly the app's five-hour candles from the 42-day hourly cache."""
    with sqlite3.connect(db_path) as db:
        rows = pd.read_sql_query(
            "SELECT timestamp_local, open, high, low, close, volume FROM hourly_candles WHERE symbol=? ORDER BY timestamp_local",
            db, params=(symbol,), parse_dates=["timestamp_local"],
        )
    rows["date"] = rows["timestamp_local"].dt.date
    output = []
    for date, group in rows.groupby("date"):
        hours = {stamp.hour: row for stamp, row in group.set_index("timestamp_local").iterrows()}
        start = 10 if all(hour in hours for hour in range(10, 15)) else 9 if all(hour in hours for hour in range(9, 14)) else None
        if start is None:
            continue
        bars = [hours[hour] for hour in range(start, start + 5)]
        output.append({
            # The included 10:00-14:00 bars are complete at 15:00 Sydney
            # time. Keep the completion timestamp so the strategy's
            # execution-window checks cannot treat the candle as available at
            # the session open.
            "time_key": pd.Timestamp(date).replace(hour=15),
            "open": float(bars[0]["open"]), "high": max(float(bar["high"]) for bar in bars),
            "low": min(float(bar["low"]) for bar in bars), "close": float(bars[-1]["close"]),
            "volume": sum(float(bar["volume"]) for bar in bars),
        })
    return pd.DataFrame(output).set_index("time_key").sort_index()


def evaluate(frame: pd.DataFrame, params: dict) -> dict:
    _, trades, data = run(frame, params, CAPITAL, ALLOCATION, SLIPPAGE_BPS, 0,
                          fee_model=australian_super_member_direct_fee)
    result = stats(trades, data, CAPITAL)
    result.update({
        "warmup_status": "FULL_WARMUP" if len(frame) >= required_warmup_candles(params) else "LIMITED_CACHE_WARMUP",
        "required_warmup_candles": required_warmup_candles(params),
        "available_candles": len(frame),
        "brokerage": "AustralianSuper Member Direct",
        "administration_fee_included": False,
    })
    score = result["total_return_pct"] - 0.35 * abs(result["max_drawdown_pct"])
    result["selection_score"] = round(score, 4)
    result["drawdown_limit_pct"] = MAX_DRAWDOWN_PCT
    result["minimum_trades"] = MIN_TRADES
    result["risk_eligible"] = (
        abs(float(result["max_drawdown_pct"])) <= MAX_DRAWDOWN_PCT
        and int(result["trades"]) >= MIN_TRADES
    )
    return {"params": params, "stats": result}


def mutate(rng: random.Random, parent: dict | None = None) -> dict:
    if parent is None:
        fast = rng.randint(2, 30)
        slow = rng.randint(fast + 2, 200)
        return {
            "lookback": rng.randint(5, 120), "fast": fast, "slow": slow,
            "entry_mode": rng.choice(("breakout", "breakout_trend", "ema_cross", "breakout_or_cross")),
            "exit_mode": rng.choice(("fast_or_slow", "slow_break", "trend_cross")),
            "downtrend_filter": rng.random() < 0.85,
            "regime_ema": rng.randint(40, 120),
            "max_holding_bars": rng.choice((0, 10, 20, 30, 45, 60)),
            "tp": round(rng.uniform(.01, .50), 4), "stop": round(rng.uniform(.01, .25), 4),
            "break_even_trigger": round(rng.uniform(.01, .08), 4), "break_even_lock": round(rng.uniform(0, .01), 4),
            "profit_lock_trigger": round(rng.uniform(.04, .20), 4), "profit_lock": round(rng.uniform(0, .04), 4),
            "trail_trigger": round(rng.uniform(.03, .20), 4), "trail_pct": round(rng.uniform(.005, .08), 4),
            "entry_filter": rng.choice(("none", "atr", "slope", "volume")), "atr_buffer": rng.choice((.05, .10, .15, .20, .25)), "volume_median_period": rng.choice((10, 20, 30)),
        }
    # Hosted proposals are intentionally allowed to omit optional parameters.
    # Start from the deterministic strategy defaults before mutating so a
    # partial proposal can never crash the continuous wrapper.
    defaults = {
        **BASELINE,
        "entry_mode": "breakout_trend",
        "exit_mode": "fast_or_slow",
        "downtrend_filter": True,
        "regime_ema": 89,
        "max_holding_bars": 0,
    }
    p = {**defaults, **parent}
    p["lookback"] = max(5, min(120, int(round(p["lookback"] + rng.gauss(0, 8)))))
    p["fast"] = max(2, min(30, int(round(p["fast"] + rng.gauss(0, 3)))))
    p["slow"] = max(p["fast"] + 2, min(200, int(round(p["slow"] + rng.gauss(0, 15)))))
    if rng.random() < .25:
        p["entry_mode"] = rng.choice(("breakout", "breakout_trend", "ema_cross", "breakout_or_cross"))
    if rng.random() < .25:
        p["exit_mode"] = rng.choice(("fast_or_slow", "slow_break", "trend_cross"))
    if rng.random() < .20:
        p["downtrend_filter"] = rng.random() < 0.85
    p["regime_ema"] = max(20, min(150, int(round(p.get("regime_ema", 89) + rng.gauss(0, 10)))))
    if rng.random() < .25:
        p["max_holding_bars"] = rng.choice((0, 10, 20, 30, 45, 60))
    if rng.random() < .25:
        p["entry_filter"] = rng.choice(("none", "atr", "slope", "volume"))
    if rng.random() < .25:
        p["atr_buffer"] = rng.choice((.05, .10, .15, .20, .25))
    if rng.random() < .20:
        p["volume_median_period"] = rng.choice((10, 20, 30))
    for key, low, high, sd in (("tp", .01, .50, .04), ("stop", .01, .25, .025),
                               ("break_even_trigger", .01, .08, .01), ("break_even_lock", 0, .01, .002),
                               ("profit_lock_trigger", .04, .20, .02), ("profit_lock", 0, .04, .006),
                               ("trail_trigger", .03, .20, .02), ("trail_pct", .005, .08, .01)):
        p[key] = round(max(low, min(high, p[key] + rng.gauss(0, sd))), 4)
    return p


def search(frame: pd.DataFrame, seed: int, candidates: int, parents: list[dict]) -> list[dict]:
    rng = random.Random(seed)
    results = []
    for _ in range(candidates):
        parent = rng.choice(parents) if parents and rng.random() < .8 else None
        results.append(evaluate(frame, mutate(rng, parent)))
    return sorted(
        results,
        key=lambda x: (x["stats"]["risk_eligible"], x["stats"]["selection_score"]),
        reverse=True,
    )


def review(client: MCPClient | None, provider: str, symbol: str, profile: dict, top: list[dict], agent_id: int = 1) -> dict:
    if client is None:
        return {"provider": provider, "status": "MCP_UNAVAILABLE"}
    prompt = (
        "You are a quantitative research reviewer. Do not invent results. "
        f"Review the locally computed {symbol} ASX daily-candle candidates below. "
        "The local evaluator handles all returns, costs and validation. "
        f"You are independent reviewer {agent_id}; do not assume other agents agree. "
        "Suggest one data-grounded mutation direction using breakout, trend, regime, "
        "exit or risk logic. Return concise JSON with hypothesis, evidence, failure_risks, "
        "next_data_grounded_improvement. Do not claim validation.\n"
        f"DATA PROFILE: {json.dumps(profile)}\nCANDIDATES: {json.dumps(top[:3])}"
    )
    try:
        text = client.ask(prompt, provider=provider)
        return {"provider": provider, "review": safe_agent_review(text)}
    except Exception as exc:
        return {"provider": provider, "error": str(exc)}


def extract_candidate_list(text: str) -> list[dict]:
    decoder = json.JSONDecoder()
    for start, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return [value]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)][:30]
    return []


def leaderboard(items: list[dict], limit: int = 5) -> list[dict]:
    """Return compact causal feedback for the next agent generation."""
    ranked = sorted(items, key=lambda x: x.get("stats", {}).get("selection_score", -1e9), reverse=True)
    return [{"params": item.get("params", {}), "stats": {
        key: item.get("stats", {}).get(key)
        for key in ("selection_score", "total_return_pct", "max_drawdown_pct", "trades", "risk_eligible")
    }} for item in ranked[:limit]]


def reflect_generation(before: list[dict], after: list[dict]) -> dict:
    """Create measured feedback for the next cycle without model-supplied claims."""
    before_top = (before or [{}])[0].get("stats", {})
    after_top = (after or [{}])[0].get("stats", {})
    before_score = float(before_top.get("selection_score") or 0.0)
    after_score = float(after_top.get("selection_score") or 0.0)
    before_dd = float(before_top.get("max_drawdown_pct") or 0.0)
    after_dd = float(after_top.get("max_drawdown_pct") or 0.0)
    delta = round(after_score - before_score, 4)
    if delta > 0:
        next_focus = "preserve the measured improvement and test robustness around the new parents"
    elif after_dd < before_dd:
        next_focus = "investigate the drawdown improvement without sacrificing causal trade evidence"
    else:
        next_focus = "change one bounded entry, exit, or regime assumption and require measurable improvement"
    return {
        "before_score": round(before_score, 4),
        "after_score": round(after_score, 4),
        "score_delta": delta,
        "before_drawdown_pct": round(before_dd, 4),
        "after_drawdown_pct": round(after_dd, 4),
        "next_focus": next_focus,
    }


def visible_model_text(text: str) -> str:
    """Drop local reasoning traces before inter-agent communication."""
    value = (text or "").strip()
    if "</think>" in value:
        value = value.split("</think>", 1)[1].strip()
    value = value.replace("<|im_end|>", "").strip()
    if value.startswith("<think>"):
        return ""
    return value


def usable_controller_brief(value: str) -> bool:
    """Accept only a compact, role-addressed MLX directive."""
    labels = ("OBJECTIVE:", "EXPLORE:", "CRITIC:", "RISK:", "EVIDENCE:")
    if not all(label in value for label in labels):
        return False
    words = [word.lower() for word in value.split() if word.strip()]
    if len(words) < 10:
        return False
    # Reject low-information repetition from a tiny local model. It must not
    # be forwarded to hosted specialists as if it were a useful directive.
    return len(set(words)) / len(words) >= 0.35


def measured_controller_fallback(symbol: str, board: list[dict]) -> str:
    """Return a useful, evidence-grounded directive when MLX text is unusable."""
    best = (board or [{}])[0].get("stats", {})
    score = best.get("selection_score", "unavailable")
    drawdown = best.get("max_drawdown_pct", "unavailable")
    trades = best.get("trades", "unavailable")
    if float(score or 0) > 0:
        explore = "test one bounded mutation around the current parent and preserve the measured positive score"
    else:
        explore = "test one bounded entry or exit mutation against the current measured parents"
    return (
        f"OBJECTIVE: Improve causal train performance for {symbol} without changing the evaluator.\n"
        f"EXPLORE: {explore}.\n"
        "CRITIC: Check whether the apparent result is supported by enough trades and chronological data.\n"
        f"RISK: Keep drawdown within the configured gate; current best is {drawdown}% with {trades} trades.\n"
        f"EVIDENCE: Compare the next population with score {score}, drawdown, trade count, and eligibility."
    )


def normalize_controller_brief(text: str, symbol: str, board: list[dict]) -> str:
    """Keep only role-addressed controller content and fill safely from measurements."""
    visible = visible_model_text(text)
    if not usable_controller_brief(visible):
        return measured_controller_fallback(symbol, board)
    labels = ("OBJECTIVE:", "EXPLORE:", "CRITIC:", "RISK:", "EVIDENCE:")
    fields = {}
    for index, label in enumerate(labels):
        start = visible.find(label) + len(label)
        end = min((visible.find(next_label, start) for next_label in labels[index + 1:] if visible.find(next_label, start) >= 0), default=len(visible))
        value = " ".join(visible[start:end].split())[:280]
        fields[label] = value
    if any(not value for value in fields.values()):
        return measured_controller_fallback(symbol, board)
    return "\n".join(f"{label} {fields[label]}" for label in labels)


def normalize_candidate(raw: dict) -> dict | None:
    """Validate one model proposal before local evaluation."""
    allowed = {
        "lookback", "fast", "slow", "entry_mode", "exit_mode", "downtrend_filter",
        "regime_ema", "max_holding_bars", "tp", "stop", "entry_filter", "atr_buffer",
        "volume_median_period", "break_even_trigger", "break_even_lock", "profit_lock_trigger",
        "profit_lock", "trail_trigger", "trail_pct",
    }
    value = {key: raw[key] for key in allowed if key in raw}
    if not value:
        return None
    int_ranges = {"lookback": (5, 120), "fast": (2, 30), "slow": (4, 200),
                  "regime_ema": (20, 150), "max_holding_bars": (0, 60),
                  "volume_median_period": (5, 60)}
    float_ranges = {"tp": (.01, .50), "stop": (.01, .25), "break_even_trigger": (.0, .20),
                    "break_even_lock": (0, .10), "profit_lock_trigger": (.0, .50),
                    "profit_lock": (0, .20), "trail_trigger": (.0, .50),
                    "trail_pct": (.001, .20), "atr_buffer": (0, 1.0)}
    try:
        for key, (low, high) in int_ranges.items():
            if key in value:
                value[key] = int(value[key])
                if not low <= value[key] <= high:
                    return None
        for key, (low, high) in float_ranges.items():
            if key in value:
                value[key] = round(float(value[key]), 4)
                if not low <= value[key] <= high:
                    return None
        if "fast" in value and "slow" in value and value["slow"] <= value["fast"]:
            return None
        if "entry_mode" in value and value["entry_mode"] not in {"breakout", "breakout_trend", "ema_cross", "breakout_or_cross"}:
            return None
        if "exit_mode" in value and value["exit_mode"] not in {"fast_or_slow", "slow_break", "trend_cross"}:
            return None
        if "entry_filter" in value and value["entry_filter"] not in {"none", "atr", "slope", "volume"}:
            return None
        if "downtrend_filter" in value:
            value["downtrend_filter"] = bool(value["downtrend_filter"])
    except (TypeError, ValueError):
        return None
    return value


def decomposition_framework(symbol: str, profile: dict, board: list[dict],
                            controller_directive: str = "") -> dict:
    """Build the explicit five-step coordination contract for each generation.

    This is deliberately data-only metadata. It gives MLX and the specialist
    agents the same shared task definition without allowing any model to score
    candidates, invent evidence, or see data outside the current causal split.
    """
    return {
        "step_1_understand_objective": {
            "objective": "Improve measured causal performance for one symbol while respecting the drawdown/trade gates.",
            "symbol": symbol,
            "data_scope": profile,
            "constraints": [
                "daily yfinance candles only for this run",
                "chronological train/validation/test evaluation",
                "no look-ahead or future-derived features",
                "one position at a time",
                "local deterministic evaluator owns returns, fees and drawdown",
            ],
        },
        "step_2_identify_independent_subtasks": [
            {"id": "explore", "question": "Which bounded entry/exit mutation addresses the measured weakness?"},
            {"id": "critic", "question": "Which assumption in the current parents is least supported by the measured leaderboard?"},
            {"id": "risk_review", "question": "Which mutation can improve robustness without violating drawdown or minimum-trade gates?"},
            {"id": "local_search", "question": "Which nearby parameter mutations are worth evaluating next?"},
        ],
        "step_3_assign_specialization": {
            "controller": "local_mlx",
            "explore": "nvidia specialist / causal hypothesis generation",
            "critic": "nvidia specialist / failure-mode review",
            "risk_review": "nvidia specialist / risk and robustness review",
            "local_search": "local deterministic mutation worker",
            "evaluator": "local deterministic evaluator; authoritative",
        },
        "step_4_define_expected_outputs": {
            "controller": "one concise visible directive: observed weakness, bounded focus per role, next evidence",
            "specialists": "one JSON candidate object using the allowed parameter keys; no performance claims",
            "local_search": "evaluated candidate records with parameters and measured statistics",
            "evaluator": "selection_score, return, drawdown, trade count, eligibility",
            "telemetry": "provider, model, latency, success/failure, fallback and cooldown state",
        },
        "step_5_plan_aggregation": [
            "MLX observes the current measured leaderboard and emits the next directive.",
            "Specialists receive the same directive, parents and measured feedback.",
            "Every proposal is evaluated locally on the same chronological train split.",
            "Population is ranked by eligibility, then selection score; top parents carry forward.",
            "The local evaluator reflects on the measured delta before the next controller pass.",
            "The compact memory commit persists directives, parents, evidence and telemetry across sessions.",
            "Validation and untouched test remain separate and are never supplied to proposal agents.",
        ],
        "agentic_cycle": ["recall", "observe", "plan", "delegate", "evaluate", "reflect", "commit"],
        "measured_leaderboard": board,
        "prior_controller_directive": controller_directive[:1600],
    }


def antigravity_controller_fallback(worker: AntigravityOptimizer, symbol: str, generation: int,
                                    board: list[dict], prior_directive: str = "") -> str | None:
    """Ask Antigravity for a directive only when MLX cannot produce one.

    MLX remains the primary controller.  This bounded fallback uses the same
    measured board and emits only orchestration text; it cannot evaluate or
    modify candidates.  Returning ``None`` preserves the deterministic
    measured fallback as the final safety net.
    """
    best = (board or [{}])[0].get("stats", {})
    prompt = (
        "You are a bounded controller fallback for causal strategy research, not advice. "
        f"Symbol {symbol}, generation {generation}. Measured best candidate: "
        f"score={best.get('selection_score')}, return={best.get('total_return_pct')}, "
        f"drawdown={best.get('max_drawdown_pct')}, trades={best.get('trades')}. "
        "Return exactly five short lines beginning OBJECTIVE:, EXPLORE:, CRITIC:, RISK:, EVIDENCE:. "
        "Use only the supplied measurements and memory signal. Do not provide parameter values, "
        "returns not shown, future information, code, or markdown. "
        f"Memory signal={prior_directive[:240]}"
    )
    started = time.monotonic()
    CONTROLLER_HEALTH["antigravity_fallbacks"] += 1
    try:
        brief = visible_model_text(worker.ask(prompt))
        if usable_controller_brief(brief):
            CONTROLLER_HEALTH["antigravity_fallback_successes"] += 1
            CONTROLLER_HEALTH["last_route"] = "antigravity_fallback"
            CONTROLLER_HEALTH["last_latency_ms"] = round((time.monotonic() - started) * 1000, 1)
            return normalize_controller_brief(brief, symbol, board)
        CONTROLLER_HEALTH["antigravity_fallback_failures"] += 1
        CONTROLLER_HEALTH["last_error"] = "Antigravity returned an unusable controller brief"
    except Exception as exc:
        CONTROLLER_HEALTH["antigravity_fallback_failures"] += 1
        CONTROLLER_HEALTH["last_error"] = str(exc)[:240]
    CONTROLLER_HEALTH["last_latency_ms"] = round((time.monotonic() - started) * 1000, 1)
    return None


def mlx_controller(client: MCPClient | None, symbol: str, generation: int, profile: dict,
                   board: list[dict], prior_directive: str = "",
                   antigravity_worker: AntigravityOptimizer | None = None) -> str:
    """Use local MLX as the bounded controller for specialist agents."""
    framework = decomposition_framework(symbol, profile, board, prior_directive)
    if client is None:
        return "Controller unavailable; preserve measured parents and test one bounded causal mutation."
    compact_board = []
    for index, item in enumerate(board[:3]):
        measured = item.get("stats", {})
        compact_board.append(
            f"{index + 1}: score={measured.get('selection_score')} "
            f"return={measured.get('total_return_pct')} "
            f"dd={measured.get('max_drawdown_pct')} trades={measured.get('trades')}"
        )
    prompt = (
        "MLX controller for causal research, not advice. "
        f"Symbol {symbol}, generation {generation}. Measured candidates: {'; '.join(compact_board)}. "
        "Return five short lines starting OBJECTIVE:, EXPLORE:, CRITIC:, RISK:, EVIDENCE:. "
        "Use only the measured candidates and the prior memory signal. Give bounded research focuses, no parameter values. "
        f"Prior memory signal={prior_directive[:240]}"
    )
    started = time.monotonic()
    CONTROLLER_HEALTH["requests"] += 1
    try:
        raw_brief = client.ask(prompt, provider="local", max_tokens=120)
        brief = visible_model_text(raw_brief)
        if usable_controller_brief(brief):
            CONTROLLER_HEALTH["successes"] += 1
            CONTROLLER_HEALTH["last_route"] = "local_mlx"
            CONTROLLER_HEALTH["last_latency_ms"] = round((time.monotonic() - started) * 1000, 1)
            return normalize_controller_brief(brief, symbol, board)
        if not brief:
            # Sentinel/Qwen can return only an end token after a cached prompt.
            # One short local retry recovers a visible directive without
            # creating a hosted request or an unbounded retry loop.
            retry = (
                f"MLX controller. For {symbol}, measured best score is "
                f"{compact_board[0] if compact_board else 'unavailable'}. "
                "Return one short line each for OBJECTIVE, EXPLORE, CRITIC, RISK, EVIDENCE."
            )
            CONTROLLER_HEALTH["requests"] += 1
            brief = visible_model_text(client.ask(retry, provider="local", max_tokens=80))
        if usable_controller_brief(brief):
            CONTROLLER_HEALTH["successes"] += 1
            CONTROLLER_HEALTH["last_route"] = "local_mlx_retry"
            CONTROLLER_HEALTH["last_latency_ms"] = round((time.monotonic() - started) * 1000, 1)
            return normalize_controller_brief(brief, symbol, board)
        if antigravity_worker is not None:
            antigravity_brief = antigravity_controller_fallback(
                antigravity_worker, symbol, generation, board, prior_directive
            )
            if antigravity_brief:
                CONTROLLER_HEALTH["fallbacks"] += 1
                return antigravity_brief
        CONTROLLER_HEALTH["fallbacks"] += 1
        CONTROLLER_HEALTH["last_route"] = "deterministic_fallback"
        CONTROLLER_HEALTH["last_error"] = "MLX returned an unusable controller brief"
        CONTROLLER_HEALTH["last_latency_ms"] = round((time.monotonic() - started) * 1000, 1)
        return measured_controller_fallback(symbol, board)
    except Exception as exc:
        CONTROLLER_HEALTH["failures"] += 1
        CONTROLLER_HEALTH["last_error"] = str(exc)[:240]
        if antigravity_worker is not None:
            antigravity_brief = antigravity_controller_fallback(
                antigravity_worker, symbol, generation, board, prior_directive
            )
            if antigravity_brief:
                CONTROLLER_HEALTH["fallbacks"] += 1
                return antigravity_brief
        CONTROLLER_HEALTH["last_route"] = "deterministic_fallback"
        CONTROLLER_HEALTH["last_latency_ms"] = round((time.monotonic() - started) * 1000, 1)
        return measured_controller_fallback(symbol, board)


def nvidia_search(client: MCPClient | None, symbol: str, profile: dict, parents: list[dict], agent_id: int,
                  generation: int = 1, feedback: dict | None = None, role: str = "explorer",
                  controller_directive: str = "", model: str | None = None) -> list[dict]:
    if client is None:
        return []
    prompt = (
        f"You are the {role} agent in generation {generation} for {symbol}. "
        "Inspect the measured leaderboard and propose one causal mutation that addresses its weakness. "
        "Return exactly one JSON object as the first and only output; no reasoning, markdown, or explanation. Use only these keys: "
        "lookback, fast, slow, entry_mode, exit_mode, downtrend_filter, regime_ema, "
        "max_holding_bars, tp, stop, entry_filter, atr_buffer, volume_median_period. "
        "entry_filter must be none, atr, slope, or volume. Do not claim returns or use future data. "
        f"PROFILE={json.dumps(profile)} PARENTS={json.dumps(parents[:5])} "
        f"FEEDBACK={json.dumps(feedback or {})} MLX_CONTROLLER_BRIEF={controller_directive[:1800]}"
    )
    started = time.monotonic()
    for attempt in range(1):
        try:
            NVIDIA_GATE.acquire(model)
            response_text = client.ask(prompt, provider="nvidia", max_tokens=1000, model=model)
            raw_candidates = extract_candidate_list(response_text)
            candidates = [candidate for raw in raw_candidates if (candidate := normalize_candidate(raw))]
            route = (client.last_meta or {}).get("provider") or "nvidia"
            if route != "nvidia":
                NVIDIA_GATE.fallback(model, f"gateway routed hosted request to {route}")
            if candidates:
                NVIDIA_GATE.success(model, route=route,
                                     latency_ms=(time.monotonic() - started) * 1000)
                return candidates
            if raw_candidates:
                NVIDIA_GATE.invalid(model)
            NVIDIA_GATE.success(model, route=route,
                                 latency_ms=(time.monotonic() - started) * 1000, empty=True)
            NVIDIA_GATE.empty(model, response_text)
            # A successful HTTP response can still contain no usable JSON.
            # Do not retry the hosted endpoint; use the local MLX lane so the
            # agent slot remains productive without adding rate-limit load.
            try:
                local_text = client.ask(prompt, provider="local", max_tokens=700)
                local_candidates = [candidate for raw in extract_candidate_list(local_text) if (candidate := normalize_candidate(raw))]
                if local_candidates:
                    NVIDIA_GATE.fallback(model, "NVIDIA returned no parseable mutation; local MLX supplied a mutation")
                    return local_candidates
            except Exception as local_exc:
                NVIDIA_GATE.fallback(model, f"local MLX fallback failed: {local_exc}")
        except Exception as exc:
            NVIDIA_GATE.failure(model, str(exc))
            # NVIDIA free endpoints can return transient 502/rate-limit
            # errors. Keep the requested NVIDIA attempt observable in gateway
            # metrics, but do not stall the endless research loop: local MLX
            # may generate a structurally identical mutation for evaluation.
            try:
                local_text = client.ask(prompt, provider="local", max_tokens=1000)
                candidates = [candidate for raw in extract_candidate_list(local_text) if (candidate := normalize_candidate(raw))]
                if candidates:
                    NVIDIA_GATE.fallback(model, "NVIDIA request failed; local MLX supplied a mutation")
                    return candidates
            except Exception:
                pass
    return []


def antigravity_search(worker: AntigravityOptimizer, symbol: str, profile: dict, parents: list[dict],
                       agent_id: int, generation: int = 1, feedback: dict | None = None,
                       role: str = "explorer", controller_directive: str = "") -> list[dict]:
    """Ask local Antigravity for a proposal; metrics still come from evaluate()."""
    prompt = (
        f"You are the {role} optimizer worker {agent_id} in generation {generation} for {symbol}. "
        "Use only the supplied measured profile, parents, and feedback. Propose exactly one causal parameter mutation. "
        "Return exactly one JSON object and no markdown, reasoning, performance claims, code, or tool calls. "
        "Use only these keys: lookback, fast, slow, entry_mode, exit_mode, downtrend_filter, regime_ema, "
        "max_holding_bars, tp, stop, entry_filter, atr_buffer, volume_median_period. "
        "entry_filter must be none, atr, slope, or volume. Never use future data. "
        f"PROFILE={json.dumps(profile)} PARENTS={json.dumps(parents[:5])} "
        f"FEEDBACK={json.dumps(feedback or {})} MLX_CONTROLLER_BRIEF={controller_directive[:1800]}"
    )
    try:
        raw_text = worker.ask(prompt)
        raw_candidates = extract_candidate_list(raw_text)
        candidates = [candidate for raw in raw_candidates if (candidate := normalize_candidate(raw))]
        if not candidates:
            ANTIGRAVITY_HEALTH["invalid_responses"] += 1
            ANTIGRAVITY_HEALTH["last_error"] = "no parseable mutation"
        return candidates
    except Exception:
        return []


def write_runtime_status(run_dir: Path, **fields):
    memory_file = run_dir.parent / "agentic_memory.json"
    fields.setdefault("memory_file", str(memory_file))
    if "memory_symbols" not in fields and memory_file.exists():
        try:
            stored = json.loads(memory_file.read_text())
            fields["memory_symbols"] = len(stored) if isinstance(stored, dict) else 0
        except (OSError, json.JSONDecodeError):
            fields["memory_symbols"] = 0
    payload = {"updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               "nvidia_model_health": NVIDIA_GATE.snapshot(),
               "local_controller_health": dict(CONTROLLER_HEALTH),
               "antigravity_health": dict(ANTIGRAVITY_HEALTH), **fields}
    (run_dir / "runtime_status.json").write_text(json.dumps(payload, indent=2) + "\n")


def load_agentic_memory(path: Path) -> dict:
    """Load compact cross-session research memory; never load raw model traces."""
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_agentic_memory(path: Path, memory: dict) -> None:
    """Persist memory atomically so an interrupted run cannot corrupt it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(memory, indent=2, default=str) + "\n")
    temporary.replace(path)


def update_agentic_memory(memory: dict, path: Path, symbol: str, **fields) -> dict:
    """Update bounded symbol memory and return the entry used by the loop."""
    entry = dict(memory.get(symbol, {}))
    entry.update(fields)
    entry["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    entry["controller"] = "local_mlx"
    entry["memory_schema"] = 1
    entry["directive_history"] = list(entry.get("directive_history", []))[-11:]
    entry["generation_history"] = list(entry.get("generation_history", []))[-11:]
    memory[symbol] = entry
    save_agentic_memory(path, memory)
    return entry


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "data/asx_daily_yfinance.sqlite3")
    ap.add_argument("--interval", choices=("1D", "APP_5H"), default="1D")
    ap.add_argument("--run-dir", type=Path, default=ROOT / "strategy_lab_runs")
    ap.add_argument("--agents", type=int, default=1, help="deterministic local search workers; keep at 1 when local compute is constrained")
    ap.add_argument("--nvidia-agents", type=int, default=9, help="independent NVIDIA search workers per symbol; requests are sequential to respect rate limits")
    ap.add_argument("--nvidia-rounds", type=int, default=3, help="NVIDIA mutation generations per symbol")
    ap.add_argument("--nvidia-concurrency", type=int, default=1, help="simultaneous NVIDIA calls; keep at 1 for free endpoint rate limits")
    ap.add_argument("--antigravity-agents", type=int, default=None, help="Antigravity optimizer workers; defaults to the NVIDIA worker count")
    ap.add_argument("--antigravity-timeout", type=int, default=60, help="seconds allowed per Antigravity proposal")
    ap.add_argument("--candidates", type=int, default=100, help="candidates per mutation agent per symbol")
    ap.add_argument("--years", type=int, default=10, help="latest years of cached candles to research")
    ap.add_argument("--seed-summary", type=Path, help="previous lab summary whose selected parameters become mutation parents")
    ap.add_argument("--symbols", default="", help="comma/space-separated symbols to research; defaults to the configured active universe")
    ap.add_argument("--exclude", default="")
    ap.add_argument("--providers", default="local,nvidia,antigravity")
    args = ap.parse_args()
    if args.antigravity_agents is None:
        args.antigravity_agents = args.nvidia_agents
    else:
        args.antigravity_agents = max(0, args.antigravity_agents)
    excluded = {x.strip().upper() for x in args.exclude.replace(",", " ").split() if x.strip()}
    requested_symbols = [x.strip().upper().replace(".AX", "") for x in args.symbols.replace(",", " ").split() if x.strip()] if args.symbols else list(UNIVERSE)
    symbols = [s for s in requested_symbols if s not in excluded]
    run_dir = args.run_dir / time.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    memory_file = args.run_dir / "agentic_memory.json"
    agentic_memory = load_agentic_memory(memory_file)
    write_runtime_status(run_dir, state="RUNNING", phase="initializing", total_symbols=len(symbols), interval=args.interval,
                         years=args.years, nvidia_models=NVIDIA_MODELS, nvidia_min_interval_seconds=NVIDIA_MIN_INTERVAL_SECONDS,
                         controller="local_mlx", agentic_loop="recall -> observe -> plan -> delegate -> evaluate -> reflect -> commit",
                         memory_file=str(memory_file), memory_symbols=len(agentic_memory))
    client = None
    try:
        client = MCPClient(ROOT.parent / "multi-model-ai-gateway/ai/mcp_server.py", "http://127.0.0.1:8788")
    except Exception as exc:
        print(f"MCP client unavailable: {exc}", file=sys.stderr)
    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    nvidia_clients = [client] if client and "nvidia" in providers else []
    antigravity_worker = None
    if "antigravity" in providers and args.antigravity_agents > 0:
        try:
            antigravity_worker = AntigravityOptimizer(args.antigravity_timeout)
        except Exception as exc:
            print(f"Antigravity optimizer unavailable: {exc}", file=sys.stderr)
    if nvidia_clients:
        for _ in range(min(2, max(0, args.nvidia_agents - 1))):
            try:
                nvidia_clients.append(MCPClient(ROOT.parent / "multi-model-ai-gateway/ai/mcp_server.py", "http://127.0.0.1:8788"))
            except Exception:
                break
    seeded_parents = {}
    if args.seed_summary and args.seed_summary.exists():
        previous = json.loads(args.seed_summary.read_text())
        seeded_parents = {
            item["symbol"]: item.get("selected_validation", {}).get("params")
            for item in previous.get("results", [])
            if item.get("selected_validation", {}).get("params")
        }
    all_results = []
    for symbol_index, symbol in enumerate(symbols):
        write_runtime_status(run_dir, state="RUNNING", phase="loading_data", symbol=symbol,
                             symbol_index=symbol_index + 1, total_symbols=len(symbols), completed_symbols=len(all_results))
        frame = load_app_5h_frame(args.db, symbol) if args.interval == "APP_5H" else load_frame(args.db, symbol)
        if args.interval == "1D":
            frame = frame.loc[frame.index >= frame.index.max() - pd.DateOffset(years=args.years)]
        if len(frame) < (2 if args.interval == "APP_5H" else 180):
            print(f"{symbol}: skipped, only {len(frame)} daily candles")
            continue
        n = len(frame)
        train_end, validation_end = int(n * .60), int(n * .80)
        train, validation, test = frame.iloc[:train_end], frame.iloc[train_end:validation_end], frame.iloc[validation_end:]
        profile = {"rows": n, "start": str(frame.index.min().date()), "end": str(frame.index.max().date()), "train_rows": len(train), "validation_rows": len(validation), "test_rows": len(test)}
        parents = [dict(BASELINE), dict(ONE_HOUR_WINNER), {**BASELINE, **APP_IMITATION}]
        if seeded_parents.get(symbol):
            parents.append(dict(seeded_parents[symbol]))
        symbol_memory = agentic_memory.get(symbol, {})
        for remembered in symbol_memory.get("top_parents", [])[:5]:
            if isinstance(remembered, dict):
                parents.append(dict(remembered))
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.agents) as pool:
            write_runtime_status(run_dir, state="RUNNING", phase="local_search", symbol=symbol,
                                 symbol_index=symbol_index + 1, total_symbols=len(symbols), completed_symbols=len(all_results))
            jobs = [pool.submit(search, train, 800000 + symbol_index * 10000 + i, args.candidates, parents) for i in range(args.agents)]
            candidates = [item for job in jobs for item in job.result()]
        candidates.append(evaluate(train, dict(BASELINE)))
        candidates.append(evaluate(train, {**BASELINE, **APP_IMITATION}))
        nvidia_proposals = []
        antigravity_proposals = []
        nvidia_rounds_completed = 0
        agentic_generations = []
        if (client and "nvidia" in providers) or antigravity_worker is not None:
            nvidia_defaults = {
                **BASELINE,
                "entry_mode": "breakout_trend",
                "exit_mode": "fast_or_slow",
                "downtrend_filter": True,
                "regime_ema": 89,
                "max_holding_bars": 0,
            }
            population = list(candidates)
            parent_params = [item["params"] for item in leaderboard(population)]
            roles = {0: "explorer", 1: "critic", 2: "risk reviewer"}
            controller_directive = symbol_memory.get(
                "last_controller_directive",
                "Begin with the measured baseline population; each specialist must make one bounded causal change.",
            )
            last_reflection = symbol_memory.get("last_reflection", {})
            for generation in range(max(1, args.nvidia_rounds)):
                prior_board = leaderboard(population)
                controller_context = controller_directive
                if last_reflection:
                    controller_context += f" REFLECTION={json.dumps(last_reflection, separators=(',', ':'))}"
                controller_directive = mlx_controller(
                    client if "local" in providers else None,
                    symbol, generation + 1, profile, prior_board, controller_context,
                    antigravity_worker=antigravity_worker,
                )
                feedback = {
                    "generation": generation + 1,
                    "objective": "increase causal train return while respecting drawdown and trade gates",
                    "leaderboard": prior_board,
                    "parents": parent_params,
                    "controller_directive": controller_directive,
                }
                framework = decomposition_framework(symbol, profile, prior_board, controller_directive)
                write_runtime_status(run_dir, state="RUNNING", phase="nvidia_mutation", symbol=symbol,
                                     symbol_index=symbol_index + 1, total_symbols=len(symbols), completed_symbols=len(all_results),
                                     generation=generation + 1, generations=args.nvidia_rounds,
                                     agentic_loop="recall -> observe -> plan -> delegate -> evaluate -> reflect -> commit",
                                     controller="local_mlx",
                                     controller_route=CONTROLLER_HEALTH.get("last_route"),
                                     decomposition_framework=framework,
                                     population_size=len(population), generation_best=prior_board[0] if prior_board else None)
                generation_candidates = []
                # The local search worker is an independent explorer in every
                # generation, not merely a one-time seed generator.
                if parent_params:
                    generation_candidates.extend(search(
                        train, 910000 + symbol_index * 10000 + generation,
                        max(1, args.candidates // 2), parent_params,
                    ))
                for batch_start in range(0, max(0, args.nvidia_agents), 3):
                    agent_ids = list(range(batch_start + 1, min(args.nvidia_agents, batch_start + 3) + 1))
                    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(args.nvidia_concurrency, len(agent_ids)))) as pool:
                        jobs = [pool.submit(nvidia_search, nvidia_clients[index % len(nvidia_clients)], symbol, profile,
                                            parent_params, agent_id, generation + 1, feedback,
                                            roles.get((agent_id - 1) % 3, "explorer"),
                                            controller_directive,
                                            NVIDIA_MODELS[(agent_id - 1) % len(NVIDIA_MODELS)])
                                for index, agent_id in enumerate(agent_ids)] if nvidia_clients else []
                        for job in jobs:
                            job_candidates = job.result()
                            for raw in job_candidates:
                                params = dict(nvidia_defaults)
                                params.update(raw)
                                generation_candidates.append(evaluate(train, params))
                            # Publish provider telemetry after every worker,
                            # not only after the whole mutation round. This
                            # keeps the console useful during long NVIDIA
                            # cooldowns and makes failures attributable to a
                            # model/worker immediately.
                            write_runtime_status(
                                run_dir, state="RUNNING", phase="nvidia_mutation", symbol=symbol,
                                symbol_index=symbol_index + 1, total_symbols=len(symbols),
                                completed_symbols=len(all_results), generation=generation + 1,
                                generations=args.nvidia_rounds,
                                agentic_loop="recall -> observe -> plan -> delegate -> evaluate -> reflect -> commit",
                                controller="local_mlx",
                                controller_route=CONTROLLER_HEALTH.get("last_route"),
                                decomposition_framework=framework,
                                population_size=len(population), generation_proposals=len(generation_candidates),
                                nvidia_model_health=NVIDIA_GATE.snapshot(),
                                antigravity_health=dict(ANTIGRAVITY_HEALTH),
                            )
                    time.sleep(2.0)
                if antigravity_worker is not None:
                    for antigravity_id in range(1, max(0, args.antigravity_agents) + 1):
                        antigravity_candidates = antigravity_search(
                            antigravity_worker, symbol, profile, parent_params,
                            antigravity_id, generation + 1, feedback,
                            roles.get((antigravity_id - 1) % 3, "explorer"), controller_directive,
                        )
                        antigravity_proposals.extend(antigravity_candidates)
                        generation_candidates.extend(evaluate(train, params) for params in antigravity_candidates)
                        # Antigravity runs locally and can take longer than a
                        # normal provider call; publish its counters after
                        # each worker so the dashboard proves it is active.
                        write_runtime_status(
                            run_dir, state="RUNNING", phase="antigravity_mutation", symbol=symbol,
                            symbol_index=symbol_index + 1, total_symbols=len(symbols),
                            completed_symbols=len(all_results), generation=generation + 1,
                            generations=args.nvidia_rounds,
                            agentic_loop="recall -> observe -> plan -> delegate -> evaluate -> reflect -> commit",
                            controller="local_mlx",
                            controller_route=CONTROLLER_HEALTH.get("last_route"),
                            decomposition_framework=framework,
                            population_size=len(population), generation_proposals=len(generation_candidates),
                            nvidia_model_health=NVIDIA_GATE.snapshot(),
                            antigravity_health=dict(ANTIGRAVITY_HEALTH),
                        )
                nvidia_proposals.extend(generation_candidates)
                population.extend(generation_candidates)
                population.sort(key=lambda x: (x["stats"]["risk_eligible"], x["stats"]["selection_score"]), reverse=True)
                population = population[:max(25, args.candidates * 2)]
                parent_params = [item["params"] for item in leaderboard(population)]
                board = leaderboard(population)
                reflection = reflect_generation(prior_board, board)
                last_reflection = reflection
                framework["post_generation_reflection"] = reflection
                agentic_generations.append({
                    "generation": generation + 1,
                    "parents": parent_params,
                    "proposals": len(generation_candidates),
                    "antigravity_proposals": len(antigravity_proposals),
                    "optimizer_workers": {"nvidia": args.nvidia_agents, "antigravity": args.antigravity_agents if antigravity_worker else 0},
                    "population_size": len(population),
                    "controller_provider": "local_mlx",
                    "controller_directive": controller_directive,
                    "decomposition_framework": framework,
                    "reflection": reflection,
                    "leaderboard": board,
                })
                history_item = {
                    "generation": generation + 1,
                    "directive": controller_directive[:1600],
                    "leaderboard": board,
                    "parents": parent_params[:5],
                    "proposals": len(generation_candidates),
                    "reflection": reflection,
                }
                symbol_memory = update_agentic_memory(
                    agentic_memory, memory_file, symbol,
                    last_generation=generation + 1,
                    last_controller_directive=controller_directive[:1600],
                    last_reflection=reflection,
                    top_parents=parent_params[:5],
                    last_leaderboard=board,
                    directive_history=symbol_memory.get("directive_history", []) + [controller_directive[:1600]],
                    generation_history=symbol_memory.get("generation_history", []) + [history_item],
                    nvidia_model_health=NVIDIA_GATE.snapshot(),
                )
                (run_dir / f"{symbol}-generation-{generation + 1:02d}.json").write_text(
                    json.dumps(agentic_generations[-1], indent=2, default=str) + "\n"
                )
                # Publish post-call telemetry as soon as the round is
                # complete; the dashboard must not wait for the next round to
                # learn whether a hosted model succeeded or fell back.
                write_runtime_status(
                    run_dir, state="RUNNING", phase="nvidia_mutation", symbol=symbol,
                    symbol_index=symbol_index + 1, total_symbols=len(symbols),
                    completed_symbols=len(all_results), generation=generation + 1,
                    generations=args.nvidia_rounds,
                    agentic_loop="recall -> observe -> plan -> delegate -> evaluate -> reflect -> commit",
                    controller="local_mlx", decomposition_framework=framework,
                    population_size=len(population), generation_best=board[0] if board else None,
                    generation_proposals=len(generation_candidates),
                    antigravity_health=dict(ANTIGRAVITY_HEALTH),
                )
                candidates = list(population)
                nvidia_rounds_completed += 1
            candidates = population
        candidates = [item for item in candidates if item["stats"]["risk_eligible"]]
        candidates.sort(key=lambda x: x["stats"]["selection_score"], reverse=True)
        if not candidates:
            print(f"{symbol}: no train candidate passed DD <= {MAX_DRAWDOWN_PCT:.1f}% and >= {MIN_TRADES} trades")
            rejected = {"symbol": symbol, "status": "REJECTED_NO_TRAIN_CANDIDATE", "profile": profile,
                        "nvidia_search_proposals": len(nvidia_proposals), "nvidia_mutation_rounds": nvidia_rounds_completed,
                        "agentic_generations": agentic_generations}
            all_results.append(rejected)
            (run_dir / f"{symbol}.json").write_text(json.dumps(rejected, indent=2, default=str) + "\n")
            write_runtime_status(run_dir, state="RUNNING", phase="symbol_complete", symbol=symbol,
                                 symbol_index=symbol_index + 1, total_symbols=len(symbols), completed_symbols=len(all_results), result_status=rejected["status"])
            continue
        validation_ranked = []
        for item in candidates[:25]:
            validation_result = evaluate(validation, item["params"])
            if validation_result["stats"]["risk_eligible"]:
                validation_ranked.append({"params": item["params"], "stats": validation_result["stats"]})
        validation_ranked.sort(key=lambda x: x["stats"]["selection_score"], reverse=True)
        if not validation_ranked:
            print(f"{symbol}: no validation candidate passed DD <= {MAX_DRAWDOWN_PCT:.1f}% and >= {MIN_TRADES} trades")
            rejected = {"symbol": symbol, "status": "REJECTED_NO_VALIDATION_CANDIDATE", "profile": profile,
                        "best_train": candidates[0], "nvidia_search_proposals": len(nvidia_proposals),
                        "nvidia_mutation_rounds": nvidia_rounds_completed, "agentic_generations": agentic_generations}
            all_results.append(rejected)
            (run_dir / f"{symbol}.json").write_text(json.dumps(rejected, indent=2, default=str) + "\n")
            write_runtime_status(run_dir, state="RUNNING", phase="symbol_complete", symbol=symbol,
                                 symbol_index=symbol_index + 1, total_symbols=len(symbols), completed_symbols=len(all_results), result_status=rejected["status"])
            continue
        selected = validation_ranked[0]
        final = evaluate(test, selected["params"])
        baseline_test = evaluate(test, dict(BASELINE))
        final["stats"]["risk_eligible"] = (
            final["stats"]["risk_eligible"]
            and abs(float(final["stats"]["max_drawdown_pct"])) <= MAX_DRAWDOWN_PCT
        )
        reviews = []
        result = {"symbol": symbol, "profile": profile, "baseline_train": evaluate(train, dict(BASELINE)), "best_train": candidates[0], "selected_validation": selected, "final_test": final, "baseline_test": baseline_test, "nvidia_search_proposals": len(nvidia_proposals), "antigravity_search_proposals": len(antigravity_proposals), "nvidia_mutation_rounds": nvidia_rounds_completed, "agentic_generations": agentic_generations, "reviews": reviews}
        all_results.append(result)
        (run_dir / f"{symbol}.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
        update_agentic_memory(
            agentic_memory, memory_file, symbol,
            last_result={"status": "COMPLETED", "final_test": final.get("stats", {}),
                         "selected_validation": selected.get("stats", {})},
            selected_params=selected.get("params", {}),
            top_parents=[item.get("params", {}) for item in candidates[:5]],
            nvidia_model_health=NVIDIA_GATE.snapshot(),
        )
        write_runtime_status(run_dir, state="RUNNING", phase="symbol_complete", symbol=symbol,
                             symbol_index=symbol_index + 1, total_symbols=len(symbols), completed_symbols=len(all_results), result_status="COMPLETED",
                             memory_file=str(memory_file), memory_symbols=len(agentic_memory))
        print(f"{symbol:4s} train={candidates[0]['stats']['total_return_pct']:8.2f}% validation={selected['stats']['total_return_pct']:8.2f}% test={final['stats']['total_return_pct']:8.2f}% baseline_test={baseline_test['stats']['total_return_pct']:8.2f}% trades={final['stats']['trades']}", flush=True)
    summary = {"status": "completed", "data_interval": args.interval, "research_years": args.years if args.interval == "1D" else None, "seed_summary": str(args.seed_summary) if args.seed_summary else None, "symbols_requested": symbols, "symbols_tested": len(all_results), "controller": "local_mlx", "agentic_loop": "recall -> observe -> plan -> delegate -> evaluate -> reflect -> commit", "memory_file": str(memory_file), "memory_symbols": len(agentic_memory), "local_search_agents": args.agents, "nvidia_models": NVIDIA_MODELS, "nvidia_min_interval_seconds": NVIDIA_MIN_INTERVAL_SECONDS, "nvidia_search_workers_per_symbol": args.nvidia_agents if "nvidia" in providers else 0, "antigravity_model": ANTIGRAVITY_MODEL if antigravity_worker else None, "antigravity_workers_per_symbol": args.antigravity_agents if antigravity_worker else 0, "nvidia_mutation_rounds": args.nvidia_rounds, "candidates_per_agent": args.candidates, "capital": CAPITAL, "allocation": ALLOCATION, "slippage_bps_per_side": SLIPPAGE_BPS, "brokerage": "AustralianSuper Member Direct", "administration_fee_included": False, "max_drawdown_pct": MAX_DRAWDOWN_PCT, "minimum_trades": MIN_TRADES, "selection": "hard DD/trade gate on train and validation -> highest test score only for the app cache; treat tiny splits as weak evidence", "results": all_results}
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(f"\nSaved {run_dir / 'summary.json'}")
    if client:
        client.close()
    for extra_client in nvidia_clients[1:]:
        extra_client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
