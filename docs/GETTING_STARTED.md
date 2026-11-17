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

## Run a research cycle

Use the console or `scripts/app_strategy_lab.py` for repeatable US.APP mutation cycles. It records status and run summaries under `strategy_lab_runs/`, which is local-only and ignored by Git.

Create `strategy_lab_runs/STOP` or press Ctrl-C to stop gracefully. The runner stops at the next safe boundary.

## Conventions

- Put executable Python files in `scripts/`.
- Put Markdown documentation in `docs/`; keep only `README.md` at the root.
- Never commit credentials, account identifiers, local paths, databases, logs, or generated run artifacts.
