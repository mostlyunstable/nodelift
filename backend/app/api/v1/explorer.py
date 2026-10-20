"""Repository Explorer: import a public GitHub repo at a pinned commit and browse its files."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.api.errors import AppError
from app.domain.records import (
    CommandRunRecord,
    DiscoveryRecord,
    FileAnalysisRecord,
    RepoFileRecord,
    RepoGraphRecord,
    RepoPatchRecord,
    RepoRevisionRecord,
    WorkflowDraftRecord,
    WorkspaceRecord,
)
from app.services.command_service import CommandRuns
from app.services.container import command_runs, explorer_service
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


@router.post("/revisions/{revision_id}/analyze", response_model=RepoRevisionRecord, status_code=202)
async def analyze(revision_id: str, svc: Svc) -> RepoRevisionRecord:
    # async so the background task is created on the server's event loop, not a worker thread
    return svc.analyze(revision_id)


@router.get("/revisions/{revision_id}/graph", response_model=RepoGraphRecord)
def graph(revision_id: str, svc: Svc) -> RepoGraphRecord:
    return svc.graph(revision_id)


@router.get("/revisions/{revision_id}/analysis", response_model=FileAnalysisRecord)
def file_analysis(
    revision_id: str, svc: Svc, path: Annotated[str, Query(max_length=400)]
) -> FileAnalysisRecord:
    return svc.file_analysis(revision_id, path)


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


# ---- workspace, tests and approved commands ----------------------------------------------------
def get_runs(request: Request) -> CommandRuns:
    return command_runs(request.app.state)


Runs = Annotated[CommandRuns, Depends(get_runs)]


@router.get("/revisions/{revision_id}/discovery", response_model=DiscoveryRecord)
def discovery(revision_id: str, svc: Svc) -> DiscoveryRecord:
    """How the repository says it is tested. Reads files only; runs nothing."""
    return svc.discovery(revision_id)


@router.get("/revisions/{revision_id}/workspace", response_model=WorkspaceRecord)
def workspace(revision_id: str, svc: Svc) -> WorkspaceRecord:
    return svc.workspace(revision_id)


@router.post("/revisions/{revision_id}/workspace", response_model=WorkspaceRecord, status_code=202)
async def prepare_workspace(revision_id: str, svc: Svc) -> WorkspaceRecord:
    return svc.prepare_workspace(revision_id)


@router.delete("/revisions/{revision_id}/workspace", response_model=WorkspaceRecord)
def reset_workspace(revision_id: str, svc: Svc) -> WorkspaceRecord:
    return svc.reset_workspace(revision_id)


class CommandRequest(BaseModel):
    command: str = Field(max_length=2000)
    approved_command: str = Field(
        max_length=2000
    )  # must repeat `command` exactly: the user's approval
    cwd: str = Field(default="", max_length=300)
    timeout_s: float = Field(default=300, ge=1, le=900)
    allow_network: bool = False
    allow_home_read: bool = False
    acknowledge_unconfined: bool = False


@router.post("/revisions/{revision_id}/commands", response_model=CommandRunRecord, status_code=202)
async def run_command(
    revision_id: str, body: CommandRequest, svc: Svc, runs: Runs
) -> CommandRunRecord:
    """Runs only a command the caller restated verbatim as approved, in the prepared workspace."""
    if body.approved_command != body.command:
        raise AppError(
            422, "not_approved", "The approved command must be exactly the command that will run"
        )
    ws = svc.ready_workspace_path(revision_id)
    run = await runs.start(
        revision_id, ws, body.command, body.cwd, body.timeout_s,
        body.allow_network, body.allow_home_read, body.acknowledge_unconfined,
    )  # fmt: skip
    return runs.record(run)


@router.get("/revisions/{revision_id}/commands", response_model=list[CommandRunRecord])
def list_commands(revision_id: str, svc: Svc, runs: Runs) -> list[CommandRunRecord]:
    svc.get(revision_id)
    return [runs.record(r) for r in runs.list_for(revision_id)]


@router.get("/revisions/{revision_id}/commands/{run_id}", response_model=CommandRunRecord)
def get_command(revision_id: str, run_id: str, runs: Runs) -> CommandRunRecord:
    return runs.record(runs.get(run_id, revision_id))


@router.post("/revisions/{revision_id}/commands/{run_id}/cancel", response_model=CommandRunRecord)
def cancel_command(revision_id: str, run_id: str, runs: Runs) -> CommandRunRecord:
    return runs.record(runs.cancel(run_id, revision_id))


# ---- proposed changes ---------------------------------------------------------------------------
class PatchRequest(BaseModel):
    path: str = Field(max_length=400)
    title: str = Field(default="", max_length=200)
    new_content: str = Field(max_length=2_000_000)


@router.get("/revisions/{revision_id}/patches", response_model=list[RepoPatchRecord])
def list_patches(revision_id: str, svc: Svc) -> list[RepoPatchRecord]:
    return svc.list_patches(revision_id)


@router.post("/revisions/{revision_id}/patches", response_model=RepoPatchRecord, status_code=201)
def create_patch(revision_id: str, body: PatchRequest, svc: Svc) -> RepoPatchRecord:
    return svc.create_patch(revision_id, body.path, body.title, body.new_content)


@router.get("/revisions/{revision_id}/patches/{patch_id}/diff", response_class=PlainTextResponse)
def patch_diff(revision_id: str, patch_id: str, svc: Svc) -> PlainTextResponse:
    return PlainTextResponse(svc.patch_diff(revision_id, patch_id), media_type="text/x-diff")


@router.get("/revisions/{revision_id}/patches/{patch_id}/export", response_class=PlainTextResponse)
def export_patch(revision_id: str, patch_id: str, svc: Svc) -> PlainTextResponse:
    """The same diff as a downloadable file you can `git apply` yourself."""
    return PlainTextResponse(
        svc.patch_diff(revision_id, patch_id),
        media_type="text/x-diff",
        headers={"Content-Disposition": f'attachment; filename="{patch_id}.patch"'},
    )


@router.post("/revisions/{revision_id}/patches/{patch_id}/apply", response_model=RepoPatchRecord)
def apply_patch(revision_id: str, patch_id: str, svc: Svc) -> RepoPatchRecord:
    return svc.apply_patch(revision_id, patch_id)


@router.post("/revisions/{revision_id}/patches/{patch_id}/revert", response_model=RepoPatchRecord)
def revert_patch(revision_id: str, patch_id: str, svc: Svc) -> RepoPatchRecord:
    return svc.revert_patch(revision_id, patch_id)


@router.delete("/revisions/{revision_id}/patches/{patch_id}", status_code=204)
def delete_patch(revision_id: str, patch_id: str, svc: Svc) -> None:
    svc.delete_patch(revision_id, patch_id)


# ---- repository code -> workflow node ------------------------------------------------------------
class DraftRequest(BaseModel):
    path: str = Field(max_length=400)
    symbol: str = Field(max_length=200)


@router.post("/revisions/{revision_id}/workflow-draft", response_model=WorkflowDraftRecord)
def workflow_draft(revision_id: str, body: DraftRequest, svc: Svc) -> WorkflowDraftRecord:
    """A reviewable draft node from one Python function. Nothing is created or run."""
    return svc.workflow_draft(revision_id, body.path, body.symbol)
