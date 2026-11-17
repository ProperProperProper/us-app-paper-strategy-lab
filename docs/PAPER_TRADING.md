# Paper-trading boundary

Paper execution is opt-in and forced through Moomoo `TrdEnv.SIMULATE`. The bot never selects a live trading environment. The competition bot loads the promoted credential-free strategy config when present, otherwise the tracked baseline, and keeps one position per symbol. Moomoo execution can still differ because its fills, session handling, and indicator engine are external to the deterministic Python evaluator.

The paper bot hot-swaps both approved parameters and `scripts/strategy_57pct.py` code at a newly completed candle. A new module must expose the required strategy runtime contract; failed imports or incompatible code are rejected and the last working strategy remains active. No process restart is required for an approved structural strategy change.

The bot monitors the complete US regular session: every completed 10-minute candle from the session start through the close is eligible for signal processing. It does not stop after a research window, a 15-session limit, or a partial-session slice. There is no strategy-level early-session entry cutoff or forced time-based exit; entries require the actual strategy signal, and exits require the configured risk, profit-capture, or trend/rule condition.

Before evaluating an entry, it requires fresh candle data and enough history for the active lookback/regime warm-up. Stale or under-warmed data causes a safe cycle error and places no order.

OpenD can return a cached historical snapshot. The bot therefore subscribes to
the `KL_10M` regular-hours stream, reads `get_cur_kline`, merges live bars by
`time_key`, validates OHLCV values, deduplicates them, and persists the repaired
set to SQLite. During regular hours, a missing current-session candle causes a
retrying no-order cycle; outside regular hours, the last completed trading
session is valid. Candle storage is retained from `2026-01-01` onward; older
rows are removed automatically when SQLite opens.

## Signal-only checks

With Moomoo OpenD available locally:

```sh
python3 scripts/competition_bot.py --list-accounts
python3 scripts/competition_bot.py US.APP --acc-id "$COMPETITION_SIM_ACCOUNT_ID" --live-paper
```

Set `COMPETITION_SIM_ACCOUNT_ID` only in the local shell from the competition SIMULATE account shown by `--list-accounts`; never commit it. Without `--live-paper`, the bot remains signal-only. Do not provide credentials or account identifiers in source, documentation, issues, or reports.

## Dashboard

```sh
python3 scripts/quant_dashboard.py
open http://127.0.0.1:8780
```

The dashboard caches candles and displays backtest and risk information. It does not place orders in this build.
