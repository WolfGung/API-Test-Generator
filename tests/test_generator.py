from pathlib import Path

import pytest

from api_test_gen.generator import OutputExists, generate
from api_test_gen.openapi import load_openapi
from api_test_gen.postman import load_postman
from tests.documents import BOOKISH, NO_SCHEMAS
from tests.helpers import collected, ruff_check

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


@pytest.fixture
def bookish(tmp_path):
    path = tmp_path / "bookish.yaml"
    path.write_text(BOOKISH)
    return load_openapi(path)


def test_generates_a_module_per_tag_and_counts_what_it_wrote(bookish, tmp_path):
    out = tmp_path / "out"
    summary = generate(bookish, out, source_name="bookish.yaml")
    assert sorted(p.name for p in out.iterdir()) == [
        "README.md", "conftest.py", "models.py", "test_default.py", "test_files.py", "test_things.py"
    ]
    assert summary.operations == 6
    assert summary.modules == ("test_things.py", "test_default.py", "test_files.py")
    assert summary.skipped == (
        "upload: request body is application/octet-stream, which the generator does not produce",
    )
    # things: list (+no credentials), create (+name, +size, +no credentials), search (+q) = 8;
    # default: ping, echo = 2; files: upload = 1
    assert summary.tests == 11
    assert collected(out) == summary.tests
    assert ruff_check(out, ignore=("E501",)) == ""
    conftest = (out / "conftest.py").read_text()
    assert 'BASE_URL = os.environ.get("API_BASE_URL", "https://api.example.com/v1")' in conftest
    assert 'MARKERS = ["things", "default", "files"]' in conftest
    assert 'pytest.skip("API_TOKEN is not set' in conftest
    things = (out / "test_things.py").read_text()
    assert "from models import Thing, ThingList\n" in things
    assert '        params={"q": "string", "page-size": 5},\n' in things


def test_output_is_deterministic(bookish, tmp_path):
    # The same leaf name under two parents: the README's run hint names the output directory by design.
    first, second = tmp_path / "a" / "out", tmp_path / "b" / "out"
    generate(bookish, first, source_name="bookish.yaml")
    generate(bookish, second, source_name="bookish.yaml")
    for path in first.iterdir():
        assert path.read_text() == (second / path.name).read_text(), path.name


def test_tags_can_be_included_or_excluded_and_base_url_overridden(bookish, tmp_path):
    out = tmp_path / "out"
    summary = generate(bookish, out, source_name="bookish.yaml", include_tags=["things"], base_url="http://127.0.0.1:9")
    assert summary.modules == ("test_things.py",) and summary.operations == 3
    assert 'BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:9")' in (out / "conftest.py").read_text()
    summary = generate(bookish, tmp_path / "out2", source_name="bookish.yaml", exclude_tags=["things", "files"])
    assert summary.modules == ("test_default.py",) and summary.tests == 2


def test_a_full_directory_is_refused_unless_overwrite_replaces_the_generated_files(bookish, tmp_path):
    out = tmp_path / "out"
    generate(bookish, out, source_name="bookish.yaml")
    (out / "test_stale.py").write_text("")
    (out / "notes.txt").write_text("mine")
    with pytest.raises(OutputExists, match="--overwrite"):
        generate(bookish, out, source_name="bookish.yaml")
    generate(bookish, out, source_name="bookish.yaml", overwrite=True, include_tags=["files"])
    assert sorted(p.name for p in out.iterdir()) == [
        "README.md", "conftest.py", "models.py", "notes.txt", "test_files.py"
    ]


def test_no_schemas_means_no_models_module(tmp_path):
    path = tmp_path / "bare.yaml"
    path.write_text(NO_SCHEMAS)
    out = tmp_path / "out"
    summary = generate(load_openapi(path), out, source_name="bare.yaml")
    assert summary.tests == 1 and not (out / "models.py").exists()
    assert "    assert response.status_code == 204, response.text[:300]\n" in (out / "test_default.py").read_text()
    assert ruff_check(out) == ""


@pytest.mark.parametrize(
    "loader, name, operations",
    [(load_openapi, "petstore-openapi3.json", 19), (load_postman, "postman-echo.postman_collection.json", 22)],
)
def test_the_public_documents_generate_lint_clean_collectable_suites(loader, name, operations, tmp_path):
    out = tmp_path / "out"
    summary = generate(loader(FIXTURES / name), out, source_name=name)
    assert summary.operations == operations
    assert collected(out) == summary.tests
    assert ruff_check(out, ignore=("E501",)) == ""
