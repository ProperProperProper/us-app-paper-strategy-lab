#!/usr/bin/env python3
"""Local browser console for the US.APP paper-strategy mutation lab."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "strategy_lab_runs"
PORT = int(os.environ.get("STRATEGY_CONSOLE_PORT", "8790"))
STATE = {"process": None, "started_at": None, "config": None}
LOCK = threading.Lock()

HTML = """<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>US.APP Strategy Lab</title><style>
body{margin:0;background:#080b12;color:#eef4ff;font:14px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}main{max-width:1180px;margin:auto;padding:28px 22px}.panel{background:#111827;border:1px solid #273449;border-radius:14px;padding:18px;margin-bottom:16px}h1{margin:0 0 6px}.muted{color:#93a4ba}.grid{display:grid;grid-template-columns:280px 1fr;gap:16px}.buttons{display:flex;gap:8px;margin-top:16px}button{border:0;border-radius:8px;padding:10px 14px;font-weight:700;cursor:pointer}.start{background:#47e0a1}.stop{background:#ff7188}input{width:100%;box-sizing:border-box;background:#0b1220;border:1px solid #273449;color:#fff;padding:10px;border-radius:8px;margin:6px 0 12px}pre{white-space:pre-wrap;max-height:480px;overflow:auto;color:#cbd5e1}@media(max-width:760px){.grid{grid-template-columns:1fr}}
</style></head><body><main><p class='muted'>Local-only · MLX + NVIDIA + Antigravity</p><h1>US.APP Strategy Research Lab</h1><p class='muted'>Models propose bounded mutations; the deterministic evaluator decides.</p><div class='grid'><aside><section class='panel'><label>Agents<input id='agents' type='number' min='1' max='4' value='2'></label><label>Candidates per agent<input id='candidates' type='number' min='1' max='1000' value='100'></label><div class='buttons'><button class='start' onclick='startLab()'>Start</button><button class='stop' onclick='stopLab()'>Stop</button></div><p id='action' class='muted'></p></section><section class='panel'><h2>Paper bot</h2><pre id='paper'>Checking…</pre></section></aside><section><section class='panel'><h2 id='status'>Checking…</h2><pre id='state'>Loading…</pre></section><section class='panel'><h2>Latest run</h2><pre id='run'>No run yet.</pre></section></section></div></main><script>
const $=id=>document.getElementById(id);async function refresh(){let d=await (await fetch('/api/state')).json();$('status').textContent=d.running?'RUNNING':'STOPPED';$('state').textContent=JSON.stringify(d,null,2);$('run').textContent=JSON.stringify(d.latest||{},null,2);let p=d.paper||{};$('paper').textContent=JSON.stringify(p,null,2)}async function startLab(){let r=await fetch('/api/start',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({agents:+$('agents').value,candidates:+$('candidates').value})});$('action').textContent=(await r.json()).message||'start requested';refresh()}async function stopLab(){let r=await fetch('/api/stop',{method:'POST'});$('action').textContent=(await r.json()).message||'stop requested';refresh()}setInterval(refresh,2000);refresh();
</script></body></html>"""


def latest_run():
    runs = sorted(p for p in RUNS.glob("APP-*") if p.is_dir())
    return runs[-1] if runs else None


def running_pid():
    process = STATE.get("process")
    if process is not None and process.poll() is None:
        return process.pid
    try:
        output = subprocess.check_output(["ps", "-axo", "pid=,command="], text=True)
        for line in output.splitlines():
            fields = line.strip().split(None, 1)
            if len(fields) == 2 and "scripts/app_strategy_lab.py" in fields[1]:
                pid = int(fields[0])
                if pid != os.getpid():
                    return pid
    except (OSError, ValueError, subprocess.CalledProcessError):
        pass
    return None


def runtime_status():
    path = RUNS / "app_runtime_status.json"
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    # A forced termination can occur before app_strategy_lab.py reaches its
    # finally block. Never expose a stale RUNNING state in that case.
    if payload.get("state") == "RUNNING" and running_pid() is None:
        payload = dict(payload)
        payload["state"] = "STOPPED"
        payload["stale_process_state"] = True
    return payload


def latest_payload():
    run = latest_run()
    if not run:
        return None
    rounds = sorted(run.glob("round-*.json"))
    if not rounds:
        return {"run_dir": str(run)}
    try:
        return json.loads(rounds[-1].read_text())
    except (OSError, json.JSONDecodeError):
        return {"run_dir": str(run), "error": "latest run is not readable"}


def paper_status():
    """Return local paper-bot liveness without exposing account identifiers."""
    processes = []
    try:
        output = subprocess.check_output(["ps", "-axo", "pid=,command="], text=True)
        for line in output.splitlines():
            if "scripts/competition_bot.py" in line and "grep" not in line:
                parts = line.strip().split(None, 1)
                if parts:
                    processes.append({"pid": int(parts[0]), "command": parts[1] if len(parts) > 1 else ""})
    except (OSError, ValueError, subprocess.CalledProcessError):
        pass
    log_path = ROOT / "scripts" / "competition_bot.log"
    recent = []
    try:
        recent = [line.strip() for line in log_path.read_text().splitlines()[-20:] if line.strip()]
    except OSError:
        pass
    # Do not surface an already-recovered exception as the current fault. A
    # successful candle recovery or strategy/plugin load establishes a new
    # healthy boundary; only errors after that boundary are recent.
    healthy_markers = ("merged live K-line recovery", "hot-swapped strategy", "hot-swapped strategy plugin")
    last_healthy = max((index for index, line in enumerate(recent) if any(marker in line for marker in healthy_markers)), default=-1)
    errors = [line for line in recent[last_healthy + 1:] if "ERROR" in line or "Traceback" in line]
    return {
        "running": bool(processes),
        "mode": "SIMULATE" if any("--live-paper" in p["command"] for p in processes) else "DRY_RUN",
        "pid": processes[0]["pid"] if processes else None,
        "last_log": recent[-1] if recent else None,
        "recent_error": errors[-1] if errors else None,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def send_json(self, payload, status=200):
        raw = json.dumps(payload, default=str).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("cache-control", "no-store")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/api/state":
            self.send_json({"running": running_pid() is not None, "pid": running_pid(), "config": STATE.get("config"), "runtime": runtime_status(), "latest": latest_payload(), "paper": paper_status()})
            return
        raw = HTML.encode()
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        if self.path == "/api/start":
            with LOCK:
                if running_pid() is not None:
                    self.send_json({"error": "lab already running"}, 409)
                    return
                length = int(self.headers.get("content-length", "0"))
                body = json.loads(self.rfile.read(length) or "{}")
                command = [sys.executable, str(ROOT / "scripts" / "app_strategy_lab.py"), "--db", str(ROOT / "quant_dashboard.sqlite3"), "--agents", str(max(1, min(5, int(body.get("agents", 5))))), "--candidates", str(max(1, min(1000, int(body.get("candidates", 1))))), "--providers", "local,nvidia,apple,antigravity", "--continuous"]
                RUNS.mkdir(exist_ok=True)
                STATE["process"] = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    os.setpriority(os.PRIO_PROCESS, STATE["process"].pid, 10)
                except (AttributeError, OSError):
                    pass
                STATE["started_at"] = time.time()
                STATE["config"] = body
                self.send_json({"message": "US.APP mutation lab started", "pid": STATE["process"].pid})
                return
        if self.path == "/api/stop":
            pid = running_pid()
            if pid is not None:
                os.kill(pid, signal.SIGINT)
                self.send_json({"message": "stop requested", "pid": pid})
            else:
                self.send_json({"message": "lab is not running"})
            return
        self.send_json({"error": "not found"}, 404)


if __name__ == "__main__":
    print(f"US.APP strategy console: http://127.0.0.1:{PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
