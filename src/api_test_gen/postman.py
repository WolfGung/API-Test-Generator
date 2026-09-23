"""Read a Postman collection (schema v2.0 or v2.1) into the intermediate representation."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from .ir import NO_SECURITY, UNSUPPORTED_SECURITY, ApiModel, Body, Operation, Parameter, Response, Security, SpecError
from .naming import to_class_name, to_identifier, unique
from .openapi import load_document, register_schema

SUPPORTED_SCHEMAS = ("/v2.0.0/", "/v2.1.0/")
METHODS_WITH_BODY = ("POST", "PUT", "PATCH", "DELETE")
DROPPED_HEADERS = {"authorization", "content-type", "accept", "user-agent", "host", "content-length"}
FORM_TYPES = {"urlencoded": "application/x-www-form-urlencoded", "formdata": "multipart/form-data"}
_VARIABLE = re.compile(r"\{\{([^{}]+)\}\}")
_COLON_SEGMENT = re.compile(r"(?<=/):([A-Za-z_][A-Za-z0-9_]*)")
_PATH_PARAM = re.compile(r"\{([^{}/]+)\}")
_ORIGIN_LABEL = re.compile(r"(?:://)?[^/?]*")  # what follows a leading variable up to the path (or a bare query)
SUPPORTED_AUTH = ("bearer", "basic", "apiKey")


def load_postman(path: Path) -> ApiModel:
    doc = load_document(path)
    info = doc.get("info") or {}
    schema = str(info.get("schema") or "")
    if not any(marker in schema for marker in SUPPORTED_SCHEMAS):
        raise SpecError(f"expected a Postman collection v2.0 or v2.1, found schema {schema!r}")
    variables = {str(v["key"]): str(v.get("value", "")) for v in doc.get("variable") or [] if v.get("key")}
    schemas: dict[str, dict[str, Any]] = {}
    operations: list[Operation] = []
    taken: set[str] = set()
    base_url = ""
    security = NO_SECURITY
    notes: list[str] = []
    unsupported: list[str] = []  # auth kinds met that the suite cannot send, in order, once each
    items = _items(doc, "the collection's 'item'")
    collection_auth = _auth(doc.get("auth")) or NO_SECURITY
    for item, folder, auth in _walk(items, "default", collection_auth):
        request = item.get("request")
        if isinstance(request, str):
            request = {"url": request, "method": "GET"}
        if not isinstance(request, dict):
            continue
        parsed = _url(request.get("url"), variables)
        if parsed is None:
            continue
        raw_path, path_examples = parsed.path, parsed.path_examples
        method = str(request.get("method") or "GET").upper()
        operation_id = unique(to_identifier(str(item.get("name") or f"{method} {raw_path}")), taken)
        class_name = to_class_name(operation_id)
        notes += [f"{operation_id}: {note}" for note in parsed.notes]
        if base_url and parsed.origin and parsed.origin != base_url:
            # One origin per suite: the first the collection names. A request on another host goes there too,
            # which the client should hear rather than find out from a 404.
            notes.append(
                f"{operation_id}: sent to {base_url}, not to {parsed.origin}: a suite has one base URL, the first "
                "the collection names"
            )
        base_url = base_url or parsed.origin
        effective = _auth(request.get("auth")) or auth
        if security is NO_SECURITY and effective.kind in SUPPORTED_AUTH:
            security = effective
        if effective.kind == "unsupported" and effective.name not in unsupported:
            unsupported.append(effective.name)
        parameters = [
            Parameter(name=name, location="path", required=True, schema={"type": "string"},
                      examples=(path_examples[name],) if path_examples.get(name) else ())
            for name in _PATH_PARAM.findall(raw_path)
        ]
        parameters += [
            Parameter(name=key, location="query", required=False, schema={"type": "string"}, examples=(value,))
            for key, value in parsed.query
        ]
        parameters += list(_headers(request.get("header"), variables, notes, operation_id))
        operations.append(
            Operation(
                operation_id=operation_id,
                method=method,
                path=raw_path,
                tag=folder,
                summary=str(item.get("name") or "").strip(),
                parameters=tuple(parameters),
                body=_body(request.get("body"), method, variables, schemas, class_name),
                responses=_responses(item.get("response") or [], schemas, class_name),
                secured=effective.kind in SUPPORTED_AUTH,
            )
        )
    if security is NO_SECURITY:
        # With a supported auth somewhere, the suite has credentials to send; without one, every kind the
        # collection uses is a kind it cannot send, and the client should hear that before a red run.
        notes += [UNSUPPORTED_SECURITY.format(what=f"{kind} auth") for kind in unsupported]
    return ApiModel(
        title=str(info.get("name") or path.stem),
        version=str(info.get("version") or ""),
        base_url=base_url,
        operations=tuple(operations),
        schemas=schemas,
        security=security,
        notes=tuple(notes),
    )


def _items(holder: dict[str, Any], what: str) -> list[Any]:
    """The `item` list of the collection or of a folder: absent means empty; anything but a list is refused."""
    items = holder.get("item", [])
    if not isinstance(items, list):
        raise SpecError(f"{what} is not a list")
    return items


def _walk(items: list[Any], folder: str, auth: Security, depth: int = 0) -> Iterator[tuple[dict, str, Security]]:
    for item in items:
        if not isinstance(item, dict):
            continue
        if "item" in item:
            own_folder = str(item.get("name") or folder) if depth == 0 else folder
            children = _items(item, f"folder {str(item.get('name') or '')!r}: 'item'")
            yield from _walk(children, own_folder, _auth(item.get("auth")) or auth, depth + 1)
        else:
            yield item, folder, auth


def _auth(raw: Any) -> Security | None:
    """None when there is no auth block; NO_SECURITY for `noauth`; for a kind the suite cannot send (digest,
    oauth, a key anywhere but a header) a Security of kind "unsupported" whose name says which."""
    if not isinstance(raw, dict) or not raw.get("type"):
        return None
    kind = str(raw["type"]).lower()
    if kind == "noauth":
        return NO_SECURITY
    if kind == "bearer":
        return Security(kind="bearer", name="bearer", header="Authorization")
    if kind == "basic":
        return Security(kind="basic", name="basic", header="Authorization")
    if kind == "apikey":
        fields = {str(f.get("key")): str(f.get("value", "")) for f in raw.get("apikey") or [] if isinstance(f, dict)}
        location = fields.get("in") or "header"
        if location != "header":
            return Security(kind="unsupported", name=f"apikey in {location}")
        return Security(kind="apiKey", name="apikey", header=fields.get("key") or "X-Api-Key", location="header")
    return Security(kind="unsupported", name=kind)


def _substitute(text: str, variables: dict[str, str]) -> str:
    return _VARIABLE.sub(lambda m: variables.get(m.group(1).strip(), m.group(0)), text)


@dataclass(frozen=True)
class _Url:
    """A request's URL taken apart. `notes` says what was not kept - a host label folded into the origin, a
    query value the collection cannot resolve - as sentences the caller prefixes with the operation's id."""

    origin: str  # "" when the collection leaves it to the suite's base URL
    path: str  # with {params}
    query: tuple[tuple[str, str], ...]
    path_examples: dict[str, str]
    notes: tuple[str, ...] = ()


def _url(raw: Any, variables: dict[str, str]) -> _Url | None:
    """The URL of a request, or None for an empty one."""
    path_examples: dict[str, str] = {}
    structured: list[tuple[str, str]] | None = None
    notes: list[str] = []
    if isinstance(raw, dict):
        for variable in raw.get("variable") or []:
            if isinstance(variable, dict) and variable.get("key"):
                path_examples[str(variable["key"])] = str(variable.get("value") or "")
        entries = [q for q in raw.get("query") or [] if isinstance(q, dict) and q.get("key")]
        if entries:
            # Postman's own structured form of the query, the one that carries the `disabled` flags: the raw
            # string keeps a switched-off entry, and where the two disagree the entries are what Postman sends.
            # A null value is blank.
            structured = [
                (str(q["key"]), _substitute(str(q.get("value") or ""), variables))
                for q in entries
                if not q.get("disabled")
            ]
        text = raw.get("raw")
        if not text:
            host = raw.get("host") or []
            host = ".".join(host) if isinstance(host, list) else str(host)
            path = raw.get("path") or []
            path = "/".join(path) if isinstance(path, list) else str(path)
            protocol = raw.get("protocol")
            text = f"{protocol}://{host}" if protocol else host
            text = f"{text}/{path}" if path else text
    else:
        text = str(raw or "")
    text = _substitute(text.strip(), variables)
    if not text:
        return None
    no_origin = False
    leading_variable = _VARIABLE.match(text)
    if leading_variable:
        # An unresolved {{variable}} in host position (Postman's own {{baseUrl}}-style convention, usually
        # supplied by an environment file this collection does not carry) is not a path parameter: it is the
        # origin, dropped and left for the generated suite's own base URL to supply. What follows it up to the
        # first `/` is part of that origin only when it looks like a host label - it holds a `.` or a `:`, as in
        # `{{env}}.api.example.com`, `{{host}}:8080` or `{{scheme}}://{{host}}`; otherwise it is the first path
        # segment (`{{baseUrl}}api/things`, with a `baseUrl` that ends in `/`) and stays in the path.
        rest = text[leading_variable.end() :]
        matched = _ORIGIN_LABEL.match(rest)
        label = matched.group(0) if matched else ""
        if "." in label or ":" in label:
            folded = text[: leading_variable.end()] + label
            notes.append(f"{folded!r} is not part of the path; it is the origin, which API_BASE_URL supplies")
            rest = rest[len(label) :]
        text = rest
        no_origin = True
    text = _COLON_SEGMENT.sub(lambda m: "{" + m.group(1) + "}", text)
    if not no_origin and "://" not in text and not text.startswith("/"):
        # No scheme still means something over the wire: Postman itself sends this request as http.
        text = f"http://{text}"
    parts = urlsplit(text)
    origin = "" if no_origin else (f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else "")
    # An unknown {{name}} in the path becomes {name}: there it is a genuine parameter.
    path = _VARIABLE.sub(lambda m: "{" + m.group(1).strip() + "}", parts.path or "/")
    if not path.startswith("/"):
        path = "/" + path
    pairs = structured if structured is not None else parse_qsl(parts.query, keep_blank_values=True)
    query = tuple(pair for pair in pairs if _query_value_resolves(pair, notes))
    return _Url(origin=origin, path=path, query=query, path_examples=path_examples, notes=tuple(notes))


def _query_value_resolves(pair: tuple[str, str], notes: list[str]) -> bool:
    """The header rule, for a query pair: a value still holding a {{name}} the collection cannot resolve is not
    sent at all - `{{trace}}` is never a query value - and a note says so."""
    key, value = pair
    unresolved = _VARIABLE.search(value)
    if unresolved is None:
        return True
    notes.append(f"query parameter {key!r} is not sent; {unresolved.group(0)} is not a collection variable")
    return False


def _headers(raw: Any, variables: dict[str, str], notes: list[str], operation_id: str) -> Iterator[Parameter]:
    """The request's own headers, the ones the client fixture does not set. A value still holding a {{name}} the
    collection cannot resolve is not sent at all - `{{trace}}` is never a header value - and a note says so."""
    if isinstance(raw, str):
        entries = [
            {"key": k.strip(), "value": v.strip()}
            for k, _, v in (line.partition(":") for line in raw.splitlines())
            if k.strip()
        ]
    else:
        entries = [h for h in raw or [] if isinstance(h, dict)]
    for entry in entries:
        key = str(entry.get("key") or "")
        if not key or entry.get("disabled") or key.lower() in DROPPED_HEADERS:
            continue
        value = _substitute(str(entry.get("value", "")), variables)
        unresolved = _VARIABLE.search(value)
        if unresolved:
            variable = unresolved.group(0)
            notes.append(f"{operation_id}: header {key!r} is not sent; {variable} is not a collection variable")
            continue
        yield Parameter(name=key, location="header", required=False, schema={"type": "string"}, examples=(value,))


def _body(
    raw: Any, method: str, variables: dict[str, str], schemas: dict[str, dict[str, Any]], class_name: str
) -> Body | None:
    """A collection shows one request that worked; it says nothing about which of its body fields are required,
    so the schema inferred here lists none and no missing-field negative is generated from it."""
    if method not in METHODS_WITH_BODY or not isinstance(raw, dict):
        return None
    mode = str(raw.get("mode") or "")
    if mode == "raw":
        text = _substitute(str(raw.get("raw") or ""), variables)
        if not text.strip():
            return None
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return Body(content_type="text/plain", schema={"type": "string"}, required=True, examples=(text,))
        schema = infer_schema(value, required=False)
        if isinstance(value, dict | list):
            schema = register_schema(schemas, f"{class_name}Request", schema)
        return Body(content_type="application/json", schema=schema, required=True, examples=(value,))
    if mode in FORM_TYPES:
        fields = {
            str(f["key"]): str(f.get("value", ""))
            for f in raw.get(mode) or []
            if isinstance(f, dict) and f.get("key") and not f.get("disabled")
        }
        if not fields:
            return None
        schema = infer_schema(fields, required=False)
        return Body(content_type=FORM_TYPES[mode], schema=schema, required=True, examples=(fields,))
    if mode == "file":
        return Body(
            content_type="application/octet-stream", schema={"type": "string", "format": "binary"}, required=True
        )
    if mode:
        # graphql, or a mode this loader does not know: the case is written skipped, with the mode in the reason,
        # rather than sent without the body the collection gave it.
        return Body(content_type=f"{mode} (a Postman body mode)", schema={}, required=True)
    return None


def _responses(saved: list[Any], schemas: dict[str, dict[str, Any]], class_name: str) -> tuple[Response, ...]:
    for response in saved:
        if not isinstance(response, dict):
            continue
        code = response.get("code")
        if not isinstance(code, int) or not 200 <= code < 300:
            continue
        content_type = next(
            (
                str(h.get("value"))
                for h in response.get("header") or []
                if isinstance(h, dict) and str(h.get("key", "")).lower() == "content-type"
            ),
            None,
        )
        body = response.get("body")
        schema = None
        if isinstance(body, str) and body.strip():
            try:
                value = json.loads(body)
            except json.JSONDecodeError:
                value = None
            if isinstance(value, dict | list):
                schema = register_schema(schemas, f"{class_name}Response", infer_schema(value))
                content_type = content_type or "application/json"
        return (
            Response(
                status=str(code), schema=schema, content_type=content_type,
                description=str(response.get("name") or ""),
            ),
        )
    return (Response(status="2XX", schema=None),)


def infer_schema(value: Any, *, required: bool = True) -> dict[str, Any]:
    """A JSON schema that describes one value: types only. With `required`, every key of an object is required
    (a saved response shows what a success carries); without it no object at any level lists any (a request
    body shows one set of fields that worked, not which of them had to be there)."""
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    if isinstance(value, list):
        if not value:
            return {"type": "array"}
        return {"type": "array", "items": infer_schema(value[0], required=required)}
    if isinstance(value, dict):
        if not value:
            return {"type": "object"}
        properties = {str(k): infer_schema(v, required=required) for k, v in value.items()}
        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = [str(k) for k in value]
        return schema
    return {}
