#!/usr/bin/env python3
"""End-to-end smoke test of a bundled runtime (or of the runtime inside Nodecraft.app).

    python3 scripts/smoke_runtime.py [RUNTIME_DIR]

Starts the backend the way the desktop shell does (empty environment, random port and token), runs a code
node that imports the standard library, runs a two-node workflow, checks auth, then shuts it down and
verifies nothing is left running.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT = Path(__file__).resolve().parents[1] / "apps/web/src-tauri/resources/runtime"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def call(port: int, token: str | None, method: str, path: str, body: object = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/v1{path}", data=data, method=method)
    if data:
        req.add_header("content-type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, json.loads(raw) if raw else None


def main() -> int:
    runtime = Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT).resolve()
    import re

    python = next(p for p in sorted((runtime / "python" / "bin").iterdir()) if re.fullmatch(r"python3\.\d+", p.name))
    work = Path(tempfile.mkdtemp(prefix="nodecraft-smoke-"))
    port, token = free_port(), os.urandom(16).hex()
    env = {  # deliberately NOT inheriting the developer's environment
        "PATH": "/usr/bin:/bin",
        "HOME": str(work),
        "PYTHONPATH": str(runtime / "site-packages"),
        "NODECRAFT_PORT": str(port),
        "NODECRAFT_API_TOKEN": token,
        "NODECRAFT_DATA_DIR": str(work / "data"),
        "NODECRAFT_LOG_DIR": str(work / "logs"),
        "NODECRAFT_SHUTDOWN_ENDPOINT": "1",
    }
    proc = subprocess.Popen(
        [str(python), "-s", "-m", "app.desktop_main"], cwd="/", env=env, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL
    )  # fmt: skip
    failures: list[str] = []

    def check(name: str, ok: bool, detail: object = "") -> None:
        print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  -> {detail}"))
        if not ok:
            failures.append(name)

    try:
        deadline = time.monotonic() + 30
        ready = False
        while time.monotonic() < deadline and proc.poll() is None:
            try:
                ready = call(port, None, "GET", "/health")[0] == 200
                if ready:
                    break
            except OSError:
                time.sleep(0.2)
        check("backend becomes ready", ready, proc.stderr.read().decode()[-500:] if proc.poll() is not None else "timeout")
        if not ready:
            return 1
        check("rejects requests without the token", call(port, None, "GET", "/workflows")[0] == 401)
        src = "import csv, io, statistics, sqlite3\ndef main(i):\n    rows = list(csv.reader(io.StringIO('a,1\\nb,3')))\n    return {'mean': statistics.mean(int(r[1]) for r in rows), 'sqlite': sqlite3.sqlite_version[:1]}"
        status, res = call(port, token, "POST", "/nodes/code/test", {"source": src, "input": None})
        check("code node can use the standard library", status == 200 and isinstance(res, dict) and res.get("output", {}).get("mean") == 2, res)
        wf = {"nodes": [
            {"id": "a", "type": "code.python", "config": {"source": "def main(i):\n    return {'v': 20}"}},
            {"id": "b", "type": "transform.json", "config": {"mapping": {"doubled": "$.v"}}},
        ], "edges": [{"source": {"node": "a"}, "target": {"node": "b", "port": "in"}}]}
        _, created = call(port, token, "POST", "/workflows", {"name": "smoke", "definition": wf})
        _, run = call(port, token, "POST", f"/workflows/{created['id']}/runs", {})  # type: ignore[index]
        final: dict[str, object] = {}
        for _ in range(100):
            _, final = call(port, token, "GET", f"/runs/{run['id']}")  # type: ignore[index,assignment]
            if final["status"] != "running":
                break
            time.sleep(0.1)
        check("two-node workflow runs to completion", final.get("status") == "succeeded", final)
        _, info = call(port, token, "GET", "/system/info")
        check("data lands in the configured directory", (work / "data" / "nodecraft.db").exists() and isinstance(info, dict))
        check("backend writes a log file", (work / "logs" / "backend.log").exists())
        check("shutdown endpoint accepted", call(port, token, "POST", "/system/shutdown")[0] == 202)
        try:
            proc.wait(timeout=15)
            exited = True
        except subprocess.TimeoutExpired:
            exited = False
        check("backend exits after shutdown", exited)
        with socket.socket() as s:
            s.settimeout(0.5)
            check("port is released", s.connect_ex(("127.0.0.1", port)) != 0)
    finally:
        if proc.poll() is None:
            proc.kill()
    print("\nsmoke test " + ("FAILED: " + ", ".join(failures) if failures else "passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
