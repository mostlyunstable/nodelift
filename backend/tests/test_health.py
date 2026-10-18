from fastapi.testclient import TestClient


def test_health_ok(client: TestClient) -> None:
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": "0.1.0"}
