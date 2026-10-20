"""Operational endpoints for the desktop shell and the Diagnostics dialog. Never returns secrets."""

import sys
import time
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from app.api.errors import AppError
from app.services.container import schema_status

router = APIRouter(prefix="/system", tags=["system"])
STARTED = time.monotonic()
VERSION = "0.1.0"


def _backups(request: Request) -> list[str]:
    folder: Path = request.app.state.settings.effective_backup_dir
    if not folder.exists():
        return []
    return [p.name for p in sorted(folder.glob("nodecraft-*.db"), reverse=True)]


@router.get("/info")
def info(request: Request) -> dict[str, Any]:
    s = request.app.state.settings
    revision, head = schema_status(request.app.state.database_url)
    return {
        "version": VERSION,
        "schema_revision": revision,
        "schema_head": head,
        "data_dir": str(s.data_dir),
        "log_dir": str(s.log_dir) if s.log_dir else None,
        "backup_dir": str(s.effective_backup_dir),
        "backups": _backups(request),
        "python": sys.version.split()[0],
        "uptime_s": round(time.monotonic() - STARTED, 1),
        "limits": {
            "max_concurrent_runs": s.max_concurrent_runs,
            "max_run_seconds": s.max_run_seconds,
        },
    }


@router.get("/logs")
def logs(request: Request, lines: int = 200) -> dict[str, Any]:
    """Tail of backend.log for the Diagnostics dialog."""
    s = request.app.state.settings
    path = s.log_dir / "backend.log" if s.log_dir else None
    if path is None or not path.exists():
        return {"path": str(path) if path else None, "lines": []}
    with path.open(errors="replace") as f:
        tail = deque((line.rstrip("\n") for line in f), maxlen=max(1, min(lines, 2000)))
    return {"path": str(path), "lines": list(tail)}


@router.post("/shutdown", status_code=202)
def shutdown(request: Request) -> dict[str, str]:
    """Ask the server process to exit cleanly (used by the desktop shell on quit)."""
    if not request.app.state.settings.shutdown_endpoint:
        raise AppError(404, "not_found", "Not available")
    server = getattr(request.app.state, "server", None)
    if server is None:
        raise AppError(409, "not_supported", "This server was not started by the desktop launcher")
    server.should_exit = True
    return {"status": "stopping"}
