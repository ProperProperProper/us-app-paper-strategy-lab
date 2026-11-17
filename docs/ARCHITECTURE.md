# System architecture

The lab uses a proposal-and-evaluation design:

1. The controller recalls persistent memory and current runtime state.
2. Specialist workers propose parameter candidates or bounded strategy variants.
3. The local evaluator runs deterministic chronological tests.
4. Validation gates reject weak, unsafe, malformed, or overfit candidates.
5. Accepted results are recorded in SQLite and persistent research memory.
6. The browser console exposes health, progress, failures, and fallback state.

The evaluator, not a model, decides returns, drawdown, fees, trade counts, chronology, and eligibility. Generated source is not executed as part of candidate evaluation.

## Main components

- `scripts/multi_symbol_strategy_lab.py` — controller, workers, memory, and evaluation loop.
- `scripts/continuous_daily_research.py` — supervised daily runner and restart logic.
- `scripts/research_console.py` — local browser console and API.
- `scripts/strategy_57pct.py` — deterministic strategy and walk-forward primitives.
- `scripts/quant_storage.py` — SQLite persistence.
- `scripts/quant_api.py` — shared data, risk, strategy, and audit interfaces.
- `scripts/advanced_research_engine.py` — data-gated research families.
- `scripts/causal_formula_engine.py` — bounded formula-tree candidates.
- `scripts/custom_indicator_engine.py` — bounded custom-indicator candidates.
- `scripts/ml_strategy_engine.py` — bounded ML candidates.

## Runtime safety

The system is long-only, one-position, and paper/tester-only in this public build. Runtime artifacts remain outside Git and are subject to local health monitoring.
