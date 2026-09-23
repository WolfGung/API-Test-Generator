import pytest

from tests.helpers import collected, ruff_check
from tools.examples import EXAMPLES, REPO, regenerate


@pytest.mark.parametrize("example", EXAMPLES, ids=[example.name for example in EXAMPLES])
def test_the_committed_example_is_what_the_generator_writes(example, tmp_path):
    fresh = tmp_path / example.name
    summary = regenerate(example, fresh)
    committed = REPO / "examples" / example.name
    # Files only: collecting the committed suite leaves a __pycache__ behind, which is not the generator's.
    names = sorted(p.name for p in committed.iterdir() if p.is_file())
    assert names == sorted(p.name for p in fresh.iterdir()), "run `make examples`"
    for path in fresh.iterdir():
        stale = f"{committed / path.name} is stale: run `make examples`"
        assert (committed / path.name).read_text() == path.read_text(), stale
    assert collected(committed) == summary.tests
    assert ruff_check(committed) == ""


def test_every_example_has_a_command_a_reader_can_run():
    for example in EXAMPLES:
        assert example.command.startswith("api-test-gen --")
        assert (REPO / example.source).exists()
