# Stock Analysis & Backtesting Dashboard

A desktop tool for exploring stock price data, technical
indicators, and simple trading strategies. It fetches market data, charts it
with TradingView's Lightweight Charts, computes indicators, and backtests
toy strategies against a Buy & Hold baseline — all in a native window.

---

## Features

- **Any ticker**, with validation and friendly errors (e.g. `AAPL`, `MSFT`, `BTC-USD`).
- **Timeframes:** 1D, 1W, 1M, 6M, 1Y, 5Y (lookback windows with sensible bar sizes).
- **Candlestick chart** with toggleable overlays: **SMA**, **EMA**, **Bollinger Bands**, **Volume**.
- **RSI** and **MACD** sub-panels, time-synced with the price chart.
- **Summary panel:** current price, daily change, 52-week high/low, annualized
  historical volatility, 30-day average volume.
- **Backtesting** (via [`backtesting.py`](https://kernc.github.io/backtesting.py/)):
  moving-average crossover and RSI-threshold strategies, with configurable
  **commission + slippage**, reporting total return, max drawdown, win rate,
  Sharpe, and trade count — always next to a **Buy & Hold** baseline.
- **Local SQLite cache** keyed by ticker + timeframe, with a manual **Refresh**
  and a staleness window. Stale data is flagged in the UI, never served silently.
- Persistent disclaimers; no price-prediction features by design.

## Project layout

```
app.py                 Entry point (python app.py)
config.py              Timeframes, staleness, indicator params, disclaimers, paths
requirements.txt
build.spec             PyInstaller build
scripts/selftest.py    Headless verification (no GUI)
data/
  provider.py          DataProvider abstract base class + canonical OHLCV shape
  yfinance_provider.py Default source (yfinance, no API key)
  cache.py             SQLite OHLCV cache
  repository.py        Provider + cache + staleness policy (the data facade)
analysis/
  indicators.py        SMA / EMA / Bollinger / RSI / MACD (pure pandas)
  statistics.py        Summary stats (52w range, volatility, avg volume)
  backtest.py          Strategies + runner + Buy & Hold baseline
ui/
  api.py               JsApi — methods exposed to the frontend
  server.py            Localhost static server for the frontend
  format.py            pandas -> lightweight-charts JSON helpers
  web/                 index.html, styles.css, app.js, vendor/ (chart library)
```

Data flows one way: **UI → `JsApi` → `MarketDataRepository` → (`CacheStore` | `DataProvider`)**,
and **analysis** modules transform DataFrames into chart/stat payloads.

---

## Setup (Windows)

**Requirements:** Python 3.11–3.14 and (for the window) the **Edge WebView2
runtime**, which is pre-installed on Windows 11. If the window is blank on an
older machine, install it from Microsoft ("Evergreen Standalone Installer").
No C compiler is needed — everything is pure-Python or ships wheels.

```powershell
# from the project folder
py -m venv .venv
.\.venv\Scripts\Activate.ps1        # if blocked: Set-ExecutionPolicy -Scope Process -Bypass
python -m pip install --upgrade pip
pip install -r requirements.txt
```

> **PowerShell execution policy:** if `Activate.ps1` is blocked, run
> `Set-ExecutionPolicy -Scope Process -Bypass` first (affects only this shell),
> or skip activation and call `.\.venv\Scripts\python.exe` directly.

### Run

```powershell
python app.py
```

The window opens and auto-loads AAPL. Type a ticker + Enter, switch timeframes,
toggle overlays, and run a backtest from the right-hand panel.

### Verify it works (no GUI)

```powershell
python scripts/selftest.py
```

Exercises the whole backend (fetch → cache → indicators → summary → backtest →
asset serving) and prints PASS/FAIL for each step. Needs an internet connection.

---

## Configuration

Everything tunable lives in **`config.py`**:

- `TIMEFRAMES` — the lookback window (`period`) + bar size (`interval`) per button.
- `STALENESS_SECONDS` — how long cached bars stay "fresh" before a refresh is attempted.
- `INDICATORS` — lengths/periods for SMA, EMA, Bollinger, RSI, MACD (shown in the UI labels).
- `BACKTEST_DEFAULTS` — starting cash and default commission/slippage percentages.
- `DATA_DIR` / `CACHE_DB` — the SQLite cache lives in `%LOCALAPPDATA%\StockDashboard`.

---

## Adding a new data provider

The app talks to data sources only through `data/provider.py::DataProvider`. To
add Polygon, Finnhub, Twelve Data, etc., subclass it and implement two methods —
nothing else in the app changes.

```python
# data/polygon_provider.py
from datetime import datetime, timedelta, timezone
import pandas as pd
from polygon import RESTClient
from .provider import DataProvider, InvalidTickerError, NetworkError, STANDARD_COLUMNS

# Map our normalized lookback tokens (config.TIMEFRAMES "period") to day counts.
_LOOKBACK_DAYS = {"1d": 1, "5d": 5, "1mo": 31, "6mo": 186, "1y": 366, "5y": 1827}

class PolygonProvider(DataProvider):
    name = "polygon"

    def __init__(self, api_key: str):
        self._client = RESTClient(api_key)

    def fetch_ohlcv(self, ticker, period, interval, intraday):
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=_LOOKBACK_DAYS.get(period, 366))
        mult, span = _to_polygon_interval(interval)   # e.g. "5m" -> (5, "minute")
        try:
            bars = self._client.get_aggs(ticker, mult, span, start.date(), end.date())
        except Exception as e:
            raise NetworkError(str(e)) from e
        if not bars:
            raise InvalidTickerError(f"No data for '{ticker}'.")

        df = pd.DataFrame([{
            "open": b.open, "high": b.high, "low": b.low,
            "close": b.close, "volume": b.volume,
            "ts": pd.Timestamp(b.timestamp, unit="ms"),
        } for b in bars]).set_index("ts").sort_index()

        # Honor the provider contract: tz-naive UTC index; daily bars normalized.
        if not intraday:
            df.index = df.index.normalize()
        return df[STANDARD_COLUMNS]

    def validate_ticker(self, ticker):
        try:
            return bool(self._client.get_ticker_details(ticker))
        except Exception:
            return False
```

Then swap it in once, in `ui/api.py::JsApi.__init__`:

```python
# self._provider = YFinanceProvider()
self._provider = PolygonProvider(api_key="YOUR_KEY")
```

The **contract** every provider must satisfy is documented in `data/provider.py`:
a tz-naive (UTC) `DatetimeIndex`, lowercase `open/high/low/close/volume` columns,
sorted ascending and unique; raise `InvalidTickerError` / `NetworkError` on failure.

---

## A note on indicators / `pandas-ta`

The original plan used `pandas-ta`. On **Python 3.14** it can't be installed: the
current PyPI release (`0.4.x`) hard-imports **`numba`**, which has no 3.14 wheel,
and the pure-Python classic release (`0.3.14b0`) was removed from PyPI. So the
five indicators are implemented directly in **pure pandas** (`analysis/indicators.py`),
matching pandas-ta's formulas (Wilder's RSI, standard MACD 12/26/9, Bollinger
20/2σ with population std). This keeps the "pure-Python, no C dependency" intent
with zero extra packages.

To use the real package instead, run on **Python 3.12** (`pip install pandas-ta`,
which pulls numba) and adapt `analysis/indicators.py` to call it — the function
signatures are designed to make that a drop-in swap.

---

## Packaging

### PyInstaller (provided)

```powershell
pip install pyinstaller
pyinstaller build.spec
```

Produces `dist\StockDashboard\StockDashboard.exe` (an *onedir* build — faster
startup and friendlier to `pythonnet` than onefile). The frontend (`ui/web`) is
bundled; the WebView2 runtime is not (it's an OS component).

If the packaged app misbehaves, set `console=True` in `build.spec` and rebuild to
see tracebacks, then add any missing module to `hiddenimports`.

### Nuitka (fallback)

Nuitka compiles to C for faster startup and a tidier bundle, but takes longer to
build and is more sensitive to native deps (`pythonnet`, `curl_cffi`):

```powershell
pip install nuitka
python -m nuitka --standalone --assume-yes-for-downloads `
  --include-data-dir=ui/web=ui/web `
  --include-package=webview --include-package=clr_loader `
  --windows-console-mode=disable `
  --output-dir=dist-nuitka app.py
```

Add `--include-package=...` for anything Nuitka misses, and drop
`--windows-console-mode=disable` while debugging.

---

## Limitations — what this can and cannot tell you

Read this before drawing conclusions from anything the app shows.

**Technical indicators** are deterministic transforms of past prices. They
*describe* what already happened (trend, momentum, dispersion); they do **not**
forecast. The same RSI or crossover "signal" precedes both rallies and reversals.

**Backtests are hypothetical and prone to flattering bias:**

- **Past performance ≠ future results.** A strategy that won on this slice of
  history can lose on the next. Markets are non-stationary.
- **Overfitting / curve-fitting.** Tweaking parameters until the backtest looks
  good usually fits noise, not signal. Few parameters and out-of-sample testing
  help, but nothing here selects parameters for you — and you should be suspicious
  of any you tuned by hand against the same data you're judging.
- **Survivorship & data quality.** yfinance gives adjusted prices for *currently
  listed* symbols; delisted companies and some corporate actions can distort or
  vanish. Intraday history is limited and sometimes patchy.
- **Costs are simplified.** Commission and slippage are modeled as flat
  percentages; real fills, market impact, partial fills, borrow costs, taxes, and
  spread dynamics are not. Fractional shares aren't supported, so very high-priced
  tickers may need larger starting cash to trade at all.
- **Look-ahead & single-asset scope.** Strategies are long-only, single-asset,
  end-of-bar — no portfolio construction, position sizing, or risk management.
- **Volatility is realized, not implied.** The "historical volatility" stat is a
  backward-looking standard deviation of past returns, not a forecast or an
  options-implied figure.

In short: use this to **learn** how indicators and backtests behave and to build
intuition — not to make investment decisions. There is no forecasting component,
by design.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Blank/white window | Install the Edge **WebView2 runtime** (Microsoft, Evergreen). |
| Want to see console errors | `$env:SD_DEBUG=1; python app.py`, then right-click → Inspect. |
| "No data" for a valid symbol | yfinance/Yahoo hiccup or rate limit — wait and **Refresh**. |
| Backtest: "Not enough bars" | Pick a longer timeframe (intraday windows are short). |
| Stale badge shown | A live refresh failed; you're seeing cached data. Try **Refresh**. |
