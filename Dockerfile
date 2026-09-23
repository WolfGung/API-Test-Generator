FROM python:3.12-slim

WORKDIR /work
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[dev]"
COPY sample_api ./sample_api
COPY fixtures ./fixtures

CMD ["api-test-gen", "--help"]
