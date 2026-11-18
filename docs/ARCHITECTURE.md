# System architecture

The lab uses a proposal-and-evaluation design:

1. The US.APP runner loads the requested bounded candle window (90 calendar days by default) and splits it chronologically.
2. Local and NVIDIA gateway workers, plus optional Antigravity, propose bounded mutations.
3. The local evaluator aggregates the 10-minute source candles into 10m, 20m, 30m, 40m, 50m, 60m, and 70m complete-session bars and scores every candidate on each interval.
4. The runner selects once using the first 21 complete sessions, then performs one continuous blind replay from session 22 through the latest candle. Each round also includes explicit profit-capture strategy variants.
5. The selected parameters are written to the local live-strategy JSON artifact.
6. The browser console exposes process status and the latest run artifact.

## Research-to-bot handoff

The handoff is file-and-database based, not model-to-order based:

```text
Moomoo OpenD
    ↓ validated 10m source candles
SQLite candle store ───────────────┐
    ↓                              │
proposal agents → local evaluator  │
                    ↓              │
          blind interval comparison│
                    ↓              │
       promoted runtime JSON       │
                    ↓              │
paper bot ← 10m feed + local interval aggregation
    ↓
Moomoo SIMULATE order path only
```

## Agent-to-agent protocol

Agent communication is durable and explicit. Each round writes messages to the
`agent_messages` table in the research SQLite database. Messages identify the
sender, recipient, round, type, correlation identifier, timestamp, and JSON
payload. The normal chain is:

`nvidia → antigravity → deterministic_evaluator → antigravity → mlx_learner`

NVIDIA proposals and roles are recorded before coordinator review. Antigravity's
configured candidate is recorded before local evaluation. The evaluator then
records candidate-versus-baseline evidence, the promotion decision, and the
learning handoff. This ledger survives process restarts and makes each round
auditable without treating model text as performance evidence.

The evaluator records the selected interval and parameters. The paper bot
reloads that artifact and the strategy module at a completed-bar boundary. A
failed reload leaves the last known-good runtime active. The bot never trusts a
model response for fills, risk, or order authorization.

The evaluator, not a model, decides returns, drawdown, trade counts, chronology, and candidate metrics. The base comparison is always a freshly rerun 10m baseline, but a candidate may win on a higher tested interval when its blind replay beats that 10m baseline. The promoted interval and strategy code are hot-swappable in the paper bot. Generated source is not executed as part of candidate evaluation. Fee-model support exists in the shared strategy engine, but the current mutation runner uses zero commission. Source and derived interval candles are persisted in SQLite.

## Main components

- `scripts/app_strategy_lab.py` — US.APP mutation runner and promotion boundary.
- `scripts/research_console.py` — local browser console and API.
- `scripts/model_client.py` — MCP gateway client for local/NVIDIA proposals.
- `scripts/agent_workers.py` — optional Antigravity proposal worker.
- `scripts/strategy_57pct.py` — deterministic strategy and walk-forward primitives.
- `scripts/quant_storage.py` — SQLite persistence.
- `scripts/quant_api.py` — shared data, risk, strategy, and audit interfaces.
- `scripts/advanced_research_engine.py` — data-gated research families.
- `scripts/causal_formula_engine.py` — bounded formula-tree candidates.
- `scripts/custom_indicator_engine.py` — bounded custom-indicator candidates.
- `scripts/ml_strategy_engine.py` — bounded ML candidates.

## Current limitations

The runner uses a continuous blind replay as a hard rule: it uses all candles in the first 21 complete sessions for selection, then replays every remaining candle through the current data end without reselection, chunking, or session blocks. No full-window score or fixed validation partition is used for promotion. SQLite persists source/derived candles, runs, optimizer results, and execution events; it is not a trained-model memory store. Runtime artifacts remain outside Git. The system is long-only, one-position, and paper/tester-only in this public build.
