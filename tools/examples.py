"""The example suites the repository commits, and the command that regenerates them: `python -m tools.examples`."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from api_test_gen.generator import Summary, generate
from api_test_gen.openapi import load_openapi
from api_test_gen.postman import load_postman

REPO = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Example:
    name: str  # the directory under examples/
    kind: str  # "spec" | "postman"
    source: str  # the document, relative to the repository
    base_url: str | None  # what the suite defaults to; None keeps the document's own
    live: str  # what the suite runs against in this repository (for the README)

    @property
    def command(self) -> str:
        parts = ["api-test-gen", f"--{self.kind}", self.source, "--out", f"examples/{self.name}"]
        if self.base_url:
            parts += ["--base-url", self.base_url]
        return " ".join(parts)


EXAMPLES = (
    Example(
        "sample_api", "spec", "sample_api/openapi.json", "http://127.0.0.1:8000", "the sample API, on every push"
    ),
    Example(
        "petstore", "spec", "fixtures/petstore-openapi3.json", "https://petstore3.swagger.io/api/v3",
        "petstore3.swagger.io, nightly",
    ),
    Example(
        "postman_echo", "postman", "fixtures/postman-echo.postman_collection.json", None,
        "generated and collected only",
    ),
)


def regenerate(example: Example, out: Path) -> Summary:
    source = REPO / example.source
    api = load_openapi(source) if example.kind == "spec" else load_postman(source)
    return generate(api, out, source_name=source.name, base_url=example.base_url, overwrite=True)


def main() -> None:
    for example in EXAMPLES:
        summary = regenerate(example, REPO / "examples" / example.name)
        print(f"examples/{example.name}: {summary.tests} tests for {summary.operations} operations")


if __name__ == "__main__":
    main()
