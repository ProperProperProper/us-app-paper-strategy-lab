# Strategy and evaluation

## Baseline

The current US.APP benchmark is a long-only breakout/trend strategy evaluated on completed candles. The current runner applies slippage to the candle-close execution price; it does not model next-candle-open fills. Its tested configuration is maintained separately from experimental candidates and should not be overwritten by research output.

The historical 2 bps benchmark used:

| Setting | Value |
|---|---:|
| Donchian lookback | 33 candles |
| Fast EMA | 17 |
| Slow EMA | 26 |
| Take profit | 10.69% |
| Stop loss | 3.54% |
| Slippage | 2 bps per side |
| Position | Long only, one position |
| Session handling | No forced session flattening in the mutation runner; final open positions are marked to market |

Historical results are evidence from a specific dataset and execution model, not a performance promise.

## Evaluation rules

- Signals use completed bars only.
- Entries and exits are simulated at the completed candle close with configured slippage.
- Parameters are selected on the first 60% of the loaded candle window.
- Validation uses the next 20%; the final test uses the last 20%.
- The current mutation runner does not perform session-by-session re-selection.
- Slippage, position limits, duplicate trades, chronology, and drawdown are checked locally. The generic evaluator supports fee models, but the current mutation runner passes zero commission and no fee model.
- A candidate cannot replace the baseline merely because it has a higher in-sample score.

## Candidate types

The current US.APP runner proposes bounded parameter mutations. The formula and ML engines remain reusable components, but are not automatically invoked by the US.APP runner. Arbitrary generated code is not executed.
