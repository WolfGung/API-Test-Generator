# Tests generated from openapi.json

Bookshelf 1.0.0: 10 operations, 23 tests in 4 modules.

## Run

Needs Python 3.12 or newer: `models.py` may use `type` statements for recursive aliases.

```bash
pip install pytest httpx pydantic
API_BASE_URL=... API_TOKEN=... pytest sample_api
```

Without credentials the secured operations are skipped, not failed, so a run
without them still tells you what the unsecured surface does.

## What is here

- `conftest.py`: the HTTP client, the credentials fixture and the marker registration.
- `models.py`: one Pydantic model per named schema; the tests validate success responses with them.
- `test_health.py`
- `test_authors.py`
- `test_books.py`
- `test_loans.py`

Every test names its operation in its docstring. Each operation has a positive
case built from the document's examples, defaults and enums, one negative case
per required query or header parameter and per required body field, and, where
the operation is secured, a case without credentials. Edit freely: the generator
only writes these files again with `--overwrite`. With `--overwrite` every
`test_*.py` in the directory is replaced, including files you added; keep your
own tests under another name.
