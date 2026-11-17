# Reproducible research

Results are reproducible only when the Python environment, candle snapshot, timestamp window, strategy commit, and execution settings match. Moomoo OpenD can revise or return a different historical candle set, so “90 days” by itself is not a reproducible dataset.

## Pin the environment

Use Python 3.9 or newer, then install the repository-pinned dependencies:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Use an explicit candle window

The runner defaults to the latest 90 calendar days in the local SQLite cache. For comparable results, provide the same inclusive timestamps to every copy:

```sh
python3 scripts/app_strategy_lab.py \
  --db quant_dashboard.sqlite3 \
  --start '2026-08-18 16:00:00' \
  --end '2026-11-16 16:00:00' \
  --agents 2 --candidates 100 \
  --providers local,nvidia,antigravity
```

The timestamps above are examples from one local cache. Use the timestamps recorded in the run profile for the actual shared dataset. Do not silently convert them between timezones.

## Match the execution model

Use the same symbol (`US.APP`), interval (`10m`), candle columns (`open`, `high`, `low`, `close`, `volume`), duplicate policy (deduplicate by `time_key`), 60/20/20 chronological split, 2 bps slippage per side, zero commission, long-only position, and one-position limit. The active evaluator executes on completed-candle closes; it does not simulate next-open fills.

Before comparing reports, record:

- Git commit (`git rev-parse HEAD`)
- Python and dependency versions
- Candle row count, first/last timestamp, and source
- Exact parameters and split boundaries
- Slippage, commission, and allocation

Results from different candle snapshots or commits must be reported as different experiments, not merged into one performance claim.
