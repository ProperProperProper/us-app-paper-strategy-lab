# CDA 1-hour strategy snapshot

Status: immutable research snapshot  
Captured from run: `strategy_lab_runs/20261114-143715/round-011.json`  
Captured: 2026-11-14  
Symbol: `CDA` (ASX)  
Base interval: 1 hour  
Source view: `stitched_candles` from the local screen-capture reconstruction  
Source rows: 1,706  
Source range: 2025-11-10 12:00 to 2026-10-16 09:00  

## Leader result

This is the best candidate recorded at the time of the snapshot. It is a
full-history research result, not an out-of-sample validation claim.

| Metric | Result |
|---|---:|
| Starting capital | A$200,000.00 |
| Ending equity | A$280,277.23 |
| Total return | 40.139% |
| Maximum drawdown | -8.068% |
| Trades | 24 |
| Wins | 12 |
| Win rate | 50.00% |
| Profit factor | 2.820 |
| Average trade | 1.560% |
| Approx. Sharpe | 0.456 |
| Selection score | 37.3152 |

The evaluator includes 2 bps slippage per side and Moomoo AU ASX brokerage of
`max(A$3, 0.03% of order value)` on every entry and exit. It compounds the
net result and rejects duplicate, overlapping, or chronologically invalid
trades.

## Exact parameters

```text
lookback             = 8 bars
fast EMA             = 29 bars
slow EMA             = 88 bars
take profit          = 36.54%
initial stop         = 21.20%
break-even trigger   = 1.00%
break-even lock      = 0.85%
profit-lock trigger  = 19.35%
profit-lock amount   = 0.24%
trailing trigger     = 3.00%
trailing distance    = 2.04%
```

## Entry rule

At the close of a completed 1-hour candle:

1. Calculate the highest high of the preceding eight completed candles.
2. Require the close to break above that prior high.
3. Require EMA(29) to be above EMA(88).
4. Require the causal downtrend gate not to be active.
5. Enter at the next eligible candle open, with 95% of available cash.

The downtrend gate blocks entries when the slow EMA drift, log-price slope,
recent-peak distance, or long regime EMA indicate a sufficiently broad decline.
All inputs are calculated only from completed candles.

## Exit rule

While long, the strategy checks the completed candle and executes at the next
candle open:

- Take profit when price reaches the 36.54% target.
- Use the 21.20% initial stop.
- Once price is 1% above entry, raise the floor to 0.85% above entry.
- Once price reaches 19.35% above entry, lock at least 0.24% above entry.
- Once price reaches 3% above entry, trail the peak by 2.04%.
- Exit on the yellow trend condition when close falls below EMA(29) but
  remains above EMA(88).
- Exit on the red condition when close falls below EMA(88).
- Do not open a new overlapping position.

Observed exit reasons in the snapshot: 16 `STOP` exits and 8
`YELLOW_EXIT` exits.

## Important limitations

- The candles are reconstructed from screen captures and include estimated
  pattern-stitched observations; they are not exchange-native historical data.
- This leader was selected on the complete available CDA history. It has not
  been independently validated on unseen data.
- Several nearby parameter variants produced the same result, so the exact
  parameter values should not be treated as uniquely identified.
- The snapshot is preserved for comparison only; future research must not
  overwrite or silently improve it.
