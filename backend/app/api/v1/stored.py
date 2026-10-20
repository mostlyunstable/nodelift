import json
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.errors import AppError
from app.api.v1.nodes import Registry
from app.domain.records import (
    RunRecord,
    RunSummary,
    VersionRecord,
    VersionSummary,
    WorkflowRecord,
    WorkflowSummary,
)
from app.domain.repositories import RevisionConflict
from app.domain.run import RunEvent
from app.domain.workflow import WorkflowDefinition
from app.services.workflow_service import WorkflowService
from app.storage.repositories import SqlRunRepository, SqlWorkflowRepository

router = APIRouter(tags=["stored workflows"])


def get_service(request: Request, registry: Registry) -> WorkflowService:
    sf = request.app.state.session_factory
    return WorkflowService(
        SqlWorkflowRepository(sf),
        SqlRunRepository(sf),
        registry,
        request.app.state.run_hub,
        request.app.state.gate,
        request.app.state.settings.max_run_seconds,
        request.app.state.settings.keep_runs_per_workflow,
    )


Service = Annotated[WorkflowService, Depends(get_service)]


class CreateWorkflow(BaseModel):
    name: str = Field(default="Untitled", min_length=1, max_length=200)
    definition: WorkflowDefinition = WorkflowDefinition()


class UpdateWorkflow(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    definition: WorkflowDefinition
    revision: int  # the revision the client last saw


class StartRun(BaseModel):
    version: int | None = None  # omitted: snapshot the draft and run that
    input: Any = None
    timeout_ms: int = Field(default=10_000, ge=100, le=30_000)


class ResumeRun(BaseModel):
    timeout_ms: int = Field(default=10_000, ge=100, le=30_000)


def _must[T](value: T | None, what: str) -> T:
    if value is None:
        raise AppError(404, "not_found", f"{what} not found")
    return value


@router.post("/workflows", response_model=WorkflowRecord, status_code=201)
def create_workflow(body: CreateWorkflow, svc: Service) -> WorkflowRecord:
    return svc.workflows.create(body.name, body.definition)


@router.get("/workflows", response_model=list[WorkflowSummary])
def list_workflows(svc: Service) -> list[WorkflowSummary]:
    return svc.workflows.list_all()


@router.get("/workflows/{workflow_id}", response_model=WorkflowRecord)
def get_workflow(workflow_id: str, svc: Service) -> WorkflowRecord:
    return _must(svc.workflows.get(workflow_id), "Workflow")


@router.put("/workflows/{workflow_id}", response_model=WorkflowRecord)
def update_workflow(workflow_id: str, body: UpdateWorkflow, svc: Service) -> WorkflowRecord:
    try:
        rec = svc.workflows.update_draft(workflow_id, body.name, body.definition, body.revision)
    except RevisionConflict as e:
        raise AppError(
            409, "revision_conflict", f"Workflow changed elsewhere (current revision {e.current})"
        ) from e
    return _must(rec, "Workflow")


@router.delete("/workflows/{workflow_id}", status_code=204)
def delete_workflow(workflow_id: str, svc: Service) -> None:
    _must(svc.workflows.delete(workflow_id) or None, "Workflow")


@router.post("/workflows/{workflow_id}/versions", response_model=VersionRecord, status_code=201)
def create_version(workflow_id: str, svc: Service) -> VersionRecord:
    return svc.snapshot(workflow_id)


@router.get("/workflows/{workflow_id}/versions", response_model=list[VersionSummary])
def list_versions(workflow_id: str, svc: Service) -> list[VersionSummary]:
    _must(svc.workflows.get(workflow_id), "Workflow")
    return svc.workflows.list_versions(workflow_id)


@router.get("/workflows/{workflow_id}/versions/{version_no}", response_model=VersionRecord)
def get_version(workflow_id: str, version_no: int, svc: Service) -> VersionRecord:
    return _must(svc.workflows.get_version(workflow_id, version_no), "Version")


@router.post("/workflows/{workflow_id}/runs", response_model=RunRecord, status_code=202)
async def start_run(workflow_id: str, body: StartRun, svc: Service) -> RunRecord:
    return await svc.start_run(workflow_id, body.version, body.input, body.timeout_ms / 1000)


@router.get("/workflows/{workflow_id}/runs", response_model=list[RunSummary])
def list_runs(workflow_id: str, svc: Service) -> list[RunSummary]:
    _must(svc.workflows.get(workflow_id), "Workflow")
    return svc.runs.list_for_workflow(workflow_id)


@router.get("/runs/{run_id}", response_model=RunRecord)
def get_run(run_id: str, svc: Service) -> RunRecord:
    return _must(svc.runs.get(run_id), "Run")


@router.get("/runs/{run_id}/events", response_model=list[RunEvent])
def list_events(
    run_id: str,
    svc: Service,
    response: Response,
    after: int = 0,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> list[RunEvent]:
    """Catch-up for a client that missed events: events with seq > `after`, at most `limit`.

    When more remain, `X-Has-More: 1` and `X-Next-After: <seq>` say where to continue.
    """
    _must(svc.runs.get(run_id), "Run")
    rows = svc.runs.list_events(run_id, after, limit + 1)
    if len(rows) > limit:
        rows = rows[:limit]
        response.headers["X-Has-More"] = "1"
        response.headers["X-Next-After"] = str(rows[-1].seq)
    return rows


def _frame(e: RunEvent) -> str:
    data = json.dumps(
        {"seq": e.seq, "type": e.type, "created_at": e.created_at.isoformat(), **e.payload}
    )
    return f"id: {e.seq}\nevent: {e.type}\ndata: {data}\n\n"


@router.get("/runs/{run_id}/events/stream")
async def stream_events(
    run_id: str,
    request: Request,
    svc: Service,
    after: int = 0,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    """Server-Sent Events. Resumes after `Last-Event-ID` (sent automatically by EventSource)."""
    _must(svc.runs.get(run_id), "Run")
    last = after
    if last_event_id and last_event_id.isdigit():
        last = max(last, int(last_event_id))

    async def gen() -> AsyncIterator[str]:
        cursor = last
        idle = 0.0
        while True:
            events = svc.runs.list_events(run_id, cursor)
            for e in events:
                cursor = e.seq
                idle = 0.0
                yield _frame(e)
                if e.type == "run.finished":
                    return
            if await request.is_disconnected():
                return
            run = svc.runs.get(run_id)
            if run is not None and run.status != "running" and not events:
                return  # finished (e.g. recovered after a restart) with nothing left to send
            await svc.hub.wait(run_id, 0.5)
            idle += 0.5
            if idle >= 15:
                idle = 0.0
                yield ": keepalive\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/runs/{run_id}/cancel", response_model=RunRecord, status_code=202)
async def cancel_run(run_id: str, svc: Service) -> RunRecord:
    return await svc.cancel_run(run_id)


@router.post("/runs/{run_id}/resume", response_model=RunRecord, status_code=202)
async def resume_run(run_id: str, svc: Service, body: ResumeRun | None = None) -> RunRecord:
    return await svc.resume_run(run_id, (body.timeout_ms if body else 10_000) / 1000)
