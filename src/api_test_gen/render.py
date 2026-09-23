"""Rendering of the generated files: Python literals, request calls, and the Jinja2 templates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .cases import Case
from .ir import ApiModel
from .naming import to_identifier, unique

TEMPLATES = Path(__file__).parent / "templates"
WIDTH = 100
INDENT = "    "


def literal(value: Any, indent: int = 0, width: int = WIDTH) -> str:
    """A JSON value as Python source: double-quoted strings, expanded one item per line only when it must be."""
    flat = _flat(value)
    if len(flat) + indent <= width or not isinstance(value, dict | list | tuple):
        return flat
    pad = " " * (indent + 4)
    close = " " * indent
    if isinstance(value, dict):
        items = [f"{pad}{_flat(key)}: {literal(item, indent + 4, width)}," for key, item in value.items()]
        return "{\n" + "\n".join(items) + f"\n{close}}}"
    items = [f"{pad}{literal(item, indent + 4, width)}," for item in value]
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
        assignments.append(f"{INDENT}{variable} = {literal(value, 4)}")
        template = template.replace("{" + name + "}", "{" + variable + "}")
    return assignments, "f" + json.dumps(template)


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
        lines.append(f"{INDENT * 2}params={literal(case.query, 8)},")
    if case.uses_auth and headers:
        merged = literal(headers, 8)
        if merged.startswith("{\n"):  # expanded: auth_headers goes on a line of its own
            lines.append(f"{INDENT * 2}headers={{\n{INDENT * 3}**auth_headers,\n{merged[2:]},")
        else:
            lines.append(f"{INDENT * 2}headers={{**auth_headers, {merged[1:]},")
    elif case.uses_auth:
        lines.append(f"{INDENT * 2}headers=auth_headers,")
    elif headers:
        lines.append(f"{INDENT * 2}headers={literal(headers, 8)},")
    if case.body_kind == "json":
        lines.append(f"{INDENT * 2}json={literal(case.body, 8)},")
    elif case.body_kind == "text":
        lines.append(f"{INDENT * 2}content={literal(case.body, 8)},")
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
        model_name = model_names.get(case.validate) if case.validate else None
        if model_name and model_name not in validated:
            validated.append(model_name)
        rendered.append(
            {
                "name": case.name,
                "doc": case.doc,
                "uses_auth": case.uses_auth,
                "skip_reason": case.skip_reason,
                "request": request_block(case),
                "checks": checks_block(case, model_name if case.expect == "success" else None),
            }
        )
    template = _environment().get_template("test_module.py.j2")
    return template.render(
        tag=tag, marker=marker, operations=operations, source_name=source_name,
        model_imports=_model_imports(sorted(validated)), cases=rendered,
    )


def render_conftest(api: ApiModel, *, source_name: str, base_url: str, markers: list[str]) -> str:
    template = _environment().get_template("conftest.py.j2")
    return template.render(
        source_name=source_name, title=api.title, version=api.version, security=api.security,
        base_url=base_url, markers=markers,
    )


def render_readme(
    api: ApiModel,
    *,
    source_name: str,
    summary_lines: list[str],
    env_lines: list[str],
    modules: list[str],
    out_hint: str,
) -> str:
    template = _environment().get_template("README.md.j2")
    return template.render(
        source_name=source_name, title=api.title, version=api.version, security=api.security,
        summary_lines=summary_lines, env_lines=env_lines, modules=modules,
        has_models=bool(api.schemas), out_hint=out_hint,
    )
