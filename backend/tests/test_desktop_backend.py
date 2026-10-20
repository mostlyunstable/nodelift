import os
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.storage import db
from app.storage.db import (
    alembic_config,
    current_revision,
    head_revision,
    migrate_legacy_db,
    prune_backups,
    upgrade_with_backup,
)
from tests.test_dev_server import free_port, listening, wait_closed
from tests.test_storage_api import DOUBLE, create, defn

BACKEND = Path(__file__).resolve().parents[1]


def seed_old_db(path: Path, revision: str = "0001") -> str:
    """A database that is one or more migrations behind, holding real data."""
    url = f"sqlite:///{path}"
    command.upgrade(alembic_config(url), revision)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO workflows (id, name, draft, revision, created_at, updated_at) "
        "VALUES ('wf_keep', 'keep me', '{}', 1, '2026-01-02 03:04:05', '2026-01-02 03:04:05')"
    )
    conn.commit()
    conn.close()
    return url


def names(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return [r[0] for r in conn.execute("SELECT name FROM workflows")]
    finally:
        conn.close()


# ---------------------------------------------------------------- migration backups


def test_existing_database_is_backed_up_before_migrating(tmp_path: Path) -> None:
    path = tmp_path / "n.db"
    url = seed_old_db(path, "0001")
    backups = tmp_path / "backups"
    backup = upgrade_with_backup(url, backups)
    assert backup is not None and backup.exists() and backup.parent == backups
    assert current_revision(url) == head_revision()  # upgraded
    assert names(path) == ["keep me"]  # data survived the migration
    assert current_revision(f"sqlite:///{backup}") == "0001"  # the backup is the OLD schema
    assert names(backup) == ["keep me"]


def test_no_backup_for_fresh_or_current_databases(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'fresh.db'}"
    backups = tmp_path / "backups"
    assert upgrade_with_backup(url, backups) is None  # brand new
    assert upgrade_with_backup(url, backups) is None  # already at head
    assert not backups.exists() or list(backups.iterdir()) == []


def test_failed_migration_restores_the_original_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "n.db"
    url = seed_old_db(path, "0001")
    before = names(path)

    def broken_upgrade(cfg: object, rev: str) -> None:
        conn = sqlite3.connect(path)
        conn.execute("DROP TABLE workflows")  # a migration that wrecks the data, then fails
        conn.commit()
        conn.close()
        raise RuntimeError("boom")

    monkeypatch.setattr(db.command, "upgrade", broken_upgrade)
    with pytest.raises(RuntimeError, match="boom"):
        upgrade_with_backup(url, tmp_path / "backups")
    assert names(path) == before  # restored
    assert current_revision(url) == "0001"


def test_only_the_newest_backups_are_kept(tmp_path: Path) -> None:
    for i in range(8):
        f = tmp_path / f"nodecraft-0001-to-0003-{i}.db"
        f.write_bytes(b"x")
        os.utime(f, (1000 + i, 1000 + i))
    (tmp_path / "unrelated.db").write_bytes(b"x")
    prune_backups(tmp_path, keep=3)
    left = sorted(p.name for p in tmp_path.iterdir())
    assert left == [
        "nodecraft-0001-to-0003-5.db",
        "nodecraft-0001-to-0003-6.db",
        "nodecraft-0001-to-0003-7.db",
        "unrelated.db",
    ]


def test_app_startup_backs_up_through_settings(tmp_path: Path) -> None:
    path = tmp_path / "n.db"
    url = seed_old_db(path, "0002")
    settings = Settings(data_dir=tmp_path)
    with TestClient(create_app(url, settings)) as c:
        info = c.get("/api/v1/system/info").json()
    assert info["schema_revision"] == info["schema_head"]
    assert len(info["backups"]) == 1 and "0002-to-" in info["backups"][0]


# ---------------------------------------------------------------- legacy import


def test_legacy_database_is_copied_not_moved(tmp_path: Path) -> None:
    legacy_dir, new_dir = tmp_path / "old", tmp_path / "new"
    legacy_dir.mkdir()
    seed_old_db(legacy_dir / "nodecraft.db", "0003")
    before = (legacy_dir / "nodecraft.db").read_bytes()
    assert migrate_legacy_db(legacy_dir / "nodecraft.db", new_dir / "nodecraft.db") is True
    assert names(new_dir / "nodecraft.db") == ["keep me"]
    assert (legacy_dir / "nodecraft.db").read_bytes() == before  # original untouched


def test_legacy_import_never_overwrites_and_skips_missing_or_empty(tmp_path: Path) -> None:
    legacy = tmp_path / "old.db"
    seed_old_db(legacy, "0003")
    target = tmp_path / "new.db"
    target.write_bytes(b"existing user data")
    assert migrate_legacy_db(legacy, target) is False
    assert target.read_bytes() == b"existing user data"
    assert migrate_legacy_db(tmp_path / "missing.db", tmp_path / "x.db") is False
    empty = tmp_path / "empty.db"
    empty.write_bytes(b"")
    assert migrate_legacy_db(empty, tmp_path / "y.db") is False
    assert not (tmp_path / "y.db").exists()


def test_legacy_import_includes_uncheckpointed_wal_data(tmp_path: Path) -> None:
    legacy = tmp_path / "old.db"
    url = seed_old_db(legacy, "0003")
    conn = sqlite3.connect(legacy)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "INSERT INTO workflows (id, name, draft, revision, created_at, updated_at) "
        "VALUES ('wf_wal', 'in the wal', '{}', 1, '2026-01-02', '2026-01-02')"
    )
    conn.commit()  # connection left open on purpose: data may only be in the -wal file
    try:
        assert migrate_legacy_db(legacy, tmp_path / "new.db") is True
        assert sorted(names(tmp_path / "new.db")) == ["in the wal", "keep me"]
    finally:
        conn.close()
    assert url


def test_corrupt_legacy_database_is_rejected(tmp_path: Path) -> None:
    legacy = tmp_path / "old.db"
    legacy.write_bytes(b"this is definitely not a sqlite file" * 100)
    with pytest.raises(sqlite3.DatabaseError):
        migrate_legacy_db(legacy, tmp_path / "new.db")
    target = tmp_path / "new.db"
    assert not target.exists()  # a partial copy must not be left behind as if it were valid
    assert legacy.read_bytes().startswith(b"this is definitely")


# ---------------------------------------------------------------- system endpoints


def make(tmp_path: Path, **kw: object) -> TestClient:
    return TestClient(
        create_app(f"sqlite:///{tmp_path / 's.db'}", Settings(data_dir=tmp_path, **kw))
    )  # type: ignore[arg-type]


def test_system_info_has_no_secrets(tmp_path: Path) -> None:
    with make(tmp_path, api_token="supersecret-token") as c:
        r = c.get("/api/v1/system/info", headers={"Authorization": "Bearer supersecret-token"})
    body = r.json()
    assert r.status_code == 200 and body["version"] and body["python"]
    assert "supersecret-token" not in r.text
    assert set(body) >= {
        "schema_revision",
        "schema_head",
        "data_dir",
        "backup_dir",
        "backups",
        "uptime_s",
    }


def test_shutdown_is_off_by_default_and_needs_a_server(tmp_path: Path) -> None:
    with make(tmp_path) as c:
        assert c.post("/api/v1/system/shutdown").status_code == 404
    with make(tmp_path, shutdown_endpoint=True) as c:
        assert c.post("/api/v1/system/shutdown").status_code == 409  # not started by the launcher
        c.app.state.server = SimpleNamespace(should_exit=False)  # type: ignore[attr-defined]
        assert c.post("/api/v1/system/shutdown").status_code == 202
        assert c.app.state.server.should_exit is True  # type: ignore[attr-defined]


def test_logs_endpoint_returns_a_bounded_tail(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "backend.log").write_text("\n".join(f"line {i}" for i in range(500)))
    with make(tmp_path, log_dir=log_dir) as c:
        body = c.get("/api/v1/system/logs", params={"lines": 5}).json()
        assert body["lines"] == [f"line {i}" for i in range(495, 500)]
        assert len(c.get("/api/v1/system/logs", params={"lines": 99999}).json()["lines"]) == 500
    with make(tmp_path / "nolog") as c:
        assert c.get("/api/v1/system/logs").json()["lines"] == []


def test_system_endpoints_require_the_token(tmp_path: Path) -> None:
    with make(tmp_path, api_token="t", shutdown_endpoint=True) as c:
        for method, path in [
            ("GET", "/system/info"),
            ("GET", "/system/logs"),
            ("POST", "/system/shutdown"),
        ]:
            assert c.request(method, f"/api/v1{path}").status_code == 401


# ---------------------------------------------------------------- the real desktop process


def launch(tmp_path: Path, port: int, **extra: str) -> subprocess.Popen[bytes]:
    env = {
        **os.environ,
        "NODECRAFT_PORT": str(port),
        "NODECRAFT_DATA_DIR": str(tmp_path / "data"),
        "NODECRAFT_LOG_DIR": str(tmp_path / "logs"),
        "NODECRAFT_ALLOWED_HOSTS": "127.0.0.1,localhost",
        "NODECRAFT_SHUTDOWN_ENDPOINT": "1",
        **extra,
    }
    env.pop("NODECRAFT_API_TOKEN", None) if "NODECRAFT_API_TOKEN" not in extra else None
    return subprocess.Popen(
        [sys.executable, "-m", "app.desktop_main"], cwd=BACKEND, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )  # fmt: skip


def get(port: int, path: str, token: str | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=2) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def wait_ready(port: int, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if get(port, "/api/v1/health")[0] == 200:
                return
        except OSError:
            time.sleep(0.2)
    raise AssertionError("desktop backend never became ready")


def test_desktop_process_requires_a_token(tmp_path: Path) -> None:
    proc = launch(tmp_path, free_port())
    _, err = proc.communicate(timeout=15)
    assert proc.returncode == 2 and b"NODECRAFT_API_TOKEN" in err


def test_desktop_process_lifecycle(tmp_path: Path) -> None:
    port, token = free_port(), "tok-" + "x" * 30
    proc = launch(tmp_path, port, NODECRAFT_API_TOKEN=token)
    try:
        wait_ready(port)
        assert get(port, "/api/v1/workflows")[0] == 401  # token enforced
        assert get(port, "/api/v1/workflows", token)[0] == 200
        # shut down through the API, the way the shell does on quit
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/v1/system/shutdown", method="POST",
            headers={"Authorization": f"Bearer {token}"},
        )  # fmt: skip
        assert urllib.request.urlopen(req, timeout=3).status == 202
        assert proc.wait(timeout=15) == 0  # clean exit code
        assert wait_closed(port, 5)
    finally:
        proc.kill()
    log = (tmp_path / "logs" / "backend.log").read_text()
    assert "backend starting" in log and "backend stopped" in log
    assert token not in log  # secrets never reach the log file


def test_desktop_process_exits_when_its_parent_dies(tmp_path: Path) -> None:
    parent = subprocess.Popen(["sleep", "300"])
    port = free_port()
    proc = launch(
        tmp_path, port, NODECRAFT_API_TOKEN="t" * 32, NODECRAFT_PARENT_PID=str(parent.pid)
    )
    try:
        wait_ready(port)
        parent.kill()  # the shell was killed without a chance to stop us
        parent.wait()
        assert proc.wait(timeout=15) == 0
        assert not listening(port)
    finally:
        proc.kill()
        parent.kill()


def test_desktop_process_imports_the_legacy_database(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    seed_old_db(legacy / "nodecraft.db", "0003")
    port, token = free_port(), "t" * 32
    proc = launch(tmp_path, port, NODECRAFT_API_TOKEN=token, NODECRAFT_LEGACY_DATA_DIR=str(legacy))
    try:
        wait_ready(port)
        status, body = get(port, "/api/v1/workflows", token)
        assert status == 200 and b"keep me" in body  # the old data is there in the new location
        proc.send_signal(signal.SIGTERM)
        # uvicorn shuts down gracefully, then re-raises the signal: -15 is a clean stop
        assert proc.wait(timeout=15) in (0, -signal.SIGTERM)
    finally:
        proc.kill()
    assert "Application shutdown complete" in (tmp_path / "logs" / "backend.log").read_text()
    assert names(legacy / "nodecraft.db") == ["keep me"]  # and the original is still intact


def test_export_helpers_unused_imports() -> None:
    assert DOUBLE and defn and create  # keep shared helpers referenced
