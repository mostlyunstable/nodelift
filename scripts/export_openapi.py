#!/usr/bin/env python3
"""Write the backend's OpenAPI schema to docs/api/openapi.json (the committed API contract).

Run from backend/:  uv run python ../scripts/export_openapi.py
A backend test fails if the committed file is stale, so API changes are always visible in review, and
`pnpm gen:api` in apps/web turns the file into TypeScript types.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.main import create_app  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "docs" / "api" / "openapi.json"


def schema() -> dict[str, object]:
    return create_app("sqlite://").openapi()


if __name__ == "__main__":
    OUT.write_text(json.dumps(schema(), indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUT}")
