#!/usr/bin/env python3
"""Run the daily multi-symbol NVIDIA mutation lab continuously.

Each completed universe pass becomes the parent population for the next pass.
The child lab still evaluates every return locally and chronologically; this
wrapper only provides persistence between generations and a stop file.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def latest_summary(run_root: Path) -> Path | None:
    summaries = sorted(run_root.glob("*/summary.json"), key=lambda p: p.stat().st_mtime)
    return summaries[-1] if summaries else None


def latest_runtime(run_root: Path, minimum_mtime: float = 0.0) -> Path | None:
    """Return the newest runtime record, optionally from the active cycle."""
    records = [
        p for p in run_root.glob("*/runtime_status.json")
        if p.stat().st_mtime >= minimum_mtime
    ]
    return max(records, key=lambda p: p.stat().st_mtime) if records else None


def runtime_age_seconds(path: Path | None) -> float | None:
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text())
        stamp = str(payload.get("updated_at", ""))
        # Python versions used by the local Xcode runtime differ in their
        # support for compact numeric UTC offsets, so normalize it explicitly.
        parsed = dt.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S%z")
        return max(0.0, time.time() - parsed.timestamp())
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        try:
            return max(0.0, time.time() - path.stat().st_mtime)
        except OSError:
            return None


def gateway_snapshot(url: str) -> dict:
    """Read bounded gateway telemetry without making the gateway mandatory."""
    endpoint = url.rstrip("/") + "/api/status"
    try:
        with urllib.request.urlopen(endpoint, timeout=3) as response:
            payload = json.loads(response.read())
        stats = payload.get("stats", {}) if isinstance(payload, dict) else {}
        nvidia = payload.get("backends", {}).get("nvidia", {}) if isinstance(payload, dict) else {}
        return {
            "reachable": True,
            "nvidia_configured": bool(nvidia.get("configured")),
            "nvidia_inflight": nvidia.get("inflight"),
            "nvidia_requests": stats.get("nvidia_requests"),
            "nvidia_failures": stats.get("nvidia_failures"),
            "nvidia_timeouts": stats.get("nvidia_timeouts"),
            "local_failures": stats.get("local_failures"),
            "last_error": stats.get("nvidia_last_error") or stats.get("local_last_error"),
        }
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
        return {"reachable": False, "error": str(exc)[:240]}


def write_supervisor_status(run_root: Path, payload: dict) -> None:
    """Persist supervisor telemetry atomically for the console and diagnostics."""
    target = run_root / "supervisor_status.json"
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    temporary.replace(target)


def signal_process_group(process: subprocess.Popen | None, signum: int) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signum)
    except (OSError, ProcessLookupError):
        try:
            process.send_signal(signum)
        except (OSError, ProcessLookupError):
            pass


def stop_process_group(process: subprocess.Popen | None, grace_seconds: float = 15.0) -> None:
    if process is None or process.poll() is not None:
        return
    signal_process_group(process, signal.SIGTERM)
    deadline = time.monotonic() + grace_seconds
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.25)
    if process.poll() is None:
        signal_process_group(process, signal.SIGKILL)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=ROOT / "data/asx_daily_yfinance.sqlite3")
    ap.add_argument("--symbols", required=True)
    ap.add_argument("--years", type=int, default=1)
    ap.add_argument("--agents", type=int, default=1)
    ap.add_argument("--nvidia-agents", type=int, default=9)
    ap.add_argument("--nvidia-rounds", type=int, default=3)
    ap.add_argument("--nvidia-concurrency", type=int, default=1)
    ap.add_argument("--antigravity-agents", type=int, default=None)
    ap.add_argument("--antigravity-timeout", type=int, default=60)
    ap.add_argument("--providers", default="local,nvidia,antigravity")
    ap.add_argument("--candidates", type=int, default=100)
    ap.add_argument("--run-dir", type=Path, default=ROOT / "strategy_lab_runs")
    ap.add_argument("--stop-file", type=Path, default=ROOT / "strategy_lab_runs/STOP_DAILY")
    ap.add_argument("--gateway-url", default=os.environ.get("MULTI_MODEL_GATEWAY_URL", "http://127.0.0.1:8788"))
    ap.add_argument("--health-timeout-seconds", type=float, default=300.0,
                    help="restart a child only when runtime telemetry is this old")
    ap.add_argument("--health-poll-seconds", type=float, default=5.0)
    ap.add_argument("--restart-backoff-seconds", type=float, default=10.0)
    ap.add_argument("--max-restart-backoff-seconds", type=float, default=300.0)
    args = ap.parse_args()
    args.run_dir.mkdir(parents=True, exist_ok=True)
    args.stop_file.parent.mkdir(parents=True, exist_ok=True)
    if args.stop_file.exists():
        args.stop_file.unlink()
    # Preserve the last completed population across supervisor restarts.  A
    # crashed child must not discard the measured parents from the prior pass.
    previous = latest_summary(args.run_dir)
    cycle = 0
    child = None
    stop_requested = False
    restart_count = 0
    consecutive_failures = 0
    last_error = None
    last_gateway = {}

    def stop(_signum, _frame):
        nonlocal stop_requested
        stop_requested = True
        signal_process_group(child, signal.SIGINT)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    write_supervisor_status(args.run_dir, {
        "state": "STARTING",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "cycle": cycle,
        "restart_count": restart_count,
        "consecutive_failures": consecutive_failures,
        "gateway": gateway_snapshot(args.gateway_url),
    })
    while not args.stop_file.exists() and not stop_requested:
        cycle += 1
        command = [
            sys.executable, str(ROOT / "scripts/multi_symbol_strategy_lab.py"),
            "--db", str(args.db), "--interval", "1D", "--symbols", args.symbols,
            "--years", str(args.years), "--agents", str(args.agents),
            "--nvidia-agents", str(args.nvidia_agents), "--nvidia-rounds", str(args.nvidia_rounds),
            "--nvidia-concurrency", str(args.nvidia_concurrency),
            "--antigravity-agents", str(args.antigravity_agents if args.antigravity_agents is not None else args.nvidia_agents),
            "--antigravity-timeout", str(args.antigravity_timeout),
            "--providers", args.providers,
            "--candidates", str(args.candidates), "--run-dir", str(args.run_dir),
        ]
        if previous and previous.exists():
            command.extend(["--seed-summary", str(previous)])
        print(f"DAILY MUTATION CYCLE {cycle}: starting", flush=True)
        launch_time = time.time()
        child = subprocess.Popen(command, cwd=ROOT, start_new_session=True)
        active_runtime = None
        stale_reason = None
        while child.poll() is None and not args.stop_file.exists() and not stop_requested:
            active_runtime = latest_runtime(args.run_dir, launch_time - 1.0) or active_runtime
            age = runtime_age_seconds(active_runtime)
            last_gateway = gateway_snapshot(args.gateway_url)
            write_supervisor_status(args.run_dir, {
                "state": "RUNNING",
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "cycle": cycle,
                "child_pid": child.pid,
                "restart_count": restart_count,
                "consecutive_failures": consecutive_failures,
                "runtime_file": str(active_runtime) if active_runtime else None,
                "runtime_age_seconds": age,
                "gateway": last_gateway,
                "last_error": last_error,
            })
            if active_runtime is not None and age is not None and age > args.health_timeout_seconds:
                stale_reason = f"runtime telemetry stale for {age:.1f}s"
                last_error = stale_reason
                print(f"DAILY MUTATION CYCLE {cycle}: {stale_reason}; restarting child", flush=True)
                stop_process_group(child)
                break
            time.sleep(max(0.5, args.health_poll_seconds))
        if stop_requested or args.stop_file.exists():
            stop_process_group(child)
        code = child.wait()
        child = None
        if stop_requested or args.stop_file.exists():
            break
        summary = latest_summary(args.run_dir)
        summary_is_current = False
        if summary and summary.exists():
            try:
                summary_is_current = summary.stat().st_mtime >= launch_time - 1.0
            except OSError:
                summary_is_current = False
        if summary_is_current and stale_reason is None and code == 0:
            previous = summary
            consecutive_failures = 0
            last_error = None
            try:
                data = json.loads(summary.read_text())
                print(f"DAILY MUTATION CYCLE {cycle}: completed {data.get('symbols_tested', 0)} symbols; parents carried forward", flush=True)
            except json.JSONDecodeError:
                pass
        else:
            restart_count += 1
            consecutive_failures += 1
            last_error = stale_reason or f"child exited {code} without a completed summary"
            delay = min(args.max_restart_backoff_seconds,
                        args.restart_backoff_seconds * (2 ** min(consecutive_failures - 1, 8)))
            print(f"DAILY MUTATION CYCLE {cycle}: {last_error}; retrying in {delay:.1f}s", flush=True)
            write_supervisor_status(args.run_dir, {
                "state": "BACKOFF",
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "cycle": cycle,
                "restart_count": restart_count,
                "consecutive_failures": consecutive_failures,
                "gateway": last_gateway or gateway_snapshot(args.gateway_url),
                "last_error": last_error,
                "backoff_seconds": delay,
            })
            deadline = time.monotonic() + delay
            while time.monotonic() < deadline and not args.stop_file.exists() and not stop_requested:
                time.sleep(min(args.health_poll_seconds, max(0.1, deadline - time.monotonic())))
    print("DAILY MUTATION LOOP STOPPED", flush=True)
    write_supervisor_status(args.run_dir, {
        "state": "STOPPED",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "cycle": cycle,
        "restart_count": restart_count,
        "consecutive_failures": consecutive_failures,
        "gateway": last_gateway or gateway_snapshot(args.gateway_url),
        "last_error": last_error,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
