"""Application configuration: timeframes, cache staleness, paths, disclaimers.

Single source of truth for tunable behavior. Importable as `config` from the
project root (where app.py lives).
"""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "StockDashboard"
APP_TITLE = "Stock Analysis & Backtesting Dashboard (Educational)"

# --- Timeframes -------------------------------------------------------------
# Each timeframe is a *lookback window* (`period`) paired with a bar size
# (`interval`). These tokens are a normalized vocabulary the DataProvider layer
# maps onto its own API (see data/provider.py). yfinance accepts them directly;
# other providers translate `period` -> start/end.
TIMEFRAMES = {
    "1D": {"period": "1d",  "interval": "5m",  "intraday": True,  "label": "1 Day"},
    "1W": {"period": "5d",  "interval": "30m", "intraday": True,  "label": "1 Week"},
    "1M": {"period": "1mo", "interval": "1d",  "intraday": False, "label": "1 Month"},
    "6M": {"period": "6mo", "interval": "1d",  "intraday": False, "label": "6 Months"},
    "1Y": {"period": "1y",  "interval": "1d",  "intraday": False, "label": "1 Year"},
    "5Y": {"period": "5y",  "interval": "1wk", "intraday": False, "label": "5 Years"},
}
DEFAULT_TICKER = "AAPL"
DEFAULT_TIMEFRAME = "6M"

# Summary stats (52-week range, volatility, average volume) are always computed
# from ~1 year of daily bars, independent of the chart's selected timeframe.
SUMMARY_TIMEFRAME = "1Y"

# --- Cache staleness --------------------------------------------------------
# How long cached bars stay "fresh". Past this the repository attempts a refresh;
# if the network fails it serves cache but flags it stale (never silently).
STALENESS_SECONDS = {
    "1D": 5 * 60,
    "1W": 15 * 60,
    "1M": 12 * 60 * 60,
    "6M": 24 * 60 * 60,
    "1Y": 24 * 60 * 60,
    "5Y": 7 * 24 * 60 * 60,
}
DEFAULT_STALENESS_SECONDS = 24 * 60 * 60

# --- Indicator parameters ---------------------------------------------------
# Lengths/periods for the overlays and oscillators. Editable here; the UI shows
# these values in the toggle labels (e.g. "SMA 50").
INDICATORS = {
    "sma_length": 50,
    "ema_length": 20,
    "bb_length": 20,
    "bb_std": 2.0,
    "rsi_length": 14,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
}

# --- Backtest defaults ------------------------------------------------------
# Costs are PERCENTAGES (0.1 == 0.1%). commission is charged per trade (buy and
# sell); slippage is modeled as a constant bid-ask spread (see analysis/backtest.py).
BACKTEST_DEFAULTS = {
    "cash": 10000.0,
    "commission_pct": 0.1,
    "slippage_pct": 0.05,
}

# --- Paths ------------------------------------------------------------------
def _data_dir() -> Path:
    """Per-user data dir (works for both source runs and a PyInstaller exe)."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d

DATA_DIR = _data_dir()
CACHE_DB = DATA_DIR / "market_cache.db"

# --- Disclaimers (surfaced verbatim in the UI) ------------------------------
DISCLAIMER_SHORT = "Educational analysis tool — not financial advice."
DISCLAIMER_LONG = (
    "This application is provided for educational and informational purposes only. "
    "Nothing here is financial, investment, or trading advice. Technical indicators "
    "and backtests describe historical, hypothetical behavior only. Past performance "
    "does not indicate future results, and no feature here predicts future prices."
)
BACKTEST_DISCLAIMER = (
    "Backtest results are historical and descriptive only — hypothetical performance "
    "on past data, net of assumed costs. Past performance does not indicate future results."
)
