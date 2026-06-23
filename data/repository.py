"""Repository: provider + cache + staleness policy.

The single data entry point for the rest of the app. It decides when to serve
cache vs. hit the network and ALWAYS reports freshness, so the UI can show an
"as of" timestamp and a stale badge — stale data is never served silently.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

import config
from .cache import CacheStore
from .provider import DataProvider, DataProviderError


@dataclass
class OHLCVResult:
    df: pd.DataFrame
    ticker: str
    timeframe: str
    fetched_at: int           # UTC epoch seconds
    is_stale: bool
    source: str               # "network" | "cache"
    provider: str

    def meta(self) -> dict:
        # Convert the fetch time to the user's local zone for display.
        dt = datetime.fromtimestamp(self.fetched_at, tz=timezone.utc).astimezone()
        return {
            "ticker": self.ticker,
            "timeframe": self.timeframe,
            "fetched_at": self.fetched_at,
            "fetched_at_iso": dt.isoformat(timespec="seconds"),
            "fetched_at_human": dt.strftime("%Y-%m-%d %H:%M %Z"),
            "is_stale": self.is_stale,
            "source": self.source,
            "provider": self.provider,
            "bars": int(len(self.df)),
        }


class MarketDataRepository:
    def __init__(self, provider: DataProvider, cache: CacheStore):
        self._provider = provider
        self._cache = cache

    def _staleness(self, timeframe: str) -> int:
        return config.STALENESS_SECONDS.get(timeframe, config.DEFAULT_STALENESS_SECONDS)

    def get_ohlcv(self, ticker: str, timeframe: str, force_refresh: bool = False) -> OHLCVResult:
        spec = config.TIMEFRAMES[timeframe]
        now = int(time.time())
        cached_df, fetched_at = self._cache.get_bars(ticker, timeframe)
        fresh_enough = (
            cached_df is not None and fetched_at is not None
            and (now - fetched_at) <= self._staleness(timeframe)
        )

        # 1) Serve fresh cache unless the caller forced a refresh.
        if cached_df is not None and fresh_enough and not force_refresh:
            return OHLCVResult(cached_df, ticker, timeframe, fetched_at,
                               False, "cache", self._provider.name)

        # 2) Otherwise try the network.
        try:
            df = self._provider.fetch_ohlcv(
                ticker, spec["period"], spec["interval"], spec["intraday"])
            self._cache.put_bars(ticker, timeframe, df, self._provider.name, fetched_at=now)
            return OHLCVResult(df, ticker, timeframe, now, False, "network", self._provider.name)
        except DataProviderError:
            # 3) Network/symbol failure: fall back to cache (flagged STALE) if we
            #    have any; otherwise re-raise so the UI shows the error.
            if cached_df is not None and fetched_at is not None:
                return OHLCVResult(cached_df, ticker, timeframe, fetched_at,
                                   True, "cache", self._provider.name)
            raise
