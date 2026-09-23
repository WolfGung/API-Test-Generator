"""Read an OpenAPI 3.0 or 3.1 document into the intermediate representation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from .ir import (
    NO_SECURITY,
    UNSUPPORTED_SECURITY,
    ApiModel,
    Body,
    Operation,
    Parameter,
    Response,
    Security,
    SpecError,
    is_json_media,
    ref_to,
)
from .naming import to_class_name, to_identifier, unique

METHODS = ("get", "put", "post", "delete", "patch", "head", "options")
COMPONENTS = "#/components/"


class _Loader(yaml.SafeLoader):
    """SafeLoader with YAML 1.2 scalars, which is the YAML an OpenAPI document is written in: no implicit
    timestamps, and only `true`/`false` are booleans. An unquoted `2024-01-31T12:00:00Z`, `on` or `yes` stays
    the string the document shows, so an example is sent as written and an enum of dates becomes a Literal of
    strings that imports; `required: true`, integers, floats and null keep their types."""


_UNTYPED = {"tag:yaml.org,2002:timestamp", "tag:yaml.org,2002:bool"}
_Loader.yaml_implicit_resolvers = {
    first: [(tag, regexp) for tag, regexp in resolvers if tag not in _UNTYPED]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Loader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
)


def load_document(path: Path) -> dict[str, Any]:
    """JSON by extension, YAML otherwise; a mapping at the top or a SpecError. The message names the cause; the
    command line puts the file in front of it."""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SpecError("not UTF-8 text") from exc
    try:
        data = json.loads(text) if path.suffix.lower() == ".json" else yaml.load(text, Loader=_Loader)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise SpecError(f"cannot parse: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecError("the document is not a mapping")
    return data


def is_json(content_type: str) -> bool:
    return is_json_media(content_type)


def register_schema(schemas: dict[str, dict[str, Any]], name: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Give an inline schema a name under components so the model generator can write a class for it."""
    taken = set(schemas)
    unique_name = unique(name, taken)
    schemas[unique_name] = schema
    return ref_to(unique_name)


def load_openapi(path: Path) -> ApiModel:
    doc = load_document(path)
    version = str(doc.get("openapi", ""))
    if not version.startswith("3."):
        raise SpecError(f"expected an OpenAPI 3.x document, found openapi={version!r}")
    components = doc.get("components") or {}
    schemas: dict[str, dict[str, Any]] = dict(components.get("schemas") or {})
    info = doc.get("info") or {}
    document_security = doc.get("security")
    operations: list[Operation] = []
    taken_ids: set[str] = set()
    security, notes = _security(components.get("securitySchemes") or {})
    for raw_path, item in (doc.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        shared = [_parameter(p, components, notes, raw_path) for p in item.get("parameters") or []]
        for method, raw_op in item.items():  # document order, so the suite reads like the document
            if method not in METHODS or not isinstance(raw_op, dict):
                continue
            operation_id = unique(to_identifier(raw_op.get("operationId") or f"{method} {raw_path}"), taken_ids)
            own = [_parameter(p, components, notes, operation_id) for p in raw_op.get("parameters") or []]
            class_name = to_class_name(operation_id)
            requirements = raw_op.get("security", document_security)
            operations.append(
                Operation(
                    operation_id=operation_id,
                    method=method.upper(),
                    path=raw_path,
                    tag=str((raw_op.get("tags") or ["default"])[0]),
                    summary=str(raw_op.get("summary") or raw_op.get("description") or "").strip(),
                    parameters=_merge_parameters(shared, own),
                    body=_body(raw_op.get("requestBody"), components, schemas, class_name),
                    responses=tuple(
                        _response(str(status), raw, components, schemas, class_name)
                        for status, raw in (raw_op.get("responses") or {}).items()
                    ),
                    secured=bool(requirements) and any(bool(r) for r in requirements),
                )
            )
    return ApiModel(
        title=str(info.get("title") or path.stem),
        version=str(info.get("version") or ""),
        base_url=_base_url(doc.get("servers") or []),
        operations=tuple(operations),
        schemas=schemas,
        security=security,
        notes=tuple(notes),
    )


def _component(raw: dict[str, Any], components: dict[str, Any]) -> dict[str, Any]:
    """Resolve a `$ref` into #/components/{parameters,requestBodies,responses}; pass other dicts through."""
    ref = raw.get("$ref")
    if not ref:
        return raw
    if not ref.startswith(COMPONENTS):
        raise SpecError(f"unsupported reference {ref!r}")
    section, _, name = ref[len(COMPONENTS) :].partition("/")
    try:
        return components[section][name]
    except KeyError as exc:
        raise SpecError(f"unresolved reference {ref!r}") from exc


def _examples(holder: dict[str, Any]) -> tuple[Any, ...]:
    """`example` and `examples` (a mapping of named examples, or a plain list) as one tuple."""
    found: list[Any] = []
    if "example" in holder:
        found.append(holder["example"])
    examples = holder.get("examples")
    if isinstance(examples, dict):
        found.extend(e.get("value") if isinstance(e, dict) and "value" in e else e for e in examples.values())
    elif isinstance(examples, list):
        found.extend(examples)
    return tuple(found)


def _resolved(schema: dict[str, Any], components: dict[str, Any]) -> dict[str, Any]:
    """The schema behind a `$ref` into #/components/schemas, any depth; an inline schema as it is."""
    hops = 0
    while "$ref" in schema:
        schema = _component(schema, components)
        hops += 1
        if hops > 50:
            raise SpecError(f"reference loop at {schema.get('$ref')!r}")
    return schema


def _parameter(raw: dict[str, Any], components: dict[str, Any], notes: list[str], where: str) -> Parameter | None:
    """A path, query or header parameter; a cookie parameter is dropped with a note naming it under `where`
    (the operation, or the path for a path-level parameter), since nothing in the suite would send it."""
    raw = _component(raw, components)
    location = raw.get("in")
    if location == "cookie":
        notes.append(f"{where}: cookie parameter {str(raw.get('name'))!r} is not supported and is not sent")
        return None
    if location not in ("path", "query", "header"):
        return None
    schema = raw.get("schema")
    if schema is None:
        content = raw.get("content") or {}
        schema = next(iter(content.values()), {}).get("schema", {}) if content else {}
    return Parameter(
        name=str(raw["name"]),
        location=location,
        required=bool(raw.get("required")) or location == "path",
        schema=dict(schema),
        # The parameter's own example first; else the schema's, where OpenAPI 3.1 documents (FastAPI's among
        # them) keep a parameter's examples.
        examples=_examples(raw) or _examples(_resolved(schema, components)),
    )


def _merge_parameters(shared: list[Parameter | None], own: list[Parameter | None]) -> tuple[Parameter, ...]:
    merged: dict[tuple[str, str], Parameter] = {}
    for parameter in [*shared, *own]:
        if parameter is not None:
            merged[(parameter.name, parameter.location)] = parameter
    return tuple(merged.values())


def _pick_content(content: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    for content_type, media in content.items():
        if is_json(content_type):
            return content_type, media or {}
    for content_type, media in content.items():
        return content_type, media or {}
    return None


def _named(schema: dict[str, Any], schemas: dict[str, dict[str, Any]], name: str, content_type: str) -> dict[str, Any]:
    """An inline JSON schema with substance gets a name; a `$ref`, an empty schema or a non-JSON one is left alone."""
    if not schema or "$ref" in schema or not is_json(content_type):
        return schema
    return register_schema(schemas, name, schema)


def _body(raw: Any, components: dict[str, Any], schemas: dict[str, dict[str, Any]], class_name: str) -> Body | None:
    if not isinstance(raw, dict):
        return None
    raw = _component(raw, components)
    picked = _pick_content(raw.get("content") or {})
    if picked is None:
        return None
    content_type, media = picked
    schema = _named(dict(media.get("schema") or {}), schemas, f"{class_name}Request", content_type)
    return Body(content_type=content_type, schema=schema, required=bool(raw.get("required")), examples=_examples(media))


def _response(
    status: str, raw: Any, components: dict[str, Any], schemas: dict[str, dict[str, Any]], class_name: str
) -> Response:
    raw = _component(raw, components) if isinstance(raw, dict) else {}
    description = str(raw.get("description") or "")
    picked = _pick_content(raw.get("content") or {})
    if picked is None:
        return Response(status=status, schema=None, description=description)
    content_type, media = picked
    schema = _named(dict(media.get("schema") or {}), schemas, f"{class_name}Response", content_type)
    return Response(status=status, schema=schema or None, content_type=content_type, description=description)


def _security(schemes: dict[str, Any]) -> tuple[Security, list[str]]:
    """The first supported scheme (bearer, basic, an API key in a header), with no notes; or no security and one
    note per scheme the suite cannot send - an OAuth flow, digest, a key in a query string or a cookie."""
    for name, scheme in schemes.items():
        kind = scheme.get("type")
        if kind == "http" and str(scheme.get("scheme", "")).lower() == "bearer":
            return Security(kind="bearer", name=name, header="Authorization"), []
        if kind == "http" and str(scheme.get("scheme", "")).lower() == "basic":
            return Security(kind="basic", name=name, header="Authorization"), []
        if kind == "apiKey" and scheme.get("in") == "header":
            return Security(kind="apiKey", name=name, header=str(scheme["name"]), location="header"), []
    notes = [
        UNSUPPORTED_SECURITY.format(what=f"{name} ({_describe(scheme)}) security") for name, scheme in schemes.items()
    ]
    return NO_SECURITY, notes


def _describe(scheme: dict[str, Any]) -> str:
    """`oauth2`, `http digest`, `apiKey in query`: the scheme as the document declares it."""
    kind = str(scheme.get("type") or "")
    if kind == "http":
        return f"http {scheme.get('scheme', '')}".strip()
    if kind == "apiKey":
        return f"apiKey in {scheme.get('in', '')}".strip()
    return kind


def _base_url(servers: list[dict[str, Any]]) -> str:
    if not servers:
        return ""
    server = servers[0]
    url = str(server.get("url") or "")
    for variable, spec in (server.get("variables") or {}).items():
        url = url.replace("{" + variable + "}", str(spec.get("default", "")))
    return url
