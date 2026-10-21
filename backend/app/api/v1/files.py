"""The files folder that file nodes read and write: browse it, add notes and data, take results out.

Only this one folder is reachable. Paths are relative, and `..`, absolute paths and symlinks that
leave it are refused, exactly as they are for the file nodes.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from app.api.errors import AppError
from app.nodes.builtin.data_nodes import MAX_BYTES, safe_path

router = APIRouter(prefix="/files", tags=["files"])
MAX_LISTED = 2000


def get_base(request: Request) -> Path:
    base: Path = request.app.state.settings.data_dir / "files"
    base.mkdir(parents=True, exist_ok=True)
    return base


Base = Annotated[Path, Depends(get_base)]


class FileInfo(BaseModel):
    path: str
    bytes: int
    modified: datetime


class FileListing(BaseModel):
    folder: str  # where the files folder is on disk, so it can be opened in Finder
    files: list[FileInfo]
    truncated: bool = False


class FileText(BaseModel):
    path: str
    text: str


class NewFile(BaseModel):
    path: str = Field(min_length=1, max_length=300)
    text: str = Field(max_length=MAX_BYTES)


def _target(base: Path, path: str) -> Path:
    try:
        return safe_path(base, path)
    except ValueError as e:
        raise AppError(422, "invalid_path", str(e)) from e


@router.get("", response_model=FileListing)
def list_files(base: Base) -> FileListing:
    root = base.resolve()
    out: list[FileInfo] = []
    truncated = False
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if p.is_symlink() or not p.is_file() or any(part.startswith(".") for part in rel.parts):
            continue
        if len(out) >= MAX_LISTED:
            truncated = True
            break
        st = p.stat()
        out.append(
            FileInfo(
                path=str(rel), bytes=st.st_size, modified=datetime.fromtimestamp(st.st_mtime, UTC)
            )
        )
    return FileListing(folder=str(root), files=out, truncated=truncated)


@router.get("/content", response_model=FileText)
def read_file(base: Base, path: Annotated[str, Query(max_length=300)]) -> FileText:
    target = _target(base, path)
    if not target.is_file():
        raise AppError(404, "not_found", "No such file")
    if target.stat().st_size > MAX_BYTES:
        raise AppError(413, "file_too_large", "The file is larger than 5 MB")
    try:
        return FileText(path=path, text=target.read_text(encoding="utf-8"))
    except UnicodeDecodeError as e:
        raise AppError(415, "not_text", "This file is not UTF-8 text") from e


@router.put("/content", response_model=FileInfo)
def write_file(body: NewFile, base: Base) -> FileInfo:
    target = _target(base, body.path)
    if target.exists() and not target.is_file():
        raise AppError(409, "not_a_file", "That name is a folder")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body.text, encoding="utf-8")
    except OSError as e:
        raise AppError(
            409, "cannot_write", f"The file could not be written ({type(e).__name__})"
        ) from e
    st = target.stat()
    return FileInfo(
        path=body.path, bytes=st.st_size, modified=datetime.fromtimestamp(st.st_mtime, UTC)
    )


@router.delete("", status_code=204)
def delete_file(base: Base, path: Annotated[str, Query(max_length=300)]) -> None:
    target = _target(base, path)
    if not target.is_file():
        raise AppError(404, "not_found", "No such file")
    target.unlink()
