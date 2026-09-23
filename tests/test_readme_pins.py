"""The README says only what the repository does.

Every number, command and quoted block on the page is checked here against what produces it: the four example
suites are generated again into a scratch directory, the command the page shows is run through the command line,
the counts and names in the prose are read from the files they describe. Nothing here needs the network, and
nothing is written outside tmp_path.
"""

from __future__ import annotations

import re
import shlex
import tomllib

import pytest
import yaml
from typer.testing import CliRunner

from api_test_gen.cli import app
from api_test_gen.generator import Summary
from api_test_gen.openapi import load_document, load_openapi
from api_test_gen.postman import SUPPORTED_SCHEMAS
from sample_api.app import TOKEN
from tests import test_live
from tests.helpers import collected
from tools.examples import EXAMPLES, REPO, Example, regenerate

README = (REPO / "README.md").read_text(encoding="utf-8")
SOURCE = REPO / "src" / "api_test_gen"
CREDENTIALS = ("API_BASE_URL", "API_TOKEN", "API_KEY", "API_USERNAME", "API_PASSWORD")  # what a generated suite reads
NUMBER_WORDS = {"one": 1, "two": 2, "both": 2, "three": 3, "four": 4, "five": 5}
MOST_WORDS = 25  # what a sentence on the first screen may have at most


def pinned(pattern: str, what: str) -> re.Match[str]:
    """The README text the pattern protects; a failure names the line the page lost."""
    match = re.search(pattern, README, re.M)
    assert match, f"the README no longer has the line for {what}: nothing matches {pattern!r}"
    return match


def counted(pattern: str, what: str) -> int:
    """A number the page spells as a word, `the four suites`; every occurrence of the phrase must agree."""
    words = re.findall(pattern, README, re.M)
    assert words, f"the README no longer has the line for {what}: nothing matches {pattern!r}"
    numbers = {NUMBER_WORDS.get(word.lower()) for word in words}
    assert len(numbers) == 1 and None not in numbers, f"{what}: the page says {sorted(set(words))}"
    return numbers.pop()


def document_format(example: Example) -> str:
    """`OpenAPI 3.1` or `Postman v2.0`, read from the document itself."""
    document = load_document(REPO / example.source)
    if example.kind == "spec":
        major, minor = str(document["openapi"]).split(".")[:2]
        return f"OpenAPI {major}.{minor}"
    version = re.search(r"/v(\d+\.\d+)\.\d+/", str(document["info"]["schema"]))
    assert version, example.source
    return f"Postman v{version.group(1)}"


def bare_word(text: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


def first_screen() -> str:
    """The page up to the `Try it` heading: the title, one sentence, the badges, the table and the bullets."""
    end = README.find("\n## Try it\n")
    assert end != -1, "the README no longer has the `## Try it` heading that ends the first screen"
    return README[:end]


@pytest.fixture(scope="module")
def fresh(tmp_path_factory) -> dict[str, Summary]:
    """Every example generated again, into a scratch directory: the numbers the table has to show."""
    root = tmp_path_factory.mktemp("fresh")
    return {example.name: regenerate(example, root / example.name) for example in EXAMPLES}


def test_the_first_screen_is_title_sentence_badges_table_and_bullets_in_short_sentences():
    screen = first_screen()
    landmarks = (
        "# API Test Generator\n", "[![CI](", "## What a document becomes", "\n| Document |", "## What this shows"
    )
    positions = [screen.find(mark) for mark in landmarks]
    assert -1 not in positions and positions == sorted(positions), (
        "the first screen: title, one sentence, badges, the table, the bullets"
    )
    assert README.startswith("# API Test Generator\n\n"), "the page opens with its title"
    tagline, after = README.split("\n\n")[1:3]
    assert "\n" not in tagline and tagline.endswith(".") and ". " not in tagline, "one sentence under the title"
    assert after.startswith("[![CI]("), "the badges follow the sentence directly"
    lines = screen.splitlines()
    badges = [index for index, line in enumerate(lines) if line.startswith("[![")]
    heading = lines.index("## What a document becomes")
    assert badges == list(range(badges[0], badges[-1] + 1)) and badges[-1] < heading, "one block of badges"
    assert not any(lines[badges[-1] + 1 : heading]), "nothing between the badges and the table's heading"
    rows = [index for index, line in enumerate(lines) if line.startswith("|")]
    bullets = [index for index, line in enumerate(lines) if line.startswith("- ")]
    assert rows and bullets and rows[-1] < bullets[0], "the table stands before the bullets"
    between = [line for line in lines[rows[-1] + 1 : bullets[0]] if line]
    assert between == ["## What this shows"], f"between the table and the bullets only their heading, not {between}"
    assert 2 <= len(bullets) <= 3, "two or three bullets of what this shows"
    prose = [line for line in lines if line and not line.startswith(("#", "|", "[!["))]
    text = re.sub(r"\]\([^)]*\)", "]", " ".join(prose)).replace("**", "")  # link targets and emphasis are not words
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        words = sentence.split()
        assert len(words) <= MOST_WORDS, f"{len(words)} words in one first-screen sentence: {sentence!r}"


def test_the_table_of_documents_matches_fresh_generation(fresh):
    rows = re.findall(r"^\| `[^`]+` \|.*\|$", README, re.M)
    assert len(rows) == len(EXAMPLES), "one table row per committed example"
    for example in EXAMPLES:
        row = pinned(
            rf"^\| `{re.escape(example.source)}` \| ([^|]+?) \| (\d+) \| (\d+)(?: \((\d+) skipped\))? \| (\d+) "
            rf"\| {re.escape(example.live)} \|$",
            f"the table row of {example.source}",
        )
        summary = fresh[example.name]
        assert row.group(1) == document_format(example), f"{example.name}: the format column"
        written = (summary.operations, summary.tests, len(summary.modules))
        shown = (int(row.group(2)), int(row.group(3)), int(row.group(5)))
        assert shown == written, f"{example.name}: operations, tests and modules in the table against fresh generation"
        assert int(row.group(4) or 0) == len(summary.skipped), f"{example.name}: tests written skipped"


def test_the_try_it_command_is_the_one_the_tests_run_and_prints_what_the_page_shows(tmp_path, monkeypatch):
    for example in EXAMPLES:
        assert f"\n{example.command}\n" in README, f"the page shows the command that writes examples/{example.name}"
    example = next(e for e in EXAMPLES if e.name == "sample_api")
    out = tmp_path / "examples" / "sample_api"  # empty, the way the tests run it; the page shows the path it names
    arguments = shlex.split(example.command)[1:]
    arguments[arguments.index("--out") + 1] = str(out)
    monkeypatch.chdir(REPO)  # the command names its document relative to the repository
    result = CliRunner().invoke(app, arguments)
    assert result.exit_code == 0, result.output
    printed = result.output.strip().replace(str(out), "examples/sample_api")
    assert f"```\n{printed}\n```" in README, f"the page shows what the command prints:\n{printed}"


def test_the_options_named_on_the_page_are_the_command_lines():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    for option in set(re.findall(r"`(--[a-z-]+)`", README)):
        assert option in result.output, f"the page names {option}, which api-test-gen --help does not"


def test_the_pytest_line_is_the_size_of_the_sample_suite():
    command = pinned(r"^API_TOKEN=(\S+) pytest examples/sample_api -q$", "the pytest command of the sample suite")
    assert command.group(1) == TOKEN, "the token the page uses is the sample API's"
    line = pinned(r"^(\d+) passed in [\d.]+s$", "the last line pytest prints for the sample suite")
    assert int(line.group(1)) == collected(REPO / "examples" / "sample_api"), "the pytest line counts the sample suite"


def test_the_quoted_test_is_in_the_example_verbatim():
    quoted = re.search(r"```python\n(def test_create_book\(.*?)\n```", README, re.S)
    assert quoted, "the README quotes test_create_book from examples/sample_api/test_books.py"
    source = (REPO / "examples" / "sample_api" / "test_books.py").read_text(encoding="utf-8")
    assert f"\n{quoted.group(1)}\n\n" in source, "the quoted function is not what the example holds"


def test_the_live_proof_is_described_as_the_live_test_runs_it():
    live = counted(r"then (\w+) sample-API suites", "how many sample-API suites run live")
    assert live == len(test_live.LIVE), "the suites the live test runs"
    ways = (
        "test_the_generated_suite_passes_against_the_sample_api",
        "test_a_wrong_token_fails_exactly_the_secured_positives",
        "test_without_a_token_the_operations_that_need_one_are_skipped",
    )
    assert counted(r"Each suite runs (\w+) ways", "the ways each suite runs") == len(ways), "one way per live test"
    for name in ways:
        assert hasattr(test_live, name), f"tests/test_live.py no longer has {name}"
    failing = pinned(r"exactly the (\d+) secured operations fail", "how many operations a wrong token fails")
    positives = set(test_live.SECURED_POSITIVES.values())
    assert {int(failing.group(1))} == positives, f"the secured positives of each suite: {test_live.SECURED_POSITIVES}"
    skipped = pinned(r"\(those (\d+) and their negatives are skipped\)", "what a run without a token skips")
    assert int(skipped.group(1)) == int(failing.group(1)), "what fails with a wrong token is what skips without one"
    assert int(failing.group(1)) == min(test_live.NEED_THE_TOKEN.values()), "a suite without negatives skips those"


def test_the_ci_claims_match_the_workflow():
    workflow = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    triggers = workflow.get("on") or workflow[True]  # PyYAML reads the `on:` key as a boolean
    assert "push" in triggers and "pull_request" in triggers, "the page says CI runs on every push"
    crons = [entry["cron"] for entry in triggers["schedule"]]
    assert len(crons) == 1 and re.fullmatch(r"\d+ \d+ \* \* \*", crons[0]), "once a night: one daily cron"
    assert "workflow_dispatch" in triggers, "the page says the Petstore job can be started by hand"
    jobs = workflow["jobs"]
    assert {"lint", "test", "petstore-live"} <= set(jobs), "the jobs the page describes"
    petstore = jobs["petstore-live"]
    assert petstore["continue-on-error"] is True, "the page says the Petstore job is allowed to fail"
    assert "schedule" in petstore["if"] and "workflow_dispatch" in petstore["if"], "nightly and by hand only"
    pinned(r"runs the Petstore suite against `petstore3\.swagger\.io`", "the nightly Petstore run")
    runs = [str(step.get("run", "")) for step in petstore["steps"]]
    assert any("petstore3.swagger.io" in run for run in runs), "the Petstore job targets petstore3.swagger.io"
    assert any("pytest" in str(step.get("run", "")) for step in jobs["test"]["steps"]), "the test job runs pytest"


def test_the_badges_point_at_this_repository_and_say_what_the_files_say():
    pinned(
        r"^\[!\[CI\]\((https://github\.com/WolfGung/API-Test-Generator/actions/workflows/ci\.yml)/badge\.svg\)\]"
        r"\(\1\)$",
        "the CI badge",
    )
    assert (REPO / ".github" / "workflows" / "ci.yml").is_file(), "the workflow the CI badge points at"
    python = pinned(
        r"^\[!\[Python ([\d.]+)\]\(https://img\.shields\.io/badge/python-([\d.]+)-blue\)\]\(pyproject\.toml\)$",
        "the Python badge",
    )
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert python.group(1) == python.group(2), "the Python badge names one version"
    assert project["requires-python"] == f">={python.group(1)}", "the Python badge says what pyproject.toml requires"
    pinned(r"^\[!\[License: MIT\]\(https://img\.shields\.io/badge/license-MIT-green\)\]\(LICENSE\)$", "the MIT badge")
    assert (REPO / "LICENSE").read_text(encoding="utf-8").startswith("MIT License"), "the licence the badge names"


def test_make_targets_named_on_the_page_exist():
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    targets = set(re.findall(r"`make ([a-z-]+)`", README))
    assert targets, "the page names make targets"
    for target in targets:
        assert f"\n{target}:" in makefile, f"`make {target}` is on the page but not in the Makefile"


def test_the_repository_map_names_what_is_there():
    listed = pinned(r"^src/api_test_gen/ +the generator: (.+)$", "the module list of the generator")
    modules = {name.strip() for name in listed.group(1).split(",")}
    on_disk = {path.stem for path in SOURCE.glob("*.py")} - {"__init__"}
    assert modules == on_disk, f"the module list against src/api_test_gen: {sorted(modules ^ on_disk)}"
    suites = len(EXAMPLES)
    for pattern, what, expected in (
        (r"^examples/ +the (\w+) generated suites", "how many suites examples/ holds", suites),
        (r"the (\w+) examples and `make examples`", "how many examples tools/examples.py has", suites),
        (r"The (\w+) suites are committed under", "how many suites are committed", suites),
        (r"The other (\w+) suites in the table", "the suites the other commands write", suites - 1),
    ):
        assert counted(pattern, what) == expected, f"{what}: {expected} in tools/examples.py"
    public = [example for example in EXAMPLES if example.source.startswith("fixtures/")]
    assert counted(r"the (\w+) public ones", "how many public documents there are") == len(public), "under fixtures/"
    for example in public:
        assert (REPO / example.source).is_file(), example.source
    for name in ("openapi.json", "bookshelf.postman_collection.json"):
        assert (REPO / "sample_api" / name).is_file(), name


def test_the_formats_named_are_the_ones_the_loaders_accept():
    named = pinned(r"Postman collections v([\d.]+) and v([\d.]+)", "the Postman schema versions the loader accepts")
    accepted = {re.search(r"/v(\d+\.\d+)\.\d+/", marker).group(1) for marker in SUPPORTED_SCHEMAS}  # type: ignore[union-attr]
    assert set(named.groups()) == accepted, f"the Postman versions the loader accepts: {sorted(accepted)}"
    openapi = pinned(r"reads OpenAPI ([\d.]+) and ([\d.]+) documents", "the OpenAPI versions the loader reads")
    in_the_table = {document_format(example).split()[1] for example in EXAMPLES if example.kind == "spec"}
    assert set(openapi.groups()) == in_the_table, "both OpenAPI versions the page names have an example"


def test_the_status_codes_and_constraints_named_are_the_ones_in_the_code():
    rendering = (SOURCE / "render.py").read_text(encoding="utf-8")
    pinned(r"expected to answer 401 or 403", "the status of a request without credentials")
    assert "in (401, 403)" in rendering, "render.py asserts 401 or 403 for a request without credentials"
    pinned(r"expected to answer 4xx", "the status of a request with something left out")
    assert "400 <= response.status_code < 500" in rendering, "render.py asserts 4xx for a request missing something"
    sampling = (SOURCE / "samples.py").read_text(encoding="utf-8")
    line = pinned(
        r"^- \*\*Values that satisfy (.+?)\*\* Of the constraints, the sampler honours (.+?);",
        "which constraints the sampler honours and which it does not",
    )
    for keyword in re.findall(r"`(\w+)`", line.group(1)):
        assert not bare_word(sampling, keyword), f"the page says the sampler ignores {keyword}, but samples.py names it"
    for keyword in re.findall(r"`(\w+)`", line.group(2)):
        assert f'"{keyword}"' in sampling, f"the page says the sampler honours {keyword}, but samples.py does not"


def test_the_environment_variables_named_are_the_ones_the_generated_conftest_reads():
    template = (SOURCE / "templates" / "conftest.py.j2").read_text(encoding="utf-8")
    line = pinned(
        r"^`conftest\.py` holds the HTTP client and the credentials fixture: (.+?)\. `models\.py`",
        "the environment variables a generated suite reads",
    )
    named = set(re.findall(r"`(API_[A-Z_]+)`", line.group(1)))
    assert named == set(CREDENTIALS), f"the page names {sorted(named)}, the generated conftest reads {CREDENTIALS}"
    for name in CREDENTIALS:
        pinned(rf"`{name}`", f"the environment variable {name}")
        assert f'os.environ.get("{name}"' in template, f"the page names {name}; the generated conftest never reads it"


def test_the_generated_suite_needs_what_the_page_says_and_not_the_generator():
    pinned(r"A generated suite needs pytest, httpx and Pydantic, not the generator\.", "what a suite depends on")
    for example in EXAMPLES:
        suite = REPO / "examples" / example.name
        assert "pip install pytest httpx pydantic" in (suite / "README.md").read_text(encoding="utf-8"), example.name
        for module in suite.glob("*.py"):
            text = module.read_text(encoding="utf-8")
            assert not re.search(r"^(?:from|import) api_test_gen", text, re.M), f"{module} imports the generator"


def test_docker_compose_has_the_two_containers_the_page_runs():
    pinned(r"^docker compose run --rm gen\b.*in two containers$", "the docker compose command")
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))
    assert set(compose["services"]) == {"api", "gen"}, "the sample API and the generator, nothing else"
    assert "api" in compose["services"]["gen"]["depends_on"], "gen waits for the sample API"


def test_the_related_work_links_are_the_other_repositories_of_the_portfolio():
    names = (
        "Toolshop-Test-Automation-Framework",
        "Marketplace-Test-Automation-Framework",
        "Web-Scraping-Automation-Framework",
        "Test-Suite-Rescue",
    )
    for name in names:
        assert f"https://github.com/WolfGung/{name})" in README, name
    related = counted(r"^(\w+) more repositories from the same portfolio", "how many related repositories")
    assert related == len(names), f"the page links {len(names)} repositories"


def test_the_yaml_scalars_the_page_names_are_read_as_strings(tmp_path):
    line = pinned(
        r"YAML scalars are read as the document wrote them: "
        r"an unquoted `([^`]+)`, `([^`]+)` or `([^`]+)` stays that string",
        "how YAML scalars are read",
    )
    path = tmp_path / "scalars.yaml"
    path.write_text("".join(f"key{index}: {scalar}\n" for index, scalar in enumerate(line.groups())))
    assert list(load_document(path).values()) == list(line.groups()), "the loader types a scalar the page says it keeps"
    pinned(r"`true` and `false`, numbers and `null` keep their types\.", "what the YAML loader still types")
    path.write_text("yes: true\nno: false\ncount: 3\nratio: 1.5\nnothing: null\n")
    assert load_document(path) == {"yes": True, "no": False, "count": 3, "ratio": 1.5, "nothing": None}


def test_what_the_page_says_is_not_generated_is_dropped_with_a_note(tmp_path):
    pinned(r"^- \*\*Cookie parameters\.\*\* A parameter with `in: cookie` is not sent; the generator prints a `note:`",
           "the cookie parameters bullet")
    loading = (SOURCE / "openapi.py").read_text(encoding="utf-8")
    assert 'in ("path", "query", "header")' in loading, "openapi.py accepts exactly path, query and header parameters"
    pinned(
        r"keys in a query string or a cookie leave the operation unsecured .*: "
        r"the generator prints a `note:` saying so",
        "the unsupported-authentication bullet",
    )
    path = tmp_path / "unsupported.yaml"
    path.write_text(
        "openapi: 3.0.3\ninfo: {title: U, version: '1'}\nsecurity: [{k: []}]\n"
        "components: {securitySchemes: {k: {type: apiKey, in: cookie, name: k}}}\n"
        "paths: {/t: {get: {parameters: [{name: c, in: cookie, schema: {}}], responses: {'200': {description: ok}}}}}\n"
    )
    api = load_openapi(path)
    assert api.security.kind == "none", "a key in a cookie leaves the suite without credentials"
    assert any("security is not supported" in note for note in api.notes), "the loader notes the scheme"
    assert any("cookie parameter" in note for note in api.notes), "the loader notes the cookie parameter"
