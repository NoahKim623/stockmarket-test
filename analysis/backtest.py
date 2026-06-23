"""Backtesting with backtesting.py (0.6.x).

Strategies are deliberately simple and LONG-ONLY for clarity. Transaction costs
use backtesting.py's native parameters:
  * commission -> a fraction of trade value charged on every buy AND sell.
  * spread     -> a constant bid-ask spread (our "slippage") as a fraction of price;
                  you effectively buy a touch higher and sell a touch lower.
Every run is compared against an identical-cost Buy & Hold baseline, so the
comparison is apples-to-apples (same engine, same cost model).

IMPORTANT: results are historical/descriptive only — hypothetical performance on
past data. Past performance does not indicate future results.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from backtesting import Backtest, Strategy
from backtesting.lib import crossover

from analysis import indicators as ind


# --- indicator adapters (array-in, array-out) for Strategy.I -----------------
# backtesting.py hands indicator functions raw price arrays; reuse our pandas
# implementations so the backtest uses exactly the same math as the chart.
def _sma(values, n):
    return ind.sma(pd.Series(values), int(n)).to_numpy()


def _ema(values, n):
    return ind.ema(pd.Series(values), int(n)).to_numpy()


def _rsi(values, n):
    return ind.rsi(pd.Series(values), int(n)).to_numpy()


# --- strategies --------------------------------------------------------------
class MaCrossStrategy(Strategy):
    n1 = 20           # fast length
    n2 = 50           # slow length
    ma_type = "SMA"   # "SMA" | "EMA"

    def init(self):
        f = _ema if str(self.ma_type).upper() == "EMA" else _sma
        self.ma1 = self.I(f, self.data.Close, self.n1)
        self.ma2 = self.I(f, self.data.Close, self.n2)

    def next(self):
        # Golden cross -> enter long; death cross -> flatten. Long-only.
        if crossover(self.ma1, self.ma2):
            if not self.position:
                self.buy()
        elif crossover(self.ma2, self.ma1):
            if self.position:
                self.position.close()


class RsiThresholdStrategy(Strategy):
    rsi_period = 14
    lower = 30
    upper = 70

    def init(self):
        self.rsi = self.I(_rsi, self.data.Close, self.rsi_period)

    def next(self):
        # Buy when oversold; exit when overbought. Long-only.
        if not self.position and self.rsi[-1] < self.lower:
            self.buy()
        elif self.position and self.rsi[-1] > self.upper:
            self.position.close()


class BuyAndHoldStrategy(Strategy):
    """Baseline: buy on the first bar and hold (same costs applied)."""
    def init(self):
        pass

    def next(self):
        if not self.position:
            self.buy()


# UI-facing, JSON-serializable schema (+ private class lookup).
STRATEGY_SCHEMA = {
    "ma_cross": {
        "label": "Moving-Average Crossover",
        "description": "Go long when the fast MA crosses above the slow MA; exit when it crosses back below. Long-only.",
        "params": [
            {"key": "n1", "label": "Fast length", "type": "int", "default": 20, "min": 2, "max": 200},
            {"key": "n2", "label": "Slow length", "type": "int", "default": 50, "min": 3, "max": 400},
            {"key": "ma_type", "label": "MA type", "type": "choice", "choices": ["SMA", "EMA"], "default": "SMA"},
        ],
    },
    "rsi_threshold": {
        "label": "RSI Threshold",
        "description": "Buy when RSI is oversold (below the lower level); exit when overbought (above the upper level). Long-only.",
        "params": [
            {"key": "rsi_period", "label": "RSI period", "type": "int", "default": 14, "min": 2, "max": 100},
            {"key": "lower", "label": "Buy below (oversold)", "type": "int", "default": 30, "min": 1, "max": 49},
            {"key": "upper", "label": "Sell above (overbought)", "type": "int", "default": 70, "min": 51, "max": 99},
        ],
    },
}
_STRATEGY_CLASSES = {"ma_cross": MaCrossStrategy, "rsi_threshold": RsiThresholdStrategy}


def _to_bt_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase OHLCV -> backtesting.py's expected Capitalized columns."""
    out = df.rename(columns={"open": "Open", "high": "High", "low": "Low",
                             "close": "Close", "volume": "Volume"})
    return out[["Open", "High", "Low", "Close", "Volume"]]


def _num(value):
    """Coerce numpy/pandas scalar to a JSON-safe float, or None for NaN/inf."""
    try:
        f = float(value)
        return f if np.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _metrics(stats) -> dict:
    return {
        "return_pct": _num(stats.get("Return [%]")),
        "max_drawdown_pct": _num(stats.get("Max. Drawdown [%]")),
        "win_rate_pct": _num(stats.get("Win Rate [%]")),
        "sharpe": _num(stats.get("Sharpe Ratio")),
        "num_trades": int(stats.get("# Trades", 0) or 0),
        "return_ann_pct": _num(stats.get("Return (Ann.) [%]")),
        "exposure_pct": _num(stats.get("Exposure Time [%]")),
        "equity_final": _num(stats.get("Equity Final [$]")),
    }


def _coerce_params(strategy_key: str, params: dict) -> dict:
    """Validate/clamp UI params against the schema (defensive — UI may send junk)."""
    schema = STRATEGY_SCHEMA[strategy_key]["params"]
    params = params or {}
    out = {}
    for p in schema:
        key, val = p["key"], params.get(p["key"], p.get("default"))
        if p["type"] == "int":
            try:
                val = int(round(float(val)))
            except (TypeError, ValueError):
                val = p["default"]
            val = max(p.get("min", val), min(p.get("max", val), val))
        elif p["type"] == "choice" and val not in p["choices"]:
            val = p["default"]
        out[key] = val
    # MA cross needs fast < slow to be meaningful.
    if strategy_key == "ma_cross" and out.get("n1", 0) >= out.get("n2", 1):
        out["n2"] = out["n1"] + 1
    return out


def run(df: pd.DataFrame, strategy_key: str, params: dict,
        cash: float = 10000.0, commission_pct: float = 0.1, slippage_pct: float = 0.05) -> dict:
    """Run `strategy_key` plus a Buy & Hold baseline with identical costs.

    `commission_pct` / `slippage_pct` are PERCENTAGES (0.1 == 0.1%). Returns a dict
    of both metric sets; raises ValueError with a friendly message on bad input.
    """
    if strategy_key not in _STRATEGY_CLASSES:
        raise ValueError(f"Unknown strategy '{strategy_key}'.")

    data = _to_bt_frame(df).dropna()
    if len(data) < 30:
        raise ValueError(f"Not enough bars to backtest ({len(data)}). Pick a longer timeframe.")

    commission = max(0.0, float(commission_pct)) / 100.0
    spread = max(0.0, float(slippage_pct)) / 100.0
    cash = float(cash)
    if cash <= 0:
        raise ValueError("Starting cash must be greater than 0.")

    def _run(strategy_cls, run_params):
        bt = Backtest(data, strategy_cls, cash=cash, commission=commission, spread=spread,
                      trade_on_close=False, exclusive_orders=True, finalize_trades=True)
        return _metrics(bt.run(**run_params))

    clean = _coerce_params(strategy_key, params)
    strat = _run(_STRATEGY_CLASSES[strategy_key], clean)
    baseline = _run(BuyAndHoldStrategy, {})

    note = None
    if strat["num_trades"] == 0:
        note = "This strategy never triggered a trade in the selected period (it effectively held cash)."

    return {
        "strategy_key": strategy_key,
        "strategy_label": STRATEGY_SCHEMA[strategy_key]["label"],
        "params": clean,
        "cash": cash,
        "commission_pct": float(commission_pct),
        "slippage_pct": float(slippage_pct),
        "bars": int(len(data)),
        "strategy": strat,
        "baseline": baseline,
        "note": note,
    }
