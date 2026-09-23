"""The Postman collection of the sample API: exported from the app, committed, and read back by the loader."""

import json

import pytest
from fastapi import FastAPI

from api_test_gen.openapi import load_openapi
from api_test_gen.postman import load_postman
from sample_api import export, postman
from sample_api.app import app

V2_1 = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"


@pytest.fixture(scope="module")
def rendered() -> str:
    """One export for the module: it serves the app and records every response."""
    return postman.render()


@pytest.fixture(scope="module")
def collection(rendered) -> dict:
    return json.loads(rendered)


def _operations() -> list[dict]:
    """The app's operations in document order, each with its method added."""
    document = app.openapi()
    return [
        {"method": method.upper(), **raw}
        for item in document["paths"].values()
        for method, raw in item.items()  # every key of a path item of this document is a method
    ]


def _items(collection: dict) -> list[dict]:
    return [item for folder in collection["item"] for item in folder["item"]]


def test_the_committed_collection_is_what_the_exporter_writes(rendered):
    assert postman.TARGET.read_text(encoding="utf-8") == rendered, "run `python -m sample_api.postman`"


def test_the_collection_names_the_app_and_carries_its_base_url_and_token(collection):
    assert collection["info"]["name"] == "Bookshelf"
    assert collection["info"]["schema"] == V2_1
    variables = {variable["key"]: variable["value"] for variable in collection["variable"]}
    assert variables == {"baseUrl": "http://127.0.0.1:8000", "token": "sample-token"}
    assert collection["auth"]["type"] == "bearer"
    assert collection["auth"]["bearer"] == [{"key": "token", "value": "{{token}}", "type": "string"}]


def test_one_folder_per_tag_and_one_item_per_operation_in_document_order(collection):
    operations = _operations()
    assert [folder["name"] for folder in collection["item"]] == list(dict.fromkeys(op["tags"][0] for op in operations))
    items = _items(collection)
    assert [(item["request"]["method"], item["name"]) for item in items] == [
        (op["method"], op["summary"]) for op in operations
    ]
    assert [item["request"].get("auth") for item in items] == [
        None if "security" in op else {"type": "noauth"} for op in operations
    ]


def test_requests_carry_the_examples_of_the_document(collection):
    by_name = {item["name"]: item["request"] for item in _items(collection)}
    assert by_name["One book"]["url"] == {
        "raw": "{{baseUrl}}/books/:book_id",
        "host": ["{{baseUrl}}"],
        "path": ["books", ":book_id"],
        "variable": [{"key": "book_id", "value": "1"}],
    }
    assert "body" not in by_name["One book"]
    listing = by_name["Books, optionally those of one author"]["url"]
    assert listing["raw"] == "{{baseUrl}}/books?author_id=1&limit=10"
    assert listing["query"] == [{"key": "author_id", "value": "1"}, {"key": "limit", "value": "10"}]
    remove = by_name["Remove a book; removing one that is gone is still 204"]["url"]
    assert remove["variable"] == [{"key": "book_id", "value": "5"}]
    add = by_name["Add a book"]
    assert add["header"] == []
    assert add["body"]["mode"] == "raw"
    assert json.loads(add["body"]["raw"]) == {
        "title": "The Dispossessed", "author_id": 1, "year": 1974, "tags": ["novel", "utopia"],
    }
    lend = by_name["Lend a book to the reader in X-Reader"]
    assert lend["header"] == [{"key": "x-reader", "value": "reader-42"}]
    assert json.loads(lend["body"]["raw"]) == {"book_id": 1}


def test_every_item_carries_the_response_the_app_gave_it(collection):
    items = _items(collection)
    assert [len(item["response"]) for item in items] == [1] * len(items)
    responses = [item["response"][0] for item in items]
    assert [r["code"] for r in responses] == [200, 200, 200, 200, 201, 200, 200, 200, 204, 201]
    assert [r["status"] for r in responses[3:5]] == ["OK", "Created"]
    assert all(r["header"] == [{"key": "Content-Type", "value": "application/json"}] for r in responses)
    assert json.loads(responses[0]["body"]) == {"status": "ok", "books": 5}  # recorded against the seeded shelf
    assert json.loads(responses[4]["body"])["id"] == 6  # the book the recording itself added
    assert [book["id"] for book in json.loads(responses[5]["body"])] == [1]  # the search: seeded shelf again
    assert responses[8]["body"] == ""  # a 204 has none
    assert json.loads(responses[9]["body"]) == {"id": 1, "book_id": 1, "reader": "reader-42"}


def test_the_export_refuses_a_token_that_is_not_the_sample_one(monkeypatch):
    monkeypatch.setattr(postman, "TOKEN", "an-operator-secret")
    with pytest.raises(RuntimeError, match="SAMPLE_API_TOKEN"):
        postman.build_collection()


def test_an_operation_the_collection_cannot_express_is_refused_by_name(monkeypatch):
    tiny = FastAPI()

    @tiny.get("/things/{thing_id}", tags=["things"], summary="One thing")
    def one_thing(thing_id: int) -> dict[str, int]:
        return {"id": thing_id}

    monkeypatch.setattr(postman, "app", tiny)
    with pytest.raises(ValueError) as refused:
        postman.build_collection()
    assert str(refused.value) == "GET /things/{thing_id}: parameter 'thing_id' has no example"


def test_the_loader_reads_it_into_the_same_operations_with_bearer_security():
    api = load_postman(postman.TARGET)
    from_document = load_openapi(export.TARGET)
    assert len(api.operations) == len(_operations()) == len(from_document.operations)
    assert api.security.kind == "bearer"
    assert api.base_url == "http://127.0.0.1:8000"
    assert [(op.method, op.path, op.tag, op.secured) for op in api.operations] == [
        (op.method, op.path, op.tag, op.secured) for op in from_document.operations
    ]
