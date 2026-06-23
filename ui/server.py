"""Tiny localhost static-file server for the frontend.

We serve ui/web over http://127.0.0.1:<port> rather than file:// because the app
lives under a path with spaces (and OneDrive), which makes file:// asset loading
fragile on Windows. pywebview's js_api bridge works regardless of URL scheme.
"""
from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):  # silence per-request console spam
        pass


def start_static_server(directory: str):
    """Start a daemon HTTP server on an ephemeral port. Returns (base_url, httpd)."""
    handler = partial(_QuietHandler, directory=directory)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)  # port 0 -> OS picks a free port
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port}", httpd
