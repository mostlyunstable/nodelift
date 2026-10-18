from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.v1.nodes import get_runner
from app.domain.ports import CodeRunner
from app.domain.run import ExecutionRun
from app.domain.workflow import ValidationIssue, WorkflowDefinition, validate_workflow
from app.engine.executor import execute_workflow

router = APIRouter(tags=["workflows"])


class ValidateResponse(BaseModel):
    valid: bool
    issues: list[ValidationIssue]


class RunRequest(BaseModel):
    workflow: WorkflowDefinition
    input: Any = None
    timeout_ms: int = Field(default=10_000, ge=100, le=30_000)


@router.post("/workflows/validate", response_model=ValidateResponse)
def validate(wf: WorkflowDefinition) -> ValidateResponse:
    issues = validate_workflow(wf)
    return ValidateResponse(valid=not issues, issues=issues)


@router.post("/runs", response_model=ExecutionRun)
async def run_workflow(
    req: RunRequest, runner: Annotated[CodeRunner, Depends(get_runner)]
) -> ExecutionRun | Any:
    issues = validate_workflow(req.workflow)
    if issues:
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_failed",
                    "message": "Workflow is invalid",
                    "details": [i.model_dump() for i in issues],
                }
            },
        )
    return await execute_workflow(req.workflow, runner, req.input, req.timeout_ms / 1000)
