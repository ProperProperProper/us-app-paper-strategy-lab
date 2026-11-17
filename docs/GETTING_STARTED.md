# Getting started

## Requirements

- macOS Apple Silicon.
- Python 3 with the project dependencies installed.
- Moomoo OpenD at `127.0.0.1:11111` when fresh Moomoo candles are required.
- The local model gateway and MLX boundary when using model-assisted research.

## Start the browser console

```sh
python3 scripts/research_console.py
open http://127.0.0.1:8790
```

## Download daily data

```sh
python3 scripts/download_asx_daily_yfinance.py --symbols CDA,BHP,CBA,CSL,WES
```

Data is stored locally in `data/asx_daily_yfinance.sqlite3`. The downloader does not modify the dashboard database.

## Run a research cycle

Use `scripts/continuous_daily_research.py` for repeatable cycles. It records status and memory under `strategy_lab_runs/`, which is local-only and ignored by Git.

Create `strategy_lab_runs/STOP_DAILY` or press Ctrl-C to stop gracefully. The wrapper restarts a crashed or stale child with bounded backoff.

## Conventions

- Put executable Python files in `scripts/`.
- Put Markdown documentation in `docs/`; keep only `README.md` at the root.
- Never commit credentials, account identifiers, local paths, databases, logs, or generated run artifacts.
