# Tests generated from postman-echo.postman_collection.json

Postman Echo (V2): 22 operations, 23 tests in 7 modules.

## Run

Needs Python 3.12 or newer: `models.py` may use `type` statements for recursive aliases.

```bash
pip install pytest httpx pydantic
API_BASE_URL=... API_USERNAME=... API_PASSWORD=... pytest postman_echo
```

Without credentials the secured operations are skipped, not failed, so a run
without them still tells you what the unsecured surface does.

## What is here

- `conftest.py`: the HTTP client, the credentials fixture and the marker registration.
- `models.py`: one Pydantic model per named schema; the tests validate success responses with them.
- `test_auth_digest.py`
- `test_auth_others.py`
- `test_cookies.py`
- `test_headers.py`
- `test_request_methods.py`
- `test_utilities.py`
- `test_draft_auth_oauth2_0.py`

Every test names its operation in its docstring. Each operation has a positive
case built from the document's examples, defaults and enums and, where the
operation is secured, a case without credentials. This document declares no
required query or header parameter and no required field of a JSON body (a
Postman collection never does), so there is no missing-parameter or
missing-field negative. Edit freely: the generator
only writes these files again with `--overwrite`. With `--overwrite` every
`test_*.py` in the directory is replaced, including files you added; keep your
own tests under another name.
