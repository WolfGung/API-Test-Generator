"""Read an OpenAPI 3.0 or 3.1 document into the intermediate representation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .ir import NO_SECURITY, ApiModel, Body, Operation, Parameter, Response, Security, SpecError, is_json_media, ref_to
from .naming import to_class_name, to_identifier, unique

METHODS = ("get", "put", "post", "delete", "patch", "head", "options")
COMPONENTS = "#/components/"


def load_document(path: Path) -> dict[str, Any]:
    """JSON by extension, YAML otherwise; a mapping at the top or a SpecError."""
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise SpecError(f"{path}: cannot parse: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecError(f"{path}: the document is not a mapping")
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
        raise SpecError(f"{path}: expected an OpenAPI 3.x document, found openapi={version!r}")
    components = doc.get("components") or {}
    schemas: dict[str, dict[str, Any]] = dict(components.get("schemas") or {})
    info = doc.get("info") or {}
    document_security = doc.get("security")
    operations: list[Operation] = []
    taken_ids: set[str] = set()
    for raw_path, item in (doc.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        shared = [_parameter(p, components) for p in item.get("parameters") or []]
        for method, raw_op in item.items():  # document order, so the suite reads like the document
            if method not in METHODS or not isinstance(raw_op, dict):
                continue
            own = [_parameter(p, components) for p in raw_op.get("parameters") or []]
            operation_id = unique(to_identifier(raw_op.get("operationId") or f"{method} {raw_path}"), taken_ids)
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
        security=_security(components.get("securitySchemes") or {}),
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


def _parameter(raw: dict[str, Any], components: dict[str, Any]) -> Parameter | None:
    raw = _component(raw, components)
    location = raw.get("in")
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
        examples=_examples(raw),
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


def _security(schemes: dict[str, Any]) -> Security:
    for name, scheme in schemes.items():
        kind = scheme.get("type")
        if kind == "http" and str(scheme.get("scheme", "")).lower() == "bearer":
            return Security(kind="bearer", name=name, header="Authorization")
        if kind == "http" and str(scheme.get("scheme", "")).lower() == "basic":
            return Security(kind="basic", name=name, header="Authorization")
        if kind == "apiKey" and scheme.get("in") == "header":
            return Security(kind="apiKey", name=name, header=str(scheme["name"]), location="header")
    return NO_SECURITY


def _base_url(servers: list[dict[str, Any]]) -> str:
    if not servers:
        return ""
    server = servers[0]
    url = str(server.get("url") or "")
    for variable, spec in (server.get("variables") or {}).items():
        url = url.replace("{" + variable + "}", str(spec.get("default", "")))
    return url
