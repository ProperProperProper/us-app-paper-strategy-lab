# ASX Strategy Research Lab

Local research and paper-trading tools for ASX and US.APP market data on macOS Apple Silicon.

The system is research-first: model output is a proposal, the deterministic evaluator is authoritative, and live order placement is disabled. Results are not financial advice or a guarantee of future performance.

## Quick start

```sh
python3 scripts/research_console.py
open http://127.0.0.1:8790
```

For continuous daily research:

```sh
python3 scripts/continuous_daily_research.py \
  --db data/asx_daily_yfinance.sqlite3 \
  --symbols 'CDA BHP CBA CSL WES RIO FMG GMG WOW' \
  --years 1 --agents 1 --nvidia-agents 3 --nvidia-rounds 3 \
  --nvidia-concurrency 1 --candidates 100
```

Moomoo OpenD must be available at `127.0.0.1:11111` for fresh candles. Local databases, credentials, logs, reports, and generated runs are ignored by Git.

## Documentation

- [Getting started](docs/GETTING_STARTED.md)
- [System architecture](docs/ARCHITECTURE.md)
- [Strategy and evaluation](docs/STRATEGY_AND_EVALUATION.md)
- [Research workflows](docs/RESEARCH_WORKFLOWS.md)
- [Model operations](docs/MODEL_OPERATIONS.md)
- [Paper-trading boundary](docs/PAPER_TRADING.md)
- [Historical CDA research](docs/CDA_RESEARCH.md)
- [Engineering concepts](docs/ENGINEERING_CONCEPTS.md)
- [Antigravity integration](docs/ANTIGRAVITY.md)
- [Security](docs/SECURITY.md)
- [Research sources](docs/research_sources.md)

## Repository layout

- `scripts/` — all Python entry points and research components.
- `docs/` — project documentation and research notes.
- `.github/workflows/` — repository checks.

## Safety

This is experimental research software. It is not financial advice. Do not enable live trading from this repository.
