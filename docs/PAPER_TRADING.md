# Paper-trading boundary

Paper execution is intentionally disabled in this public tester-focused build. The execution boundary is retained for research and integration testing, but the dashboard and CLI reject paper-order startup. The competition bot and both Moomoo copy-paste strategies now use the active 33-bar / EMA 17-26 baseline. Moomoo execution can still differ because its fills, session handling, and indicator engine are external to the deterministic Python evaluator.

## Signal-only checks

With Moomoo OpenD available locally:

```sh
python3 scripts/competition_bot.py --list-accounts
python3 scripts/competition_bot.py AAPL NVDA --acc-index 0
```

These commands are for account discovery and signal inspection only. Do not provide credentials or account identifiers in source, documentation, issues, or reports.

## Dashboard

```sh
python3 scripts/quant_dashboard.py
open http://127.0.0.1:8780
```

The dashboard caches candles and displays backtest and risk information. It does not place orders in this build.
