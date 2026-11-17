# Strategy and evaluation

## Baseline

The benchmark is a completed-candle, next-open, long-only breakout/trend strategy. Its tested configuration is maintained separately from experimental candidates and should not be overwritten by research output.

The historical 2 bps benchmark used:

| Setting | Value |
|---|---:|
| Donchian lookback | 45 candles |
| Fast EMA | 8 |
| Slow EMA | 89 |
| Take profit | 6.38% |
| Stop loss | 3.95% |
| Slippage | 2 bps per side |
| Position | Long only, one position |
| Session handling | Flat before close |

Historical results are evidence from a specific dataset and execution model, not a performance promise.

## Evaluation rules

- Signals use completed bars only.
- Entries occur at the next bar open.
- Parameters are selected only from prior data.
- Validation and test windows remain chronologically unseen during selection.
- Fees, slippage, position limits, duplicate trades, chronology, and drawdown are checked locally.
- A candidate cannot replace the baseline merely because it has a higher in-sample score.

## Candidate types

Workers may propose parameter mutations, bounded indicator combinations, ML candidates, or whitelisted formula trees. Formula trees have fixed operators and depth limits; arbitrary generated code is not executed.
