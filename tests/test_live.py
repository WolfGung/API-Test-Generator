"""The generated sample-API suites, run as a client would run them, against the sample API.

The Makefile and tests/conftest.py promise that the generated sample-API suite runs against the sample API
itself; this module is the test behind that promise. Every committed suite whose `live` entry in
tools.examples names the sample API (the one generated from openapi.json and the one from the Postman
collection) is copied out of examples/ and run as a separate pytest process, with API_BASE_URL pointing at
the server the session fixture started and the credentials in the environment alone, the way its README says
to run it: green with the token, exactly the secured positives red with a wrong one, the tests that need a
token skipped without one.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sample_api.app import TOKEN
from tests.helpers import collected
from tools.examples import EXAMPLES, REPO

pytestmark = pytest.mark.live

LIVE = [example for example in EXAMPLES if "the sample API" in example.live]
assert LIVE, "no committed example runs against the sample API"

# What each document says about credentials. The secured operations are the same four in both suites: add,
# replace and remove a book, and lend one. So a wrong token fails four positives in either. The OpenAPI
# document also gives create_book and replace_book three required body fields each and create_loan a
# required header and a required field: eight negatives that send the token too, so without one that suite
# skips twelve tests. The collection carries no required-field information, so its suite skips only the four
# positives. The four no-credentials cases of either suite never ask for the token, and pass.
SECURED_POSITIVES = {"sample_api": 4, "sample_api_postman": 4}
NEED_THE_TOKEN = {"sample_api": 12, "sample_api_postman": 4}


@pytest.fixture(params=LIVE, ids=[example.name for example in LIVE])
def suite(request, tmp_path) -> Path:
    """A copy of the committed suite, in a directory named as the example is, so a run leaves nothing under
    examples/ and the suite is run on its own, without this repository's pytest configuration."""
    copy = tmp_path / request.param.name
    shutil.copytree(REPO / "examples" / request.param.name, copy)
    return copy


def run_suite(suite: Path, url: str, **env: str) -> subprocess.CompletedProcess[str]:
    """Run the suite as its README says: `pytest <directory>` in a separate process that writes no cache, with
    the server's URL and only the credentials given here in the environment."""
    clean = {k: v for k, v in os.environ.items() if k not in ("API_TOKEN", "API_BASE_URL")}
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(suite), "-q", "-p", "no:cacheprovider"],
        cwd=suite.parent, env={**clean, "PYTHONDONTWRITEBYTECODE": "1", "API_BASE_URL": url, **env},
        capture_output=True, text=True, check=False,
    )


def outcome(result: subprocess.CompletedProcess[str], word: str) -> int:
    """How many tests the run's summary line counts under `word`: `23 passed`, `4 failed`, `12 skipped`."""
    match = re.search(rf"(\d+) {word}", result.stdout)
    return int(match.group(1)) if match else 0


def transcript(result: subprocess.CompletedProcess[str]) -> str:
    """The run as it happened, for the assertion message: its exit status, then everything it printed."""
    return f"exit status {result.returncode}\n{result.stdout}{result.stderr}"


def test_the_generated_suite_passes_against_the_sample_api(suite, sample_api_url):
    result = run_suite(suite, sample_api_url, API_TOKEN=TOKEN)
    assert result.returncode == 0, transcript(result)
    assert outcome(result, "passed") == collected(suite), transcript(result)
    assert outcome(result, "skipped") == 0, transcript(result)


def test_it_passes_a_second_time_against_the_same_process(suite, sample_api_url):
    first = run_suite(suite, sample_api_url, API_TOKEN=TOKEN)
    second = run_suite(suite, sample_api_url, API_TOKEN=TOKEN)
    assert first.returncode == 0, transcript(first)
    assert second.returncode == 0, transcript(second)


def test_a_wrong_token_fails_exactly_the_secured_positives(suite, sample_api_url):
    result = run_suite(suite, sample_api_url, API_TOKEN="wrong")
    positives = SECURED_POSITIVES[suite.name]
    assert result.returncode != 0, transcript(result)
    assert outcome(result, "failed") == positives, transcript(result)
    assert outcome(result, "passed") == collected(suite) - positives, transcript(result)


def test_without_a_token_the_operations_that_need_one_are_skipped(suite, sample_api_url):
    result = run_suite(suite, sample_api_url)
    skipped = NEED_THE_TOKEN[suite.name]
    assert result.returncode == 0, transcript(result)
    assert outcome(result, "skipped") == skipped, transcript(result)
    assert outcome(result, "passed") == collected(suite) - skipped, transcript(result)
