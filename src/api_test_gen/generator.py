"""Generate a suite: fixtures, models, one module per tag, a README; then count what was written."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .cases import cases_for
from .ir import ApiModel
from .models import class_names, generate_models
from .naming import plural, to_identifier, unique
from .render import render_conftest, render_module, render_readme

FIXED_FILES = ("conftest.py", "models.py", "README.md")
ENV_HINTS = {
    "bearer": ["API_TOKEN=..."],
    "basic": ["API_USERNAME=...", "API_PASSWORD=..."],
    "apiKey": ["API_KEY=..."],
    "none": [],
}


class OutputExists(RuntimeError):
    """The output path is a file, or a directory with files in it while overwriting was not asked for."""


class UnknownTag(ValueError):
    """An include or exclude tag that no operation of the document carries."""

    def __init__(self, unknown: list[str], known: tuple[str, ...]) -> None:
        noun = "tag" if len(unknown) == 1 else "tags"
        has = f"the document has: {', '.join(known)}" if known else "the document has no tags"
        super().__init__(f"unknown {noun} {', '.join(unknown)}; {has}")


@dataclass(frozen=True)
class Summary:
    operations: int
    tests: int
    modules: tuple[str, ...]
    skipped: tuple[str, ...]  # "<operation_id>: <reason>" for every positive case that is written skipped
    notes: tuple[str, ...]  # what the suite cannot do: the document's notes, plus a server URL it cannot reach


def generate(
    api: ApiModel,
    out: Path,
    *,
    source_name: str,
    base_url: str | None = None,
    overwrite: bool = False,
    include_tags: Iterable[str] = (),
    exclude_tags: Iterable[str] = (),
) -> Summary:
    include, exclude = list(include_tags), list(exclude_tags)
    unknown = [tag for tag in dict.fromkeys([*include, *exclude]) if tag not in api.tags]
    if unknown:
        raise UnknownTag(unknown, api.tags)
    if out.exists() and not out.is_dir():
        raise OutputExists(f"{out} exists and is not a directory")
    if out.is_dir() and any(out.iterdir()) and not overwrite:
        raise OutputExists(f"{out} is not empty; pass --overwrite to replace the generated files in it")
    operations = [op for op in api.operations if (not include or op.tag in include) and op.tag not in exclude]
    tags: list[str] = []
    for operation in operations:
        if operation.tag not in tags:
            tags.append(operation.tag)
    taken: set[str] = set()
    markers = {tag: unique(to_identifier(tag), taken) for tag in tags}
    names = class_names(api.schemas)
    files: dict[str, str] = {}
    modules: list[str] = []
    skipped: list[str] = []
    tests = 0
    for tag in tags:
        per_operation = [(op, cases_for(op, api)) for op in operations if op.tag == tag]
        cases = [case for _, found in per_operation for case in found]
        tests += len(cases)
        skipped += [
            f"{op.operation_id}: {case.skip_reason}"
            for op, found in per_operation
            for case in found
            if case.skip_reason
        ]
        module = f"test_{markers[tag]}.py"
        files[module] = render_module(
            tag=tag, marker=markers[tag], cases=cases, model_names=names, operations=len(per_operation),
            source_name=source_name,
        )
        modules.append(module)
    effective_base_url = api.base_url if base_url is None else base_url
    notes = [*api.notes, *_base_url_notes(effective_base_url)]
    files["conftest.py"] = render_conftest(
        api, source_name=source_name, base_url=effective_base_url, markers=list(markers.values()),
    )
    if api.schemas:
        files["models.py"] = generate_models(api, source_name)
    files["README.md"] = render_readme(
        api,
        source_name=source_name,
        summary_lines=[
            f"{plural(len(operations), 'operation')}, {plural(tests, 'test')} in {plural(len(modules), 'module')}."
        ],
        env_lines=["API_BASE_URL=...", *ENV_HINTS.get(api.security.kind, [])],
        modules=modules,
        out_hint=out.name or ".",
        notes=notes,
    )
    # Only now, with every file rendered, is the directory touched: a failure above leaves it as it was.
    if overwrite and out.is_dir():
        for stale in out.iterdir():
            if stale.is_file() and (
                stale.name in FIXED_FILES or (stale.name.startswith("test_") and stale.suffix == ".py")
            ):
                stale.unlink()
    out.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (out / name).write_text(content, encoding="utf-8")
    return Summary(
        operations=len(operations), tests=tests, modules=tuple(modules), skipped=tuple(skipped), notes=tuple(notes)
    )


def _base_url_notes(base_url: str) -> list[str]:
    """A default BASE_URL the client cannot use: none at all, or a relative one like Petstore's `/api/v3`, on
    which httpx raises at the first request. Either way API_BASE_URL has to be set, and the note says so."""
    if not base_url:
        return ["the document names no server: API_BASE_URL is required to run the suite"]
    if "://" not in base_url:
        return [f"the suite's default server URL {base_url!r} has no host: API_BASE_URL is required to run it"]
    return []
