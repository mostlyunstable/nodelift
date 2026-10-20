import logging
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

log = logging.getLogger("nodecraft.db")

# Lives inside the package so it is found in a source checkout and in a bundled app alike.
MIGRATIONS_DIR = Path(__file__).with_name("migrations")


def _ensure_sqlite_dir(url: str) -> None:
    if url.startswith("sqlite:///") and ":memory:" not in url:
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)


def make_engine(url: str) -> Engine:
    _ensure_sqlite_dir(url)
    engine = create_engine(url)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_conn, _record):  # type: ignore[no-untyped-def]
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def alembic_config(url: str) -> Config:
    # No .ini file: its logging section would replace the application's log handlers.
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def head_revision() -> str:
    head = ScriptDirectory.from_config(alembic_config("sqlite://")).get_current_head()
    assert head is not None
    return head


def current_revision(url: str) -> str | None:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()


def upgrade_to_head(url: str) -> None:
    _ensure_sqlite_dir(url)
    command.upgrade(alembic_config(url), "head")


def _sqlite_path(url: str) -> Path | None:
    if url.startswith("sqlite:///") and ":memory:" not in url:
        return Path(url.removeprefix("sqlite:///"))
    return None


def copy_sqlite(src: Path, dst: Path) -> None:
    """Consistent copy (includes WAL content), safe while the source is open."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(src)
    target = sqlite3.connect(dst)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def prune_backups(backup_dir: Path, keep: int) -> None:
    backups = sorted(
        backup_dir.glob("nodecraft-*.db"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    for old in backups[keep:]:
        old.unlink(missing_ok=True)


def upgrade_with_backup(url: str, backup_dir: Path | None, keep: int = 5) -> Path | None:
    """Upgrade to head, backing up an existing database first (restored if the migration fails).

    Returns the backup path when one was made.
    """
    db_path = _sqlite_path(url)
    if db_path is None or backup_dir is None or not db_path.exists():
        upgrade_to_head(url)
        return None
    current = current_revision(url)
    head = head_revision()
    if current is None or current == head:  # brand-new file, or nothing to migrate
        upgrade_to_head(url)
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = backup_dir / f"nodecraft-{current}-to-{head}-{stamp}.db"
    copy_sqlite(db_path, backup)
    log.info("backed up database to %s before migrating %s -> %s", backup, current, head)
    try:
        upgrade_to_head(url)
    except BaseException:
        log.exception("migration failed; restoring the pre-migration backup")
        for suffix in ("-wal", "-shm"):
            Path(str(db_path) + suffix).unlink(missing_ok=True)
        shutil.copyfile(backup, db_path)
        raise
    prune_backups(backup_dir, keep)
    return backup


def migrate_legacy_db(legacy: Path, target: Path) -> bool:
    """One-time copy of a database from an older location. Never modifies or deletes the original.

    Returns True when a copy was made. Refuses to overwrite an existing target or to keep a copy
    that fails an integrity check.
    """
    if target.exists() or not legacy.exists() or legacy.stat().st_size == 0:
        return False
    try:
        copy_sqlite(legacy, target)
        conn = sqlite3.connect(target)
        try:
            ok = conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            conn.close()
    except BaseException:
        target.unlink(missing_ok=True)  # never leave a partial copy that looks like real data
        raise
    if not ok:
        target.unlink(missing_ok=True)
        raise RuntimeError(f"legacy database at {legacy} failed its integrity check; not imported")
    log.info("imported existing database from %s", legacy)
    return True
