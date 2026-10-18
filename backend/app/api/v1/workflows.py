from fastapi import APIRouter
from pydantic import BaseModel

from app.api.v1.nodes import Registry
from app.domain.workflow import ValidationIssue, WorkflowDefinition, validate_workflow

router = APIRouter(tags=["workflows"])


class ValidateResponse(BaseModel):
    valid: bool
    issues: list[ValidationIssue]


@router.post("/workflows/validate", response_model=ValidateResponse)
def validate(wf: WorkflowDefinition, registry: Registry) -> ValidateResponse:
    issues = validate_workflow(wf, registry)
    return ValidateResponse(valid=not issues, issues=issues)
