"""Fixtures the generator's tests share."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from sample_api.app import app
from sample_api.serve import serving


@pytest.fixture(scope="session")
def sample_api_url() -> Iterator[str]:
    """The sample API, served on a free port for the whole session.

    Yields its base URL, `http://127.0.0.1:<port>`. The sample API's own tests talk to it with a plain httpx
    client; the live proof of a generated suite runs that suite as a subprocess with API_BASE_URL set to it.
    The state tests leave behind (a book added, book 5 removed) is what the app promises to tolerate.
    """
    with serving(app) as url:
        yield url
