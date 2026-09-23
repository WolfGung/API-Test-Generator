"""Pydantic models for the named schemas of a document, as Python source."""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from .ir import ApiModel, SpecError, ref_name, required_names
from .naming import to_class_name, to_identifier, unique
from .openapi import register_schema

DOC_LIMIT = 100


def generate_models(api: ApiModel, source_name: str) -> str:
    schemas = copy.deepcopy(api.schemas)
    _hoist_inline_objects(schemas)
    names = _class_names(schemas)
    writer = _Writer(schemas, names)
    class_order = [name for name in schemas if writer.is_class(name)]
    alias_names = [name for name in schemas if name not in class_order]
    blocks = [writer.class_block(name) for name in class_order]
    blocks += writer.alias_blocks(alias_names)
    if class_order:
        rebuilt = ", ".join(names[name] for name in class_order)
        header = f"for _model in ({rebuilt},):"
        if len(header) > 100:
            header = "for _model in (\n" + "".join(f"    {names[name]},\n" for name in class_order) + "):"
        blocks.append([header, "    _model.model_rebuild()"])
    lines = [f'"""Models for {source_name}: one class per named schema, used to validate response bodies."""', ""]
    if blocks:
        lines += ["from __future__ import annotations", ""]
    if writer.typing_used:
        lines += [f"from typing import {', '.join(sorted(writer.typing_used))}", ""]
    if writer.pydantic_used:
        lines += [f"from pydantic import {', '.join(sorted(writer.pydantic_used))}", ""]
    for index, block in enumerate(blocks):
        # A class needs two blank lines before it (E302), and so does whatever follows one (E305); the import
        # section already ends in a blank line, so only the first block needs one more - and only when it is
        # itself a class. A document with no classes at all opens straight on its first alias, one blank line
        # after the imports, which is what isort's own formatting expects there (I001).
        if index == 0 and not class_order:
            lines += [*block, ""]
        else:
            lines += ["", *block, ""]
    return "\n".join(lines).rstrip("\n") + "\n"


# Names a class must not take: what the module imports, and the constants a schema called `none` or `true`
# would otherwise shadow (`class None` is a SyntaxError).
RESERVED = {"Any", "Literal", "BaseModel", "ConfigDict", "Field", "TypeAdapter", "None", "True", "False"}

# Field names that would shadow something Pydantic's own machinery needs: an annotation builtin used in a type
# expression, or an attribute BaseModel itself defines. Written out rather than read from `dir(BaseModel)` so the
# generated code does not change across pydantic versions.
ANNOTATION_BUILTINS = ("list", "dict", "str", "int", "float", "bool")
BASEMODEL_ATTRS = (
    "copy", "dict", "json", "schema", "schema_json", "validate", "construct",
    "parse_obj", "parse_raw", "parse_file", "from_orm", "update_forward_refs", "fields",
)


def _is_nullable(schema: dict[str, Any]) -> bool:
    """`nullable: true` (OpenAPI 3.0) or a `type` list containing "null" (3.1 / plain JSON Schema)."""
    return bool(schema.get("nullable")) or (isinstance(schema.get("type"), list) and "null" in schema["type"])


def _has_type(part: Any) -> bool:
    """Whether `type_of` can derive a real type from this allOf part, rather than falling back to `Any`."""
    keywords = {"$ref", "type", "enum", "properties", "allOf", "anyOf", "oneOf"}
    return isinstance(part, dict) and bool(keywords & part.keys())


def _safe_field_name(prop_name: str, taken: set[str]) -> tuple[str, bool]:
    """A snake_case identifier that cannot shadow an annotation builtin, a BaseModel attribute, or a `model_*`
    name - plus whether the class also needs `protected_namespaces=()`. Pydantic's own check for a `model_*`
    name matches by prefix, so a trailing underscore alone does not always clear it: `model_dump` becomes
    `model_dump_`, which still starts with the protected `model_dump` and would otherwise still warn."""
    name = to_identifier(prop_name)
    shadows_model_namespace = name.startswith("model_")
    if name in ANNOTATION_BUILTINS or name in BASEMODEL_ATTRS or shadows_model_namespace:
        name += "_"
    return unique(name, taken), shadows_model_namespace


def _class_names(schemas: dict[str, dict[str, Any]]) -> dict[str, str]:
    taken: set[str] = set(RESERVED)  # a schema called "Field" must not shadow pydantic's
    return {name: unique(to_class_name(name), taken) for name in schemas}


def class_names(schemas: dict[str, dict[str, Any]]) -> dict[str, str]:
    """The class or alias name the models module uses for each named schema, in schema order."""
    return _class_names(schemas)


def _hoist_inline_objects(schemas: dict[str, dict[str, Any]]) -> None:
    """Give every inline object nested inside a named schema a name of its own, so it becomes a class."""
    queue = list(schemas.items())
    while queue:
        name, schema = queue.pop(0)
        base = to_class_name(name)
        _hoist_properties(schema, base, schemas, queue)
        if isinstance(schema.get("items"), dict):
            _hoist(schema, "items", schema["items"], f"{base}Item", schemas, queue)
        for combinator in ("allOf", "anyOf", "oneOf"):
            for index, part in enumerate(schema.get(combinator) or []):
                if combinator == "allOf" and _is_merged(part):
                    # The part's properties become the class's own (see `_Writer._flatten`), so hoisting the
                    # part as well would leave an `…Option` class nothing references; only what is nested
                    # inside it needs a name, and it takes the class's, where the property ends up.
                    _hoist_merged_part(part, base, schemas, queue)
                    continue
                _hoist(schema[combinator], index, part, f"{base}Option{index + 1}", schemas, queue)


def _is_merged(part: Any) -> bool:
    """Whether an `allOf` part of a named schema is an inline object whose properties `_Writer._flatten` merges
    into the class (a `$ref` part is merged too, but points at a class of its own and is never hoisted)."""
    return isinstance(part, dict) and "$ref" not in part and "properties" in part


def _hoist_merged_part(part: dict[str, Any], base: str, schemas: dict[str, dict[str, Any]], queue: list) -> None:
    """Name the inline objects inside an `allOf` part that is merged into the class called `base`: its
    properties, and those of its own merged `allOf` parts, which `_flatten` folds in the same way."""
    _hoist_properties(part, base, schemas, queue)
    for nested in part.get("allOf") or []:
        if _is_merged(nested):
            _hoist_merged_part(nested, base, schemas, queue)


def _hoist_properties(schema: dict[str, Any], base: str, schemas: dict[str, dict[str, Any]], queue: list) -> None:
    for prop_name, prop in list((schema.get("properties") or {}).items()):
        _hoist(schema["properties"], prop_name, prop, f"{base}{to_class_name(prop_name)}", schemas, queue)


def _hoist(
    container: Any, key: Any, schema: Any, new_name: str, schemas: dict[str, dict[str, Any]], queue: list
) -> None:
    if not isinstance(schema, dict) or "$ref" in schema:
        return
    if "properties" in schema:
        ref = register_schema(schemas, new_name, schema)
        # The class itself is never "nullable" - only a use site is - so a nullable inline object is hoisted into
        # a plain class, and the nullability stays here, at the one place that referenced it.
        container[key] = {"anyOf": [ref, {"type": "null"}]} if _is_nullable(schema) else ref
        queue.append((ref_name(ref["$ref"]), schema))
        return
    if isinstance(schema.get("items"), dict):
        _hoist(schema, "items", schema["items"], f"{new_name}Item", schemas, queue)
    for combinator in ("allOf", "anyOf", "oneOf"):
        for index, part in enumerate(schema.get(combinator) or []):
            _hoist(schema[combinator], index, part, f"{new_name}Option{index + 1}", schemas, queue)


def _literal(value: Any) -> str:
    """A string as a double-quoted literal written as itself (`ensure_ascii` would turn a character outside the
    BMP into a surrogate pair, which is another string in Python source); anything else as its repr."""
    return json.dumps(value, ensure_ascii=False) if isinstance(value, str) else repr(value)


_STRING_LITERAL = re.compile(r'"(?:[^"\\]|\\.)*"')
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _mentions(type_expr: str, alias_class_names: dict[str, str]) -> set[str]:
    """Schema names an alias's type expression depends on; identifier-shaped text inside string literals (an
    enum value that happens to spell another alias's name, say) is not a dependency."""
    without_strings = _STRING_LITERAL.sub("", type_expr)
    return {alias_class_names[word] for word in _IDENTIFIER.findall(without_strings) if word in alias_class_names}


def _docline(schema: dict[str, Any], fallback: str) -> str:
    text = str(schema.get("description") or "").strip().splitlines()
    line = text[0].strip() if text else fallback
    line = line.replace('"', "'").replace("\\", "/")
    return line if len(line) <= DOC_LIMIT else line[: DOC_LIMIT - 1] + "…"


class _Writer:
    def __init__(self, schemas: dict[str, dict[str, Any]], names: dict[str, str]) -> None:
        self.schemas = schemas
        self.names = names
        self.typing_used: set[str] = set()
        self.pydantic_used: set[str] = set()

    def any(self) -> str:
        self.typing_used.add("Any")
        return "Any"

    def resolve(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Follow `$ref` to the named schema, any depth, with the same guards as `ApiModel.resolve`: a name the
        document does not have and a pure `$ref` cycle are document errors, not a KeyError or an endless loop."""
        hops = 0
        while "$ref" in schema:
            schema = self.schemas[self.target(schema["$ref"])]
            hops += 1
            if hops > 50:
                raise SpecError(f"reference loop at {schema.get('$ref')!r}")
        return schema

    def target(self, ref: str) -> str:
        """The schema name a `$ref` points at, refused when the document has no schema of that name."""
        name = ref_name(ref)
        if name not in self.schemas:
            raise SpecError(f"unresolved reference {ref!r}")
        return name

    def is_class(self, name: str) -> bool:
        """A class is written for a schema with properties, or an allOf with an object part (after resolving
        $refs, has properties or type: object, or is itself composed from one by the same rule); anything else
        is an alias."""
        schema = self.schemas[name]
        if "properties" in schema:
            return True
        return "allOf" in schema and any(self._is_object_part(part, frozenset()) for part in schema["allOf"])

    def _is_object_part(self, part: Any, visited: frozenset[str]) -> bool:
        """Whether an allOf part is - or, through $ref and its own nested allOf, resolves to - an object
        schema. `visited` holds the $ref names already unwound on this path, so a $ref cycle ends here rather
        than recursing forever (a Pet <-> Tagged style mutual allOf, not just a straight self-reference)."""
        if not isinstance(part, dict):
            return False
        if "$ref" in part:
            name = ref_name(part["$ref"])
            if name in visited:
                return False
            visited = visited | {name}
        resolved = self.resolve(part)
        if "properties" in resolved or resolved.get("type") == "object":
            return True
        return "allOf" in resolved and any(self._is_object_part(p, visited) for p in resolved["allOf"])

    def type_of(self, schema: Any) -> str:
        if not isinstance(schema, dict) or not schema:
            return self.any()
        if "$ref" in schema:
            expr = self.names[self.target(schema["$ref"])]
            return f"{expr} | None" if _is_nullable(self.resolve(schema)) else expr
        nullable = bool(schema.get("nullable"))
        if "allOf" in schema:
            parts = [part for part in schema["allOf"] if _has_type(part)]
            expr = self.type_of(parts[0]) if parts else f"dict[str, {self.any()}]"
        elif "anyOf" in schema or "oneOf" in schema:
            exprs: list[str] = []
            for option in schema.get("anyOf") or schema.get("oneOf") or []:
                if isinstance(option, dict) and self.resolve(option).get("type") == "null":
                    nullable = True
                    continue
                expr = self.type_of(option)
                if expr not in exprs:
                    exprs.append(expr)
            expr = " | ".join(exprs) if exprs else self.any()
        elif isinstance(schema.get("type"), list):
            kinds = [k for k in schema["type"] if k != "null"]
            nullable = nullable or len(kinds) < len(schema["type"])
            exprs = list(dict.fromkeys(self.type_of({**schema, "type": kind}) for kind in kinds))
            expr = " | ".join(exprs) if exprs else self.any()
        elif "enum" in schema or "const" in schema:
            declared = schema["enum"] if "enum" in schema else [schema["const"]]
            values = [v for v in declared if v is not None]
            nullable = nullable or len(values) < len(declared)
            self.typing_used.add("Literal")
            expr = f"Literal[{', '.join(_literal(v) for v in values)}]" if values else self.any()
        else:
            kind = schema.get("type")
            if kind == "string":
                expr = "str"
            elif kind == "integer":
                expr = "int"
            elif kind == "number":
                expr = "float"
            elif kind == "boolean":
                expr = "bool"
            elif kind == "array":
                expr = f"list[{self.type_of(schema['items'])}]" if "items" in schema else f"list[{self.any()}]"
            elif kind == "object" or "properties" in schema:
                extra = schema.get("additionalProperties")
                value = self.type_of(extra) if isinstance(extra, dict) and extra else self.any()
                expr = f"dict[str, {value}]"
            else:
                expr = self.any()
        return f"{expr} | None" if nullable and not expr.endswith("| None") else expr

    def _flatten(
        self, schema: dict[str, Any], visited: frozenset[str] = frozenset(), name: str | None = None
    ) -> tuple[dict[str, Any], list[str]]:
        """Properties and required names, with `allOf` parts merged in (references resolved). `visited` holds
        the schema names already on this path - the class this started from, plus every `$ref` followed to get
        here - so a part whose `$ref` names one of them contributes nothing, ending a cycle instead of
        recursing forever. `name` is what an error about this schema's own `required` calls it."""
        properties: dict[str, Any] = {}
        required: list[str] = []
        for part in schema.get("allOf") or []:
            target = self.target(part["$ref"]) if isinstance(part, dict) and "$ref" in part else None
            if target is not None and target in visited:
                continue
            part_visited = visited | {target} if target is not None else visited
            part_properties, part_required = self._flatten(self.resolve(part), part_visited, target)
            properties.update(part_properties)
            required += [field for field in part_required if field not in required]
        properties.update(schema.get("properties") or {})
        required += [field for field in required_names(schema, name) if field not in required]
        return properties, required

    def class_block(self, name: str) -> list[str]:
        schema = self.schemas[name]
        properties, required = self._flatten(schema, frozenset({name}), name)
        self.pydantic_used.add("BaseModel")
        lines = [f"class {self.names[name]}(BaseModel):", f'    """{_docline(schema, self.names[name])}"""']
        config: list[str] = []
        if schema.get("additionalProperties") is False:
            config.append('extra="forbid"')
        fields: list[str] = []
        taken: set[str] = set()
        aliased = False
        needs_open_namespaces = False
        for prop_name, prop in properties.items():
            field_name, shadows_model_namespace = _safe_field_name(prop_name, taken)
            needs_open_namespaces = needs_open_namespaces or shadows_model_namespace
            type_expr = self.type_of(prop)
            alias = prop_name if field_name != prop_name else None
            aliased = aliased or alias is not None
            # writeOnly only binds the request; this module validates responses, so such a property is never
            # required here even when the schema's own `required` list says so.
            write_only = isinstance(prop, dict) and bool(prop.get("writeOnly"))
            if prop_name in required and not write_only:
                if alias is None:
                    fields.append(f"    {field_name}: {type_expr}")
                else:
                    self.pydantic_used.add("Field")
                    fields.append(f"    {field_name}: {type_expr} = Field(alias={_literal(alias)})")
            else:
                optional = type_expr if type_expr.endswith("| None") else f"{type_expr} | None"
                if alias is None:
                    fields.append(f"    {field_name}: {optional} = None")
                else:
                    self.pydantic_used.add("Field")
                    fields.append(f"    {field_name}: {optional} = Field(default=None, alias={_literal(alias)})")
        if aliased:
            config.append("populate_by_name=True")
        if needs_open_namespaces:
            config.append("protected_namespaces=()")
        if config:
            self.pydantic_used.add("ConfigDict")
            lines += ["", f"    model_config = ConfigDict({', '.join(config)})"]
        if fields:
            lines += ["", *fields]
        return lines

    def alias_blocks(self, names: list[str]) -> list[list[str]]:
        """`Name = <type>` lines, each after any alias it mentions; a name in a reference cycle (self or mutual)
        becomes a PEP 695 `type Name = <type>` statement instead, which tolerates the forward reference."""
        pending = {name: (self.names[name], self.type_of(self.schemas[name])) for name in names}
        alias_class_names = {self.names[name]: name for name in names}
        emitted: list[str] = []
        blocks: list[list[str]] = []
        while pending:
            progressed = False
            for name, (class_name, type_expr) in list(pending.items()):
                if _mentions(type_expr, alias_class_names) <= set(emitted):
                    blocks.append([f"{class_name} = {type_expr}"])
                    emitted.append(name)
                    del pending[name]
                    progressed = True
            if not progressed:  # a reference cycle: nothing left can be emitted before something still pending
                blocks += [[f"type {class_name} = {type_expr}"] for class_name, type_expr in pending.values()]
                break
        return blocks
