"""Write the app's OpenAPI document to sample_api/openapi.json: `python -m sample_api.export`."""

from __future__ import annotations

import json
from pathlib import Path

from .app import app

TARGET = Path(__file__).with_name("openapi.json")


def render() -> str:
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    TARGET.write_text(render(), encoding="utf-8")
    print(f"wrote {TARGET}")
