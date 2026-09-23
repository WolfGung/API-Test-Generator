"""The test cases of one operation: a positive request and the negatives the document justifies."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any

from .ir import ApiModel, Operation, Parameter, ref_name
from .naming import to_identifier, unique
from .samples import has_example, required_fields, sample_for

SUPPORTED_AUTH = ("bearer", "basic", "apiKey")
PLACEHOLDER = re.compile(r"\{([^{}/]+)\}")
DOC_LIMIT = 100


@dataclass(frozen=True)
class Case:
    name: str
    kind: str  # "positive" | "missing_parameter" | "missing_field" | "no_credentials"
    method: str
    path: str
    doc: str
    path_params: dict[str, Any]
    query: dict[str, Any]
    headers: dict[str, str]
    body: Any  # None when the request carries no body
    body_kind: str | None  # "json" | "text" | None
    expect: str  # "success" | "client_error" | "unauthorized"
    expected_status: int | None  # exact status for "success" when the document names one
    validate: str | None  # model name to validate the success payload against
    uses_auth: bool
    skip_reason: str | None = None


def cases_for(operation: Operation, api: ApiModel) -> list[Case]:
    taken: set[str] = set()
    positive = _positive(operation, api, taken)
    cases = [positive]
    if positive.skip_reason:
        return cases
    for parameter in operation.parameters:
        if parameter.required and parameter.location in ("query", "header"):
            cases.append(_without_parameter(operation, positive, parameter, taken))
    if operation.body and operation.body.is_json and isinstance(positive.body, dict):
        for field in required_fields(operation.body.schema, api):
            if field in positive.body:
                cases.append(_without_field(operation, positive, field, taken))
    if operation.secured and api.security.kind in SUPPORTED_AUTH:
        cases.append(
            replace(
                positive,
                name=unique(f"test_{operation.operation_id}_without_credentials", taken),
                kind="no_credentials",
                doc=_doc(operation, "without credentials must be refused"),
                expect="unauthorized",
                expected_status=None,
                validate=None,
                uses_auth=False,
            )
        )
    return cases


def declares_required(api: ApiModel) -> bool:
    """Whether the document justifies any missing-parameter or missing-field negative, by the rule `cases_for`
    applies: an operation with a required query or header parameter, or a JSON body whose schema requires a
    field. Path parameters are always required and get no negative; a Postman collection declares nothing as
    required, so its suite has none of these negatives and its README says so."""
    for operation in api.operations:
        if any(p.required and p.location in ("query", "header") for p in operation.parameters):
            return True
        if operation.body and operation.body.is_json and required_fields(operation.body.schema, api):
            return True
    return False


def _value(parameter: Parameter, api: ApiModel) -> Any:
    return parameter.examples[0] if parameter.examples else sample_for(parameter.schema, api)


def _given(parameter: Parameter, api: ApiModel) -> bool:
    """Whether the positive request carries the parameter: a required one always, an optional one when the
    document gives it a value (an example on the parameter or its schema, a default, a const), as body fields."""
    return parameter.required or bool(parameter.examples) or has_example(api.resolve(parameter.schema))


def _doc(operation: Operation, tail: str) -> str:
    """One line for the test's docstring; quotes and backslashes are replaced so the docstring cannot break."""
    text = f"{operation.method} {operation.path}: {tail}" if tail else f"{operation.method} {operation.path}"
    text = " ".join(text.split()).replace('"', "'").replace("\\", "/")
    return text if len(text) <= DOC_LIMIT else text[: DOC_LIMIT - 1] + "…"


def _positive(operation: Operation, api: ApiModel, taken: set[str]) -> Case:
    path_params = {p.name: _value(p, api) for p in operation.parameters_in("path")}
    for name in PLACEHOLDER.findall(operation.path):  # a placeholder the document never declared
        path_params.setdefault(name, "string")
    query = {p.name: _value(p, api) for p in operation.parameters_in("query") if _given(p, api)}
    headers = {p.name: str(_value(p, api)) for p in operation.parameters_in("header") if _given(p, api)}
    body: Any = None
    body_kind: str | None = None
    skip_reason: str | None = None
    if operation.body is not None:
        if operation.body.is_json:
            schema = api.resolve(operation.body.schema) if operation.body.schema else {}
            if operation.body.examples:
                body, body_kind = operation.body.examples[0], "json"
            elif schema or operation.body.required:
                body, body_kind = sample_for(operation.body.schema, api), "json"
        elif operation.body.content_type.startswith("text/"):
            body = operation.body.examples[0] if operation.body.examples else "text"
            body_kind = "text"
        else:
            skip_reason = f"request body is {operation.body.content_type}, which the generator does not produce"
    success = operation.success
    validate = None
    if success and success.is_json and success.schema and "$ref" in success.schema:
        validate = ref_name(success.schema["$ref"])  # a text or binary success is asserted by status only
    if body_kind == "json" and body is None:
        if operation.body.required:
            body = {}  # required, but the schema gives nothing sensible: send an empty object instead
        else:
            body_kind = None  # optional, with no schema and no example: no body is sent at all
    return Case(
        name=unique(f"test_{operation.operation_id}", taken),
        kind="positive",
        method=operation.method,
        path=operation.path,
        doc=_doc(operation, operation.summary),
        path_params=path_params,
        query=query,
        headers=headers,
        body=body,
        body_kind=body_kind,
        expect="success",
        expected_status=operation.success_status,
        validate=validate,
        uses_auth=operation.secured and api.security.kind in SUPPORTED_AUTH,
        skip_reason=skip_reason,
    )


def _without_parameter(operation: Operation, positive: Case, parameter: Parameter, taken: set[str]) -> Case:
    where = "query parameter" if parameter.location == "query" else "header"
    return replace(
        positive,
        name=unique(f"test_{operation.operation_id}_without_{to_identifier(parameter.name)}", taken),
        kind="missing_parameter",
        doc=_doc(operation, f"without the required {where} {parameter.name!r} must be refused"),
        query=(
            {k: v for k, v in positive.query.items() if k != parameter.name}
            if parameter.location == "query"
            else positive.query
        ),
        headers=(
            {k: v for k, v in positive.headers.items() if k != parameter.name}
            if parameter.location == "header"
            else positive.headers
        ),
        expect="client_error",
        expected_status=None,
        validate=None,
    )


def _without_field(operation: Operation, positive: Case, field: str, taken: set[str]) -> Case:
    return replace(
        positive,
        name=unique(f"test_{operation.operation_id}_without_{to_identifier(field)}", taken),
        kind="missing_field",
        doc=_doc(operation, f"without the required body field {field!r} must be refused"),
        body={k: v for k, v in positive.body.items() if k != field},
        expect="client_error",
        expected_status=None,
        validate=None,
    )
