# Paper-trading boundary

Paper execution is opt-in and forced through Moomoo `TrdEnv.SIMULATE`. The bot never selects a live trading environment. The competition bot loads the promoted credential-free strategy config when present, otherwise the tracked baseline, and keeps one position per symbol. Moomoo execution can still differ because its fills, session handling, and indicator engine are external to the deterministic Python evaluator.

The paper bot hot-swaps both approved parameters and `scripts/strategy_57pct.py` code at a newly completed candle. A new module must expose the required strategy runtime contract; failed imports or incompatible code are rejected and the last working strategy remains active. No process restart is required for an approved structural strategy change.

The bot monitors the complete US regular session: every completed 10-minute candle from the session start through the close is eligible for signal processing. It does not stop after a research window, a 15-session limit, or a partial-session slice. New entries are blocked at the close cutoff and any open paper position is closed/marked at session end according to the strategy runtime.

## Signal-only checks

With Moomoo OpenD available locally:

```sh
python3 scripts/competition_bot.py --list-accounts
python3 scripts/competition_bot.py US.APP --acc-index 2 --live-paper
```

Use the account index for the paper/competition account shown by `--list-accounts`; `2` is only an example and must be confirmed locally. Without `--live-paper`, the bot remains signal-only. Do not provide credentials or account identifiers in source, documentation, issues, or reports.

## Dashboard

```sh
python3 scripts/quant_dashboard.py
open http://127.0.0.1:8780
```

The dashboard caches candles and displays backtest and risk information. It does not place orders in this build.
