"""Provider-agnostic market-data interface.

Add a new source (Polygon, Finnhub, Twelve Data, ...) by subclassing
``DataProvider`` and implementing ``fetch_ohlcv`` + ``validate_ticker``. Nothing
else in the app changes — the repository, cache, analysis, and UI all speak this
one interface and the canonical OHLCV shape below.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

#: Canonical OHLCV columns every provider must return (lowercase, float).
STANDARD_COLUMNS = ["open", "high", "low", "close", "volume"]


class DataProviderError(Exception):
    """Base class for any data-layer failure surfaced to the UI."""


class InvalidTickerError(DataProviderError):
    """Symbol does not exist / returns no data."""


class NetworkError(DataProviderError):
    """Upstream source unreachable or errored out."""


class DataProvider(ABC):
    #: Short identifier stored alongside cached rows (e.g. "yfinance").
    name: str = "abstract"

    @abstractmethod
    def fetch_ohlcv(self, ticker: str, period: str, interval: str, intraday: bool) -> pd.DataFrame:
        """Return OHLCV bars for ``ticker``.

        Contract the rest of the app relies on:
          * index: tz-NAIVE ``pandas.DatetimeIndex`` whose instants are UTC,
            sorted ascending and unique. Intraday bars keep time-of-day; daily/
            weekly bars are normalized to midnight of the trading date.
          * columns: exactly ``STANDARD_COLUMNS`` (lowercase), float dtype.
          * ``period``/``interval`` come from the normalized set in
            ``config.TIMEFRAMES``.

        Raise ``InvalidTickerError`` for unknown symbols and ``NetworkError`` for
        upstream failures so the repository/UI can show a friendly message.
        """

    @abstractmethod
    def validate_ticker(self, ticker: str) -> bool:
        """Cheap existence check. Must not raise for a merely-unknown symbol."""
