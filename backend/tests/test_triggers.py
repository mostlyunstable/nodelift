from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.container import trigger_service
from app.services.triggers import next_after
from tests.test_storage_api import DOUBLE, create, defn, wait_run


def add(client: TestClient, wid: str, **body):  # type: ignore[no-untyped-def]
    return client.post(f"/api/v1/workflows/{wid}/triggers", json=body)


def test_next_after_interval_and_daily() -> None:
    now = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    assert next_after(15, None, now) == now + timedelta(minutes=15)
    daily = next_after(None, "08:30", now)
    assert daily > now and daily - now <= timedelta(days=1, hours=1)
    assert daily.astimezone().strftime("%H:%M") == "08:30"


def test_schedule_validation(client: TestClient) -> None:
    wid = create(client, defn(DOUBLE))["id"]
    assert add(client, wid, kind="schedule").status_code == 422  # neither
    assert add(client, wid, kind="schedule", every_minutes=5, daily_at="08:00").status_code == 422
    assert add(client, wid, kind="schedule", every_minutes=0).status_code == 422
    assert add(client, wid, kind="schedule", daily_at="25:00").status_code == 422
    assert add(client, "nope", kind="schedule", every_minutes=5).status_code == 404
    ok = add(client, wid, kind="schedule", every_minutes=5)
    assert ok.status_code == 201 and ok.json()["trigger"]["next_run_at"]
    assert len(client.get(f"/api/v1/workflows/{wid}/triggers").json()) == 1


def fire_due(client: TestClient, now: datetime | None = None) -> int:
    svc = trigger_service(client.app.state)  # type: ignore[attr-defined]
    return client.portal.call(svc.fire_due, now)  # type: ignore[union-attr, no-any-return]


def test_due_schedule_starts_a_run_and_moves_on(client: TestClient) -> None:
    wid = create(client, defn(DOUBLE))["id"]
    tid = add(client, wid, kind="schedule", every_minutes=1).json()["trigger"]["id"]
    assert fire_due(client) == 0  # not due yet
    later = datetime.now(UTC) + timedelta(minutes=2)
    assert fire_due(client, later) == 1
    rec = client.get(f"/api/v1/workflows/{wid}/triggers").json()[0]
    assert rec["id"] == tid and rec["last_run_id"]
    assert datetime.fromisoformat(rec["next_run_at"]) > later
    wait_run(client, rec["last_run_id"])


def test_disabled_schedule_does_not_fire(client: TestClient) -> None:
    wid = create(client, defn(DOUBLE))["id"]
    tid = add(client, wid, kind="schedule", every_minutes=1).json()["trigger"]["id"]
    off = client.put(f"/api/v1/triggers/{tid}", json={"enabled": False}).json()
    assert off["enabled"] is False and off["next_run_at"] is None
    assert fire_due(client, datetime.now(UTC) + timedelta(hours=1)) == 0
    on = client.put(f"/api/v1/triggers/{tid}", json={"enabled": True}).json()
    assert on["next_run_at"]


def test_webhook_token_is_shown_once_and_starts_a_run(client: TestClient) -> None:
    wid = create(client, defn(DOUBLE))["id"]
    made = add(client, wid, kind="webhook").json()
    path = made["webhook_path"]
    assert path.startswith("/api/v1/hooks/" + made["trigger"]["id"] + "/")
    assert "token" not in str(client.get(f"/api/v1/workflows/{wid}/triggers").json()).lower()
    r = client.post(path, json={"v": 4})
    assert r.status_code == 202
    run = wait_run(client, r.json()["run_id"])
    assert run["status"] == "succeeded"


def test_webhook_rejects_wrong_token_and_disabled(client: TestClient) -> None:
    wid = create(client, defn(DOUBLE))["id"]
    made = add(client, wid, kind="webhook").json()
    tid = made["trigger"]["id"]
    assert client.post(f"/api/v1/hooks/{tid}/wrong").status_code == 404
    assert client.post("/api/v1/hooks/trg_nope/wrong").status_code == 404
    client.put(f"/api/v1/triggers/{tid}", json={"enabled": False})
    assert client.post(made["webhook_path"], json={}).status_code == 409
    bad = client.post(made["webhook_path"], content="not json", headers={"content-type": "x/y"})
    assert bad.status_code in (409, 422)


def test_webhook_needs_no_app_token_but_everything_else_does(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from app.config import Settings

    settings = Settings(
        data_dir=tmp_path / "d", secret_backend="memory", api_token="s3cret-token-x"
    )
    with TestClient(create_app(f"sqlite:///{tmp_path / 't.db'}", settings)) as c:
        auth = {"Authorization": "Bearer s3cret-token-x"}
        wid = c.post(
            "/api/v1/workflows",
            json={"name": "w", "definition": defn(DOUBLE)},
            headers=auth,
        ).json()["id"]
        made = c.post(
            f"/api/v1/workflows/{wid}/triggers", json={"kind": "webhook"}, headers=auth
        ).json()
        assert c.get(f"/api/v1/workflows/{wid}/triggers").status_code == 401
        assert c.post(made["webhook_path"], json={"v": 1}).status_code == 202


def test_delete_trigger_and_cascade(client: TestClient) -> None:
    wid = create(client, defn(DOUBLE))["id"]
    tid = add(client, wid, kind="schedule", every_minutes=5).json()["trigger"]["id"]
    assert client.delete(f"/api/v1/triggers/{tid}").status_code == 204
    assert client.delete(f"/api/v1/triggers/{tid}").status_code == 404
    add(client, wid, kind="webhook")
    assert client.delete(f"/api/v1/workflows/{wid}").status_code == 204
