"""Upgrading old workflow files to the current format.

Add a function for each format change: `MIGRATIONS[n]` turns a version-n document into version n+1.
Files from a NEWER Nodecraft are refused with a clear message instead of being half-understood.
"""

from collections.abc import Callable
from typing import Any

from app.domain.errors import AppError

CURRENT_SCHEMA_VERSION = 1

Migration = Callable[[dict[str, Any]], dict[str, Any]]
MIGRATIONS: dict[int, Migration] = {}  # none yet: version 1 is the first format


def unsupported_message(version: object, current: int) -> str:
    return (
        f"This workflow uses format version {version}; this Nodecraft understands up to {current}. "
        "Update Nodecraft to open it."
    )


def migrate_definition(
    raw: dict[str, Any],
    migrations: dict[int, Migration] | None = None,
    current: int = CURRENT_SCHEMA_VERSION,
) -> dict[str, Any]:
    table = MIGRATIONS if migrations is None else migrations
    version = raw.get("schema_version", 1)  # a file without a version predates versioning: v1
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise AppError(
            422,
            "invalid_schema_version",
            f"schema_version must be a positive integer, got {version!r}",
        )
    if version > current:
        raise AppError(422, "unsupported_schema_version", unsupported_message(version, current))
    data = dict(raw)
    while version < current:
        step = table.get(version)
        if step is None:
            raise AppError(
                422,
                "missing_migration",
                f"No migration from format version {version} to {version + 1}",
            )
        data = step(dict(data))
        version += 1
        data["schema_version"] = version
    data["schema_version"] = current
    return data
