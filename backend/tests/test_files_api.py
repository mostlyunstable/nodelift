from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """Overrides the shared fixture: these tests write files, so they get a folder of their own."""
    settings = Settings(data_dir=tmp_path / "data", secret_backend="memory")
    with TestClient(create_app(f"sqlite:///{tmp_path / 't.db'}", settings)) as c:
        yield c


def put(c: TestClient, path: str, text: str):  # type: ignore[no-untyped-def]
    return c.put("/api/v1/files/content", json={"path": path, "text": text})


def test_add_list_read_delete(client: TestClient) -> None:
    assert client.get("/api/v1/files").json()["files"] == []
    assert put(client, "study/notes.txt", "Mitochondria make energy.").status_code == 200
    listing = client.get("/api/v1/files").json()
    assert [f["path"] for f in listing["files"]] == ["study/notes.txt"]
    assert listing["files"][0]["bytes"] == len("Mitochondria make energy.")
    assert Path(listing["folder"]).name == "files"
    got = client.get("/api/v1/files/content", params={"path": "study/notes.txt"}).json()
    assert got["text"] == "Mitochondria make energy."
    assert client.delete("/api/v1/files", params={"path": "study/notes.txt"}).status_code == 204
    assert client.delete("/api/v1/files", params={"path": "study/notes.txt"}).status_code == 404
    assert client.get("/api/v1/files").json()["files"] == []


def test_only_the_files_folder_is_reachable(client: TestClient) -> None:
    for bad in ("../x.txt", "/etc/passwd", "a/../../x", "~/x", "a\\b"):
        assert put(client, bad, "x").status_code == 422, bad
        assert client.get("/api/v1/files/content", params={"path": bad}).status_code == 422, bad
        assert client.delete("/api/v1/files", params={"path": bad}).status_code == 422, bad


def test_hidden_files_are_not_listed_and_binary_is_refused(client: TestClient) -> None:
    folder = Path(client.get("/api/v1/files").json()["folder"])
    (folder / ".secret").write_text("x")
    (folder / "pic.bin").write_bytes(b"\xff\xfe\x00\x80")
    assert [f["path"] for f in client.get("/api/v1/files").json()["files"]] == ["pic.bin"]
    r = client.get("/api/v1/files/content", params={"path": "pic.bin"})
    assert r.status_code == 415 and r.json()["error"]["code"] == "not_text"
    assert client.get("/api/v1/files/content", params={"path": "missing.txt"}).status_code == 404
    assert put(client, "pic.bin/inside.txt", "x").status_code == 409  # a file is in the way
    assert put(client, "pic.bin", "x").status_code == 200  # replacing a file is fine
