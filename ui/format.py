"""Helpers that shape pandas data into lightweight-charts JSON payloads."""
from __future__ import annotations

import math

import pandas as pd


def index_to_times(idx: pd.DatetimeIndex, intraday: bool):
    """lightweight-charts time axis values.

    Intraday -> UTC epoch seconds (numeric ``UTCTimestamp``).
    Daily/weekly -> 'YYYY-MM-DD' business-day strings.
    """
    epoch = idx.to_numpy(dtype="datetime64[s]").astype("int64")
    if intraday:
        return [int(e) for e in epoch]
    return [pd.Timestamp(int(e), unit="s").strftime("%Y-%m-%d") for e in epoch]


def _finite(v):
    """JSON/charts can't carry NaN/inf; represent as None so points are skipped."""
    if v is None:
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def candles(df: pd.DataFrame, intraday: bool):
    t = index_to_times(df.index, intraday)
    o, h, l, c = (df["open"].tolist(), df["high"].tolist(),
                  df["low"].tolist(), df["close"].tolist())
    return [{"time": t[i], "open": o[i], "high": h[i], "low": l[i], "close": c[i]}
            for i in range(len(df))]


def volume(df: pd.DataFrame, intraday: bool,
           up="rgba(38,166,154,0.45)", down="rgba(239,83,80,0.45)"):
    t = index_to_times(df.index, intraday)
    o, c, v = df["open"].tolist(), df["close"].tolist(), df["volume"].tolist()
    return [{"time": t[i], "value": v[i], "color": (up if c[i] >= o[i] else down)}
            for i in range(len(df))]


def line_series(idx: pd.DatetimeIndex, series, intraday: bool):
    """[{time, value}] with NaN points dropped (renders as line breaks)."""
    t = index_to_times(idx, intraday)
    vals = list(series)
    out = []
    for i in range(len(vals)):
        v = _finite(vals[i])
        if v is not None:
            out.append({"time": t[i], "value": v})
    return out


def hist_series(idx: pd.DatetimeIndex, series, intraday: bool,
                up="#26a69a", down="#ef5350"):
    """[{time, value, color}] for a signed histogram (e.g. MACD), NaNs dropped."""
    t = index_to_times(idx, intraday)
    vals = list(series)
    out = []
    for i in range(len(vals)):
        v = _finite(vals[i])
        if v is not None:
            out.append({"time": t[i], "value": v, "color": up if v >= 0 else down})
    return out
