"""Read a Postman collection (schema v2.0 or v2.1) into the intermediate representation."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from .ir import NO_SECURITY, ApiModel, Body, Operation, Parameter, Response, Security, SpecError
from .naming import to_class_name, to_identifier, unique
from .openapi import load_document, register_schema

SUPPORTED_SCHEMAS = ("/v2.0.0/", "/v2.1.0/")
METHODS_WITH_BODY = ("POST", "PUT", "PATCH", "DELETE")
DROPPED_HEADERS = {"authorization", "content-type", "accept", "user-agent", "host", "content-length"}
FORM_TYPES = {"urlencoded": "application/x-www-form-urlencoded", "formdata": "multipart/form-data"}
_VARIABLE = re.compile(r"\{\{([^{}]+)\}\}")
_COLON_SEGMENT = re.compile(r"(?<=/):([A-Za-z_][A-Za-z0-9_]*)")
_PATH_PARAM = re.compile(r"\{([^{}/]+)\}")
UNSUPPORTED = Security(kind="unsupported")


def load_postman(path: Path) -> ApiModel:
    doc = load_document(path)
    info = doc.get("info") or {}
    schema = str(info.get("schema") or "")
    if not any(marker in schema for marker in SUPPORTED_SCHEMAS):
        raise SpecError(f"{path}: expected a Postman collection v2.0 or v2.1, found schema {schema!r}")
    variables = {str(v["key"]): str(v.get("value", "")) for v in doc.get("variable") or [] if v.get("key")}
    schemas: dict[str, dict[str, Any]] = {}
    operations: list[Operation] = []
    taken: set[str] = set()
    base_url = ""
    security = NO_SECURITY
    for item, folder, auth in _walk(doc.get("item") or [], "default", _auth(doc.get("auth")) or NO_SECURITY):
        request = item.get("request")
        if isinstance(request, str):
            request = {"url": request, "method": "GET"}
        if not isinstance(request, dict):
            continue
        parsed = _url(request.get("url"), variables)
        if parsed is None:
            continue
        origin, raw_path, query, path_examples = parsed
        base_url = base_url or origin
        method = str(request.get("method") or "GET").upper()
        operation_id = unique(to_identifier(str(item.get("name") or f"{method} {raw_path}")), taken)
        class_name = to_class_name(operation_id)
        effective = _auth(request.get("auth")) or auth
        if security is NO_SECURITY and effective.kind in ("bearer", "basic", "apiKey"):
            security = effective
        parameters = [
            Parameter(name=name, location="path", required=True, schema={"type": "string"},
                      examples=(path_examples[name],) if path_examples.get(name) else ())
            for name in _PATH_PARAM.findall(raw_path)
        ]
        parameters += [
            Parameter(name=key, location="query", required=False, schema={"type": "string"}, examples=(value,))
            for key, value in query
        ]
        parameters += list(_headers(request.get("header"), variables))
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
                secured=effective.kind in ("bearer", "basic", "apiKey"),
            )
        )
    return ApiModel(
        title=str(info.get("name") or path.stem),
        version=str(info.get("version") or ""),
        base_url=base_url,
        operations=tuple(operations),
        schemas=schemas,
        security=security,
    )


def _walk(items: list[Any], folder: str, auth: Security, depth: int = 0) -> Iterator[tuple[dict, str, Security]]:
    for item in items:
        if not isinstance(item, dict):
            continue
        if "item" in item:
            own_folder = str(item.get("name") or folder) if depth == 0 else folder
            yield from _walk(item["item"], own_folder, _auth(item.get("auth")) or auth, depth + 1)
        else:
            yield item, folder, auth


def _auth(raw: Any) -> Security | None:
    """None when there is no auth block; NO_SECURITY for `noauth`; UNSUPPORTED for kinds the suite cannot send."""
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
        if fields.get("in") == "query":
            return UNSUPPORTED
        return Security(kind="apiKey", name="apikey", header=fields.get("key") or "X-Api-Key", location="header")
    return UNSUPPORTED


def _substitute(text: str, variables: dict[str, str]) -> str:
    return _VARIABLE.sub(lambda m: variables.get(m.group(1).strip(), m.group(0)), text)


def _url(raw: Any, variables: dict[str, str]) -> tuple[str, str, list[tuple[str, str]], dict[str, str]] | None:
    """(origin, path with {params}, query pairs, path parameter examples) or None for an empty URL."""
    path_examples: dict[str, str] = {}
    if isinstance(raw, dict):
        for variable in raw.get("variable") or []:
            if isinstance(variable, dict) and variable.get("key"):
                path_examples[str(variable["key"])] = str(variable.get("value") or "")
        text = raw.get("raw")
        if not text:
            host = raw.get("host") or []
            host = ".".join(host) if isinstance(host, list) else str(host)
            path = raw.get("path") or []
            path = "/".join(path) if isinstance(path, list) else str(path)
            pairs = [
                f"{q.get('key')}={q.get('value', '')}"
                for q in raw.get("query") or []
                if isinstance(q, dict) and q.get("key") and not q.get("disabled")
            ]
            protocol = raw.get("protocol")
            text = f"{protocol}://{host}" if protocol else host
            text = f"{text}/{path}" if path else text
            if pairs:
                text = f"{text}?{'&'.join(pairs)}"
    else:
        text = str(raw or "")
    text = _substitute(text.strip(), variables)
    if not text:
        return None
    # Unknown {{name}} becomes {name}: in the path that is a parameter, in the host it stays visible.
    text = _VARIABLE.sub(lambda m: "{" + m.group(1).strip() + "}", text)
    text = _COLON_SEGMENT.sub(lambda m: "{" + m.group(1) + "}", text)
    parts = urlsplit(text)
    origin = f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""
    path = parts.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    query = parse_qsl(parts.query, keep_blank_values=True)
    return origin, path, query, path_examples


def _headers(raw: Any, variables: dict[str, str]) -> Iterator[Parameter]:
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
        yield Parameter(
            name=key, location="header", required=False, schema={"type": "string"},
            examples=(_substitute(str(entry.get("value", "")), variables),),
        )


def _body(
    raw: Any, method: str, variables: dict[str, str], schemas: dict[str, dict[str, Any]], class_name: str
) -> Body | None:
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
        schema = infer_schema(value)
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
        return Body(content_type=FORM_TYPES[mode], schema=infer_schema(fields), required=True, examples=(fields,))
    if mode == "file":
        return Body(
            content_type="application/octet-stream", schema={"type": "string", "format": "binary"}, required=True
        )
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


def infer_schema(value: Any) -> dict[str, Any]:
    """A JSON schema that describes one value: types only, every key of an object required."""
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    if isinstance(value, list):
        return {"type": "array", "items": infer_schema(value[0])} if value else {"type": "array"}
    if isinstance(value, dict):
        if not value:
            return {"type": "object"}
        return {
            "type": "object",
            "properties": {str(k): infer_schema(v) for k, v in value.items()},
            "required": [str(k) for k in value],
        }
    return {}
