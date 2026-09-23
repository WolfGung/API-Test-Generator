"""Fixtures the generator's tests share."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn

from sample_api.app import app


@pytest.fixture(scope="session")
def sample_api_url() -> Iterator[str]:
    """The sample API, served by uvicorn on a free port in a daemon thread for the whole session.

    Yields its base URL, `http://127.0.0.1:<port>`. The sample API's own tests talk to it with a plain httpx
    client; the live proof of a generated suite runs that suite as a subprocess with API_BASE_URL set to it.
    The state tests leave behind (a book added, book 5 removed) is what the app promises to tolerate.
    """
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, name="sample-api", daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("the sample API did not start")
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)
