"""Entry point: `python app.py` launches the desktop dashboard.

Architecture (see README): a local static HTTP server serves the HTML/JS
frontend; pywebview opens a native window pointed at it and exposes the Python
backend through `js_api`. The frontend renders TradingView Lightweight Charts.
"""
from __future__ import annotations

import os
from pathlib import Path

import webview

import config
from ui.api import JsApi
from ui.server import start_static_server


def main():
    web_dir = Path(__file__).resolve().parent / "ui" / "web"
    base_url, httpd = start_static_server(str(web_dir))

    api = JsApi()
    window = webview.create_window(
        config.APP_TITLE,
        url=f"{base_url}/index.html",
        js_api=api,
        width=1440,
        height=920,
        min_size=(1080, 720),
        background_color="#0b0e14",
    )
    api.set_window(window)

    # Set SD_DEBUG=1 to enable right-click → Inspect (DevTools) for troubleshooting.
    debug = bool(os.environ.get("SD_DEBUG"))
    try:
        # Blocks on the GUI event loop until the window is closed.
        # On Windows this uses the Edge WebView2 runtime via pythonnet.
        webview.start(debug=debug)
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    main()
