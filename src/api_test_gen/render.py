"""Rendering of the generated files: Python literals, docstrings, request calls, and the Jinja2 templates."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .cases import Case, declares_required
from .ir import ApiModel
from .naming import plural, to_identifier, unique

TEMPLATES = Path(__file__).parent / "templates"
WIDTH = 100  # what a value inside a call may take of its line; the rest is for the keyword before it
LINE_LENGTH = 120  # ruff's line length: the limit for docstrings and for statements with nothing nested
INDENT = "    "
SKIP = "@pytest.mark.skip(reason="
MERGED_HEADERS = "headers={**auth_headers, "


def _width(text: str) -> int:
    """Columns the text takes, counted the way ruff's line-length rule counts them: a wide character is two."""
    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)


def literal(value: Any, indent: int = 0, width: int = WIDTH, prefix: int = 0, suffix: int = 0) -> str:
    """A JSON value as Python source: double-quoted strings, expanded one item per line only when it must be.

    `indent` is the indentation of the line the value starts on, `prefix` the width of what that line already
    holds before the value (a keyword, a key, an assignment) and `suffix` the width of what follows it on the
    same line (a comma, a bracket); the flat form is used when it fits `width` with them. A string that does not
    fit becomes parenthesised implicit concatenation, one chunk per line.
    """
    flat = _flat(value)
    if indent + prefix + _width(flat) + suffix <= width:
        return flat
    if not isinstance(value, dict | list | tuple):
        return _parenthesised(value, indent, width)
    pad = " " * (indent + 4)
    close = " " * indent
    if isinstance(value, dict):
        items = []
        for key, item in value.items():
            rendered_key = literal(key, indent + 4, width, suffix=3)  # `: (` follows a key whose value expands
            after_key = (1 if "\n" in rendered_key else _width(rendered_key)) + 2  # `"key": ` or `): `
            items.append(f"{pad}{rendered_key}: {literal(item, indent + 4, width, after_key, suffix=1)},")
        return "{\n" + "\n".join(items) + f"\n{close}}}"
    items = [f"{pad}{literal(item, indent + 4, width, suffix=1)}," for item in value]
    return "[\n" + "\n".join(items) + f"\n{close}]"


def _flat(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if value is None or isinstance(value, bool | int | float):
        return repr(value)
    if isinstance(value, dict):
        return "{" + ", ".join(f"{_flat(k)}: {_flat(v)}" for k, v in value.items()) + "}"
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_flat(v) for v in value) + "]"
    return json.dumps(str(value))


def _parenthesised(value: Any, indent: int, width: int) -> str:
    """A scalar too wide for its line, in parentheses on lines of its own: a string as implicit concatenation of
    chunks that fit, each escaped exactly as the whole string would have been, so the value stays the same."""
    pad = " " * (indent + 4)
    close = " " * indent
    if not isinstance(value, str):
        return f"(\n{pad}{_flat(value)}\n{close})"
    room = max(width - len(pad) - 2, 1)  # for the escaped text of one chunk, its quotes excluded
    chunks: list[str] = []
    current, used = "", 0
    for char in value:
        piece = json.dumps(char, ensure_ascii=False)[1:-1]
        span = _width(piece)
        if current and used + span > room:
            chunks.append(current)
            current, used = "", 0
        current += piece
        used += span
    chunks.append(current)
    return "(\n" + "".join(f'{pad}"{chunk}"\n' for chunk in chunks) + f"{close})"


def _escape_docstring(text: str) -> str:
    """`text` as it may stand inside a triple-quoted literal: backslashes doubled, a triple quote escaped."""
    return text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')


def _pieces(word: str, room: int) -> list[str]:
    """An escaped word in pieces no wider than `room`, cut only between escape units: `\\x` stays whole."""
    pieces: list[str] = []
    current, used, index = "", 0, 0
    while index < len(word):
        unit = word[index : index + 2] if word[index] == "\\" else word[index]
        index += len(unit)
        span = _width(unit)
        if current and used + span > room:
            pieces.append(current)
            current, used = "", 0
        current += unit
        used += span
    return [*pieces, current] if current else pieces


def _wrap(text: str, room: int) -> list[str]:
    """`text` escaped for a triple-quoted literal and wrapped to `room` columns: at spaces where it can, inside a
    word only when the word alone is wider than a line, and never inside an escape sequence."""
    lines: list[str] = []
    current, used = "", 0
    for word in text.split():
        for piece in _pieces(_escape_docstring(word), room):
            span = _width(piece)
            if current and used + 1 + span > room:
                lines.append(current)
                current, used = "", 0
            current, used = (f"{current} {piece}", used + 1 + span) if current else (piece, span)
    if current:
        lines.append(current)
    return lines


def docstring(text: str, indent: int = 0) -> str:
    """A docstring literal for `text`, escaped so nothing in it can end the literal early: on one line when that
    fits the line length at `indent`, otherwise the part before the summary on the first line, the summary
    wrapped under it, and the closing quotes on a line of their own."""
    text = " ".join(text.split())
    escaped = _escape_docstring(text)
    if escaped.endswith('"'):
        backslashes = len(escaped) - 1 - len(escaped[:-1].rstrip("\\"))
        if backslashes % 2 == 0:  # not escaped yet, so it would join the closing quotes
            escaped = escaped[:-1] + '\\"'
    single = f'"""{escaped}"""'
    if indent + _width(single) <= LINE_LENGTH:
        return single
    room = LINE_LENGTH - indent
    head, separator, summary = text.partition(": ")
    if separator and _width(_escape_docstring(head)) + 4 <= room:  # the opening quotes, the head, the colon
        lines = [f"{_escape_docstring(head)}:", *_wrap(summary, room)]
    else:
        lines = _wrap(text, room - 3)
    pad = " " * indent
    return "\n".join([f'"""{lines[0]}', *(f"{pad}{line}" for line in lines[1:]), f'{pad}"""'])


def doctext(text: str, indent: int = 0) -> str:
    """`text` escaped for a triple-quoted literal that goes on after it, wrapped to the line length at `indent`."""
    pad = " " * indent
    return f"\n{pad}".join(_wrap(text, LINE_LENGTH - indent - 3))


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        autoescape=False,
    )
    env.filters["literal"] = literal
    env.filters["docstring"] = docstring
    env.filters["doctext"] = doctext
    env.globals["LINE_LENGTH"] = LINE_LENGTH
    return env


def _path_lines(case: Case) -> tuple[list[str], str]:
    """One assignment per path parameter, and the path as an f-string that uses them."""
    if not case.path_params:
        return [], json.dumps(case.path)
    taken = {"client", "auth_headers", "response"}
    assignments: list[str] = []
    template = case.path
    for name, value in case.path_params.items():
        variable = unique(to_identifier(name), taken)
        assignments.append(f"{INDENT}{variable} = {literal(value, 4, prefix=len(variable) + 3)}")
        template = template.replace("{" + name + "}", "{" + variable + "}")
    return assignments, "f" + json.dumps(template)


def _keyword(name: str, value: Any) -> str:
    """One `name=<value>,` line of the request call, the value fitted behind its keyword."""
    return f"{INDENT * 2}{name}={literal(value, 8, prefix=len(name) + 1, suffix=1)},"


def request_block(case: Case) -> str:
    """The path assignments and the `response = client.request(...)` statement of one test."""
    headers = dict(case.headers)
    if case.body_kind == "text":
        headers["Content-Type"] = "text/plain"
    assignments, path = _path_lines(case)
    lines = [
        *assignments,
        f"{INDENT}response = client.request(",
        f"{INDENT * 2}{json.dumps(case.method)},",
        f"{INDENT * 2}{path},",
    ]
    if case.query:
        lines.append(_keyword("params", case.query))
    if case.uses_auth and headers:
        # The dict's own opening brace becomes the one in `headers={`, so the prefix is one shorter than it reads.
        merged = literal(headers, 8, prefix=len(MERGED_HEADERS) - 1, suffix=1)
        if merged.startswith("{\n"):  # expanded: auth_headers goes on a line of its own
            lines.append(f"{INDENT * 2}headers={{\n{INDENT * 3}**auth_headers,\n{merged[2:]},")
        else:
            lines.append(f"{INDENT * 2}{MERGED_HEADERS}{merged[1:]},")
    elif case.uses_auth:
        lines.append(f"{INDENT * 2}headers=auth_headers,")
    elif headers:
        lines.append(_keyword("headers", headers))
    if case.body_kind == "json":
        lines.append(_keyword("json", case.body))
    elif case.body_kind == "text":
        lines.append(_keyword("content", case.body))
    lines.append(f"{INDENT})")
    return "\n".join(lines)


def checks_block(case: Case, model_name: str | None) -> str:
    """The assertions of one test."""
    if case.expect == "unauthorized":
        lines = [f"{INDENT}assert response.status_code in (401, 403), response.text[:300]"]
    elif case.expect == "client_error":
        lines = [f"{INDENT}assert 400 <= response.status_code < 500, response.text[:300]"]
    elif case.expected_status is not None:
        lines = [f"{INDENT}assert response.status_code == {case.expected_status}, response.text[:300]"]
    else:
        lines = [f"{INDENT}assert 200 <= response.status_code < 300, response.text[:300]"]
    if case.expect == "success" and model_name:
        lines.append(f"{INDENT}TypeAdapter({model_name}).validate_python(response.json())")
    return "\n".join(lines)


def skip_decorator(reason: str) -> str:
    """The `@pytest.mark.skip(...)` line of a case the generator writes but cannot make run."""
    return f"{SKIP}{literal(reason, prefix=len(SKIP), suffix=1, width=LINE_LENGTH)})"


def _natural(text: str) -> list[Any]:
    """`text` split for ruff's natural order of digit runs: a run with a leading zero compares digit by digit, as
    a fraction, and sorts before any run without one; the others compare by value (length first, then digits)."""
    return [
        ((0, part) if part.startswith("0") else (1, len(part), part)) if part.isdigit() else part
        for part in re.split(r"(\d+)", text)
    ]


def _isort_key(name: str) -> tuple[int, list[Any], list[Any]]:
    """Where ruff's isort puts a member of a `from` import: constants (all caps, more than one letter) first,
    then classes, then the rest; within a group case-insensitively with digit runs in natural order, the
    original spelling deciding ties."""
    if len(name) > 1 and name.isupper():
        group = 0
    elif name[:1].isupper():
        group = 1
    else:
        group = 2
    return group, _natural(name.lower()), _natural(name)


def _model_imports(names: list[str]) -> str:
    if not names:
        return ""
    line = f"from models import {', '.join(names)}"
    if len(line) <= WIDTH:
        return line
    return "from models import (\n" + "".join(f"{INDENT}{name},\n" for name in names) + ")"


def render_module(
    *, tag: str, marker: str, cases: list[Case], model_names: dict[str, str], operations: int, source_name: str
) -> str:
    """One test module: the cases of every operation of one tag."""
    rendered = []
    validated: list[str] = []
    for case in cases:
        model_name = model_names.get(case.validate) if case.expect == "success" and case.validate else None
        if model_name and model_name not in validated:
            validated.append(model_name)
        rendered.append(
            {
                "name": case.name,
                "doc": case.doc,
                "uses_auth": case.uses_auth,
                "skip": skip_decorator(case.skip_reason) if case.skip_reason else "",
                "request": request_block(case),
                "checks": checks_block(case, model_name),
            }
        )
    template = _environment().get_template("test_module.py.j2")
    return template.render(
        module_doc=f"{tag}: {plural(operations, 'operation')} from {source_name}, generated by api-test-gen.",
        marker=marker,
        model_imports=_model_imports(sorted(validated, key=_isort_key)),
        cases=rendered,
    )


def render_conftest(api: ApiModel, *, source_name: str, base_url: str, markers: list[str]) -> str:
    template = _environment().get_template("conftest.py.j2")
    version = f" {api.version}" if api.version else ""
    heading = f"Fixtures for the suite generated from {source_name} ({api.title}{version})."
    return template.render(heading=heading, security=api.security, base_url=base_url, markers=markers)


def render_readme(
    api: ApiModel,
    *,
    source_name: str,
    summary_lines: list[str],
    env_lines: list[str],
    modules: list[str],
    out_hint: str,
    notes: Iterable[str] = (),
) -> str:
    template = _environment().get_template("README.md.j2")
    return template.render(
        source_name=source_name, title=api.title, version=api.version, security=api.security,
        summary_lines=summary_lines, env_lines=env_lines, modules=modules,
        has_models=bool(api.schemas), out_hint=out_hint, declares_required=declares_required(api),
        notes=list(notes),
    )
