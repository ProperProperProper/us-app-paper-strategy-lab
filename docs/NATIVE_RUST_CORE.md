# Native Rust core

The project keeps provider integrations and orchestration in native ARM64
Python because Moomoo, MLX, Antigravity, NVIDIA gateway access, Pandas, and
the existing paper-bot interfaces are Python-first.

The deterministic candle hot path now has a native Rust implementation:

- OHLCV validation and monotonic timestamp checks;
- complete-session 10m-to-10m/20m/30m/40m/50m/60m/70m aggregation; and
- causal strategy indicators: fast/slow/regime EMA, prior breakout high,
  ATR(14), EMA drifts, log-price regression slope, and prior recent peak; and
- zero-copy array exchange across the Python/Rust boundary during each call.

Build it on Apple Silicon with:

```sh
cargo build --release --manifest-path native/strategy_core/Cargo.toml
python3 -c 'from scripts.native_core import available; print(available())'
```

`strategy_57pct.py` uses the Rust implementation automatically when the
compiled library exists and retains the deterministic Python implementation as
a portability fallback. The strategy equations, blind replay, agent loop,
SQLite orchestration, Moomoo access, and SIMULATE-only paper execution remain
Python. Rust output must match the Python fallback before it is relied upon for
research comparisons. Parity is checked against the Python implementation on
the locally cached US.APP candles before promotion; the current verified parity
set contains 8,625 candles and all nine native indicator columns.

The default supervisor allocation is five lab agents on this ten-core Apple
Silicon machine, leaving approximately half the CPU available for the paper
bot, model providers, and other applications. Each round remains bounded to
one candidate per agent.

Deterministic mutation candidates run in separate Python worker processes, not
threads, so CPU-bound evaluation is not serialized by Python's GIL. Provider
calls and promotion remain in the coordinator process. The evaluator is capped
at four worker processes plus one coordinator, and NumPy/BLAS thread pools are
forced to one thread each, so the project is hard-capped at approximately half
of this machine's ten CPU cores.
