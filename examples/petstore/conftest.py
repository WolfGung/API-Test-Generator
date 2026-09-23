"""Fixtures for the suite generated from petstore-openapi3.json (Swagger Petstore - OpenAPI 3.0 1.0.27).

API_BASE_URL points the suite at a server; the default below is the document's.
API_KEY is the key the secured operations send in the api_key header.
API_TIMEOUT is the request timeout in seconds (default 10).
"""

import os

import httpx
import pytest

BASE_URL = os.environ.get("API_BASE_URL", "https://petstore3.swagger.io/api/v3")
TIMEOUT = float(os.environ.get("API_TIMEOUT", "10"))
MARKERS = ["pet", "store", "user"]


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
    key = os.environ.get("API_KEY")
    if not key:
        pytest.skip("API_KEY is not set; the secured operations need it")
    return {"api_key": key}
