"""Optional native Rust bridge for validated candle operations."""
from __future__ import annotations

import ctypes
from pathlib import Path

import numpy as np
import pandas as pd


class _Candle(ctypes.Structure):
    _fields_ = [
        ("time_ns", ctypes.c_int64),
        ("open", ctypes.c_double),
        ("high", ctypes.c_double),
        ("low", ctypes.c_double),
        ("close", ctypes.c_double),
        ("volume", ctypes.c_double),
    ]


class _Features(ctypes.Structure):
    _fields_ = [(name, ctypes.c_double) for name in (
        "ema_fast", "ema_slow", "prior_high", "atr14", "regime_ema",
        "slow_drift", "regime_drift", "log_slope", "recent_peak",
    )]


def _library() -> ctypes.CDLL | None:
    root = Path(__file__).resolve().parents[1] / "native" / "strategy_core" / "target"
    candidates = [root / "release" / "libstrategy_core.dylib", root / "debug" / "libstrategy_core.dylib"]
    for path in candidates:
        if path.exists():
            lib = ctypes.CDLL(str(path))
            lib.strategy_validate.argtypes = [ctypes.POINTER(_Candle), ctypes.c_size_t]
            lib.strategy_validate.restype = ctypes.c_int32
            lib.strategy_aggregate.argtypes = [ctypes.POINTER(_Candle), ctypes.c_size_t, ctypes.c_int32, ctypes.POINTER(_Candle), ctypes.c_size_t]
            lib.strategy_aggregate.restype = ctypes.c_ssize_t
            lib.strategy_features.argtypes = [ctypes.POINTER(_Candle), ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t, ctypes.POINTER(_Features), ctypes.c_size_t]
            lib.strategy_features.restype = ctypes.c_ssize_t
            lib.strategy_profit_capture_exit.argtypes = [ctypes.c_double] * 8
            lib.strategy_profit_capture_exit.restype = ctypes.c_int32
            return lib
    return None


def available() -> bool:
    return _library() is not None


def _rows(frame: pd.DataFrame) -> ctypes.Array:
    values = np.empty(len(frame), dtype=_Candle)
    values["time_ns"] = frame.index.view("int64")
    for name in ("open", "high", "low", "close", "volume"):
        values[name] = pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=np.float64)
    return values


def validate(frame: pd.DataFrame) -> bool:
    lib = _library()
    if lib is None:
        return False
    rows = _rows(frame)
    return bool(lib.strategy_validate(rows.ctypes.data_as(ctypes.POINTER(_Candle)), len(rows)))


def aggregate(frame: pd.DataFrame, interval_minutes: int) -> pd.DataFrame:
    lib = _library()
    if lib is None:
        raise RuntimeError("native Rust strategy core is not built")
    rows = _rows(frame)
    output = np.empty(len(rows), dtype=_Candle)
    count = lib.strategy_aggregate(
        rows.ctypes.data_as(ctypes.POINTER(_Candle)), len(rows), int(interval_minutes),
        output.ctypes.data_as(ctypes.POINTER(_Candle)), len(output),
    )
    if count < 0:
        raise ValueError(f"native candle operation failed with code {count}")
    count = int(count)
    result = pd.DataFrame({name: output[name][:count] for name in ("open", "high", "low", "close", "volume")})
    result.index = pd.to_datetime(output["time_ns"][:count], unit="ns")
    result.index.name = "time_key"
    return result


def features(frame: pd.DataFrame, fast: int, slow: int, lookback: int,
             regime_span: int, slope_window: int, slope_lag: int) -> pd.DataFrame:
    lib = _library()
    if lib is None:
        raise RuntimeError("native Rust strategy core is not built")
    rows = _rows(frame)
    output = np.empty(len(rows), dtype=_Features)
    count = lib.strategy_features(
        rows.ctypes.data_as(ctypes.POINTER(_Candle)), len(rows), int(fast), int(slow),
        int(lookback), int(regime_span), int(slope_window), int(slope_lag),
        output.ctypes.data_as(ctypes.POINTER(_Features)), len(output),
    )
    if count < 0:
        raise ValueError(f"native feature operation failed with code {count}")
    return pd.DataFrame({name: output[name][:int(count)] for name in output.dtype.names}, index=frame.index)


def profit_capture_exit(price: float, entry: float, peak: float, atr: float,
                        arm_return: float, lock_return: float,
                        atr_multiple: float, min_retrace: float) -> bool:
    lib = _library()
    if lib is None:
        raise RuntimeError("native Rust strategy core is not built")
    return bool(lib.strategy_profit_capture_exit(
        float(price), float(entry), float(peak), float(atr), float(arm_return),
        float(lock_return), float(atr_multiple), float(min_retrace),
    ))
