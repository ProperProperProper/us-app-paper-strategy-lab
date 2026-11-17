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

Use the same symbol (`US.APP`), 10-minute source candles, and candle columns (`open`, `high`, `low`, `close`, `volume`). The interval research layer derives complete-session 10m, 20m, 30m, 40m, 50m, 60m, and 70m bars without crossing session boundaries. It deduplicates by `time_key`, uses a rolling 21-session training window, one unseen session per step, 2 bps slippage per side, zero commission, long-only position, and one-position limit. The base comparison is always the freshly rerun 10m baseline; a candidate may be promoted at a higher interval if its blind replay beats that baseline. The active evaluator executes on completed-candle closes; it does not simulate next-open fills.

The 21-session training window and one-session test step are intentional: they prioritize the latest regime and expose changes one session at a time. Comparisons using another training window or test step are separate experiments.

Hard rule: each decision uses every candle in the immediately preceding 21 complete sessions, then tests exactly the next unseen session. The training window advances one session at a time until the current data end. There are no full-window scores, fixed validation slices, or multi-session test chunks.

Promotion is a separate decision from measurement: candidates are judged by the rolling one-session blind replay against the baseline replay. There is no chunked test gate.

The paper execution process reloads approved strategy code and configuration at completed-candle boundaries. The active code/config commit and hot-swapped run identifier must be recorded when comparing paper results.

Paper session coverage is the full US regular session represented by the Moomoo 10-minute candles; comparisons must not silently truncate the session or mix partial-session data.

Every rejection artifact also contains a fresh baseline replay over the same rolling one-session sequence and full current window.

Before comparing reports, record:

- Git commit (`git rev-parse HEAD`)
- Python and dependency versions
- Candle row count, first/last timestamp, and source
- Exact parameters and split boundaries
- Slippage, commission, and allocation

Results from different candle snapshots or commits must be reported as different experiments, not merged into one performance claim.

## Included snapshot

The repository includes `data/us_app_10m_2026-08-18_2026-11-16.csv` and its manifest. It is a sanitized 90-day OHLCV snapshot with no account information. Verify its SHA-256 against the manifest, then run against the fixed timestamps above. The snapshot is the comparison dataset; Moomoo OpenD is only needed to obtain newer data or create another explicitly identified experiment.

To create a new explicitly identified snapshot from a local cache:

```sh
python3 scripts/export_candle_snapshot.py \
  --db quant_dashboard.sqlite3 \
  --output data/us_app_10m_NEW.csv \
  --start 'YYYY-MM-DD HH:MM:SS' \
  --end 'YYYY-MM-DD HH:MM:SS'
```
