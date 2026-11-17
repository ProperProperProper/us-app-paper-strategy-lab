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

## Reports and artifacts

Generated reports and run artifacts are local-only. They must not be committed because they may contain large datasets, runtime state, local paths, or account-related information.
