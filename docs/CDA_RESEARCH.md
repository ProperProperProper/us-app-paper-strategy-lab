# Historical CDA research

The CDA workflow is separate from the daily ASX downloader and the current multi-symbol research loop. It uses a reconstructed screen-capture dataset stored locally in SQLite.

```sh
python3 scripts/codan_screen_capture_tester.py
python3 scripts/codan_screen_capture_tester.py --optimize --trials 500
```

The tester uses the `stitched_backtest_candles` view by default, with a complete reconstruction available through `stitched_candles`. It aggregates session bars into the configured five-hour research candle and discards the final partial hour rather than carrying it into another session.

Reconstructed candles are estimates. Results are for research only and should not be treated as market data or a live-trading signal.
