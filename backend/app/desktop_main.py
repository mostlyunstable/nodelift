"""Entry point used by the desktop shell (and tests), configured only through environment variables.

Required: NODECRAFT_API_TOKEN. Typical: NODECRAFT_PORT, NODECRAFT_DATA_DIR, NODECRAFT_LOG_DIR,
NODECRAFT_PARENT_PID, NODECRAFT_SHUTDOWN_ENDPOINT=1, NODECRAFT_LEGACY_DATA_DIR.
"""

import logging
import logging.handlers
import os
import sys
import threading
import time
from pathlib import Path

import uvicorn

from app.config import Settings, get_settings
from app.main import create_app
from app.storage.db import migrate_legacy_db

log = logging.getLogger("nodecraft")


def configure_logging(log_dir: Path | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file = logging.handlers.RotatingFileHandler(
            log_dir / "backend.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
        )
        handlers.append(file)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def watch_parent(pid: int, server: uvicorn.Server) -> None:
    """Exit if the process that launched us dies, even by SIGKILL: no orphaned backend."""
    while True:
        time.sleep(1)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            log.warning("parent process %s is gone; shutting down", pid)
            server.should_exit = True
            time.sleep(5)
            os._exit(0)  # graceful shutdown did not finish in time


def run(settings: Settings) -> int:
    if not settings.api_token:
        print("NODECRAFT_API_TOKEN is required in desktop mode", file=sys.stderr)
        return 2
    settings.assert_safe_bind()
    configure_logging(settings.log_dir)
    if settings.legacy_data_dir is not None:
        migrate_legacy_db(
            settings.legacy_data_dir / "nodecraft.db", settings.data_dir / "nodecraft.db"
        )
    app = create_app(settings=settings)
    config = uvicorn.Config(
        app, host=settings.host, port=settings.port, log_config=None, access_log=True
    )
    server = uvicorn.Server(config)
    app.state.server = server
    if settings.parent_pid is not None:
        threading.Thread(
            target=watch_parent, args=(settings.parent_pid, server), daemon=True
        ).start()
    log.info(
        "Nodecraft backend starting on %s:%s (data %s)",
        settings.host,
        settings.port,
        settings.data_dir,
    )
    server.run()
    log.info("Nodecraft backend stopped")
    return 0


def main() -> None:
    sys.exit(run(get_settings()))


if __name__ == "__main__":
    main()
