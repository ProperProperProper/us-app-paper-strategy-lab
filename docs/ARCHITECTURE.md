# System architecture

The lab uses a proposal-and-evaluation design:

1. The US.APP runner loads the recent candle cache and splits it chronologically.
2. Local and NVIDIA gateway workers, plus optional Antigravity, propose bounded mutations.
3. The local evaluator scores every candidate.
4. The runner selects the best training candidates, re-evaluates them on validation data, and evaluates the selected candidate on the final holdout.
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

The runner uses a 60% train / 20% validation / 20% test split. It does not re-select a strategy at every session boundary, run a supervisor, or persist learned memory in this repository. Runtime artifacts remain outside Git. The system is long-only, one-position, and paper/tester-only in this public build.
