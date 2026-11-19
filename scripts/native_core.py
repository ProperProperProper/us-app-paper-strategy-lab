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
