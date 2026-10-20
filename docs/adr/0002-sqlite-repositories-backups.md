# 0002 — SQLite behind repository protocols; backups before migrations

**Status:** accepted

**Decision.** Persistence is SQLite (WAL) through SQLAlchemy, behind `Protocol`s in `app/domain/repositories.py`.
Alembic migrations ship inside the package (`app/storage/migrations`) so a bundled app finds them. Before applying a
migration to an existing database the app copies it with SQLite's backup API (`backups/`, last 5 kept) and restores the
copy if the migration fails. An older `~/.nodecraft` database is copied, never moved, into the new data folder.

**Why.** A local-first desktop app must never strand or corrupt a user's data on upgrade. Protocols keep the engine and
services independent of the database, so Postgres is a new repository implementation plus a test run, not a rewrite.

**Not done.** Postgres has never been run. Timestamps are stored UTC and returned timezone-aware (`UTCDateTime`).
Runs older than the newest 200 per workflow are pruned.
