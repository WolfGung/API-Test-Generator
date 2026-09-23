"""A request value for a schema: what the document gives first, a plain value of the right type otherwise."""

from __future__ import annotations

from typing import Any

from .ir import ApiModel, ref_name, required_names

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


def sample_for(schema: dict[str, Any], api: ApiModel, depth: int = 0, expanding: frozenset[str] = frozenset()) -> Any:
    """A request value for `schema`. `expanding` names the `$ref`s already on the way down this call's own
    recursion; re-entering one of them (a tree, a linked list, a self-referencing thread) stops there instead
    of recursing until `MAX_DEPTH`, which stays only as a backstop for non-`$ref` recursion.
    """
    if depth > MAX_DEPTH:
        return None
    ref = schema.get("$ref")
    name = ref_name(ref) if ref is not None else None
    if name is not None:
        if name in expanding:
            return None  # a cycle through this reference: no finite sample to offer
        expanding = expanding | {name}
    schema = api.resolve(schema)
    # The document's example wins: `example`, the first of `examples`, then `default` and `const`, then the enum.
    if "example" in schema:
        return schema["example"]
    examples = schema.get("examples")
    if isinstance(examples, list) and examples:
        return examples[0]
    if isinstance(examples, dict) and examples:
        first = next(iter(examples.values()))
        return first.get("value", first) if isinstance(first, dict) else first
    for key in ("default", "const"):
        if key in schema:
            return schema[key]
    if schema.get("enum"):
        return schema["enum"][0]
    if "allOf" in schema:
        values = [sample_for(part, api, depth + 1, expanding) for part in schema["allOf"]]
        merged: dict[str, Any] = {}
        has_dict = False
        for value in values:
            if isinstance(value, dict):
                has_dict = True
                merged.update(value)
        if has_dict:
            return merged
        # No part sampled to an object (e.g. an enum `$ref` plus a sibling `description`): the merge has
        # nothing to merge, so fall back to whatever scalar the first resolvable part offers.
        return next((value for value in values if value is not None), None)
    for combinator in ("anyOf", "oneOf"):
        if combinator in schema:
            options = [o for o in schema[combinator] if api.resolve(o).get("type") != "null"] or schema[combinator]
            return sample_for(options[0], api, depth + 1, expanding) if options else None
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
        item = sample_for(schema["items"], api, depth + 1, expanding) if "items" in schema else "string"
        if item is None:
            return []  # e.g. a list of a self-referencing type: no finite item, so an empty list stands in
        return [item] * max(1, int(schema.get("minItems") or 0))
    if kind == "object":
        return _object(schema, api, depth, expanding, name)
    return None


def required_fields(schema: dict[str, Any], api: ApiModel) -> list[str]:
    """Every field the schema requires: `allOf` parts are resolved through `$ref` and flattened recursively,
    in document order, without duplicates. This mirrors exactly what `sample_for`'s own `allOf` merge puts
    into the sample, so the sampler and the negative cases generated from it agree on what "required" means.
    """
    ref = schema.get("$ref")
    name = ref_name(ref) if ref is not None else None
    schema = api.resolve(schema)
    fields: list[str] = []
    if "allOf" in schema:
        for part in schema["allOf"]:
            for field in required_fields(part, api):
                if field not in fields:
                    fields.append(field)
        return fields
    for field in required_names(schema, name):
        if field not in fields:
            fields.append(field)
    return fields


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


def has_example(schema: dict[str, Any]) -> bool:
    """Whether the (resolved) schema gives a value of its own: an example, a default or a const. An optional body
    field or parameter is sent only then."""
    return any(key in schema for key in ("example", "examples", "default", "const"))


def _object(
    schema: dict[str, Any], api: ApiModel, depth: int, expanding: frozenset[str], name: str | None
) -> dict[str, Any]:
    properties = schema.get("properties") or {}
    required = [field for field in required_names(schema, name) if field in properties]
    optional = [name for name in properties if name not in required and has_example(api.resolve(properties[name]))]
    wanted = required + optional
    return {name: sample_for(properties[name], api, depth + 1, expanding) for name in wanted}
