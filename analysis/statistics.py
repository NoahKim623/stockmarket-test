"""Summary statistics, computed from ~1 year of daily bars.

Kept separate from the chart's timeframe so the 52-week range and volatility are
meaningful no matter what the user is looking at.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Trading days per year — the standard annualization constant for daily data.
TRADING_DAYS = 252


def annualized_volatility(close: pd.Series, periods: int = TRADING_DAYS) -> float:
    """Annualized historical volatility, as a percent.

    Volatility here = standard deviation of daily LOG returns, scaled to a year
    by sqrt(trading days). Log returns r_t = ln(P_t / P_{t-1}); we use the sample
    std (ddof=1). This is *realized* (backward-looking) volatility, not a forecast.
    """
    logret = np.log(close / close.shift(1)).dropna()
    if len(logret) < 2:
        return float("nan")
    return float(logret.std(ddof=1) * np.sqrt(periods) * 100.0)


def summarize(df_daily: pd.DataFrame) -> dict:
    """Return the summary-panel stats from a daily OHLCV DataFrame."""
    close, high, low, vol = (df_daily["close"], df_daily["high"],
                             df_daily["low"], df_daily["volume"])

    last = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) >= 2 else last
    change_abs = last - prev
    change_pct = (change_abs / prev * 100.0) if prev else 0.0

    window = df_daily.iloc[-TRADING_DAYS:]  # up to last 252 trading days
    return {
        "current_price": last,
        "daily_change_abs": change_abs,
        "daily_change_pct": change_pct,
        "high_52w": float(window["high"].max()),
        "low_52w": float(window["low"].min()),
        "hist_vol_annual_pct": annualized_volatility(close),
        "avg_volume_30d": float(vol.iloc[-30:].mean()) if len(vol) else float("nan"),
    }
