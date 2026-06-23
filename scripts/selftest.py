"""Headless self-test — verify the backend without launching the GUI.

    python scripts/selftest.py

Checks config, ticker validation, network fetch + SQLite cache, indicators,
summary stats, both backtest strategies vs. a Buy & Hold baseline, and that the
frontend assets are served. Exits non-zero if any check fails. Requires network
for the data-dependent checks.
"""
import json
import os
import sys
import urllib.request

# Make the project root importable when run as `python scripts/selftest.py`.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config  # noqa: E402
from ui.api import JsApi  # noqa: E402
from ui.server import start_static_server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))


def main():
    api = JsApi()

    cfg = api.get_config()
    check("config loads", cfg.get("ok") and len(cfg["timeframes"]) == 6,
          f"{len(cfg['timeframes'])} timeframes, {len(cfg['strategies'])} strategies")

    tick = config.DEFAULT_TICKER
    check("validate known ticker", api.validate_ticker(tick).get("valid") is True, tick)
    check("reject unknown ticker", api.validate_ticker("ZZZZNOPE123").get("valid") is False)

    dash = api.get_dashboard(tick, "1Y", True)
    if not dash.get("ok"):
        check("fetch dashboard (network)", False, dash.get("error", ""))
        print("\nNetwork fetch failed — check your connection. Skipping data checks.")
        return 1

    check("fetch dashboard from network", dash["meta"]["source"] == "network",
          f"{dash['meta']['bars']} bars")
    json.dumps(dash)
    check("dashboard is JSON-serializable (bridge-safe)", True)

    ix = dash["indicators"]
    check("indicators computed",
          all(len(ix[k]) > 0 for k in ["sma", "ema", "rsi", "macd", "macd_hist"]),
          f"rsi={len(ix['rsi'])} macd={len(ix['macd'])}")

    s = dash["summary"]
    check("summary stats sane",
          bool(s) and s["high_52w"] > s["low_52w"] and s["current_price"] > 0,
          f"price={s['current_price']:.2f}, vol={s['hist_vol_annual_pct']:.1f}%")

    check("second load served from cache", api.get_dashboard(tick, "1Y", False)["meta"]["source"] == "cache")

    for strat, params in [("ma_cross", {"n1": 20, "n2": 50, "ma_type": "SMA"}),
                          ("rsi_threshold", {"rsi_period": 14, "lower": 30, "upper": 70})]:
        bt = api.run_backtest(tick, "1Y", strat, params, 10000, 0.1, 0.05)
        ok = bt.get("ok") and "strategy" in bt and "baseline" in bt
        detail = (f"strat={bt['strategy']['return_pct']:.2f}% vs B&H={bt['baseline']['return_pct']:.2f}% "
                  f"({bt['strategy']['num_trades']} trades)") if ok else bt.get("error", "")
        check(f"backtest {strat} vs Buy & Hold", ok, detail)
        if ok:
            json.dumps(bt)

    base, httpd = start_static_server(os.path.join(ROOT, "ui", "web"))
    try:
        served = [urllib.request.urlopen(base + p, timeout=5).status == 200 for p in
                  ["/index.html", "/styles.css", "/app.js",
                   "/vendor/lightweight-charts.standalone.production.js"]]
        check("frontend assets served", all(served), f"{sum(served)}/4 assets")
    finally:
        httpd.shutdown()

    print()
    if all(results):
        print(f"ALL {len(results)} CHECKS PASSED.   cache db: {config.CACHE_DB}")
        return 0
    print(f"{results.count(False)} of {len(results)} checks FAILED.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
