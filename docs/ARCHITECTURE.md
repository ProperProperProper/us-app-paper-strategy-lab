# System architecture

The lab uses a proposal-and-evaluation design:

1. The US.APP runner loads the requested bounded candle window (90 calendar days by default) and splits it chronologically.
2. Local and NVIDIA gateway workers, plus optional Antigravity, propose bounded mutations.
3. The local evaluator scores every candidate.
4. The runner performs a blind one-session walk-forward: it selects from the prior 21 sessions, then replays exactly the next complete session before advancing one session. Each round also includes explicit profit-capture strategy variants.
5. The selected parameters are written to the local live-strategy JSON artifact.
6. The browser console exposes process status and the latest run artifact.

The evaluator, not a model, decides returns, drawdown, trade counts, chronology, and candidate metrics. Generated source is not executed as part of candidate evaluation. Fee-model support exists in the shared strategy engine, but the current mutation runner uses zero commission.

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

The runner uses rolling blind replay: after 21 complete training sessions, it selects before the next session and replays exactly one unseen session, advancing one session at a time to the end of the data. There are no fixed validation partitions or multi-session test blocks. The system does not run a supervisor or persist learned memory in this repository. Runtime artifacts remain outside Git. The system is long-only, one-position, and paper/tester-only in this public build.
