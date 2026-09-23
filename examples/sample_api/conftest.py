"""Fixtures for the suite generated from openapi.json (Bookshelf 1.0.0).

API_BASE_URL points the suite at a server; the default below is the document's.
API_TOKEN is the bearer token the secured operations send.
API_TIMEOUT is the request timeout in seconds (default 10).
"""

import os

import httpx
import pytest

BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")
TIMEOUT = float(os.environ.get("API_TIMEOUT", "10"))
MARKERS = ["health", "authors", "books", "loans"]


def pytest_configure(config):
    for marker in MARKERS:
        config.addinivalue_line("markers", marker)


@pytest.fixture(scope="session")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=TIMEOUT) as client:
        yield client


@pytest.fixture(scope="session")
def auth_headers():
    """Credentials for the secured operations, from the environment."""
    token = os.environ.get("API_TOKEN")
    if not token:
        pytest.skip("API_TOKEN is not set; the secured operations need a bearer token")
    return {"Authorization": f"Bearer {token}"}
