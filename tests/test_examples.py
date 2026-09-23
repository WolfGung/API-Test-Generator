import shlex

import pytest
from typer.testing import CliRunner

from api_test_gen.cli import app
from tests.helpers import collected, ruff_check
from tools.examples import EXAMPLES, REPO, regenerate

EXAMPLE_IDS = [example.name for example in EXAMPLES]


@pytest.mark.parametrize("example", EXAMPLES, ids=EXAMPLE_IDS)
def test_the_committed_example_is_what_the_generator_writes(example, tmp_path):
    fresh = tmp_path / example.name
    summary = regenerate(example, fresh)
    committed = REPO / "examples" / example.name
    names = sorted(p.name for p in committed.iterdir())
    assert names == sorted(p.name for p in fresh.iterdir()), "run `make examples`"
    for path in fresh.iterdir():
        stale = f"{committed / path.name} is stale: run `make examples`"
        assert (committed / path.name).read_bytes() == path.read_bytes(), stale
    assert collected(committed) == summary.tests, f"{committed} does not collect the {summary.tests} tests written"
    assert ruff_check(committed) == ""


@pytest.mark.parametrize("example", EXAMPLES, ids=EXAMPLE_IDS)
def test_the_command_of_every_example_reproduces_it(example, tmp_path, monkeypatch):
    """The README prints these commands: run through the CLI into an empty directory, each must write the
    committed suite byte for byte."""
    monkeypatch.chdir(REPO)  # the command names its document relative to the repository
    arguments = shlex.split(example.command)
    assert arguments[0] == "api-test-gen"
    out = tmp_path / example.name  # the README's run hint names the output directory, so the leaf name matters
    out.mkdir()  # empty: the command carries no --overwrite
    arguments[arguments.index("--out") + 1] = str(out)
    result = CliRunner().invoke(app, arguments[1:])
    assert result.exit_code == 0, result.output
    committed = REPO / "examples" / example.name
    assert sorted(p.name for p in out.iterdir()) == sorted(p.name for p in committed.iterdir())
    for path in out.iterdir():
        differs = f"`{example.command}` does not reproduce {path.name}"
        assert path.read_bytes() == (committed / path.name).read_bytes(), differs
