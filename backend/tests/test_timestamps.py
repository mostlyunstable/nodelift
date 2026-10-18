from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import Settings
from app.domain.workflow import WorkflowDefinition
from app.main import create_app
from app.storage.db import make_engine, make_session_factory, upgrade_to_head
from app.storage.models import WorkflowRow
from tests.test_run_events import start_run
from tests.test_storage_api import DOUBLE, create, defn, wait_run


def timestamps(data: Any, path: str = "") -> list[tuple[str, str]]:
    """Every created_at / updated_at value in a JSON document."""
    found: list[tuple[str, str]] = []
    if isinstance(data, dict):
        for k, v in data.items():
            if k in ("created_at", "updated_at") and isinstance(v, str):
                found.append((f"{path}.{k}", v))
            found += timestamps(v, f"{path}.{k}")
    elif isinstance(data, list):
        for i, v in enumerate(data):
            found += timestamps(v, f"{path}[{i}]")
    return found


def is_utc(value: str) -> bool:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.utcoffset() == timedelta(0) and (value.endswith("Z") or value.endswith("+00:00"))


def test_every_timestamp_the_api_returns_is_explicit_utc(client: TestClient) -> None:
    wf = create(client, defn(DOUBLE))
    wid = wf["id"]
    client.post(f"/api/v1/workflows/{wid}/versions")
    run_id = start_run(client, wid, input={"v": 1})
    wait_run(client, run_id)
    responses = {
        "create": wf,
        "get": client.get(f"/api/v1/workflows/{wid}").json(),
        "list": client.get("/api/v1/workflows").json(),
        "versions": client.get(f"/api/v1/workflows/{wid}/versions").json(),
        "version": client.get(f"/api/v1/workflows/{wid}/versions/1").json(),
        "runs": client.get(f"/api/v1/workflows/{wid}/runs").json(),
        "run": client.get(f"/api/v1/runs/{run_id}").json(),
        "events": client.get(f"/api/v1/runs/{run_id}/events").json(),
    }
    total = 0
    for name, body in responses.items():
        found = timestamps(body)
        assert found, f"{name} has no timestamps to check"
        for where, value in found:
            assert is_utc(value), f"{name}{where} = {value!r} is not explicit UTC"
        total += len(found)
    assert total >= 12


def test_timestamps_are_close_to_now(client: TestClient) -> None:
    before = datetime.now(UTC) - timedelta(seconds=2)
    wid = create(client, defn(DOUBLE))["id"]
    stored = client.get(f"/api/v1/workflows/{wid}").json()["created_at"]
    parsed = datetime.fromisoformat(stored.replace("Z", "+00:00"))
    assert before <= parsed <= datetime.now(UTC) + timedelta(seconds=2)


def test_rows_written_before_the_fix_are_read_as_utc(tmp_path: Path) -> None:
    """Older databases hold naive UTC strings; they must not be reinterpreted as local time."""
    url = f"sqlite:///{tmp_path / 'old.db'}"
    upgrade_to_head(url)
    draft = WorkflowDefinition(id="wf_old", name="old").model_dump_json()
    with make_engine(url).begin() as conn:
        conn.execute(
            text(
                "INSERT INTO workflows (id, name, draft, revision, created_at, updated_at) "
                "VALUES ('wf_old', 'old', :d, 1, "
                "'2026-01-02 03:04:05.000000', '2026-01-02 03:04:05.000000')"
            ),
            {"d": draft},
        )
    with TestClient(create_app(url, Settings(data_dir=tmp_path))) as c:
        row = c.get("/api/v1/workflows").json()[0]
        assert row["updated_at"] == "2026-01-02T03:04:05Z"


def test_non_utc_values_are_stored_as_utc(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'tz.db'}"
    upgrade_to_head(url)
    sf = make_session_factory(make_engine(url))
    ist = timezone(timedelta(hours=5, minutes=30))
    with sf.begin() as s:
        s.add(
            WorkflowRow(
                id="wf_tz",
                name="tz",
                draft={},
                revision=1,
                created_at=datetime(2026, 1, 2, 8, 0, tzinfo=ist),
                updated_at=datetime(2026, 1, 2, 8, 0, tzinfo=ist),
            )
        )
    with make_engine(url).connect() as conn:
        raw = conn.execute(text("SELECT created_at FROM workflows WHERE id='wf_tz'")).scalar_one()
    assert str(raw).startswith("2026-01-02 02:30:00")  # 08:00 IST == 02:30 UTC
    with sf() as s:
        loaded = s.get(WorkflowRow, "wf_tz")
        assert loaded is not None and loaded.created_at == datetime(2026, 1, 2, 2, 30, tzinfo=UTC)
        assert loaded.created_at.tzinfo is not None
