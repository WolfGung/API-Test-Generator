"""The command line: api-test-gen --spec openapi.yaml --out tests/ (or --postman collection.json)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from . import __version__
from .generator import OutputExists, UnknownTag, generate
from .ir import SpecError
from .naming import plural
from .openapi import load_openapi
from .postman import load_postman

app = typer.Typer(
    add_completion=False,
    rich_markup_mode=None,
    pretty_exceptions_enable=False,  # a failure is one `error:` line, never a traceback with local variables
    help="Turn an OpenAPI 3 document or a Postman collection into a pytest suite with response validation.",
)


@app.command()
def run(
    spec: Annotated[
        Path | None,
        typer.Option("--spec", exists=True, dir_okay=False, help="An OpenAPI 3.0 or 3.1 document, YAML or JSON."),
    ] = None,
    postman: Annotated[
        Path | None,
        typer.Option("--postman", exists=True, dir_okay=False, help="A Postman collection, schema v2.0 or v2.1."),
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", file_okay=False, help="The directory to write the suite into.")
    ] = None,
    base_url: Annotated[
        str | None,
        typer.Option("--base-url", help="The server the suite defaults to; API_BASE_URL still wins at run time."),
    ] = None,
    overwrite: Annotated[
        bool, typer.Option("--overwrite", help="Replace the generated files of an earlier run in --out.")
    ] = False,
    include_tag: Annotated[
        list[str] | None, typer.Option("--include-tag", help="Only these tags (Postman: folders); repeatable.")
    ] = None,
    exclude_tag: Annotated[
        list[str] | None, typer.Option("--exclude-tag", help="Leave these tags out; repeatable.")
    ] = None,
    version: Annotated[bool, typer.Option("--version", help="Print the version and exit.")] = False,
) -> None:
    """Generate the suite and print what was written."""
    if version:
        typer.echo(f"api-test-gen {__version__}")
        raise typer.Exit()
    if (spec is None) == (postman is None):
        raise typer.BadParameter("give exactly one of --spec or --postman")
    if out is None:
        raise typer.BadParameter("--out is required")
    source = spec if spec is not None else postman
    assert source is not None
    try:
        api = load_openapi(source) if spec is not None else load_postman(source)
        summary = generate(
            api, out, source_name=source.name, base_url=base_url, overwrite=overwrite,
            include_tags=include_tag or (), exclude_tags=exclude_tag or (),
        )
    except SpecError as exc:
        typer.echo(f"error: {source}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except (OutputExists, UnknownTag) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except Exception as exc:  # the backstop: whatever slipped past the loaders is still one line, not a traceback
        typer.echo(f"error: cannot generate from {source}: {type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    tests, operations = plural(summary.tests, "test"), plural(summary.operations, "operation")
    written = f"Wrote {tests} for {operations} to {out}"
    typer.echo(f"{written}: {', '.join(summary.modules)}" if summary.modules else written)
    for line in summary.skipped:
        typer.echo(f"skipped: {line}")


def main() -> None:
    app()
