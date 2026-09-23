import httpx

from sample_api import export
from sample_api.app import TOKEN, app

AUTH = {"Authorization": f"Bearer {TOKEN}"}


def test_the_committed_document_is_what_the_app_serves():
    assert export.TARGET.read_text(encoding="utf-8") == export.render(), "run `python -m sample_api.export`"


def test_reads_are_open_and_writes_need_the_token(sample_api_url):
    with httpx.Client(base_url=sample_api_url) as client:
        assert client.get("/books/1").json()["title"] == "The Dispossessed"
        book = {"title": "x", "author_id": 1, "year": 2000}
        assert client.post("/books", json=book).status_code == 401
        assert client.post("/books", json=book, headers={"Authorization": "Bearer no"}).status_code == 401
        created = client.post("/books", json=book, headers=AUTH)
        assert created.status_code == 201 and created.json()["id"] >= 6


def test_delete_is_idempotent_and_the_examples_survive_a_full_pass(sample_api_url):
    with httpx.Client(base_url=sample_api_url) as client:
        assert client.delete("/books/5", headers=AUTH).status_code == 204
        assert client.delete("/books/5", headers=AUTH).status_code == 204
        assert client.get("/books/1").status_code == 200  # the id every other example points at
        same = {"title": "The Dispossessed", "author_id": 1, "year": 1974}
        assert client.put("/books/1", json=same, headers=AUTH).status_code == 200
        loan = client.post("/loans", json={"book_id": 1}, headers={**AUTH, "X-Reader": "reader-42"})
        assert loan.status_code == 201 and loan.json()["reader"] == "reader-42"
        assert client.post("/loans", json={"book_id": 1}, headers=AUTH).status_code == 422  # X-Reader is required


def test_the_document_carries_what_the_generator_reads():
    document = app.openapi()
    assert document["openapi"].startswith("3.1")
    assert document["components"]["securitySchemes"] == {"HTTPBearer": {"type": "http", "scheme": "bearer"}}
    assert document["paths"]["/books"]["post"]["security"] == [{"HTTPBearer": []}]
    assert "security" not in document["paths"]["/books"]["get"]
    assert document["paths"]["/books/search"]["get"]["parameters"][0]["required"] is True
    assert document["components"]["schemas"]["Book"]["additionalProperties"] is False
    assert document["paths"]["/books/{book_id}"]["delete"]["parameters"][0]["schema"]["examples"] == [5]
    assert document["paths"]["/books"]["get"]["operationId"] == "list_books"
