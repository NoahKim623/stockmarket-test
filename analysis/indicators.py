"""Technical indicators in pure pandas.

Formulas match the conventional definitions used by pandas-ta / TradingView so
results are directly comparable. (pandas-ta can't be installed on Python 3.14 —
see README — so these provide the same math with no extra dependency.)

Every function takes/returns a pandas Series aligned to the input index; values
that are not yet defined (warm-up period) are NaN and the UI simply skips them.
"""
from __future__ import annotations

import pandas as pd

import config


def sma(close: pd.Series, length: int) -> pd.Series:
    """Simple moving average: arithmetic mean of the last `length` closes."""
    return close.rolling(window=length, min_periods=length).mean()


def ema(close: pd.Series, length: int) -> pd.Series:
    """Exponential moving average (recursive form, adjust=False).

    EMA_t = a*close_t + (1-a)*EMA_{t-1}, with a = 2/(length+1). adjust=False is the
    standard recursive EMA used by TradingView/pandas-ta (vs. the de-biased form).
    """
    return close.ewm(span=length, adjust=False, min_periods=length).mean()


def bollinger(close: pd.Series, length: int = 20, std: float = 2.0) -> dict:
    """Bollinger Bands: an SMA midline ± `std` standard deviations.

    Uses population std (ddof=0) to match pandas-ta's default.
    """
    mid = close.rolling(window=length, min_periods=length).mean()
    sd = close.rolling(window=length, min_periods=length).std(ddof=0)
    return {"upper": mid + std * sd, "middle": mid, "lower": mid - std * sd}


def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """Wilder's Relative Strength Index.

    Average gains/losses are smoothed with Wilder's RMA (an EMA with
    alpha = 1/length) — the canonical RSI. RSI = 100 - 100/(1 + RS),
    RS = avg_gain / avg_loss. When there are no losses, RS -> inf and RSI -> 100.
    """
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """MACD line = EMA(fast) - EMA(slow); signal = EMA(signal) of the MACD line;
    histogram = MACD - signal."""
    ema_fast = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
    ema_slow = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return {"macd": macd_line, "signal": signal_line, "hist": macd_line - signal_line}


def compute_all(df: pd.DataFrame, settings: dict | None = None) -> dict:
    """Compute every indicator from an OHLCV df. Returns a dict of pandas Series."""
    s = {**config.INDICATORS, **(settings or {})}
    close = df["close"]
    bb = bollinger(close, s["bb_length"], s["bb_std"])
    m = macd(close, s["macd_fast"], s["macd_slow"], s["macd_signal"])
    return {
        "sma": sma(close, s["sma_length"]),
        "ema": ema(close, s["ema_length"]),
        "bb_upper": bb["upper"], "bb_middle": bb["middle"], "bb_lower": bb["lower"],
        "rsi": rsi(close, s["rsi_length"]),
        "macd": m["macd"], "macd_signal": m["signal"], "macd_hist": m["hist"],
    }
