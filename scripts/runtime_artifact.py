"""Strict, dependency-free validation for promoted paper-runtime artifacts."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

ENTRYPOINT = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_][\w]*$")
SUPPORTED_INTERVALS = tuple(range(1, 22))
REQUIRED_TOP_LEVEL = {"plugin", "params", "interval", "mode", "promotion"}
REQUIRED_PLUGIN = {"name", "version", "python_root", "entrypoint", "constructor"}
REQUIRED_PROMOTION = {"baseline", "candidate", "replay_protocol"}
REPLAY_PROTOCOL = "first_21_complete_sessions_then_one_continuous_unseen_replay"


def validate_runtime_artifact(payload: Any) -> dict[str, Any]:
    """Return the payload if safe for loading, otherwise raise ``ValueError``.

    This intentionally mirrors the public plugin framework contract without
    requiring Pydantic in the broker-facing paper process.
    """
    if not isinstance(payload, dict) or set(payload) != REQUIRED_TOP_LEVEL:
        raise ValueError("runtime artifact has an invalid top-level schema")
    plugin = payload["plugin"]
    if not isinstance(plugin, dict) or set(plugin) != REQUIRED_PLUGIN:
        raise ValueError("runtime artifact plugin descriptor is invalid")
    for field in ("name", "version", "python_root", "entrypoint"):
        if not isinstance(plugin[field], str) or not plugin[field].strip():
            raise ValueError(f"runtime artifact plugin field is invalid: {field}")
    if not ENTRYPOINT.fullmatch(plugin["entrypoint"]):
        raise ValueError("runtime artifact entrypoint is invalid")
    if not plugin["entrypoint"].startswith("strategy_plugins."):
        raise ValueError("runtime artifact entrypoint is outside the trusted plugin namespace")
    root = Path(plugin["python_root"]).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("runtime artifact python_root does not exist")
    if not isinstance(plugin["constructor"], dict):
        raise ValueError("runtime artifact constructor must be an object")
    lab_root = plugin["constructor"].get("lab_root")
    if lab_root is not None and not Path(str(lab_root)).expanduser().resolve().is_dir():
        raise ValueError("runtime artifact lab_root does not exist")
    if not isinstance(payload["params"], dict):
        raise ValueError("runtime artifact params must be an object")
    if payload["mode"] != "SIMULATE":
        raise ValueError("paper bot accepts SIMULATE runtime artifacts only")
    if payload["interval"] not in SUPPORTED_INTERVALS:
        raise ValueError(f"runtime artifact interval must be one of {SUPPORTED_INTERVALS}")
    promotion = payload["promotion"]
    if not isinstance(promotion, dict) or set(promotion) != REQUIRED_PROMOTION:
        raise ValueError("runtime artifact promotion evidence is invalid")
    if not isinstance(promotion["baseline"], dict) or not isinstance(promotion["candidate"], dict):
        raise ValueError("runtime artifact promotion metrics must be objects")
    if promotion["replay_protocol"] != REPLAY_PROTOCOL:
        raise ValueError("runtime artifact replay protocol is not approved")
    return payload
