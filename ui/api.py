"""JsApi: methods exposed to the HTML/JS frontend via pywebview's js_api bridge.

Every public method returns a JSON-serializable dict and NEVER raises across the
bridge: failures come back as {"ok": False, "error": <friendly message>} so the
UI shows a message instead of crashing. (All numeric values are coerced to native
Python types in the analysis/format layers so json serialization can't choke.)
"""
from __future__ import annotations

import traceback

import config
from analysis import backtest as bt
from analysis import indicators as ind
from analysis import statistics as stats
from data.cache import CacheStore
from data.provider import DataProviderError, InvalidTickerError, NetworkError
from data.repository import MarketDataRepository
from data.yfinance_provider import YFinanceProvider
from ui import format as fmt


class JsApi:
    def __init__(self):
        self._provider = YFinanceProvider()
        self._cache = CacheStore(config.CACHE_DB)
        self._repo = MarketDataRepository(self._provider, self._cache)
        self._window = None

    def set_window(self, window):
        self._window = window

    # -- config / metadata --------------------------------------------------
    def get_config(self):
        s = config.INDICATORS
        return {
            "ok": True,
            "default_ticker": config.DEFAULT_TICKER,
            "default_timeframe": config.DEFAULT_TIMEFRAME,
            "timeframes": [{"key": k, "label": v["label"]} for k, v in config.TIMEFRAMES.items()],
            "indicators": {
                "sma_label": f"SMA {s['sma_length']}",
                "ema_label": f"EMA {s['ema_length']}",
                "bb_label": f"BB {s['bb_length']},{s['bb_std']:g}",
                "rsi_label": f"RSI {s['rsi_length']}",
                "macd_label": f"MACD {s['macd_fast']},{s['macd_slow']},{s['macd_signal']}",
            },
            "strategies": [
                {"key": k, "label": v["label"], "description": v["description"], "params": v["params"]}
                for k, v in bt.STRATEGY_SCHEMA.items()
            ],
            "backtest_defaults": config.BACKTEST_DEFAULTS,
            "disclaimer_short": config.DISCLAIMER_SHORT,
            "disclaimer_long": config.DISCLAIMER_LONG,
            "backtest_disclaimer": config.BACKTEST_DISCLAIMER,
        }

    def validate_ticker(self, ticker):
        try:
            t = (ticker or "").strip().upper()
            if not t:
                return {"ok": False, "valid": False, "error": "Please enter a ticker symbol."}
            return {"ok": True, "valid": bool(self._provider.validate_ticker(t)), "ticker": t}
        except Exception as e:
            return {"ok": False, "valid": False, "error": f"Validation failed: {e}"}

    # -- main data load -----------------------------------------------------
    def get_dashboard(self, ticker, timeframe, force_refresh=False):
        """Candles + volume + indicator overlays/oscillators + summary stats."""
        try:
            t = (ticker or "").strip().upper()
            if not t:
                return {"ok": False, "error": "Please enter a ticker symbol."}
            if timeframe not in config.TIMEFRAMES:
                timeframe = config.DEFAULT_TIMEFRAME
            intraday = config.TIMEFRAMES[timeframe]["intraday"]

            result = self._repo.get_ohlcv(t, timeframe, force_refresh=bool(force_refresh))
            df = result.df
            if df is None or df.empty:
                return {"ok": False, "error": f"No data available for '{t}'."}

            ix = ind.compute_all(df)
            indicators = {
                "sma": fmt.line_series(df.index, ix["sma"], intraday),
                "ema": fmt.line_series(df.index, ix["ema"], intraday),
                "bb_upper": fmt.line_series(df.index, ix["bb_upper"], intraday),
                "bb_middle": fmt.line_series(df.index, ix["bb_middle"], intraday),
                "bb_lower": fmt.line_series(df.index, ix["bb_lower"], intraday),
                "rsi": fmt.line_series(df.index, ix["rsi"], intraday),
                "macd": fmt.line_series(df.index, ix["macd"], intraday),
                "macd_signal": fmt.line_series(df.index, ix["macd_signal"], intraday),
                "macd_hist": fmt.hist_series(df.index, ix["macd_hist"], intraday),
            }

            return {
                "ok": True,
                "meta": result.meta(),
                "candles": fmt.candles(df, intraday),
                "volume": fmt.volume(df, intraday),
                "indicators": indicators,
                "summary": self._summary(t),
            }
        except InvalidTickerError as e:
            return {"ok": False, "error": str(e)}
        except (NetworkError, DataProviderError) as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:  # last-resort guard: the UI must never see a crash
            traceback.print_exc()
            return {"ok": False, "error": f"Unexpected error: {e}"}

    def _summary(self, ticker):
        """Summary stats from ~1y of daily bars. Best-effort: returns None on failure
        so a summary hiccup never blocks the chart."""
        try:
            res = self._repo.get_ohlcv(ticker, config.SUMMARY_TIMEFRAME, force_refresh=False)
            if res.df is None or res.df.empty:
                return None
            data = stats.summarize(res.df)
            data["as_of"] = res.meta()["fetched_at_human"]
            return data
        except Exception:
            return None

    # -- backtesting --------------------------------------------------------
    def run_backtest(self, ticker, timeframe, strategy, params,
                     cash, commission_pct, slippage_pct):
        try:
            t = (ticker or "").strip().upper()
            if not t:
                return {"ok": False, "error": "Please enter a ticker symbol."}
            if timeframe not in config.TIMEFRAMES:
                timeframe = config.DEFAULT_TIMEFRAME

            res = self._repo.get_ohlcv(t, timeframe, force_refresh=False)
            df = res.df
            if df is None or df.empty:
                return {"ok": False, "error": f"No data available for '{t}'."}

            out = bt.run(df, strategy, params or {},
                         cash=cash, commission_pct=commission_pct, slippage_pct=slippage_pct)
            out["ok"] = True
            out["ticker"] = t
            out["timeframe"] = timeframe
            out["meta"] = res.meta()
            return out
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        except (NetworkError, DataProviderError) as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "error": f"Backtest failed: {e}"}
