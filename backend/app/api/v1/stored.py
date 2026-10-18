from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.errors import AppError
from app.api.v1.nodes import get_runner
from app.domain.ports import CodeRunner
from app.domain.records import (
    RunRecord,
    RunSummary,
    VersionRecord,
    VersionSummary,
    WorkflowRecord,
    WorkflowSummary,
)
from app.domain.repositories import RevisionConflict
from app.domain.workflow import WorkflowDefinition
from app.services.workflow_service import WorkflowService
from app.storage.repositories import SqlRunRepository, SqlWorkflowRepository

router = APIRouter(tags=["stored workflows"])


def get_service(
    request: Request, runner: Annotated[CodeRunner, Depends(get_runner)]
) -> WorkflowService:
    sf = request.app.state.session_factory
    return WorkflowService(SqlWorkflowRepository(sf), SqlRunRepository(sf), runner)


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


@router.post("/workflows/{workflow_id}/runs", response_model=RunRecord, status_code=201)
async def start_run(workflow_id: str, body: StartRun, svc: Service) -> RunRecord:
    return await svc.run(workflow_id, body.version, body.input, body.timeout_ms / 1000)


@router.get("/workflows/{workflow_id}/runs", response_model=list[RunSummary])
def list_runs(workflow_id: str, svc: Service) -> list[RunSummary]:
    _must(svc.workflows.get(workflow_id), "Workflow")
    return svc.runs.list_for_workflow(workflow_id)


@router.get("/runs/{run_id}", response_model=RunRecord)
def get_run(run_id: str, svc: Service) -> RunRecord:
    return _must(svc.runs.get(run_id), "Run")
