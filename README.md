# API Test Generator

A command-line tool that turns an OpenAPI 3 document or a Postman collection into a runnable pytest suite.

[![CI](https://github.com/WolfGung/API-Test-Generator/actions/workflows/ci.yml/badge.svg)](https://github.com/WolfGung/API-Test-Generator/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## What a document becomes

| Document | Format | Operations | Tests | Test modules | Run against |
| --- | --- | --- | --- | --- | --- |
| `sample_api/openapi.json` | OpenAPI 3.1 | 10 | 23 | 4 | the sample API, on every push |
| `sample_api/bookshelf.postman_collection.json` | Postman v2.1 | 10 | 14 | 4 | the sample API, on every push |
| `fixtures/petstore-openapi3.json` | OpenAPI 3.0 | 19 | 33 (1 skipped) | 3 | petstore3.swagger.io, nightly |
| `fixtures/postman-echo.postman_collection.json` | Postman v2.0 | 22 | 23 (1 skipped) | 7 | generated and collected only |

## What this shows

- **Moving Postman collections to pytest.** The collection exported from the sample API becomes a suite that runs green against it. Folders become modules; saved responses become response models.
- **An API test suite for an existing backend, from its document.** The suite generated from the sample API's OpenAPI document runs against that API on every push. A wrong token fails exactly the secured operations, and nothing else.
- **Readable code you keep editing.** One module per tag, one function per case, every value traceable to the document, `ruff` clean. A generated suite needs pytest, httpx and Pydantic, not the generator.

## Try it

```bash
python3 -m venv .venv && source .venv/bin/activate
make install
api-test-gen --spec sample_api/openapi.json --out examples/sample_api --base-url http://127.0.0.1:8000
```

The tests run this exact command into an empty directory. In this checkout `examples/sample_api` already holds its output: add `--overwrite` to write it again, or point `--out` elsewhere. The command prints what it wrote:

```
Wrote 23 tests for 10 operations to examples/sample_api: test_health.py, test_authors.py, test_books.py, test_loans.py
```

Then, with the sample API running (`make api` in another shell):

```bash
API_TOKEN=sample-token pytest examples/sample_api -q
```

```
23 passed in 0.16s
```

One of the generated tests, as written to `examples/sample_api/test_books.py`:

```python
def test_create_book(client, auth_headers):
    """POST /books: Add a book"""
    response = client.request(
        "POST",
        "/books",
        headers=auth_headers,
        json={
            "title": "The Dispossessed",
            "author_id": 1,
            "year": 1974,
            "tags": ["novel", "utopia"],
        },
    )
    assert response.status_code == 201, response.text[:300]
    TypeAdapter(Book).validate_python(response.json())
```

The other three suites in the table come from the same command, again into an empty directory each:

```bash
api-test-gen --postman sample_api/bookshelf.postman_collection.json --out examples/sample_api_postman --base-url http://127.0.0.1:8000
api-test-gen --spec fixtures/petstore-openapi3.json --out examples/petstore --base-url https://petstore3.swagger.io/api/v3
api-test-gen --postman fixtures/postman-echo.postman_collection.json --out examples/postman_echo
```

## What the generator writes

The generator reads OpenAPI 3.0 and 3.1 documents (YAML or JSON, `$ref` within the document) and Postman collections v2.0 and v2.1 (folders, saved responses, collection variables) into one model; `--include-tag` and `--exclude-tag` narrow the suite to some tags, which for a collection are its folders. For each operation it writes:

- **A positive case.** Path, query and header values come from the document — `example`, `examples`, `default`, the first `enum` value — and, failing those, from the type: `"string"`, `1`, `true`, or a format-aware value for `email`, `date-time`, `uuid` and the like. A JSON body is built the same way from the schema: required fields plus any optional field that carries an example. The assertion is the documented success status, and the body is validated against the Pydantic model of the documented response schema.
- **One negative case per required query or header parameter and per required top-level body field:** the same request with that one thing left out, expected to answer 4xx.
- **A case without credentials** where the operation is secured, expected to answer 401 or 403.

YAML scalars are read as the document wrote them: an unquoted `2024-01-31T12:00:00Z`, `on` or `yes` stays that string, not a date or a boolean, so an example is sent as the document shows it and an enum of dates stays an enum of strings. `true` and `false`, numbers and `null` keep their types.

An operation with a form, multipart or binary body gets a test marked `skip`, with the reason in it. The four suites are committed under [`examples/`](examples/) exactly as the generator writes them. `tests/test_examples.py` regenerates each and refuses a difference; `tests/test_readme_pins.py` refuses this page when a number moves.

`conftest.py` holds the HTTP client and the credentials fixture: `API_BASE_URL` points the suite at a server, and `API_TOKEN`, `API_KEY` or `API_USERNAME`/`API_PASSWORD` carry the credentials, without which the secured operations are skipped rather than failed. `models.py` holds one Pydantic model per named schema, with `extra="forbid"` where the document closes the schema and an alias wherever a property name cannot be a Python field name. A Postman collection has no schemas, so the model of a response is inferred from the saved example response, types only; and since a collection says nothing about which fields are required, no missing-field negative comes from one, and the suite's own README says so.

## What is not generated

- **Path parameters get no negative case.** Leaving one out changes the route, not the request.
- **Bodies that are not JSON or plain text.** Form, multipart and binary bodies produce a positive test marked `skip` with the reason in it, so the gap is visible in the run rather than silent.
- **Values that satisfy a `pattern`, `multipleOf`, `uniqueItems`, `exclusiveMaximum` or a rule across fields.** Of the constraints, the sampler honours `minimum`, `exclusiveMinimum`, `maximum`, `minLength`, `maxLength` and `minItems`; its values are plausible, not exhaustive, and a document that carries examples gets a better suite.
- **Chains.** Nothing creates a resource and then reads it back; every case stands alone against whatever state the server has, which is why the sample API's delete is idempotent.
- **Authentication other than bearer, basic and an API key in a header.** Digest, OAuth flows and keys in a query string leave the operation unsecured in the generated suite: its requests go out without credentials, and a server that insists on them will say so.
- **Response headers, timing, and anything the document does not say.**

## How the proof is run

`make test` runs the generator's own tests: the loaders against small documents and the two public ones, the model generator (the generated source is imported and used), the renderer, the command line, the committed examples against fresh generation, and then both sample-API suites as a client would run them. That last part is `pytest` in a subprocess against the sample API served in-process. Each suite runs three ways: with the token (everything passes), with a wrong token (exactly the 4 secured operations fail), without one (those 4 and their negatives are skipped). Nothing in `make test` reaches the network.

CI does the same on every push, and once a night runs the Petstore suite against `petstore3.swagger.io`; the same job can be started by hand. That job is allowed to fail: the public Petstore is shared writable state, and a red there is information about the server, not about the generator.

```bash
docker compose run --rm gen     # the sample API and its generated suite, in two containers
```

## Repository

```
src/api_test_gen/   the generator: ir, openapi, postman, samples, cases, naming, models, render, generator, cli
sample_api/         the Bookshelf API, its exported openapi.json and the Postman collection exported from it
fixtures/           the Petstore document and the Postman Echo collection
examples/           the four generated suites, committed as the generator writes them
tests/              the generator's tests, including the live run against the sample API
tools/examples.py   the table of the four examples and `make examples`
```

## Licence

MIT — see [LICENSE](LICENSE).

## Related work

Four more repositories from the same portfolio:

- **[Toolshop-Test-Automation-Framework](https://github.com/WolfGung/Toolshop-Test-Automation-Framework)** — a test automation framework built from scratch for an online shop: API, browser and end-to-end cases against a public demo shop or a local Docker stand, with test design documents.
- **[Marketplace-Test-Automation-Framework](https://github.com/WolfGung/Marketplace-Test-Automation-Framework)** — API and browser tests for a marketplace shop, run against a small stand shipped in the repository with a nightly drift check of the public demo site, a smoke set, video and traces per browser test and a published Allure report.
- **[Web-Scraping-Automation-Framework](https://github.com/WolfGung/Web-Scraping-Automation-Framework)** — a scraper that collects two practice sites and a demo store of its own, over HTTP and through a browser, detects changes between nightly runs and publishes the data, the change report and the test report.
- **[Test-Suite-Rescue](https://github.com/WolfGung/Test-Suite-Rescue)** — a deliberately sick test suite, its cured version with the same coverage on Playwright and on Selenium, and the measured difference between them against the same application, reproducible with one command.

## Hire me

I take short, well-defined jobs: a test automation framework from scratch, an API test suite for an existing backend, end-to-end tests for a critical flow, fixing flaky tests and reducing run time, setting up CI for existing tests, scrapers and data pipelines. Profile on Guru: [https://www.guru.com/freelancers/pavel-zhukov-atum](https://www.guru.com/freelancers/pavel-zhukov-atum). Time zone: Central European Time (CET/CEST), so my working hours overlap with Central European business hours. I work in writing.
