"""Repository Explorer: import a public GitHub repo at a pinned commit and browse its files."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field

from app.domain.records import RepoFileRecord, RepoRevisionRecord
from app.services.container import explorer_service
from app.services.explorer_service import ExplorerService, FileContent

router = APIRouter(prefix="/explorer", tags=["explorer"])


def get_service(request: Request) -> ExplorerService:
    return explorer_service(request.app.state)


Svc = Annotated[ExplorerService, Depends(get_service)]


class ImportRequest(BaseModel):
    url: str = Field(max_length=300)


@router.post("/imports", response_model=RepoRevisionRecord)
async def start_import(body: ImportRequest, svc: Svc, response: Response) -> RepoRevisionRecord:
    """202 while a new import runs in the background; 200 if this exact commit is already known."""
    rev, started = await svc.start_import(body.url)
    response.status_code = 202 if started else 200
    return rev


@router.get("/revisions", response_model=list[RepoRevisionRecord])
def list_revisions(svc: Svc) -> list[RepoRevisionRecord]:
    return svc.list_revisions()


@router.get("/revisions/{revision_id}", response_model=RepoRevisionRecord)
def get_revision(revision_id: str, svc: Svc) -> RepoRevisionRecord:
    return svc.get(revision_id)


@router.post("/revisions/{revision_id}/cancel", response_model=RepoRevisionRecord)
def cancel_import(revision_id: str, svc: Svc) -> RepoRevisionRecord:
    return svc.cancel(revision_id)


@router.delete("/revisions/{revision_id}", status_code=204)
def delete_revision(revision_id: str, svc: Svc) -> None:
    svc.delete(revision_id)


@router.get("/revisions/{revision_id}/files", response_model=list[RepoFileRecord])
def list_files(revision_id: str, svc: Svc) -> list[RepoFileRecord]:
    return svc.files(revision_id)


@router.get("/revisions/{revision_id}/file", response_model=FileContent)
def read_file(
    revision_id: str, svc: Svc, path: Annotated[str, Query(max_length=400)]
) -> FileContent:
    return svc.read_file(revision_id, path)
