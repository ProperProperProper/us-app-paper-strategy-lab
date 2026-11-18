# Research workflows

## US.APP mutation research

```sh
python3 scripts/app_strategy_lab.py --db quant_dashboard.sqlite3 \
  --agents 2 --candidates 100 --providers local,nvidia,antigravity
```

The loop loads all available candles (or an explicitly requested timestamp window) and generates bounded proposals. It selects using the first 21 complete sessions, then evaluates continuously from session 22 through the latest candle and writes run summaries plus the promoted parameter file locally. The SQLite agent ledger persists proposals, controller configuration, evaluation evidence, promotion decisions, and MLX learning records; it is an evidence ledger, not automatic adapter training.

After 21 complete sessions are available, the lab selects once and tests every subsequent candle continuously to the data end. This avoids hidden chunks and per-session reselection while still keeping the entire test period unseen at selection time. It is a fixed-boundary trade-off, not a guarantee of future performance.

## Required research protocol

Every strategy investigation follows this order:

1. Keep the entry condition signal-driven and record the exact signal timestamps.
2. Keep buy-and-hold as a benchmark only; never compare it as though it had the same entry policy.
3. Test strategy variants, not only scalar parameters. For profit research this includes target, break-even, profit-lock, trailing, trend-exit, and the `atr_peak_retrace` custom indicator.
4. Use all available history in the fixed candle snapshot unless the research request specifies explicit start/end timestamps.
5. Evaluate chronologically with the hard continuous blind protocol: train on all candles in the first 21 complete sessions, then test every candle from session 22 through the latest candle without reselection or chunking. Report trade count and drawdown with every return.
6. Compare every candidate interval against a freshly rerun 10m baseline. Promote only when the selected interval's blind replay improves that baseline; a high full-window result alone is not sufficient.

Agents may propose hypotheses, but the local deterministic evaluator is the only authority for fills, returns, drawdown, trade count, and promotion.
Agent prompts include deterministic data evidence for the active window: exact timestamps, candle and session counts, endpoint prices, raw close-to-close movement, and baseline training/final-test metrics. Agents must ground challenges in that evidence and may not invent trades or performance.

## Agent challenge loop

Agents are intentionally given opposing responsibilities. An explorer proposes a falsifiable idea; a critic tries to break it through benchmark mismatch, leakage, regime dependence, and overfitting; a risk reviewer tests drawdown and causal execution; and the coordinator rejects unsupported claims before local evaluation. Each agent must state the failure mode and the evidence that would disprove its proposal. A candidate is research output only after the deterministic evaluator checks it; a candidate is promotion material only after the final unseen test and blind session replay.

## Reports and artifacts

Generated reports and run artifacts are local-only. They must not be committed because they may contain large datasets, runtime state, local paths, or account-related information.
