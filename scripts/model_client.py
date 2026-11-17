"""Small MCP client used by the US.APP research loop."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


class MCPClient:
    def __init__(self, server: Path, gateway: str):
        env = os.environ.copy()
        env["MULTI_MODEL_GATEWAY_URL"] = gateway
        self.proc = subprocess.Popen(
            [sys.executable, str(server)], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, text=True, env=env,
        )
        self.request_id = 0
        self.last_meta: dict = {}
        self.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "us-app-strategy-lab", "version": "1.0"}})
        self.notify("notifications/initialized", {})

    def notify(self, method: str, params: dict):
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n")
        self.proc.stdin.flush()

    def call(self, method: str, params: dict):
        self.request_id += 1
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.request_id, "method": method, "params": params}) + "\n")
        self.proc.stdin.flush()
        while True:
            row = self.proc.stdout.readline()
            if not row:
                raise RuntimeError("MCP server exited")
            response = json.loads(row)
            if response.get("id") == self.request_id:
                if "error" in response:
                    raise RuntimeError(response["error"].get("message", "MCP error"))
                return response.get("result", {})

    def ask(self, prompt: str, provider="local", max_tokens=700, model=None) -> str:
        arguments = {"prompt": prompt, "provider": provider, "max_tokens": max_tokens}
        if model:
            arguments["model"] = model
        result = self.call("tools/call", {"name": "gateway_chat", "arguments": arguments})
        structured = result.get("structuredContent", {}) or {}
        self.last_meta = structured.get("routing", {}) or {}
        self.last_meta["model"] = structured.get("model")
        text = structured.get("text", "") or result.get("content", [{}])[0].get("text", "")
        if isinstance(text, str) and text.lstrip().startswith("{"):
            try:
                envelope = json.loads(text)
                choices = envelope.get("choices") if isinstance(envelope, dict) else None
                if choices:
                    message = choices[0].get("message", {}) or {}
                    text = message.get("content") or message.get("reasoning_content") or ""
            except (TypeError, ValueError, AttributeError):
                pass
        return text

    def close(self):
        self.proc.terminate()
