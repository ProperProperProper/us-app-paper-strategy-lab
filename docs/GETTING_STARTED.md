# Getting started

## Requirements

- macOS Apple Silicon.
- Python 3 with the project dependencies installed.
- Moomoo OpenD at `127.0.0.1:11111` when fresh Moomoo candles are required.
- The local model gateway and MLX boundary when using model-assisted research.

See [External gateway and MCP setup](EXTERNAL_GATEWAY.md) for service startup, MCP path discovery, environment variables, and verification.

## Start the browser console

```sh
python3 scripts/research_console.py
open http://127.0.0.1:8790
```

## Run a research cycle

Use the console or `scripts/app_strategy_lab.py` for repeatable US.APP mutation cycles. It records status and run summaries under `strategy_lab_runs/`, which is local-only and ignored by Git.

Create `strategy_lab_runs/STOP` or press Ctrl-C to stop gracefully. The runner stops at the next safe boundary.

For session-time supervision of the lab, console, and SIMULATE paper bot, run:

```sh
python3 scripts/session_monitor.py
```

## Run the paper bot

With Moomoo OpenD running and a local SIMULATE account selected:

```sh
python3 scripts/competition_bot.py US.APP \
  --acc-id "$COMPETITION_SIM_ACCOUNT_ID" \
  --interval 30 --live-paper
```

The bot reads the promoted local artifact when present. It stores incoming
1-minute source candles in SQLite, aggregates the promoted 1–21m interval locally,
and hot-swaps approved strategy code/config without a process restart. The
console's Paper bot panel shows process state, SIMULATE mode, last candle
refresh, and recent errors.

The research loop does not place orders directly. Its only handoff to the bot
is the accepted runtime artifact; the bot remains the sole order submitter.

## Conventions

- Put executable Python files in `scripts/`.
- Put Markdown documentation in `docs/`; keep only `README.md` at the root.
- Never commit credentials, account identifiers, local paths, databases, logs, or generated run artifacts.
