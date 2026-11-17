# Google Antigravity integration

Google Antigravity is connected locally through the existing Multi-Model AI Gateway using MCP.

## What is connected

- `gateway_health` — reads gateway, MLX, and NVIDIA health/telemetry.
- `gateway_chat` — sends bounded requests through the gateway’s existing provider allowlist.
- `gateway_router_sample` — creates a reviewable routing example without changing data or strategy state.

The strategy lab can also run Antigravity as a proposal-only optimizer worker
(`--providers local,nvidia,antigravity`, one worker by default). It receives
the measured profile and current parents, returns one bounded parameter
mutation, and never supplies returns, trades, or validation. The local
deterministic evaluator remains the only source of metrics and eligibility.

Antigravity does not connect directly to NVIDIA, MLX, the strategy database, or the paper trader. The gateway remains the single routing boundary and the deterministic evaluator remains the authority for research results.

## Local setup

The workspace configuration is at:

```text
the local `.agents/mcp_config.json` configuration file
```

It starts the existing stdio MCP server and points it to `http://127.0.0.1:8788`.

In Antigravity, reload MCP servers from the MCP manager after opening the `TradingSystem` workspace. The gateway must be running first.

## Safety boundary

Antigravity is a development/research assistant only. It must not place live orders, alter the strategy evaluator, introduce future data, or treat model suggestions as performance evidence. Any proposed strategy change still has to pass the existing chronological research and audit process.
