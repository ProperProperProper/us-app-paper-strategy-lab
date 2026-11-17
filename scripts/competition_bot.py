#!/usr/bin/env python3
"""Moomoo paper-competition bot for the 10-minute Donchian/EMA baseline.

The bot is paper-only by construction: every order uses TrdEnv.SIMULATE.
Order submission additionally requires --live-paper. Without that flag the
bot prints signals and intended orders but never submits anything.

Strategy:
  - 33 completed 10-minute bars for the Donchian breakout
  - EMA 17 / EMA 26 trend filter
  - long-only, one position per symbol
  - 10.69% take profit or 3.54% stop loss
  - 95% of available cash per entry

Moomoo OpenD must be running on 127.0.0.1:11111 and logged in. This script
does not contain credentials or attempt to unlock a live account.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import math
import signal
import sys
import time
from datetime import time as dt_time
from pathlib import Path
from typing import Any

import pandas as pd
from moomoo import (
    KLType,
    OpenQuoteContext,
    OpenSecTradeContext,
    OrderType,
    RET_OK,
    SubType,
    TrdEnv,
    TrdMarket,
    TrdSide,
)

from quant_storage import save_candles, save_execution_event
from quant_api import BASELINE, audit_api, risk_api, strategy_api
from strategy_57pct import profit_capture_exit


POSITION_FRACTION = 0.95
POLL_SECONDS = 30
MIN_BARS = 240
MAX_CANDLE_LAG_MINUTES = 120
STATE_PATH = Path(__file__).with_name("competition_bot_state.json")
LOG_PATH = Path(__file__).with_name("competition_bot.log")
ROOT = Path(__file__).resolve().parents[1]
STRATEGY_CONFIG_PATHS = (ROOT / "paper_bot_live_strategy.json", ROOT / "config" / "us_app_paper_strategy.json")
STRATEGY_SOURCE = Path(__file__).with_name("strategy_57pct.py")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
    )


def scalar(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def row_value(frame: pd.DataFrame, row: int, names: tuple[str, ...], default: float = 0.0) -> float:
    for name in names:
        if name in frame.columns:
            return scalar(frame.iloc[row][name], default)
    return default


def code(symbol: str) -> str:
    symbol = symbol.upper().strip()
    return symbol if "." in symbol else f"US.{symbol}"


class CompetitionBot:
    def __init__(self, symbols: list[str], acc_index: int, live_paper: bool, interval: int, acc_id: int | None = None) -> None:
        self.symbols = [code(s) for s in symbols]
        self.acc_index = acc_index
        self.acc_id = acc_id
        self.live_paper = live_paper
        self.interval = interval
        self.running = True
        self.last_error: str | None = None
        self.peak_price = 0.0
        self.break_even_armed = False
        self.profit_lock_armed = False
        self.state = self._load_state()
        self.strategy_module = None
        self.strategy_mtime = None
        self.strategy_baseline = dict(BASELINE)
        self.strategy_signal = strategy_api.signal
        self.strategy_profit_capture_exit = profit_capture_exit
        self.strategy_params = dict(BASELINE)
        self._refresh_strategy_code(force=True)
        self.quote = OpenQuoteContext(host="127.0.0.1", port=11111)
        self.quote_subscribed: set[str] = set()
        self.trade = OpenSecTradeContext(
            filter_trdmarket=TrdMarket.US,
            host="127.0.0.1",
            port=11111,
        )

    def _load_strategy_params(self) -> dict[str, Any]:
        for path in STRATEGY_CONFIG_PATHS:
            try:
                payload = json.loads(path.read_text())
                params = payload.get("params", payload)
                if isinstance(params, dict):
                    logging.info("loaded strategy config %s", path)
                    return {**self.strategy_baseline, **params}
            except (OSError, json.JSONDecodeError, TypeError):
                continue
        logging.info("using tracked baseline strategy defaults")
        return dict(self.strategy_baseline)

    def _refresh_strategy_code(self, force: bool = False) -> None:
        """Hot-reload strategy code/config; retain the last good runtime on error."""
        try:
            mtime = STRATEGY_SOURCE.stat().st_mtime_ns
            if not force and mtime == self.strategy_mtime:
                return
            module_name = f"paper_strategy_hot_{mtime}"
            spec = importlib.util.spec_from_file_location(module_name, STRATEGY_SOURCE)
            if spec is None or spec.loader is None:
                raise ImportError("strategy source loader unavailable")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            if not all(hasattr(module, name) for name in ("BASELINE", "strategy_signal", "profit_capture_exit")):
                raise ImportError("strategy source missing required runtime contract")
            self.strategy_module = module
            self.strategy_mtime = mtime
            self.strategy_baseline = dict(module.BASELINE)
            self.strategy_signal = module.strategy_signal
            self.strategy_profit_capture_exit = module.profit_capture_exit
            self.strategy_params = self._load_strategy_params()
            logging.info("hot-swapped strategy code mtime=%s params=%s", mtime, self.strategy_params)
        except Exception as exc:
            logging.exception("strategy hot-swap rejected; retaining last working code: %s", exc)

    def _load_state(self) -> dict[str, Any]:
        if STATE_PATH.exists():
            state = json.loads(STATE_PATH.read_text())
        else:
            state = {"last_bar": {}, "entries": {}}
        state.setdefault("pending", {})
        return state

    def _save_state(self) -> None:
        STATE_PATH.write_text(json.dumps(self.state, indent=2) + "\n")

    def close(self) -> None:
        self.quote.close()
        self.trade.close()

    def _ensure_live_candle_subscription(self, symbol: str) -> None:
        """Enable OpenD's live K-line cache before asking for current bars."""
        if symbol in self.quote_subscribed:
            return
        ret, error = self.quote.subscribe(
            [symbol],
            [SubType.K_10M],
            is_first_push=True,
            subscribe_push=False,
            extended_time=False,
            session="RTH",
        )
        if ret != RET_OK:
            raise RuntimeError(f"live candle subscription failed for {symbol}: {error}")
        self.quote_subscribed.add(symbol)

    @staticmethod
    def _clean_candles(data: pd.DataFrame) -> pd.DataFrame:
        required = {"time_key", "open", "high", "low", "close", "volume"}
        missing = required.difference(data.columns)
        if missing:
            raise RuntimeError(f"candle response missing columns: {sorted(missing)}")
        data = data.copy()
        data["time_key"] = pd.to_datetime(data["time_key"], errors="coerce")
        if data["time_key"].isna().any():
            raise RuntimeError("candle response contains invalid timestamps")
        data = data.drop_duplicates("time_key", keep="last").sort_values("time_key")
        numeric = data[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
        finite = numeric.apply(lambda column: column.map(math.isfinite))
        if numeric.isna().any().any() or not finite.all().all():
            raise RuntimeError("candle response contains non-finite OHLCV values")
        data[["open", "high", "low", "close", "volume"]] = numeric
        malformed = (
            (data["low"] > data[["open", "close", "high"]].min(axis=1))
            | (data["high"] < data[["open", "close", "low"]].max(axis=1))
            | (data["low"] <= 0)
            | (data["high"] <= 0)
        )
        if malformed.any():
            raise RuntimeError("candle response contains malformed OHLC ranges")
        return data

    @staticmethod
    def _stale_during_open(latest: pd.Timestamp) -> tuple[bool, float]:
        """Compare Moomoo's ET candle time with ET, not the computer's local timezone."""
        eastern_latest = latest.tz_localize("America/New_York") if latest.tzinfo is None else latest.tz_convert("America/New_York")
        now = pd.Timestamp.now(tz="America/New_York")
        lag_minutes = max(0.0, (now - eastern_latest).total_seconds() / 60.0)
        in_rth = now.weekday() < 5 and pd.Timestamp("09:30", tz="America/New_York").time() <= now.time() < pd.Timestamp("16:00", tz="America/New_York").time()
        return in_rth and (eastern_latest.date() != now.date() or lag_minutes > MAX_CANDLE_LAG_MINUTES), lag_minutes

    def stop(self, *_: Any) -> None:
        self.running = False

    def account_funds(self) -> float:
        kwargs = {"trd_env": TrdEnv.SIMULATE, "acc_id": self.acc_id} if self.acc_id else {"trd_env": TrdEnv.SIMULATE, "acc_index": self.acc_index}
        ret, data = self.trade.accinfo_query(**kwargs)
        if ret != RET_OK:
            raise RuntimeError(f"account query failed: {data}")
        for field in ("available_funds", "cash", "power", "total_assets"):
            if field in data.columns:
                return scalar(data.iloc[0][field])
        raise RuntimeError(f"no usable cash field in account response: {list(data.columns)}")

    def position(self, symbol: str) -> tuple[float, float]:
        kwargs = {"trd_env": TrdEnv.SIMULATE, "acc_id": self.acc_id} if self.acc_id else {"trd_env": TrdEnv.SIMULATE, "acc_index": self.acc_index}
        ret, data = self.trade.position_list_query(**kwargs)
        if ret != RET_OK:
            raise RuntimeError(f"position query failed: {data}")
        if data.empty or "code" not in data.columns:
            return 0.0, 0.0
        rows = data[data["code"].astype(str) == symbol]
        if rows.empty:
            return 0.0, 0.0
        row = rows.iloc[0]
        qty = scalar(row.get("qty", row.get("position", 0)))
        avg = scalar(row.get("cost_price", row.get("average_cost", 0)))
        return qty, avg

    def market_price(self, symbol: str) -> float:
        ret, data = self.quote.get_market_snapshot([symbol])
        if ret != RET_OK or data.empty:
            raise RuntimeError(f"snapshot failed for {symbol}: {data}")
        return row_value(data, 0, ("last_price", "cur_price"))

    def candles(self, symbol: str) -> pd.DataFrame:
        self._ensure_live_candle_subscription(symbol)
        ret, history, _ = self.quote.request_history_kline(
            symbol,
            ktype=KLType.K_10M,
            max_count=MIN_BARS,
            extended_time=False,
            session="RTH",
        )
        if ret != RET_OK:
            raise RuntimeError(f"candle history query failed for {symbol}: {history}")
        data = self._clean_candles(history)

        # request_history_kline can remain cached.  get_cur_kline is the live
        # subscribed feed; merge it by timestamp so it repairs the cache and
        # preserves only validated, deduplicated bars.
        live_ret, live_data = self.quote.get_cur_kline(symbol, MIN_BARS, KLType.K_10M)
        if live_ret == RET_OK and isinstance(live_data, pd.DataFrame) and not live_data.empty:
            live = self._clean_candles(live_data)
            data = self._clean_candles(pd.concat([data, live], ignore_index=True))
            logging.info("merged live K-line recovery for %s latest=%s", symbol, data["time_key"].max())
        else:
            logging.warning("live K-line recovery unavailable for %s: %s", symbol, live_data)
        save_candles(data.set_index("time_key"), symbol, 10)
        latest = data["time_key"].max()
        stale, lag_minutes = self._stale_during_open(latest)
        if stale:
            raise RuntimeError(f"stale candle data during RTH for {symbol}: latest={latest} lag_minutes={lag_minutes:.1f}")
        return data

    def submit(self, symbol: str, side: Any, qty: int, reason: str) -> None:
        logging.info("%s %s qty=%d mode=%s", reason, symbol, qty, "LIVE_PAPER" if self.live_paper else "DRY_RUN")
        save_execution_event("INTENDED_ORDER", symbol, {"side": str(side), "qty": qty, "reason": reason, "paper": True})
        if not self.live_paper:
            return
        order_kwargs = {"trd_env": TrdEnv.SIMULATE, "acc_id": self.acc_id} if self.acc_id else {"trd_env": TrdEnv.SIMULATE, "acc_index": self.acc_index}
        ret, data = self.trade.place_order(
            price=0,
            qty=qty,
            code=symbol,
            trd_side=side,
            order_type=OrderType.MARKET,
            **order_kwargs,
        )
        if ret != RET_OK:
            save_execution_event("ORDER_ERROR", symbol, {"side": str(side), "qty": qty, "reason": reason, "error": str(data), "paper": True})
            raise RuntimeError(f"paper order failed for {symbol}: {data}")
        logging.info("order accepted: %s", data.to_dict("records"))
        save_execution_event("ORDER_ACCEPTED", symbol, {"side": str(side), "qty": qty, "reason": reason, "response": data.to_dict("records"), "paper": True})

    def tick(self) -> None:
        for symbol in self.symbols:
            try:
                candles = self.candles(symbol)
                signal_data = self.strategy_signal(candles, self.strategy_params)
                if self.state["last_bar"].get(symbol) == signal_data["bar"]:
                    continue
                self._refresh_strategy_code()
                signal_data = self.strategy_signal(candles, self.strategy_params)
                qty, avg = self.position(symbol)
                price = self.market_price(symbol)
                logging.info("%s bar=%s price=%.4f position=%.4f signal=%s trend_exit=%s", symbol, signal_data["bar"], price, qty, signal_data["long_signal"], signal_data["trend_exit"])

                pending = self.state["pending"].get(symbol)
                if pending:
                    filled = (pending == "BUY" and qty > 0) or (pending == "SELL" and qty <= 0)
                    if filled:
                        self.state["pending"].pop(symbol, None)
                    else:
                        self.state["last_bar"][symbol] = signal_data["bar"]
                        self._save_state()
                        continue

                if qty > 0:
                    self.peak_price = max(self.peak_price, price, avg)
                    stop_loss = price <= avg * (1 - float(self.strategy_params["stop"]))
                    take_profit = price >= avg * (1 + float(self.strategy_params["tp"]))
                    indicator_exit = self.strategy_params.get("profit_exit_mode") == "atr_peak_retrace" and self.strategy_profit_capture_exit(price, avg, self.peak_price, float(signal_data.get("atr14", 0.0)), self.strategy_params)
                    session_exit = bool(signal_data["session_exit"])
                    if take_profit or stop_loss or indicator_exit or session_exit or signal_data["yellow_exit"] or signal_data["red_exit"] or signal_data["trend_exit"]:
                        self.submit(symbol, TrdSide.SELL, int(qty), "EXIT")
                        self.state["pending"][symbol] = "SELL"
                        self.peak_price = 0.0
                        self.break_even_armed = False
                        self.profit_lock_armed = False
                    self.state["last_bar"][symbol] = signal_data["bar"]
                    self._save_state()
                    continue

                if signal_data["long_signal"] and signal_data["entry_allowed"]:
                    cash = self.account_funds()
                    decision = risk_api.entry_decision(cash, price, POSITION_FRACTION)
                    audit_api.event("RISK_DECISION", symbol, {**decision.__dict__, "signal": signal_data})
                    if decision.allowed:
                        self.submit(symbol, TrdSide.BUY, decision.quantity, "ENTRY")
                        self.state["pending"][symbol] = "BUY"
                        self.peak_price = price
                        self.break_even_armed = False
                        self.profit_lock_armed = False
                    self.state["last_bar"][symbol] = signal_data["bar"]
                    self._save_state()
                    continue
                # Mark the bar only after all queries and any order submission
                # have completed. A failed cycle can therefore be retried.
                self.state["last_bar"][symbol] = signal_data["bar"]
                self._save_state()
            except Exception as exc:
                self.last_error = repr(exc)
                logging.exception("symbol cycle failed: %s", symbol)
                save_execution_event("CYCLE_ERROR", symbol, {"paper": True, "error": repr(exc)})

    def run(self) -> None:
        logging.info("starting %s symbols=%s account_index=%d", "LIVE_PAPER" if self.live_paper else "DRY_RUN", self.symbols, self.acc_index)
        while self.running:
            self.tick()
            for _ in range(self.interval):
                if not self.running:
                    break
                time.sleep(1)
        logging.info("stopped")


def list_accounts() -> int:
    ctx = OpenSecTradeContext(filter_trdmarket=TrdMarket.US, host="127.0.0.1", port=11111)
    try:
        ret, data = ctx.get_acc_list()
        if ret != RET_OK:
            print(data)
            return 1
        print(data.to_string(index=False))
        return 0
    finally:
        ctx.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbols", nargs="*", help="US symbols, e.g. AAPL NVDA; defaults to config only when supplied")
    parser.add_argument("--acc-index", type=int, default=0, help="SIMULATE US account index when supported")
    parser.add_argument("--acc-id", type=int, help="SIMULATE account ID from local --list-accounts output")
    parser.add_argument("--interval", type=int, default=POLL_SECONDS)
    parser.add_argument("--live-paper", action="store_true", help="Submit orders to the selected Moomoo SIMULATE account; never a live account")
    parser.add_argument("--list-accounts", action="store_true")
    args = parser.parse_args()
    setup_logging()
    if args.list_accounts:
        return list_accounts()
    if not args.symbols:
        parser.error("provide at least one symbol, or use --list-accounts")
    bot = CompetitionBot(args.symbols, args.acc_index, args.live_paper, args.interval, args.acc_id)
    signal.signal(signal.SIGINT, bot.stop)
    signal.signal(signal.SIGTERM, bot.stop)
    try:
        bot.run()
    finally:
        bot.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
