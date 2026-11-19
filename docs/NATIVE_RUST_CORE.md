# Native Rust core

The project keeps provider integrations and orchestration in native ARM64
Python because Moomoo, MLX, Antigravity, NVIDIA gateway access, Pandas, and
the existing paper-bot interfaces are Python-first.

The deterministic candle hot path now has a native Rust implementation:

- OHLCV validation and monotonic timestamp checks;
- complete-session 10m-to-10m/20m/30m/40m/50m/60m/70m aggregation; and
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
research comparisons.
