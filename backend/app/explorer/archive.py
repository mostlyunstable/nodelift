"""Safe extraction of a GitHub tarball. The archive is hostile input."""

import tarfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.domain.errors import AppError
from app.explorer.languages import detect_language, looks_binary

MAX_PATH_LEN = 300
MAX_COMPONENT_LEN = 200


@dataclass(frozen=True)
class Limits:
    max_files: int = 20_000
    max_file_bytes: int = 1_000_000
    max_total_bytes: int = 300_000_000


@dataclass
class ExtractedFile:
    path: str
    size: int
    lines: int
    language: str
    binary: bool
    stored: bool
    skip_reason: str | None  # too_large | binary | not_utf8 | None


class Cancelled(Exception):
    pass


def safe_relative_path(name: str) -> str | None:
    """The archive path minus its top-level folder, or None if it is unsafe or empty."""
    if "\\" in name or "\x00" in name:
        return None
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if len(parts) < 2:  # the top-level directory itself
        return None
    rel = parts[1:]
    if any(p == ".." for p in rel):
        return None
    if any(len(p) > MAX_COMPONENT_LEN for p in rel):
        return None
    out = str(PurePosixPath(*rel))
    return out if len(out) <= MAX_PATH_LEN else None


def _count_lines(text: str) -> int:
    return text.count("\n") + (1 if text and not text.endswith("\n") else 0)


def extract_tarball(
    archive: Path,
    dest: Path,
    limits: Limits,
    cancel: threading.Event | None = None,
    on_progress: Callable[[int], None] | None = None,
) -> list[ExtractedFile]:
    """Index every regular file; store the text of those that are small UTF-8 text files.

    Links, devices and directories are ignored. Entries with unsafe paths are dropped.
    """
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    files: list[ExtractedFile] = []
    seen: set[str] = set()
    total = 0
    try:
        tf = tarfile.open(archive, mode="r|gz")  # noqa: SIM115 - streaming; closed below
    except (tarfile.TarError, OSError) as e:
        raise AppError(
            502, "bad_archive", "GitHub returned an archive that could not be read"
        ) from e
    try:
        for member in tf:
            if cancel is not None and cancel.is_set():
                raise Cancelled
            if not member.isfile():
                continue
            rel = safe_relative_path(member.name)
            if rel is None or rel in seen:
                continue
            seen.add(rel)
            if len(files) >= limits.max_files:
                raise AppError(
                    413, "repo_too_large", f"The repository has more than {limits.max_files} files"
                )
            total += member.size
            if total > limits.max_total_bytes:
                raise AppError(413, "repo_too_large", "The repository is too large to import")
            lang = detect_language(rel)
            if member.size > limits.max_file_bytes:
                files.append(ExtractedFile(rel, member.size, 0, lang, False, False, "too_large"))
                continue
            fh = tf.extractfile(member)
            data = fh.read() if fh is not None else b""
            if looks_binary(data):
                files.append(ExtractedFile(rel, member.size, 0, lang, True, False, "binary"))
                continue
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                files.append(ExtractedFile(rel, member.size, 0, lang, True, False, "not_utf8"))
                continue
            target = (root / rel).resolve()
            if (
                root not in target.parents
            ):  # defence in depth; safe_relative_path already forbids '..'
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            files.append(
                ExtractedFile(rel, member.size, _count_lines(text), lang, False, True, None)
            )
            if on_progress is not None and len(files) % 200 == 0:
                on_progress(len(files))
    except tarfile.TarError as e:
        raise AppError(
            502, "bad_archive", "GitHub returned an archive that could not be read"
        ) from e
    finally:
        tf.close()
    return files
