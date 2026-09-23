"""The intermediate representation: what both loaders produce and every later stage reads."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SCHEMA_REF_PREFIX = "#/components/schemas/"


class SpecError(ValueError):
    """The document cannot be read as the format it was handed over as."""


@dataclass(frozen=True)
class Parameter:
    name: str
    location: str  # "path" | "query" | "header"
    required: bool
    schema: dict[str, Any]
    examples: tuple[Any, ...] = ()


@dataclass(frozen=True)
class Body:
    content_type: str
    schema: dict[str, Any]
    required: bool
    examples: tuple[Any, ...] = ()

    @property
    def is_json(self) -> bool:
        return self.content_type == "application/json" or self.content_type.endswith("+json")


@dataclass(frozen=True)
class Response:
    status: str  # "200", "2XX" or "default"
    schema: dict[str, Any] | None
    content_type: str | None = None
    description: str = ""

    @property
    def is_json(self) -> bool:
        return bool(self.content_type) and (
            self.content_type == "application/json" or self.content_type.endswith("+json")
        )


@dataclass(frozen=True)
class Security:
    kind: str  # "bearer" | "basic" | "apiKey" | "none"
    name: str = ""  # the scheme's name in the document
    header: str = ""  # apiKey only: the header that carries the key
    location: str = "header"  # apiKey only; keys in a query string or a cookie are not supported


NO_SECURITY = Security(kind="none")


@dataclass(frozen=True)
class Operation:
    operation_id: str
    method: str  # upper case
    path: str  # "/pet/{petId}"
    tag: str
    summary: str
    parameters: tuple[Parameter, ...] = ()
    body: Body | None = None
    responses: tuple[Response, ...] = ()
    secured: bool = False

    @property
    def success(self) -> Response | None:
        """The documented success: the lowest numeric 2xx status, else a "2XX" range, else nothing."""
        numeric = [r for r in self.responses if r.status.isdigit() and r.status.startswith("2")]
        if numeric:
            return min(numeric, key=lambda r: int(r.status))
        for response in self.responses:
            if response.status.upper() == "2XX":
                return response
        return None

    @property
    def success_status(self) -> int | None:
        success = self.success
        return int(success.status) if success and success.status.isdigit() else None

    def parameters_in(self, location: str) -> tuple[Parameter, ...]:
        return tuple(p for p in self.parameters if p.location == location)


@dataclass(frozen=True)
class ApiModel:
    title: str
    version: str
    base_url: str
    operations: tuple[Operation, ...]
    schemas: dict[str, dict[str, Any]] = field(default_factory=dict)
    security: Security = NO_SECURITY

    def resolve(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Follow `$ref` to the named schema it points at, any depth; anything else comes back as it is."""
        hops = 0
        while "$ref" in schema:
            name = ref_name(schema["$ref"])
            if name not in self.schemas:
                raise SpecError(f"unresolved reference {schema['$ref']!r}")
            schema = self.schemas[name]
            hops += 1
            if hops > 50:
                raise SpecError(f"reference loop at {name!r}")
        return schema

    @property
    def tags(self) -> tuple[str, ...]:
        """Tags in order of first appearance."""
        seen: dict[str, None] = {}
        for operation in self.operations:
            seen.setdefault(operation.tag)
        return tuple(seen)


def ref_name(ref: str) -> str:
    """'#/components/schemas/Pet' -> 'Pet'."""
    if not ref.startswith(SCHEMA_REF_PREFIX):
        raise SpecError(f"only references into {SCHEMA_REF_PREFIX} are supported, got {ref!r}")
    return ref[len(SCHEMA_REF_PREFIX) :]


def ref_to(name: str) -> dict[str, str]:
    return {"$ref": f"{SCHEMA_REF_PREFIX}{name}"}
