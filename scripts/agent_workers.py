"""Bounded code-authority proposal worker for the US.APP lab."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

ANTIGRAVITY_BIN = os.environ.get("ANTIGRAVITY_BIN", "/Applications/Gemini.app/Contents/Helpers/agy")
ANTIGRAVITY_MODEL = os.environ.get("ANTIGRAVITY_MODEL", "gemini-3.8-flash-low")
HEALTH = {"model": ANTIGRAVITY_MODEL, "requests": 0, "successes": 0, "failures": 0, "last_error": None, "last_latency_ms": None}


class AntigravityOptimizer:
    """Allow proposals only; the local evaluator remains authoritative."""

    def __init__(self, timeout_seconds: int = 60):
        binary = shutil.which(ANTIGRAVITY_BIN) or (ANTIGRAVITY_BIN if Path(ANTIGRAVITY_BIN).exists() else None)
        if not binary:
            raise FileNotFoundError(f"Antigravity CLI not found: {ANTIGRAVITY_BIN}")
        self.binary = binary
        self.timeout_seconds = max(10, int(timeout_seconds))

    def ask(self, prompt: str) -> str:
        started = time.monotonic()
        HEALTH["requests"] += 1
        command = [self.binary, "--model", ANTIGRAVITY_MODEL, "--effort", "low", "--mode", "plan", "--disable-slash-commands", "--output-format", "json", "--print-timeout", f"{self.timeout_seconds}s", "--print", prompt]
        try:
            completed = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=self.timeout_seconds + 10, check=False)
            if completed.returncode != 0:
                raise RuntimeError((completed.stderr or completed.stdout or f"exit={completed.returncode}").strip()[:240])
            envelope = json.loads(completed.stdout)
            response = envelope.get("response", "") if isinstance(envelope, dict) else ""
            if not isinstance(response, str) or not response.strip():
                raise RuntimeError("Antigravity returned an empty response")
            HEALTH["successes"] += 1
            HEALTH["last_latency_ms"] = round((time.monotonic() - started) * 1000, 1)
            return response
        except Exception as exc:
            HEALTH["failures"] += 1
            HEALTH["last_error"] = str(exc)[:240]
            HEALTH["last_latency_ms"] = round((time.monotonic() - started) * 1000, 1)
            raise
