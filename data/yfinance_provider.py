"""yfinance-backed DataProvider — the default source (no API key required)."""
from __future__ import annotations

import logging

import yfinance as yf

from .provider import (DataProvider, InvalidTickerError, NetworkError,
                       STANDARD_COLUMNS)

# yfinance is chatty on bad symbols; quiet it so our UI owns all error messaging.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)


class YFinanceProvider(DataProvider):
    name = "yfinance"

    def fetch_ohlcv(self, ticker, period, interval, intraday):
        try:
            df = yf.Ticker(ticker).history(
                period=period,
                interval=interval,
                auto_adjust=True,   # split/dividend-adjusted OHLC: consistent for charts AND backtests
                actions=False,
            )
        except Exception as e:  # any network/parse failure from yfinance
            raise NetworkError(f"Could not reach the data source: {e}") from e

        if df is None or df.empty:
            raise InvalidTickerError(
                f"No data for '{ticker}'. Check the symbol (e.g. AAPL, MSFT, BTC-USD).")

        df = df.rename(columns=str.lower)
        missing = [c for c in STANDARD_COLUMNS if c not in df.columns]
        if missing:
            raise InvalidTickerError(f"Data for '{ticker}' was incomplete (missing {missing}).")

        df = df[STANDARD_COLUMNS].dropna()
        df = df[~df.index.duplicated(keep="last")].sort_index()
        if df.empty:
            raise InvalidTickerError(f"No usable bars for '{ticker}'.")

        # Normalize the index to tz-naive UTC per the provider contract.
        if df.index.tz is not None:
            if intraday:
                df.index = df.index.tz_convert("UTC").tz_localize(None)
            else:  # daily/weekly: keep the calendar trading date
                df.index = df.index.tz_localize(None).normalize()
        elif not intraday:
            df.index = df.index.normalize()
        df.index.name = "ts"
        return df

    def validate_ticker(self, ticker):
        try:
            probe = yf.Ticker(ticker).history(
                period="5d", interval="1d", auto_adjust=True, actions=False)
            return probe is not None and not probe.empty
        except Exception:
            return False
