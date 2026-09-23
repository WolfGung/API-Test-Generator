"""Write a Postman collection of the app to sample_api/bookshelf.postman_collection.json:
`python -m sample_api.postman`.

The collection is built from the app's own OpenAPI document - one folder per tag, one request per operation,
the document's examples as its values - and every request carries the response the app really gave it,
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
_PLACEHOLDER = re.compile(r"\{([^{}/]+)\}")


def build_collection() -> dict[str, Any]:
    """The collection: folders in tag order, requests in document order, each with the response it got."""
    document = app.openapi()
    folders: dict[str, list[dict[str, Any]]] = {}
    for path, item in document["paths"].items():
        for method, operation in item.items():  # every key of a path item of this document is a method
            folders.setdefault(operation["tags"][0], []).append(_item(method, path, operation, document))
    with serving(app) as base_url, httpx.Client(base_url=base_url) as client:
        reset()  # the shelf as the process started, so what is recorded does not depend on what ran before
        for items in folders.values():
            for item in items:
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


def _example(schema: dict[str, Any]) -> Any:
    """The first example of a parameter's or property's schema; the app gives every one of them one."""
    return schema["examples"][0]


def _item(method: str, path: str, operation: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    """One request, named by the operation's summary. An operation the document does not secure says so with
    `noauth`; the others inherit the collection's bearer token."""
    parameters = operation.get("parameters") or []
    request: dict[str, Any] = {}
    if "security" not in operation:
        request["auth"] = {"type": "noauth"}
    request["method"] = method.upper()
    request["header"] = [
        {"key": p["name"], "value": str(_example(p["schema"]))} for p in parameters if p["in"] == "header"
    ]
    body = _body(operation, document)
    if body is not None:
        request["body"] = {
            "mode": "raw", "raw": json.dumps(body, ensure_ascii=False), "options": {"raw": {"language": "json"}},
        }
    request["url"] = _url(path, parameters)
    return {"name": operation["summary"], "request": request}


def _url(path: str, parameters: list[dict[str, Any]]) -> dict[str, Any]:
    """`{{baseUrl}}` plus the path, `{name}` written as `:name` with its value under `variable`; the query
    parameters under `query` and in the raw URL."""
    postman_path = _PLACEHOLDER.sub(lambda m: f":{m.group(1)}", path)
    query = [{"key": p["name"], "value": str(_example(p["schema"]))} for p in parameters if p["in"] == "query"]
    raw = "{{baseUrl}}" + postman_path
    if query:
        raw += "?" + "&".join(f"{entry['key']}={entry['value']}" for entry in query)
    url: dict[str, Any] = {"raw": raw, "host": ["{{baseUrl}}"], "path": postman_path.strip("/").split("/")}
    if query:
        url["query"] = query
    variables = [{"key": p["name"], "value": str(_example(p["schema"]))} for p in parameters if p["in"] == "path"]
    if variables:
        url["variable"] = variables
    return url


def _body(operation: dict[str, Any], document: dict[str, Any]) -> dict[str, Any] | None:
    """The JSON body of an operation that takes one: every property of its schema, with the property's example."""
    content = (operation.get("requestBody") or {}).get("content") or {}
    if "application/json" not in content:
        return None
    schema = content["application/json"]["schema"]
    if "$ref" in schema:
        schema = document["components"]["schemas"][schema["$ref"].rsplit("/", 1)[1]]
    return {name: _example(prop) for name, prop in schema["properties"].items()}


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
