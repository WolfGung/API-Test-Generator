"""Write a Postman collection of the app to sample_api/bookshelf.postman_collection.json:
`python -m sample_api.postman`.

The collection is built from the app's own OpenAPI document - one folder per tag, one request per operation,
the document's examples as its values - and every request carries the response the app really gave it, each
recorded against a freshly seeded shelf. Two exports are byte-identical.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx

from .app import TOKEN, app, reset
from .serve import serving

TARGET = Path(__file__).with_name("bookshelf.postman_collection.json")
SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
BASE_URL = "http://127.0.0.1:8000"
SAMPLE_TOKEN = "sample-token"  # the app's default token, the only one the committed collection may carry
_PLACEHOLDER = re.compile(r"\{([^{}/]+)\}")


def build_collection() -> dict[str, Any]:
    """The collection: folders in tag order, requests in document order, each with the response it got.

    Refuses to run with any token but the sample one, since the collection commits the token it records with;
    refuses, naming the operation, anything the app's document leaves it unable to express.
    """
    if TOKEN != SAMPLE_TOKEN:
        raise RuntimeError(
            f"SAMPLE_API_TOKEN is set to something other than {SAMPLE_TOKEN!r}; the collection commits the token "
            "it records with, so unset it before exporting"
        )
    document = app.openapi()
    folders: dict[str, list[dict[str, Any]]] = {}
    for path, item in document["paths"].items():
        for method, operation in item.items():  # every key of a path item of this document is a method
            name = f"{method.upper()} {path}"
            tags = operation.get("tags") or []
            if not tags:
                raise ValueError(f"{name}: no tag to file the request under")
            folders.setdefault(tags[0], []).append(_item(name, method, path, operation, document))
    with serving(app) as base_url, httpx.Client(base_url=base_url) as client:
        for items in folders.values():
            for item in items:
                reset()  # every response answers the seeded shelf, whatever was recorded before it
                item["response"] = [_record(client, item)]
    return {
        "info": {
            "name": document["info"]["title"],
            "description": document["info"]["description"],
            "version": document["info"]["version"],
            "schema": SCHEMA,
        },
        "item": [{"name": tag, "item": items} for tag, items in folders.items()],
        "auth": {"type": "bearer", "bearer": [{"key": "token", "value": "{{token}}", "type": "string"}]},
        "variable": [
            {"key": "baseUrl", "value": BASE_URL, "type": "string"},
            {"key": "token", "value": TOKEN, "type": "string"},
        ],
    }


def render() -> str:
    return json.dumps(build_collection(), indent=2, sort_keys=False, ensure_ascii=False) + "\n"


def _example(schema: dict[str, Any], what: str) -> Any:
    """The first example of a parameter's or property's schema: the value the collection carries for it."""
    examples = schema.get("examples")
    if not examples:
        raise ValueError(f"{what} has no example")
    return examples[0]


def _entry(name: str, parameter: dict[str, Any]) -> dict[str, str]:
    """A key/value entry for a parameter, the way Postman keeps path variables, query entries and headers."""
    value = _example(parameter["schema"], f"{name}: parameter {parameter['name']!r}")
    return {"key": parameter["name"], "value": str(value)}


def _item(name: str, method: str, path: str, operation: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    """One request, named by the operation's summary. An operation the document does not secure says so with
    `noauth`; the others inherit the collection's bearer token."""
    summary = operation.get("summary")
    if not summary:
        raise ValueError(f"{name}: no summary to name the request by")
    parameters = operation.get("parameters") or []
    request: dict[str, Any] = {}
    if "security" not in operation:
        request["auth"] = {"type": "noauth"}
    request["method"] = method.upper()
    request["header"] = [_entry(name, p) for p in parameters if p["in"] == "header"]
    body = _body(name, operation, document)
    if body is not None:
        request["body"] = {
            "mode": "raw", "raw": json.dumps(body, ensure_ascii=False), "options": {"raw": {"language": "json"}},
        }
    request["url"] = _url(name, path, parameters)
    return {"name": summary, "request": request}


def _url(name: str, path: str, parameters: list[dict[str, Any]]) -> dict[str, Any]:
    """`{{baseUrl}}` plus the path, `{name}` written as `:name` with its value under `variable`; the query
    parameters under `query` and in the raw URL."""
    postman_path = _PLACEHOLDER.sub(lambda m: f":{m.group(1)}", path)
    query = [_entry(name, p) for p in parameters if p["in"] == "query"]
    raw = "{{baseUrl}}" + postman_path
    if query:
        raw += "?" + "&".join(f"{entry['key']}={entry['value']}" for entry in query)
    url: dict[str, Any] = {"raw": raw, "host": ["{{baseUrl}}"], "path": postman_path.strip("/").split("/")}
    if query:
        url["query"] = query
    variables = [_entry(name, p) for p in parameters if p["in"] == "path"]
    if variables:
        url["variable"] = variables
    return url


def _body(name: str, operation: dict[str, Any], document: dict[str, Any]) -> dict[str, Any] | None:
    """The JSON body of an operation that takes one: every property of its schema, with the property's example."""
    request_body = operation.get("requestBody")
    if request_body is None:
        return None
    content = request_body.get("content") or {}
    if "application/json" not in content:
        raise ValueError(f"{name}: the request body is {', '.join(content) or 'empty'}, not application/json")
    schema = content["application/json"]["schema"]
    if "$ref" in schema:
        schema = document["components"]["schemas"][schema["$ref"].rsplit("/", 1)[1]]
    properties = schema.get("properties")
    if not properties:
        raise ValueError(f"{name}: the request body schema has no properties to take examples from")
    return {field: _example(prop, f"{name}: body field {field!r}") for field, prop in properties.items()}


def _record(client: httpx.Client, item: dict[str, Any]) -> dict[str, Any]:
    """Send the item's request to the served app and keep what came back the way Postman saves a response:
    the real status, the Content-Type header and the body."""
    request = item["request"]
    url = request["url"]
    values = {variable["key"]: variable["value"] for variable in url.get("variable", [])}
    path = "/" + "/".join(values[segment[1:]] if segment.startswith(":") else segment for segment in url["path"])
    headers = {header["key"]: header["value"] for header in request["header"]}
    if "auth" not in request:
        headers["Authorization"] = f"Bearer {TOKEN}"
    body = request.get("body")
    if body is not None:
        headers["Content-Type"] = "application/json"
    response = client.request(
        request["method"], path,
        params={entry["key"]: entry["value"] for entry in url.get("query", [])},
        headers=headers,
        content=body["raw"] if body is not None else None,
    )
    content_type = response.headers.get("content-type")
    return {
        "name": item["name"],
        "status": response.reason_phrase,
        "code": response.status_code,
        "header": [{"key": "Content-Type", "value": content_type}] if content_type else [],
        "body": response.text,
    }


if __name__ == "__main__":
    TARGET.write_text(render(), encoding="utf-8")
    print(f"wrote {TARGET}")
