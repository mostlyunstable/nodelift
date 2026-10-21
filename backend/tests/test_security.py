import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.security import hostname
from app.config import Settings
from app.main import create_app
from tests.test_storage_api import create

TOKEN = "t0ken-for-tests-0123456789"


def make(tmp_path: Path, **kw: object) -> TestClient:
    settings = Settings(data_dir=tmp_path, **kw)  # type: ignore[arg-type]
    return TestClient(create_app(f"sqlite:///{tmp_path / 's.db'}", settings))


# ---------------------------------------------------------------- Host header (DNS rebinding)


@pytest.mark.parametrize(
    "host",
    ["evil.example", "evil.example:8000", "127.0.0.1.evil.example", "0.0.0.0", "10.0.0.5:8000", ""],
)
def test_unknown_host_is_rejected(client: TestClient, host: str) -> None:
    r = client.get("/api/v1/health", headers={"Host": host})
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden_host"


@pytest.mark.parametrize(
    "host", ["127.0.0.1", "127.0.0.1:8000", "localhost:5173", "LOCALHOST", "[::1]:8000"]
)
def test_loopback_hosts_are_accepted(client: TestClient, host: str) -> None:
    assert client.get("/api/v1/health", headers={"Host": host}).status_code == 200


def test_rebinding_attack_shape_is_blocked(client: TestClient) -> None:
    """Attacker page: Host and Origin are both attacker.example, JSON POST to the code endpoint."""
    r = client.post(
        "/api/v1/nodes/code/test",
        json={"source": "def main(i):\n    return 1", "input": None},
        headers={"Host": "attacker.example:8000", "Origin": "http://attacker.example:8000"},
    )
    assert r.status_code == 403


def test_hostname_parsing() -> None:
    assert hostname("127.0.0.1:8000") == "127.0.0.1"
    assert hostname("[::1]:8000") == "[::1]"
    assert hostname("Example.COM") == "example.com"


# ---------------------------------------------------------------- Origin


@pytest.mark.parametrize(
    "origin",
    ["https://evil.example", "http://localhost:9999", "null", "http://localhost:5173.evil.example"],
)
def test_foreign_origin_is_rejected(client: TestClient, origin: str) -> None:
    r = client.get("/api/v1/workflows", headers={"Origin": origin})
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden_origin"


def test_allowed_and_absent_origin(client: TestClient) -> None:
    assert (
        client.get("/api/v1/workflows", headers={"Origin": "http://localhost:5173"}).status_code
        == 200
    )
    assert (
        client.get("/api/v1/workflows", headers={"Origin": "http://127.0.0.1:5173/"}).status_code
        == 200
    )
    assert client.get("/api/v1/workflows").status_code == 200  # same-origin GETs carry no Origin


def test_origin_allowlist_is_configurable(tmp_path: Path) -> None:
    with make(tmp_path, allowed_origins="tauri://localhost") as c:
        assert (
            c.get("/api/v1/workflows", headers={"Origin": "tauri://localhost"}).status_code == 200
        )
        assert (
            c.get("/api/v1/workflows", headers={"Origin": "http://localhost:5173"}).status_code
            == 403
        )


# ---------------------------------------------------------------- token


def test_token_required_on_every_route_except_health(tmp_path: Path) -> None:
    with make(tmp_path, api_token=TOKEN) as c:
        assert c.get("/api/v1/health").status_code == 200  # liveness probe stays open
        checked = 0
        paths = c.app.openapi()["paths"]  # type: ignore[attr-defined]
        for path, ops in paths.items():
            if path == "/api/v1/health":
                continue
            for method in ops:
                url = path
                for name in ("workflow_id", "run_id", "version_no", "trigger_id", "token"):
                    url = url.replace("{" + name + "}", "1")
                if path.startswith("/api/v1/hooks/"):
                    # a webhook is authenticated by the secret in its own URL, not by the app token
                    assert c.request(method.upper(), url).status_code == 404
                    continue
                r = c.request(method.upper(), url)
                assert r.status_code == 401, (method, path, r.status_code)
                assert r.headers["www-authenticate"] == "Bearer"
                checked += 1
        for doc in ("/docs", "/redoc", "/openapi.json"):  # docs expose the whole API surface
            assert c.get(doc).status_code == 401, doc
        assert checked >= 15  # guard against the loop silently checking nothing


def test_token_validation(tmp_path: Path) -> None:
    with make(tmp_path, api_token=TOKEN) as c:
        bad = [
            {},
            {"Authorization": "Bearer wrong"},
            {"Authorization": TOKEN},  # missing scheme
            {"Authorization": f"Basic {TOKEN}"},
            {"Authorization": f"Bearer {TOKEN}x"},
            {"Authorization": "Bearer "},
        ]
        for headers in bad:
            assert c.get("/api/v1/workflows", headers=headers).status_code == 401, headers
        ok = c.get("/api/v1/workflows", headers={"Authorization": f"bearer {TOKEN}"})
        assert ok.status_code == 200  # scheme is case-insensitive


def test_token_protects_execution_and_streams(tmp_path: Path) -> None:
    with make(tmp_path, api_token=TOKEN) as c:
        auth = {"Authorization": f"Bearer {TOKEN}"}
        body = {"source": "def main(i):\n    return 1", "input": None}
        assert c.post("/api/v1/nodes/code/test", json=body).status_code == 401
        assert c.post("/api/v1/nodes/code/test", json=body, headers=auth).status_code == 200
        assert c.get("/api/v1/runs/x/events/stream").status_code == 401


def test_host_check_runs_before_token(tmp_path: Path) -> None:
    with make(tmp_path, api_token=TOKEN) as c:
        r = c.get(
            "/api/v1/health", headers={"Host": "evil.example", "Authorization": f"Bearer {TOKEN}"}
        )
        assert r.status_code == 403


# ---------------------------------------------------------------- execution gate (P0-2)


def slow_source(seconds: float) -> dict[str, object]:
    return {
        "source": f"import time\ndef main(i):\n    time.sleep({seconds})\n    return 1",
        "input": None,
    }


def test_node_tests_are_capped_and_slots_are_released(tmp_path: Path) -> None:
    with make(tmp_path, max_concurrent_node_tests=1) as c:
        results: list[int] = []
        t = threading.Thread(
            target=lambda: results.append(
                c.post("/api/v1/nodes/code/test", json=slow_source(1.5)).status_code
            )
        )
        t.start()
        time.sleep(0.5)
        blocked = c.post("/api/v1/nodes/code/test", json=slow_source(0.1))
        assert (
            blocked.status_code == 429 and blocked.json()["error"]["code"] == "too_many_node_tests"
        )
        generic = c.post(
            "/api/v1/nodes/test",
            json={"type": "code.python", "config": {"source": "def main(i):\n    return 1"}},
        )
        assert generic.status_code == 429  # the generic endpoint shares the same gate
        t.join()
        assert results == [200]
        again = c.post("/api/v1/nodes/code/test", json=slow_source(0.1))
        assert again.status_code == 200  # the slot was released


def test_failed_node_test_releases_its_slot(tmp_path: Path) -> None:
    with make(tmp_path, max_concurrent_node_tests=1) as c:
        for _ in range(3):  # a request that raises (422) must not leak a slot
            c.post("/api/v1/nodes/test", json={"type": "nope"})
        r = c.post("/api/v1/nodes/code/test", json=slow_source(0.1))
        assert r.status_code == 200
        for _ in range(3):  # user-code failure is a 200 result; also must release
            c.post("/api/v1/nodes/code/test", json={"source": "def main(", "input": None})
        assert c.post("/api/v1/nodes/code/test", json=slow_source(0.1)).status_code == 200


def test_runs_and_node_tests_have_separate_budgets(tmp_path: Path) -> None:
    with make(tmp_path, max_concurrent_runs=1, max_concurrent_node_tests=1) as c:
        wid = create(
            c,
            {
                "nodes": [
                    {
                        "id": "a",
                        "type": "code.python",
                        "config": {"source": slow_source(5)["source"]},
                    }
                ]
            },
        )["id"]
        run = c.post(f"/api/v1/workflows/{wid}/runs", json={})
        assert run.status_code == 202
        second = c.post(f"/api/v1/workflows/{wid}/runs", json={})
        assert second.status_code == 429  # run slot taken
        assert (
            c.post("/api/v1/nodes/code/test", json=slow_source(0.1)).status_code == 200
        )  # tests unaffected
        c.post(f"/api/v1/runs/{run.json()['id']}/cancel")


# ---------------------------------------------------------------- CORS for the desktop webview


DESKTOP_ORIGIN = "tauri://localhost"


def preflight(c: TestClient, origin: str, headers: str = "authorization,content-type") -> object:
    return c.options(
        "/api/v1/workflows",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": headers,
        },
    )


def test_preflight_from_the_desktop_webview_succeeds_without_a_token(tmp_path: Path) -> None:
    """Browsers never send credentials on a preflight, so it must not hit the token check."""
    with make(tmp_path, api_token=TOKEN, allowed_origins=DESKTOP_ORIGIN) as c:
        r = preflight(c, DESKTOP_ORIGIN)
        assert r.status_code == 200  # type: ignore[attr-defined]
        assert r.headers["access-control-allow-origin"] == DESKTOP_ORIGIN  # type: ignore[attr-defined]
        allowed = r.headers["access-control-allow-headers"].lower()  # type: ignore[attr-defined]
        assert "authorization" in allowed and "content-type" in allowed
        # ...but the real request still needs the token
        assert c.get("/api/v1/workflows", headers={"Origin": DESKTOP_ORIGIN}).status_code == 401
        ok = c.get(
            "/api/v1/workflows",
            headers={"Origin": DESKTOP_ORIGIN, "Authorization": f"Bearer {TOKEN}"},
        )
        assert ok.status_code == 200
        assert ok.headers["access-control-allow-origin"] == DESKTOP_ORIGIN


def test_preflight_from_other_origins_is_refused(tmp_path: Path) -> None:
    with make(tmp_path, api_token=TOKEN, allowed_origins=DESKTOP_ORIGIN) as c:
        for origin in ("https://evil.example", "http://localhost:5173", "null"):
            r = preflight(c, origin)
            assert r.status_code in (400, 403), origin  # type: ignore[attr-defined]
            assert "access-control-allow-origin" not in r.headers  # type: ignore[attr-defined]


def test_cors_does_not_allow_unlisted_headers_or_methods(tmp_path: Path) -> None:
    with make(tmp_path, allowed_origins=DESKTOP_ORIGIN) as c:
        assert preflight(c, DESKTOP_ORIGIN, "x-custom-header").status_code == 400  # type: ignore[attr-defined]
        r = c.options(
            "/api/v1/workflows",
            headers={
                "Origin": DESKTOP_ORIGIN,
                "Access-Control-Request-Method": "PATCH",
            },
        )
        assert r.status_code == 400
