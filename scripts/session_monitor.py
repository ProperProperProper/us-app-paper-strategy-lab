#!/usr/bin/env python3
"""Keep the US.APP research and paper processes healthy through RTH close."""
from __future__ import annotations

import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from urllib.request import urlopen
from datetime import datetime, time as clock_time
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
ET = ZoneInfo("America/New_York")
LOG = ROOT / "scripts" / "session_monitor.log"
MONITOR_STARTED = time.time()
HANDLED_FAULTS: set[str] = set()
HANDOFF = ROOT / "strategy_lab_runs" / "supervisor_handoff.json"


def log(message: str) -> None:
    line = f"{datetime.now(ET).isoformat()} {message}"
    print(line, flush=True)
    with LOG.open("a") as handle:
        handle.write(line + "\n")


def record_handoff(source: str, message: str, code_fix_candidate: bool) -> None:
    """Persist a review queue for Codex/Antigravity fault assessment."""
    HANDOFF.parent.mkdir(parents=True, exist_ok=True)
    try:
        payload = json.loads(HANDOFF.read_text()) if HANDOFF.exists() else {}
    except (OSError, json.JSONDecodeError):
        payload = {}
    faults = payload.get("faults", []) if isinstance(payload.get("faults"), list) else []
    event = {
        "created_at": datetime.now(ET).isoformat(),
        "source": source,
        "message": str(message)[-1000:],
        "severity": "error",
        "status": "PENDING_CODEX_REVIEW",
        "code_fix_candidate": bool(code_fix_candidate),
        "automatic_action": "service_restart_or_safe_continuation",
    }
    faults.append(event)
    payload = {"status": "PENDING_CODEX_REVIEW", "faults": faults[-100:]}
    temporary = HANDOFF.with_name(HANDOFF.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    temporary.replace(HANDOFF)


def processes(pattern: str) -> list[tuple[int, str]]:
    output = subprocess.check_output(["ps", "-axo", "pid=,command="], text=True)
    rows = []
    for line in output.splitlines():
        fields = line.strip().split(None, 1)
        if fields and pattern in (fields[1] if len(fields) > 1 else ""):
            rows.append((int(fields[0]), fields[1]))
    return rows


def stop(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGINT)
    except ProcessLookupError:
        pass


def keep_one(pattern: str) -> None:
    rows = processes(pattern)
    for pid, _ in sorted(rows)[1:]:
        log(f"stopping duplicate {pattern} pid={pid}")
        stop(pid)


def account_id() -> int:
    from contextlib import redirect_stderr, redirect_stdout
    from io import StringIO
    from moomoo import OpenSecTradeContext, RET_OK, TrdMarket
    silence = StringIO()
    with redirect_stdout(silence), redirect_stderr(silence):
        ctx = OpenSecTradeContext(filter_trdmarket=TrdMarket.US, host="127.0.0.1", port=11111)
        try:
            ret, data = ctx.get_acc_list()
            rows = data[data["competition_acc_name"].astype(str).str.contains("Global Paper Trading Competition", na=False)] if ret == RET_OK else []
            if len(rows) != 1:
                raise RuntimeError("competition SIMULATE account was not uniquely identified")
            return int(rows.iloc[0]["acc_id"])
        finally:
            ctx.close()


def start(command: list[str], label: str) -> None:
    process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if label == "strategy lab":
        try:
            os.setpriority(os.PRIO_PROCESS, process.pid, 10)
            log(f"lowered strategy lab priority pid={process.pid}")
        except (AttributeError, OSError):
            log(f"could not lower strategy lab priority pid={process.pid}")
    log(f"restarted {label}")


def ensure_processes() -> None:
    keep_one("scripts/app_strategy_lab.py")
    keep_one("scripts/research_console.py")
    keep_one("scripts/competition_bot.py")
    if not processes("scripts/app_strategy_lab.py"):
        start([PYTHON, "scripts/app_strategy_lab.py", "--db", "quant_dashboard.sqlite3", "--run-dir", "strategy_lab_runs", "--agents", "5", "--candidates", "1", "--providers", "local,nvidia,apple,antigravity", "--continuous"], "strategy lab")
    if not processes("scripts/research_console.py"):
        start([PYTHON, "scripts/research_console.py"], "research console")
    if not processes("scripts/competition_bot.py"):
        start([PYTHON, "scripts/competition_bot.py", "US.APP", "--acc-id", str(account_id()), "--interval", "30", "--live-paper"], "paper bot")


def recent_runtime_fault(path: Path) -> str | None:
    if not path.exists() or path.stat().st_mtime < MONITOR_STARTED:
        return None
    try:
        lines = path.read_text(errors="replace").splitlines()[-80:]
    except OSError:
        return None
    for line in reversed(lines):
        if "Traceback (most recent call last)" in line or " ERROR " in f" {line} ":
            return line[-240:]
    return None


def check_open_d() -> None:
    with socket.create_connection(("127.0.0.1", 11111), timeout=2):
        pass


def check_console() -> None:
    with urlopen("http://127.0.0.1:8790/api/state", timeout=3) as response:
        if response.status != 200:
            raise RuntimeError(f"research console HTTP {response.status}")
        payload = json.loads(response.read())
    if not payload.get("running"):
        raise RuntimeError("research console reports not running")


def restart_process(pattern: str, label: str) -> None:
    for pid, _ in processes(pattern):
        log(f"restarting {label} after runtime fault pid={pid}")
        stop(pid)


def code_is_newer_than_process(pattern: str, paths: list[Path]) -> bool:
    rows = processes(pattern)
    if not rows:
        return False
    pid = rows[0][0]
    try:
        started = subprocess.check_output(["ps", "-p", str(pid), "-o", "lstart="], text=True).strip()
        process_time = datetime.strptime(started, "%a %b %d %H:%M:%S %Y").timestamp()
        return any(path.exists() and path.stat().st_mtime > process_time for path in paths)
    except (OSError, ValueError, subprocess.CalledProcessError):
        return False


def health_check() -> None:
    if code_is_newer_than_process("scripts/app_strategy_lab.py", [ROOT / "scripts/app_strategy_lab.py", ROOT / "scripts/strategy_57pct.py"]):
        for pid, _ in processes("scripts/app_strategy_lab.py"):
            log(f"restarting lab for newer source pid={pid}")
            stop(pid)
    if code_is_newer_than_process("scripts/competition_bot.py", [ROOT / "scripts/competition_bot.py", ROOT / "scripts/strategy_57pct.py"]):
        for pid, _ in processes("scripts/competition_bot.py"):
            log(f"restarting bot for newer source pid={pid}")
            stop(pid)
    bot_fault = recent_runtime_fault(ROOT / "scripts" / "competition_bot.log")
    if bot_fault and bot_fault not in HANDLED_FAULTS:
        HANDLED_FAULTS.add(bot_fault)
        log(f"paper bot fault detected: {bot_fault}")
        record_handoff("paper_bot", bot_fault, "Traceback" in bot_fault or "rejected" in bot_fault.lower())
        restart_process("scripts/competition_bot.py", "paper bot")
    ensure_processes()
    check_open_d()
    check_console()
    for db_path in (ROOT / "quant_dashboard.sqlite3",):
        with sqlite3.connect(db_path) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError(f"SQLite integrity failure: {db_path}")
            if db.execute("SELECT count(*) FROM candles WHERE time_key < '2026-01-01T00:00:00'").fetchone()[0]:
                raise RuntimeError(f"pre-2026 candle data detected: {db_path}")
    state = ROOT / "strategy_lab_runs" / "app_runtime_status.json"
    if state.exists():
        lab_state = json.loads(state.read_text()).get("state")
        if lab_state not in {"RUNNING", "STOPPED"}:
            restart_process("scripts/app_strategy_lab.py", "strategy lab")
            raise RuntimeError(f"invalid strategy lab runtime state: {lab_state}")


def main() -> int:
    while True:
        now = datetime.now(ET)
        if now.weekday() >= 5 or now.time() >= clock_time(16, 5):
            log("US session monitor finished")
            return 0
        try:
            health_check()
        except Exception as exc:
            log(f"health fault: {exc}")
            record_handoff("session_monitor", str(exc), True)
        time.sleep(30)


if __name__ == "__main__":
    raise SystemExit(main())
