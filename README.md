# ASX Strategy Research Lab and Paper-Trading Research Tools

This repository contains local-only research and paper-trading tools for ASX
market data on macOS Apple Silicon. The current production path is the daily
multi-symbol Strategy Research Lab: it uses one year of daily Yahoo Finance
candles, chronological train/validation/test evaluation, a local MLX controller,
bounded NVIDIA research workers, persistent agent memory, and a browser console.
The local deterministic evaluator remains authoritative for returns, drawdown,
fees, trade counts, and eligibility.

**Keywords:** Moomoo paper trading bot, Moomoo OpenD API, quantitative trading,
algorithmic trading, APP stock, Donchian breakout, EMA strategy, walk-forward
optimization, SQLite market data, paper trading dashboard, Apple Silicon, Rust.

> Research and paper trading only. This project does not provide financial
> advice and does not guarantee performance. Live trading is intentionally not
> supported by the dashboard.

Research and backtesting code for long-only breakout/trend hypotheses. Model
output is treated as a proposal only; generated code is never executed and no
live orders are enabled.

## Current Strategy Research Lab

Start the local console from this repository:

```sh
python3 research_console.py
open http://127.0.0.1:8790
```

The continuous daily run is started with:

```sh
python3 scripts/continuous_daily_research.py \
  --db data/asx_daily_yfinance.sqlite3 \
  --symbols 'CDA BHP CBA CSL WES RIO FMG GMG WOW ALL AMC ANZ NAB WBC MQG TCL CPU REA WTC XRO CAR SEK RMD MIN NXT STO S32 QAN COL TWE' \
  --years 1 --agents 1 --nvidia-agents 3 --nvidia-rounds 3 \
  --nvidia-concurrency 1 --candidates 100
```

The loop is `recall → observe → plan → delegate → evaluate → reflect →
commit`. MLX is the controller, NVIDIA models provide bounded specialist
proposals, and the local evaluator decides every result. Agent memory is
persisted in `strategy_lab_runs/agentic_memory.json`; generated run folders,
databases, reports, and local credentials are intentionally ignored by Git.
The console exposes model health, request/failure/fallback counters, current
symbol and generation, decomposition steps, persistent-memory status, and the
active gateway state.

The continuous wrapper is also a self-healing supervisor. It writes
`strategy_lab_runs/supervisor_status.json`, checks the child runtime heartbeat
and gateway telemetry, preserves the last completed summary as the next seed,
and restarts a crashed or stale child with bounded exponential backoff. A
stale heartbeat is only declared after five minutes by default, which is long
enough for the configured hosted-model and Antigravity calls. Use
`--health-timeout-seconds` to adjust that threshold; create
`strategy_lab_runs/STOP_DAILY` or press Ctrl-C to stop it gracefully.

Daily research is separate from the reconstructed CDA screen-capture dataset.
The daily downloader is rate-aware and stores local SQLite data only:

```sh
python3 scripts/download_asx_daily_yfinance.py --symbols CDA,BHP,CBA,CSL,WES
```

This project is research software, not financial advice. It does not place
live orders and does not promise performance.

## Highlights

- Moomoo OpenD candle ingestion with SQLite persistence.
- Strict walk-forward testing: parameters are selected only on prior data and
  scored only on the next unseen fold.
- Shared strategy, data, risk, audit, and execution interfaces in
  `quant_api.py`.
- Paper execution code is retained for reference but disabled; the dashboard is tester-only.
- Local dashboard for charts, trades, optimizer progress, risk decisions, and
  execution status.
- Optional AI routing is provided by the separate local `multi-model-ai-gateway`
  and `mlx-sentinel` repositories.

## 2 bps baseline

The current benchmark uses completed 10-minute candles and enters at the next candle open:

| Setting | Value |
|---|---:|
| Donchian lookback | 45 candles |
| Fast EMA | 8 |
| Slow EMA | 89 |
| Take profit | 6.38% |
| Stop loss | 3.95% |
| Slippage | 2 bps per side |
| Position | Long only, one position |
| Session handling | Flat before the close |

Saved US.APP results for the benchmark: 78 trades, 59.0% win rate, 44.01% sum of trade returns, 51.53% compounded return, and 11.10% maximum drawdown.

The 2 bps figure is an execution assumption, not a guarantee. Results depend on the data vendor, fills, commissions, liquidity, and date range.

## Main files

- `scripts/multi_symbol_strategy_lab.py` — deterministic evaluator, MLX
  controller, bounded NVIDIA workers, memory, and runtime telemetry.
- `scripts/continuous_daily_research.py` — repeatable daily research wrapper.
- `research_console.py` — local browser console and API.
- `scripts/download_asx_daily_yfinance.py` — rate-aware daily OHLCV downloader.
- `advanced_research_engine.py`, `causal_formula_engine.py`,
  `custom_indicator_engine.py`, and `ml_strategy_engine.py` — bounded,
  data-gated research components.
- `strategy_57pct.py`, `competition_bot.py`, and `quant_dashboard.py` — older
  research/paper-trading utilities retained for reference; live order placement
  is disabled.

Moomoo OpenD must be running on `127.0.0.1:11111` to fetch fresh candles. Do not commit API keys or credentials; use the macOS Keychain or environment variables locally.

## NVIDIA API models

### Open-ended causal research mode

The interval sweep is intentionally generative rather than limited to the
original CDA parameters. Each continuous cycle searches the cached 1H data
and its causal 2H–6H aggregations with:

- the frozen CDA rule and ordinary parameter mutations;
- expanding-window logistic/MLP candidates;
- a whitelisted compositional formula language (`causal_formula_engine.py`)
  that can combine OHLCV fields, rolling statistics, EMA/SMA/ROC/z-scores,
  comparisons and crossovers; and
- NVIDIA workers that may propose either parameters or formula trees.

This is “endless” in the practical sense: every cycle can generate new,
mutated candidates until the operator stops it. It is not arbitrary code
execution. Formula trees have a fixed operator whitelist and depth limit,
and every return is recomputed by the local fee-inclusive ledger. Features
use only the current completed bar and prior bars; validation and test windows
remain chronologically unseen during selection.

The advanced-family registry is in `advanced_research_engine.py`. It includes
Kalman/state filters, regime models, GARCH variants, extreme-value and
information features, OU/statistical-arbitrage primitives, triple-barrier and
meta-label training, conformal-style uncertainty hooks, symbolic/genetic
formula search, ensemble models, and optional neural families. Copula/PCA,
execution-impact, market-making, and Hawkes-event families are data-gated:
they remain disabled until the required cross-sectional, tick, or execution
data is actually available. Order-book families are intentionally excluded.

The lab does not call NVIDIA directly. It routes bounded research requests
through the local `multi-model-ai-gateway`, while `mlx-sentinel` provides the
local MLX inference boundary and security checks. See those repositories for
Keychain setup, model allowlists, rate limiting, and service operations.

## Research note

The original 2 bps baseline remains the profit benchmark. The research harness is for validation and should not automatically replace the baseline with a lower-return parameter set.

The baseline is immutable. Its locked Git tag is `baseline-2bps-6.38tp`; all exit experiments, including green/yellow/red state models, must use separate files and candidate versions.

The promoted 8% TP candidate tested at +53.86% compounded return with approximately -11.10% maximum drawdown over the full test period. It is preserved separately because its Jan–June split was weaker than the 6.38% baseline.

This is research software, not financial advice or a promise of future performance.

## Local Codan screen-capture tester

This local copy includes a separate tester for the reconstructed ASX:CDA 1-hour
data. It reads the copied SQLite database in `data/` and does not use Moomoo
OpenD or submit orders:

```sh
python3 scripts/codan_screen_capture_tester.py
python3 scripts/codan_screen_capture_tester.py --optimize --trials 500
```

The tester now defaults to one five-hour CDA candle per session. It uses the
six session bars labelled 09:00–14:00, aggregates the first five
(09:00–14:00), and deliberately discards the final 14:00–15:00 hour rather
than carrying it into another session. Use `--bars 1` only when you
explicitly need the original 1-hour comparison.

Reports are written to `reports/`. The default input view is
`stitched_backtest_candles`, which contains exact screen-header readings and
quality-filtered pattern-stitched candles. The complete reconstruction is
available through the `stitched_candles` view in the source SQLite database.
The tester defaults to A$200,000 starting capital and models Moomoo AU ASX
brokerage on every entry and exit as `max(A$3, 0.03% of order value)`.
Signals use completed candles and execute at the next bar open; duplicate
candles, duplicate trades, overlapping trades, and invalid signal/entry/exit
chronology are rejected. Screen-reconstructed candles are estimates and are
for research only.

## ASX daily research data

Daily ASX candles downloaded from Yahoo Finance are kept separately from the
reconstructed screen-capture data:

```sh
python3 scripts/download_asx_daily_yfinance.py
```

The default download covers a liquid 30-symbol ASX research universe and
stores de-duplicated OHLCV rows in `data/asx_daily_yfinance.sqlite3`. Use
`--symbols BHP,CBA,CSL` to request a smaller set. Each run and source ticker
are recorded in SQLite; the downloader does not alter the dashboard database.

## Moomoo paper-competition bot

`competition_bot.py` is retained as an execution boundary, but paper execution
is currently hard-disabled while the tester is being validated.

Start Moomoo OpenD and log in, then identify the US paper account index:

```sh
python3 competition_bot.py --list-accounts
```

Run a signal-only check:

```sh
python3 competition_bot.py AAPL NVDA --acc-index 0
```

The dashboard and CLI reject paper-order startup in the current tester-only
build. No order path is enabled.

## Moomoo Quant Dashboard

`quant_dashboard.py` combines the tester, optimizer, charts, and trade list in
one local dashboard. Paper execution controls are hidden and disabled:

```sh
python3 quant_dashboard.py
open http://127.0.0.1:8780
```

The dashboard fetches `US.APP` candles directly from Moomoo OpenD with
`request_history_kline`, caches them in `quant_dashboard.sqlite3`, and uses
those cached candles for the tester. It stores each run, optimizer result,
trade, and paper execution event in SQLite. The dashboard reports return,
ending equity, maximum drawdown, trades, win rate, profit factor, average
trade, Sharpe approximation, equity curve, monthly returns, optimizer
rankings, and the complete trade list. No paper order placement is enabled in
this build.

To generate the local Quant-style report:

```sh
python3 BBI_5m_Backtest/local_quant_tester.py \\
  --csv /path/to/CDA_daily.csv --symbol CDA --optimize
open local_quant_report/report.html
```

`BBI_5m_Backtest/local_quant_tester.py` is a legacy standalone report tool;
the supported multi-symbol console is `research_console.py` on port 8790.
