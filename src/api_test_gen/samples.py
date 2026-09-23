"""A request value for a schema: what the document gives first, a plain value of the right type otherwise."""

from __future__ import annotations

from typing import Any

from .ir import ApiModel

FORMAT_SAMPLES: dict[str, Any] = {
    "email": "user@example.com",
    "date": "2024-01-31",
    "date-time": "2024-01-31T12:00:00Z",
    "time": "12:00:00",
    "uuid": "123e4567-e89b-12d3-a456-426614174000",
    "uri": "https://example.com/resource",
    "url": "https://example.com/resource",
    "hostname": "example.com",
    "ipv4": "192.0.2.1",
    "ipv6": "2001:db8::1",
    "password": "correct-horse-battery-staple",
    "byte": "c3RyaW5n",
    "binary": "string",
}
MAX_DEPTH = 8


def sample_for(schema: dict[str, Any], api: ApiModel, depth: int = 0) -> Any:
    if depth > MAX_DEPTH:
        return None
    schema = api.resolve(schema)
    for key in ("example", "default", "const"):
        if key in schema:
            return schema[key]
    examples = schema.get("examples")
    if isinstance(examples, list) and examples:
        return examples[0]
    if isinstance(examples, dict) and examples:
        first = next(iter(examples.values()))
        return first.get("value", first) if isinstance(first, dict) else first
    if schema.get("enum"):
        return schema["enum"][0]
    if "allOf" in schema:
        merged: dict[str, Any] = {}
        for part in schema["allOf"]:
            value = sample_for(part, api, depth + 1)
            if isinstance(value, dict):
                merged.update(value)
        return merged
    for combinator in ("anyOf", "oneOf"):
        if combinator in schema:
            options = [o for o in schema[combinator] if api.resolve(o).get("type") != "null"] or schema[combinator]
            return sample_for(options[0], api, depth + 1) if options else None
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), None)
    if kind is None:
        kind = "object" if "properties" in schema else "array" if "items" in schema else None
    if kind == "string":
        return _string(schema)
    if kind == "integer":
        return int(_number(schema))
    if kind == "number":
        return float(_number(schema))
    if kind == "boolean":
        return True
    if kind == "array":
        item = sample_for(schema["items"], api, depth + 1) if "items" in schema else "string"
        return [item] * max(1, int(schema.get("minItems") or 0))
    if kind == "object":
        return _object(schema, api, depth)
    return None


def _string(schema: dict[str, Any]) -> str:
    fmt = schema.get("format")
    if fmt in FORMAT_SAMPLES:
        return FORMAT_SAMPLES[fmt]
    value = "string"
    minimum = int(schema.get("minLength") or 0)
    if minimum > len(value):
        value = "x" * minimum
    maximum = schema.get("maxLength")
    if maximum is not None and len(value) > int(maximum):
        value = value[: int(maximum)]
    return value


def _number(schema: dict[str, Any]) -> float:
    value = 1.0
    minimum = schema.get("minimum")
    exclusive = schema.get("exclusiveMinimum")
    if isinstance(exclusive, bool):  # OpenAPI 3.0 spelling: a flag on `minimum`
        if exclusive and minimum is not None:
            value = float(minimum) + 1
        elif minimum is not None:
            value = float(minimum)
    elif exclusive is not None:  # JSON Schema 2020-12 spelling: a number of its own
        value = float(exclusive) + 1
    elif minimum is not None:
        value = float(minimum)
    maximum = schema.get("maximum")
    if maximum is not None and value > float(maximum):
        value = float(maximum)
    return value


def _has_example(schema: dict[str, Any]) -> bool:
    return any(key in schema for key in ("example", "examples", "default", "const"))


def _object(schema: dict[str, Any], api: ApiModel, depth: int) -> dict[str, Any]:
    properties = schema.get("properties") or {}
    required = [name for name in schema.get("required") or [] if name in properties]
    optional = [name for name in properties if name not in required and _has_example(api.resolve(properties[name]))]
    wanted = required + optional
    return {name: sample_for(properties[name], api, depth + 1) for name in wanted}
