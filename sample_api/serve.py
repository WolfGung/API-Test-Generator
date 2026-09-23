"""Serve the app for as long as a `with` block lasts: uvicorn on a free port, in a daemon thread."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import uvicorn
from fastapi import FastAPI

START_TIMEOUT = 10.0  # seconds to wait for the server to be up before giving up
STOP_TIMEOUT = 10.0  # seconds to wait for it to finish after being told to exit


@contextmanager
def serving(app: FastAPI) -> Iterator[str]:
    """Yield the base URL of `app`, `http://127.0.0.1:<port>`, served by uvicorn on a free port in a daemon
    thread; the port is read from the socket the server bound, and the server is stopped when the block ends."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, name="sample-api", daemon=True)
    thread.start()
    deadline = time.monotonic() + START_TIMEOUT
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            server.should_exit = True
            raise RuntimeError("the sample API did not start")
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=STOP_TIMEOUT)
