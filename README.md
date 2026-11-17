# US.APP Paper Strategy Research Lab

<img width="1164" height="701" alt="Screenshot 2026-11-17 at 4 37 43 PM" src="https://github.com/user-attachments/assets/9a8a46eb-fc9d-49bd-a23b-9d07f04c14cf" />

An Apple Silicon quantitative trading research lab for US.APP 10-minute candles, Moomoo OpenD data, deterministic backtesting, chronological holdout validation, and AI-proposed strategy mutations.

This repository is designed for paper-trading research and strategy experimentation. It cannot select a live trading environment; paper orders require an explicit runtime flag and are forced through Moomoo `TrdEnv.SIMULATE`.

The system is research-first: model output is a proposal, the deterministic evaluator is authoritative, and paper order placement is opt-in. Results are not financial advice or a guarantee of future performance.

**Keywords:** US.APP, Moomoo OpenD, paper trading, algorithmic trading, quantitative finance, backtesting, strategy mutation, AI agents, Apple Silicon, MLX, NVIDIA models, Antigravity, SQLite.

## Quick start

```sh
python3 scripts/research_console.py
open http://127.0.0.1:8790
```

Moomoo OpenD must be available at `127.0.0.1:11111` for fresh candles. Local databases, credentials, logs, reports, and generated runs are ignored by Git.

## Documentation

- [Getting started](docs/GETTING_STARTED.md)
- [System architecture](docs/ARCHITECTURE.md)
- [Strategy and evaluation](docs/STRATEGY_AND_EVALUATION.md)
- [Research workflows](docs/RESEARCH_WORKFLOWS.md)
- [Model operations](docs/MODEL_OPERATIONS.md)
- [External gateway and MCP setup](docs/EXTERNAL_GATEWAY.md)
- [Paper-trading boundary](docs/PAPER_TRADING.md)
- [Engineering concepts](docs/ENGINEERING_CONCEPTS.md)
- [Antigravity integration](docs/ANTIGRAVITY.md)
- [Security](docs/SECURITY.md)
- [Reproducible research](docs/REPRODUCIBILITY.md)

## Repository layout

- `scripts/` — all Python entry points and research components.
- `docs/` — project documentation and research notes.
- `.github/workflows/` — repository checks.

## Safety

This is experimental research software. It is not financial advice. Do not enable live trading from this repository.
