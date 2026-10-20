# ruff: noqa: E501
"""The debugging loop end to end: discover tests, prepare a workspace, propose and apply a fix,
run an approved command, and see the result. Every safety rule is checked from outside."""

import os
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.runtime import sandbox
from tests.test_explorer import FakeGitHub, make_tar

TOP = "octo-hello-aaaa"
BUGGY = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"
TEST = (
    "import unittest\nfrom calc import add\n\n"
    "class T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n\n"
    "if __name__ == '__main__':\n    unittest.main()\n"
)


@pytest.fixture
def gh(tmp_path: Path) -> FakeGitHub:
    fake = FakeGitHub()
    fake.tarball = make_tar(
        tmp_path / "w.tgz",
        {
            f"{TOP}/calc.py": BUGGY.encode(),
            f"{TOP}/test_calc.py": TEST.encode(),
            f"{TOP}/package.json": b'{"scripts": {"test": "echo hi"}}',
            f"{TOP}/data.bin": b"\x00\x01\x02binary",
            f"{TOP}/big.txt": b"x" * 2_000_000,
            f"{TOP}/Makefile": b"test:\n\tpython3 -m unittest\n",
        },
    ).read_bytes()
    return fake


@pytest.fixture
def api(tmp_path: Path, gh: FakeGitHub) -> Iterator[TestClient]:
    settings = Settings(data_dir=tmp_path / "data", secret_backend="memory")
    app = create_app(f"sqlite:///{tmp_path / 't.db'}", settings)
    app.state.github_transport = httpx.MockTransport(gh)
    with TestClient(app) as c:
        yield c


def wait(c: TestClient, url: str, key: str, want: str, timeout: float = 20) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        r = c.get(url).json()
        if r[key] == want:
            return r
        time.sleep(0.05)
    raise AssertionError(f"{url} never reached {want}: {r}")


@pytest.fixture
def rev(api: TestClient) -> str:
    r = api.post("/api/v1/explorer/imports", json={"url": "github.com/octo/hello"}).json()
    wait(api, f"/api/v1/explorer/revisions/{r['id']}", "analysis_status", "done")
    return r["id"]


@pytest.fixture
def ws(api: TestClient, rev: str) -> str:
    assert api.post(f"/api/v1/explorer/revisions/{rev}/workspace").status_code == 202
    wait(api, f"/api/v1/explorer/revisions/{rev}/workspace", "state", "ready")
    return rev


def run_cmd(api: TestClient, rev: str, command: str, **kw: object) -> dict:
    body = {"command": command, "approved_command": command, **kw}
    r = api.post(f"/api/v1/explorer/revisions/{rev}/commands", json=body)
    assert r.status_code == 202, r.text
    return (
        wait(
            api,
            f"/api/v1/explorer/revisions/{rev}/commands/{r.json()['id']}",
            "status",
            "running",
            0,
        )
        if False
        else _finish(api, rev, r.json()["id"])
    )


def _finish(api: TestClient, rev: str, cid: str, timeout: float = 30) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        r = api.get(f"/api/v1/explorer/revisions/{rev}/commands/{cid}").json()
        if r["status"] != "running":
            return r
        time.sleep(0.05)
    raise AssertionError("command never finished")


# ---- discovery ------------------------------------------------------------------------------------
def test_discovery_cites_the_files_and_runs_nothing(api: TestClient, rev: str) -> None:
    d = api.get(f"/api/v1/explorer/revisions/{rev}/discovery").json()
    labels = {s["label"]: s for s in d["suggestions"]}
    assert {"npm run test", "make test"} <= set(labels)
    assert labels["make test"]["evidence"] == "Makefile:1 target test"
    assert "test_calc.py" in d["test_files"]


# ---- workspace --------------------------------------------------------------------------------------
def test_workspace_is_a_full_copy_including_binary_and_large_files(
    api: TestClient, ws: str
) -> None:
    path = Path(api.get(f"/api/v1/explorer/revisions/{ws}/workspace").json()["path"])
    assert (path / "data.bin").read_bytes().startswith(b"\x00\x01")
    assert (
        path / "big.txt"
    ).stat().st_size == 2_000_000  # over the 1 MB index limit, but present here
    assert api.get(f"/api/v1/explorer/revisions/{ws}/workspace").json()["file_count"] == 6


def test_commands_need_a_prepared_workspace(api: TestClient, rev: str) -> None:
    r = api.post(
        f"/api/v1/explorer/revisions/{rev}/commands",
        json={"command": "echo hi", "approved_command": "echo hi"},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "workspace_not_ready"


# ---- approval ---------------------------------------------------------------------------------------
def test_a_command_must_be_restated_exactly_as_approved(api: TestClient, ws: str) -> None:
    r = api.post(
        f"/api/v1/explorer/revisions/{ws}/commands",
        json={"command": "echo hi", "approved_command": "echo bye"},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "not_approved"
    assert api.get(f"/api/v1/explorer/revisions/{ws}/commands").json() == []  # nothing ran


def test_importing_and_analyzing_never_start_a_command(api: TestClient, rev: str) -> None:
    assert api.get(f"/api/v1/explorer/revisions/{rev}/commands").json() == []


# ---- running ----------------------------------------------------------------------------------------
def test_the_debugging_loop_fail_propose_apply_pass(api: TestClient, ws: str) -> None:
    base = f"/api/v1/explorer/revisions/{ws}"
    failed = run_cmd(api, ws, "python3 -m unittest discover")
    assert failed["status"] == "failed" and failed["exit_code"] != 0
    assert "AssertionError" in failed["output"] and "-1 != 5" in failed["output"]

    p = api.post(
        f"{base}/patches", json={"path": "calc.py", "title": "Fix add()", "new_content": FIXED}
    )
    assert p.status_code == 201 and (p.json()["additions"], p.json()["deletions"]) == (1, 1)
    pid = p.json()["id"]
    diff = api.get(f"{base}/patches/{pid}/diff").text
    assert (
        diff.startswith("diff --git a/calc.py b/calc.py")
        and "-    return a - b" in diff
        and "+    return a + b" in diff
    )

    # proposing changed nothing yet: the repository copy and the workspace both still hold the bug
    assert api.get(f"{base}/file", params={"path": "calc.py"}).json()["content"] == BUGGY
    assert "FAILED" in run_cmd(api, ws, "python3 -m unittest discover")["output"]

    assert api.post(f"{base}/patches/{pid}/apply").json()["applied"] is True
    passed = run_cmd(api, ws, "python3 -m unittest discover")
    assert passed["status"] == "succeeded" and passed["exit_code"] == 0 and "OK" in passed["output"]
    # the imported source itself was never modified
    assert api.get(f"{base}/file", params={"path": "calc.py"}).json()["content"] == BUGGY

    assert api.post(f"{base}/patches/{pid}/revert").json()["applied"] is False
    assert run_cmd(api, ws, "python3 -m unittest discover")["status"] == "failed"


def test_patch_validation_conflicts_export_and_delete(api: TestClient, ws: str) -> None:
    base = f"/api/v1/explorer/revisions/{ws}"
    assert (
        api.post(f"{base}/patches", json={"path": "calc.py", "new_content": BUGGY}).json()["error"][
            "code"
        ]
        == "no_changes"
    )
    assert (
        api.post(f"{base}/patches", json={"path": "data.bin", "new_content": "x"}).status_code
        == 422
    )  # not an indexed text file
    assert api.post(f"{base}/patches", json={"path": "../x", "new_content": "x"}).status_code == 404
    pid = api.post(f"{base}/patches", json={"path": "calc.py", "new_content": FIXED}).json()["id"]
    exp = api.get(f"{base}/patches/{pid}/export")
    assert "attachment" in exp.headers["content-disposition"] and exp.text.startswith("diff --git")

    ws_file = Path(api.get(f"{base}/workspace").json()["path"]) / "calc.py"
    ws_file.write_text("# edited by a command\n")  # the workspace file drifted
    c = api.post(f"{base}/patches/{pid}/apply")
    assert c.status_code == 409 and c.json()["error"]["code"] == "patch_conflict"
    assert ws_file.read_text() == "# edited by a command\n"  # not overwritten
    api.delete(f"{base}/workspace")  # reset: back to the imported state
    assert api.post(f"{base}/workspace").status_code == 202
    wait(api, f"{base}/workspace", "state", "ready")
    assert api.post(f"{base}/patches/{pid}/apply").status_code == 200
    assert (
        api.delete(f"{base}/patches/{pid}").status_code == 409
    )  # applied patches must be reverted first
    api.post(f"{base}/patches/{pid}/revert")
    assert api.delete(f"{base}/patches/{pid}").status_code == 204


@pytest.mark.skipif(not sandbox.available(), reason="needs macOS Seatbelt")
class TestConfinement:
    def test_no_network_by_default_and_it_is_opt_in(self, api: TestClient, ws: str) -> None:
        import socket
        import threading

        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(5)
        hits: list[int] = []
        threading.Thread(
            target=lambda: [hits.append(1) for _ in iter(lambda: srv.accept()[0].close(), None)],
            daemon=True,
        ).start()
        cmd = f"python3 -c \"import socket; socket.create_connection(('127.0.0.1', {srv.getsockname()[1]}), timeout=2); print('connected')\""
        denied = run_cmd(api, ws, cmd)
        assert denied["status"] == "failed" and hits == []
        allowed = run_cmd(api, ws, cmd, allow_network=True)
        assert allowed["status"] == "succeeded" and "connected" in allowed["output"]
        srv.close()

    def test_home_folder_is_unreadable_unless_the_user_allows_it(
        self, api: TestClient, ws: str
    ) -> None:
        canary = Path.home() / f".nodecraft-cmd-canary-{os.getpid()}"
        canary.write_text("secret")
        try:
            cmd = f"python3 -c \"print(open('{canary}').read())\""
            assert run_cmd(api, ws, cmd)["status"] == "failed"
            ok = run_cmd(api, ws, cmd, allow_home_read=True)
            assert ok["status"] == "succeeded" and "secret" in ok["output"]
        finally:
            canary.unlink(missing_ok=True)

    def test_writes_only_inside_the_workspace_and_server_secrets_are_not_inherited(
        self, api: TestClient, ws: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NODECRAFT_API_TOKEN_TEST", "super-secret-token")
        outside = Path.home() / f".nodecraft-cmd-outside-{os.getpid()}"
        cmd = f"python3 -c \"open('inside.txt','w').write('ok'); open('{outside}','w').write('x')\""
        r = run_cmd(api, ws, cmd)
        assert r["status"] == "failed" and not outside.exists()
        wsdir = Path(api.get(f"/api/v1/explorer/revisions/{ws}/workspace").json()["path"])
        assert (wsdir / "inside.txt").read_text() == "ok"
        env = run_cmd(api, ws, "env")
        assert "super-secret-token" not in env["output"] and "NODECRAFT" not in env["output"]

    def test_cannot_package_install_without_network(self, api: TestClient, ws: str) -> None:
        r = run_cmd(api, ws, "python3 -m pip download --no-deps -d x requests")
        assert r["status"] == "failed"


def test_timeout_and_cancel_kill_the_whole_process_tree(api: TestClient, ws: str) -> None:
    base = f"/api/v1/explorer/revisions/{ws}"
    r = run_cmd(api, ws, 'python3 -c "import time; time.sleep(60)"', timeout_s=1)
    assert r["status"] == "timeout"
    marker = str(100000 + os.getpid() % 800000)  # unique, so no other process can match it
    cmd = f"python3 -c \"import subprocess,time; subprocess.Popen(['sleep','{marker}']); time.sleep(60)\""
    started = api.post(f"{base}/commands", json={"command": cmd, "approved_command": cmd}).json()
    time.sleep(1.5)
    import subprocess

    def ps() -> str:
        out = subprocess.run(["/bin/ps", "-A", "-o", "command="], capture_output=True, text=True)
        return out.stdout

    assert f"sleep {marker}" in ps()  # the grandchild really exists before we cancel
    assert api.post(f"{base}/commands/{started['id']}/cancel").status_code == 200
    assert _finish(api, ws, started["id"])["status"] == "cancelled"
    time.sleep(0.5)
    assert f"sleep {marker}" not in ps()  # ...and is gone afterwards


def test_executables_outside_the_workspace_and_unknown_programs_are_refused(
    api: TestClient, ws: str
) -> None:
    base = f"/api/v1/explorer/revisions/{ws}"
    for cmd, code in [
        ("./../../../bin/ls", "invalid_command"),
        ("definitely-not-a-program-xyz", "command_not_found"),
        ("", "invalid_command"),
    ]:
        r = api.post(f"{base}/commands", json={"command": cmd, "approved_command": cmd})
        assert r.status_code == 422 and r.json()["error"]["code"] == code, (cmd, r.text)
    r = api.post(
        f"{base}/commands",
        json={"command": "echo hi", "approved_command": "echo hi", "cwd": "../.."},
    )
    assert r.status_code == 422


def test_unconfined_machines_need_an_explicit_acknowledgement(
    api: TestClient, ws: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sandbox, "available", lambda: False)
    base = f"/api/v1/explorer/revisions/{ws}"
    r = api.post(f"{base}/commands", json={"command": "echo hi", "approved_command": "echo hi"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "unconfined_needs_acknowledgement"
    ok = api.post(
        f"{base}/commands",
        json={"command": "echo hi", "approved_command": "echo hi", "acknowledge_unconfined": True},
    )
    assert ok.status_code == 202
    assert _finish(api, ws, ok.json()["id"])["confinement"]["confined"] is False


def test_risky_commands_are_flagged_in_the_record(api: TestClient, ws: str) -> None:
    r = run_cmd(api, ws, "python3 -m pip install nothing-here")
    assert any("Installs packages" in n for n in r["notes"])


def test_call_relationships_are_served_per_file_both_ways(api: TestClient, rev: str) -> None:
    base = f"/api/v1/explorer/revisions/{rev}"
    tc = api.get(f"{base}/analysis", params={"path": "test_calc.py"}).json()
    ref = [r for r in tc["references"] if r["name"] == "add"][0]
    assert (ref["dst_path"], ref["dst_symbol"], ref["confidence"]) == ("calc.py", "add", "resolved")
    assert ref["scope"] == "T.test_add" and ref["line"] == 6
    line = TEST.splitlines()[ref["line"] - 1]
    assert line[ref["column"] - 1 : ref["end_column"] - 1] == "add"  # the span is exactly the name
    calc = api.get(f"{base}/analysis", params={"path": "calc.py"}).json()
    assert [(c["path"], c["scope"], c["dst_symbol"]) for c in calc["called_by"]] == [
        ("test_calc.py", "T.test_add", "add")
    ]
