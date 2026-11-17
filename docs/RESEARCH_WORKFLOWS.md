# Research workflows

## US.APP mutation research

```sh
python3 scripts/app_strategy_lab.py --db quant_dashboard.sqlite3 \
  --agents 2 --candidates 100 --providers local,nvidia,antigravity
```

The loop defaults to 90 calendar days and generates bounded proposals, evaluates them on chronological train/validation/test slices, and writes run summaries plus the promoted parameter file locally. It does not provide a persistent learning-memory store.

## Required research protocol

Every strategy investigation follows this order:

1. Keep the entry condition signal-driven and record the exact signal timestamps.
2. Keep buy-and-hold as a benchmark only; never compare it as though it had the same entry policy.
3. Test strategy variants, not only scalar parameters. For profit research this includes target, break-even, profit-lock, trailing, trend-exit, and the `atr_peak_retrace` custom indicator.
4. Use the longest available bounded history that matches the research request; the active lab default is 90 calendar days.
5. Evaluate chronologically, preserve an untouched final test segment, and report trade count and drawdown with every return.
6. Promote a candidate only after it improves the relevant holdout evidence; a high full-window result alone is not sufficient.

Agents may propose hypotheses, but the local deterministic evaluator is the only authority for fills, returns, drawdown, trade count, and promotion.
Agent prompts include deterministic data evidence for the active window: exact timestamps, candle and session counts, endpoint prices, raw close-to-close movement, and baseline train/validation/test metrics. Agents must ground challenges in that evidence and may not invent trades or performance.

## Agent challenge loop

Agents are intentionally given opposing responsibilities. An explorer proposes a falsifiable idea; a critic tries to break it through benchmark mismatch, leakage, regime dependence, and overfitting; a risk reviewer tests drawdown and causal execution; and the coordinator rejects unsupported claims before local evaluation. Each agent must state the failure mode and the evidence that would disprove its proposal. A candidate is research output only after the deterministic evaluator checks it; a candidate is promotion material only after chronological validation and final-test evidence.

## Reports and artifacts

Generated reports and run artifacts are local-only. They must not be committed because they may contain large datasets, runtime state, local paths, or account-related information.
