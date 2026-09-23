import json
import os
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from api_test_gen import __version__
from api_test_gen.cli import app
from tests.documents import BOOKISH
from tests.helpers import REPO

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
    assert result.output.splitlines() == [
        f"Wrote 0 tests for 0 operations to {out}",
        "note: the document names no server: API_BASE_URL is required to run the suite",
    ]


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


# --- Refusals: a malformed document is refused with an `error:` line naming the file and the cause. ----------

DANGLING_REF = """
openapi: 3.0.3
info: {title: Dangling, version: "1"}
paths:
  /things:
    get:
      operationId: listThings
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {type: object, properties: {owner: {$ref: "#/components/schemas/Missing"}}}
"""

REF_CYCLE = """
openapi: 3.0.3
info: {title: Cycle, version: "1"}
components:
  schemas:
    A: {$ref: "#/components/schemas/B"}
    B: {$ref: "#/components/schemas/A"}
paths:
  /things:
    get:
      operationId: listThings
      responses:
        "200": {description: ok, content: {application/json: {schema: {$ref: "#/components/schemas/A"}}}}
"""

REQUIRED_TRUE = """
openapi: 3.0.3
info: {title: Required, version: "1"}
paths:
  /things:
    post:
      operationId: createThing
      requestBody:
        required: true
        content:
          application/json:
            schema: {type: object, required: true, properties: {name: {type: string}}}
      responses:
        "201": {description: made}
"""


def run_cli(*arguments: str, timeout: float = 20) -> subprocess.CompletedProcess[str]:
    """The command line in a subprocess, so a run that never finishes fails by timeout instead of stalling
    the suite."""
    return subprocess.run(
        [sys.executable, "-c", "from api_test_gen.cli import main; main()", *arguments],
        capture_output=True, text=True, timeout=timeout, check=False, cwd=REPO,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def refused(result, spec: Path, cause: str, out: Path) -> None:
    assert result.exit_code == 1, result.output
    assert f"error: {spec}: {cause}" in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit), result.exception
    assert not out.exists()


def test_a_dangling_reference_is_refused_naming_the_file_and_the_reference(tmp_path):
    spec = tmp_path / "dangling.yaml"
    spec.write_text(DANGLING_REF)
    out = tmp_path / "x"
    result = runner.invoke(app, ["--spec", str(spec), "--out", str(out)])
    refused(result, spec, "unresolved reference '#/components/schemas/Missing'", out)


def test_a_reference_cycle_is_refused_and_the_command_finishes(tmp_path):
    spec = tmp_path / "cycle.yaml"
    spec.write_text(REF_CYCLE)
    out = tmp_path / "x"
    result = run_cli("--spec", str(spec), "--out", str(out))
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"error: {spec}: reference loop at " in result.stderr, result.stderr
    assert "Traceback" not in result.stderr and not out.exists()


def test_a_required_that_is_not_a_list_is_refused_naming_the_schema(tmp_path):
    spec = tmp_path / "required.yaml"
    spec.write_text(REQUIRED_TRUE)
    out = tmp_path / "x"
    result = runner.invoke(app, ["--spec", str(spec), "--out", str(out)])
    refused(result, spec, "schema 'CreateThingRequest': 'required' must be a list of property names, not True", out)


def test_a_file_that_is_not_utf8_is_refused(tmp_path):
    spec = tmp_path / "latin1.yaml"
    spec.write_bytes("openapi: 3.0.3\ninfo: {title: Café, version: '1'}\npaths: {}\n".encode("latin-1"))
    out = tmp_path / "x"
    result = runner.invoke(app, ["--spec", str(spec), "--out", str(out)])
    refused(result, spec, "not UTF-8 text", out)


def test_a_collection_whose_item_is_null_is_refused(tmp_path):
    collection = tmp_path / "null.postman_collection.json"
    v2_1 = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
    collection.write_text(json.dumps({"info": {"name": "Null", "schema": v2_1}, "item": None}))
    out = tmp_path / "x"
    result = runner.invoke(app, ["--postman", str(collection), "--out", str(out)])
    refused(result, collection, "the collection's 'item' is not a list", out)


def test_any_other_failure_is_reported_as_an_error_line_without_a_traceback(tmp_path, monkeypatch):
    def broken(*_, **__):
        raise RuntimeError("rendering broke")

    monkeypatch.setattr("api_test_gen.cli.generate", broken)
    spec = write(tmp_path)
    out = tmp_path / "x"
    result = runner.invoke(app, ["--spec", str(spec), "--out", str(out)])
    assert result.exit_code == 1, result.output
    assert f"error: cannot generate from {spec}: RuntimeError: rendering broke" in result.output
    assert "Traceback" not in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit), result.exception
    assert not out.exists()


OAUTH_ONLY = """
openapi: 3.0.3
info: {title: OAuth, version: "1"}
servers: [{url: /v1}]
security: [{oauth: [read]}]
components:
  securitySchemes:
    oauth: {type: oauth2, flows: {}}
paths:
  /things:
    get:
      operationId: listThings
      parameters:
        - {name: session, in: cookie, schema: {type: string}}
      responses:
        "200": {description: ok}
"""


def test_what_the_suite_cannot_do_is_printed_as_note_lines(tmp_path):
    spec = tmp_path / "oauth.yaml"
    spec.write_text(OAUTH_ONLY)
    out = tmp_path / "suite"
    result = runner.invoke(app, ["--spec", str(spec), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [
        f"Wrote 1 test for 1 operation to {out}: test_default.py",
        "note: oauth (oauth2) security is not supported; the suite sends no credentials",
        "note: list_things: cookie parameter 'session' is not supported and is not sent",
        "note: the suite's default server URL '/v1' has no host: API_BASE_URL is required to run it",
    ]
    readme = (out / "README.md").read_text()
    assert "\noauth (oauth2) security is not supported; the suite sends no credentials\n" in readme
