# US.APP Paper Strategy Research Lab

<img width="1164" height="701" alt="Screenshot 2026-11-17 at 4 37 43 PM" src="https://github.com/user-attachments/assets/9a8a46eb-fc9d-49bd-a23b-9d07f04c14cf" />

An Apple Silicon quantitative trading research lab for US.APP 10-minute candles, Moomoo OpenD data, deterministic backtesting, chronological blind replay, and AI-proposed strategy mutations.

This repository is designed for paper-trading research and strategy experimentation. It cannot select a live trading environment; paper orders require an explicit runtime flag and are forced through Moomoo `TrdEnv.SIMULATE`.

The system is research-first: model output is a proposal, the deterministic evaluator is authoritative, and paper order placement is opt-in. Results are not financial advice or a guarantee of future performance.

## How research becomes paper execution

The research lab and paper bot are one pipeline:

1. Moomoo OpenD supplies validated 10-minute US.APP candles. The candles and derived interval bars are stored in SQLite.
2. MLX/local and NVIDIA agents propose bounded strategy hypotheses; required Antigravity coordinates and configures the proposals. None of the agents decides performance or submits orders.
3. The deterministic evaluator tests every candidate on complete 10m, 20m, 30m, 40m, 50m, 60m, and 70m session bars using one continuous blind replay: the first 21 complete sessions are training/selection data, then every candle from session 22 through the latest candle is unseen test data.
4. The fresh 10m baseline is always the comparison reference. A candidate may win on a higher interval when its blind replay beats that 10m baseline.
5. An accepted candidate writes the local `paper_bot_live_strategy.json` artifact with its parameters, strategy version, and selected interval.
6. The paper bot hot-swaps approved parameters, interval, and strategy code at a completed-bar boundary. It receives 10m Moomoo data, aggregates it locally when required, and submits only signal-driven orders to `TrdEnv.SIMULATE`.

The browser console at `http://127.0.0.1:8790` shows both research-lab state and paper-bot health. The legacy 8780 dashboard is not required for the current pipeline.

**Keywords:** US.APP, Moomoo OpenD, paper trading, algorithmic trading, quantitative finance, backtesting, strategy mutation, AI agents, Apple Silicon, MLX, NVIDIA models, Antigravity, SQLite.

## Quick start

```sh
python3 scripts/research_console.py
open http://127.0.0.1:8790
```

Moomoo OpenD must be available at `127.0.0.1:11111` for fresh candles. The lab, dashboard, and paper bot share the root `quant_dashboard.sqlite3` database; credentials, logs, reports, and generated runs are ignored by Git.

## Documentation

- [Getting started](docs/GETTING_STARTED.md)
- [System architecture](docs/ARCHITECTURE.md)
- [Strategy and evaluation](docs/STRATEGY_AND_EVALUATION.md)
- [Research workflows](docs/RESEARCH_WORKFLOWS.md)
- [Model operations](docs/MODEL_OPERATIONS.md)
- [External gateway and MCP setup](docs/EXTERNAL_GATEWAY.md)
- [Paper-trading boundary](docs/PAPER_TRADING.md)
- [Engineering concepts](docs/ENGINEERING_CONCEPTS.md)
- [Native Rust core](docs/NATIVE_RUST_CORE.md)
- [Antigravity integration](docs/ANTIGRAVITY.md)
- [Antigravity code-audit handover](docs/ANTIGRAVITY_CODE_AUDIT_HANDOVER.md)
- [Security](docs/SECURITY.md)
- [Reproducible research](docs/REPRODUCIBILITY.md)

## Repository layout

- `scripts/` — all Python entry points and research components.
- `docs/` — project documentation and research notes.
- `.github/workflows/` — repository checks.

The public repository contains the code and reproducibility assets. Local SQLite databases, promoted runtime configuration, logs, account selection, and generated run artifacts stay outside Git and are backed up separately when configured.

## Safety

This is experimental research software. It is not financial advice. Do not enable live trading from this repository.
