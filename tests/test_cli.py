from pathlib import Path

from typer.testing import CliRunner

from api_test_gen import __version__
from api_test_gen.cli import app
from tests.documents import BOOKISH

runner = CliRunner()


def write(tmp_path: Path) -> Path:
    path = tmp_path / "bookish.yaml"
    path.write_text(BOOKISH)
    return path


def test_generates_and_reports(tmp_path):
    spec = write(tmp_path)
    out = tmp_path / "suite"
    result = runner.invoke(app, ["--spec", str(spec), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [
        f"Wrote 11 tests for 6 operations to {out}: test_things.py, test_default.py, test_files.py",
        "skipped: upload: request body is application/octet-stream, which the generator does not produce",
    ]
    assert (out / "conftest.py").exists()


def test_a_document_without_operations_is_reported_without_a_module_list(tmp_path):
    empty = tmp_path / "empty.yaml"
    empty.write_text("openapi: 3.0.3\ninfo: {title: Empty, version: '1'}\npaths: {}\n")
    out = tmp_path / "suite"
    result = runner.invoke(app, ["--spec", str(empty), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [f"Wrote 0 tests for 0 operations to {out}"]


def test_exactly_one_input_is_required(tmp_path):
    spec = write(tmp_path)
    neither = runner.invoke(app, ["--out", str(tmp_path / "x")])
    assert neither.exit_code == 2 and "exactly one of --spec or --postman" in neither.output
    both = runner.invoke(app, ["--spec", str(spec), "--postman", str(spec), "--out", str(tmp_path / "x")])
    assert both.exit_code == 2


def test_document_errors_and_full_directories_exit_with_one(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("swagger: '2.0'\n")
    result = runner.invoke(app, ["--spec", str(bad), "--out", str(tmp_path / "x")])
    assert result.exit_code == 1 and "error: " in result.output and "OpenAPI 3" in result.output
    out = tmp_path / "full"
    out.mkdir()
    (out / "keep.txt").write_text("")
    result = runner.invoke(app, ["--spec", str(write(tmp_path)), "--out", str(out)])
    assert result.exit_code == 1 and "--overwrite" in result.output


def test_an_unknown_tag_is_an_error_that_names_the_tags_the_document_has(tmp_path):
    out = tmp_path / "x"
    result = runner.invoke(app, ["--spec", str(write(tmp_path)), "--out", str(out), "--include-tag", "nope"])
    assert result.exit_code == 1, result.output
    assert "error: unknown tag nope; the document has: things, default, files" in result.output
    assert not out.exists()


def test_out_at_a_file_is_a_usage_error_without_a_traceback(tmp_path):
    target = tmp_path / "suite.txt"
    target.write_text("")
    result = runner.invoke(app, ["--spec", str(write(tmp_path)), "--out", str(target)])
    assert result.exit_code == 2 and "is a file" in result.output and "Traceback" not in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert target.read_text() == ""


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0 and result.output.strip() == f"api-test-gen {__version__}"
