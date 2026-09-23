.PHONY: install test lint examples api petstore-live

install:
	python3 -m pip install -e ".[dev]"

# The generator's own tests: loaders, cases, models, the committed examples,
# and the generated sample-API suite run against the sample API itself.
test:
	python3 -m pytest

lint:
	ruff check src tests tools sample_api examples

# Regenerate the four committed example suites; the tests refuse examples
# that differ from what the generator writes.
examples:
	python3 -m tools.examples

# The sample API by hand, on http://127.0.0.1:8000 (docs at /docs).
api:
	python3 -m uvicorn sample_api.app:app --port 8000

# The Petstore suite against the public server. It is somebody else's data,
# so a red here is information, not a verdict; CI runs it nightly the same way.
petstore-live:
	api-test-gen --spec fixtures/petstore-openapi3.json --out build/petstore --overwrite \
		--base-url https://petstore3.swagger.io/api/v3
	API_KEY=special-key python3 -m pytest build/petstore -q -p no:cacheprovider
