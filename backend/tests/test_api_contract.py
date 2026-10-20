import json
from pathlib import Path

from app.main import create_app

CONTRACT = Path(__file__).resolve().parents[2] / "docs" / "api" / "openapi.json"


def test_the_committed_api_contract_is_current() -> None:
    """Change an endpoint or model and this fails until the contract is regenerated and reviewed:

    cd backend && uv run python ../scripts/export_openapi.py && cd ../apps/web && pnpm gen:api
    """
    current = json.loads(json.dumps(create_app("sqlite://").openapi(), sort_keys=True))
    committed = json.loads(CONTRACT.read_text())
    assert current == committed, (
        "docs/api/openapi.json is stale; regenerate it (see this test's docstring)"
    )


def test_every_route_is_documented_with_a_response_model_or_status() -> None:
    schema = create_app("sqlite://").openapi()
    undocumented = [
        f"{method.upper()} {path}"
        for path, ops in schema["paths"].items()
        for method, op in ops.items()
        if not op.get("responses")
    ]
    assert undocumented == []
    assert len(schema["paths"]) >= 25  # guards against the router wiring silently losing routes
