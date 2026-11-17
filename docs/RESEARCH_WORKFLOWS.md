# Research workflows

## Continuous daily research

```sh
python3 scripts/continuous_daily_research.py \
  --db data/asx_daily_yfinance.sqlite3 \
  --symbols 'CDA BHP CBA CSL WES RIO FMG GMG WOW' \
  --years 1 --agents 1 --nvidia-agents 3 --nvidia-rounds 3 \
  --nvidia-concurrency 1 --candidates 100
```

The loop follows `recall → observe → plan → delegate → evaluate → reflect → commit`. It persists memory, summaries, model telemetry, and supervisor status locally.

## ASX daily data

```sh
python3 scripts/download_asx_daily_yfinance.py
```

Use `--symbols BHP,CBA,CSL` for a smaller universe. Data is de-duplicated and stored in SQLite.

## Historical CDA screen-capture data

```sh
python3 scripts/codan_screen_capture_tester.py
python3 scripts/codan_screen_capture_tester.py --optimize --trials 500
```

This workflow uses reconstructed local data, five-hour session aggregation, completed-candle signals, next-bar execution, and transaction brokerage assumptions. It does not use OpenD or submit orders.

## Reports and artifacts

Generated reports and run artifacts are local-only. They must not be committed because they may contain large datasets, runtime state, local paths, or account-related information.
