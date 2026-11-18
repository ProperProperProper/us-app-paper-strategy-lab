# Google Antigravity integration

Google Antigravity is the required coordinator and controller for the US.APP
mutation runner. The separate gateway/MCP integration is an external workspace
dependency.

## What is connected

- `gateway_health` — reads gateway, MLX, and NVIDIA health/telemetry.
- `gateway_chat` — sends bounded requests through the gateway’s existing provider allowlist.
- `gateway_router_sample` — creates a reviewable routing example without changing data or strategy state.

The strategy lab runs Antigravity as the mandatory controller and proposal worker
(`--providers local,nvidia,antigravity`, one worker by default). It receives
the measured profile and current parents, returns one bounded parameter
mutation, and never supplies returns, trades, or validation. The local
deterministic evaluator remains the only source of metrics and eligibility.

The deterministic evaluator remains the authority for research results. Antigravity does not write strategy code, write the database, or submit paper orders.

## Local setup

The optional gateway/MCP configuration is managed outside this repository. When using the gateway-backed local or NVIDIA providers, it must be running at the configured local endpoint before starting the lab.

## Safety boundary

Antigravity is a development/research controller only. It must not place
orders, alter the evaluator, introduce future data, or supply performance
metrics. Its configurations are constrained and then evaluated locally. If it
cannot authenticate or respond, the lab stops rather than silently bypassing
the controller.
