"""Write the API's OpenAPI document to frontend/openapi.json.

The frontend generates its TypeScript types from that file (`npm run gen:api`), and a test keeps
it equal to the live schema, so a changed DTO breaks the frontend build instead of the browser.

Run from backend/:  uv run python -m app.api.export_openapi
"""

from __future__ import annotations

import json
from pathlib import Path

from app.api.main import app

TARGET = Path(__file__).resolve().parents[3] / "frontend" / "openapi.json"


def render() -> str:
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    TARGET.write_text(render(), encoding="utf-8", newline="\n")
    print(f"wrote {TARGET}")
