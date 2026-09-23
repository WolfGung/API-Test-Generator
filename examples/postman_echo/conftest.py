"""Fixtures for the suite generated from postman-echo.postman_collection.json (Postman Echo (V2)).

API_BASE_URL points the suite at a server; the default below is the document's.
API_USERNAME and API_PASSWORD are the credentials the secured operations send.
API_TIMEOUT is the request timeout in seconds (default 10).
"""

import base64
import os

import httpx
import pytest

BASE_URL = os.environ.get("API_BASE_URL", "https://postman-echo.com")
TIMEOUT = float(os.environ.get("API_TIMEOUT", "10"))
MARKERS = ["auth_digest", "auth_others", "cookies", "headers", "request_methods", "utilities", "draft_auth_oauth2_0"]


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
    username, password = os.environ.get("API_USERNAME"), os.environ.get("API_PASSWORD")
    if not username or password is None:
        pytest.skip("API_USERNAME and API_PASSWORD are not set; the secured operations need them")
    credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {credentials}"}
