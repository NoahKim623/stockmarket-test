"""SQLite OHLCV cache, keyed by (ticker, timeframe).

Bars are stored as UTC epoch seconds so the cache is timezone-unambiguous. A
companion ``cache_meta`` row records when each (ticker, timeframe) set was
fetched, which the repository uses to decide staleness.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from typing import Optional, Tuple

import numpy as np
import pandas as pd

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ohlcv (
    ticker    TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    ts        INTEGER NOT NULL,            -- bar time, UTC epoch seconds
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (ticker, timeframe, ts)
);
CREATE TABLE IF NOT EXISTS cache_meta (
    ticker     TEXT NOT NULL,
    timeframe  TEXT NOT NULL,
    fetched_at INTEGER NOT NULL,           -- when we fetched, UTC epoch seconds
    provider   TEXT,
    PRIMARY KEY (ticker, timeframe)
);
"""


class CacheStore:
    def __init__(self, db_path: str):
        # check_same_thread=False: pywebview dispatches JS-API calls on a worker
        # thread. A single lock serializes all access (writes are tiny/atomic).
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    @staticmethod
    def _to_epoch_seconds(idx: pd.DatetimeIndex) -> np.ndarray:
        # Provider contract guarantees tz-naive UTC; datetime64[s] -> int64 epoch.
        return idx.to_numpy(dtype="datetime64[s]").astype("int64")

    def put_bars(self, ticker: str, timeframe: str, df: pd.DataFrame,
                 provider: str, fetched_at: Optional[int] = None) -> None:
        if fetched_at is None:
            fetched_at = int(time.time())
        epoch = self._to_epoch_seconds(df.index)
        o, h, l, c, v = (df["open"].tolist(), df["high"].tolist(), df["low"].tolist(),
                         df["close"].tolist(), df["volume"].tolist())
        rows = [
            (ticker, timeframe, int(epoch[i]),
             float(o[i]), float(h[i]), float(l[i]), float(c[i]), float(v[i]))
            for i in range(len(df))
        ]
        with self._lock:
            # Replace the whole set for this key so fresh/stale rows never mix.
            self._conn.execute("DELETE FROM ohlcv WHERE ticker=? AND timeframe=?", (ticker, timeframe))
            self._conn.executemany("INSERT OR REPLACE INTO ohlcv VALUES (?,?,?,?,?,?,?,?)", rows)
            self._conn.execute("INSERT OR REPLACE INTO cache_meta VALUES (?,?,?,?)",
                               (ticker, timeframe, int(fetched_at), provider))
            self._conn.commit()

    def get_bars(self, ticker: str, timeframe: str) -> Tuple[Optional[pd.DataFrame], Optional[int]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, open, high, low, close, volume FROM ohlcv "
                "WHERE ticker=? AND timeframe=? ORDER BY ts ASC", (ticker, timeframe)).fetchall()
            meta = self._conn.execute(
                "SELECT fetched_at FROM cache_meta WHERE ticker=? AND timeframe=?",
                (ticker, timeframe)).fetchone()
        if not rows:
            return None, None
        df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
        df.index = pd.to_datetime(df["ts"].to_numpy(), unit="s")  # tz-naive UTC
        df.index.name = "ts"
        df = df.drop(columns=["ts"])
        return df, (meta[0] if meta else None)

    def clear(self, ticker: Optional[str] = None) -> None:
        with self._lock:
            if ticker is None:
                self._conn.execute("DELETE FROM ohlcv")
                self._conn.execute("DELETE FROM cache_meta")
            else:
                self._conn.execute("DELETE FROM ohlcv WHERE ticker=?", (ticker,))
                self._conn.execute("DELETE FROM cache_meta WHERE ticker=?", (ticker,))
            self._conn.commit()
