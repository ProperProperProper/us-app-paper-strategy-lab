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
- After the first 21 complete sessions, parameters are selected using only the immediately preceding 21 sessions.
- Session 22 onward is one continuous unseen out-of-sample replay through the latest candle. The training boundary does not advance and the strategy is not reselected during the test.
- This continuous replay prevents hidden chunks and per-session reselection; it does not guarantee the best future strategy.
- Blind replay re-selects from prior-session hypotheses before every session, then evaluates exactly that unseen session. There is no separate fixed validation slice or chunked test.
- Slippage, position limits, duplicate trades, chronology, and drawdown are checked locally. The generic evaluator supports fee models, but the current mutation runner passes zero commission and no fee model.
- A candidate cannot replace the baseline merely because it has a higher in-sample score. Promotion uses continuous blind replay against a fresh baseline replay: it requires higher aggregate return, at least three replay trades, and no more than one percentage point of additional replay drawdown.
- Before every rejection, the runner freshly re-tests the unchanged baseline on the same final-test slice and full current window, and stores those metrics alongside the candidate decision.

## Candidate types

The current US.APP runner proposes bounded parameter and strategy-variant mutations. In addition to entry and risk parameters, agents explicitly investigate profit-capture exits: take-profit distance, break-even protection, profit locks, trailing stops, and the exit rule (`fast_or_slow`, `slow_break`, or `trend_cross`). These variants are evaluated on rolling training/replay sessions; they do not replace the baseline automatically. The formula and ML engines remain reusable components, but are not automatically invoked by the US.APP runner. Arbitrary generated code is not executed.

The current research question is whether a profit-capture exit can retain more of a large trend than the baseline's earlier exit rules while protecting accrued gains and avoiding materially higher drawdown. The mutation lab no longer applies a hidden calendar-day lookback; it uses all available deduplicated candles unless an explicit `--start` and/or `--end` is supplied. This is a hypothesis under investigation, not an established exit recommendation. Buy-and-hold has only one trade over a window and is therefore a benchmark, not strong evidence of a safe exit policy.

Every mutation round deterministically evaluates a fixed set of profit-exit hypotheses, including wider targets paired with break-even/profit-lock/trailing protection and slower exit rules. Proposal agents are instructed to consider the same profit-capture question, while the local evaluator remains the sole source of performance results.

The `atr_peak_retrace` custom indicator is price/volatility based rather than time based. After a position reaches its profit-arm threshold, it exits when price falls below the strongest of: the locked-in return floor, the peak less an ATR multiple, or the configured minimum peak retracement. It has no elapsed-time or fixed-holding-period condition and can be evaluated on any candle interval that supplies OHLC data.
