"""Blocking request-stream transformer used by the concurrency benchmark."""

import os
import time
from pathlib import Path

from mitmproxy import http

try:
    from mitmproxy.script import run_in_thread
except ImportError:
    # Keep this benchmark runnable on unmodified main. Without the marker
    # implementation, the blocking callback runs on the proxy event loop and
    # benchmark.ps1 reports the expected failure.
    def run_in_thread(function):
        return function


BLOCKING_SECONDS = float(os.environ.get("BENCH_REQUEST_STREAM_DELAY", "3"))
MARKER = Path(os.environ["BENCH_REQUEST_STREAM_MARKER"])


def requestheaders(flow: http.HTTPFlow) -> None:
    if flow.request.path != "/slow":
        return

    blocked_once = False

    @run_in_thread
    def transform(chunk: bytes) -> bytes:
        nonlocal blocked_once
        if chunk and not blocked_once:
            blocked_once = True
            MARKER.write_text("blocking\n")
            time.sleep(BLOCKING_SECONDS)
        return chunk

    flow.request.stream = transform
