"""Schedules and webhooks for a workflow."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.errors import AppError
from app.domain.records import TriggerRecord
from app.services.container import trigger_service
from app.services.triggers import MAX_HOOK_BODY, TriggerService

router = APIRouter(tags=["triggers"])


def get_service(request: Request) -> TriggerService:
    return trigger_service(request.app.state)


Service = Annotated[TriggerService, Depends(get_service)]


class NewTrigger(BaseModel):
    kind: str = Field(pattern="^(schedule|webhook)$")
    every_minutes: int | None = None
    daily_at: str | None = None


class TriggerCreated(BaseModel):
    trigger: TriggerRecord
    # Shown once, when a webhook is created. Never returned again.
    webhook_path: str | None = None


class Enable(BaseModel):
    enabled: bool


@router.get("/workflows/{workflow_id}/triggers", response_model=list[TriggerRecord])
def list_triggers(workflow_id: str, svc: Service) -> list[TriggerRecord]:
    if svc.workflows.workflows.get(workflow_id) is None:
        raise AppError(404, "not_found", "Workflow not found")
    return svc.triggers.list_for_workflow(workflow_id)


@router.post("/workflows/{workflow_id}/triggers", response_model=TriggerCreated, status_code=201)
def add_trigger(workflow_id: str, body: NewTrigger, svc: Service) -> TriggerCreated:
    if body.kind == "schedule":
        return TriggerCreated(
            trigger=svc.add_schedule(workflow_id, body.every_minutes, body.daily_at)
        )
    rec, token = svc.add_webhook(workflow_id)
    return TriggerCreated(trigger=rec, webhook_path=f"/api/v1/hooks/{rec.id}/{token}")


@router.put("/triggers/{trigger_id}", response_model=TriggerRecord)
def set_enabled(trigger_id: str, body: Enable, svc: Service) -> TriggerRecord:
    return svc.set_enabled(trigger_id, body.enabled)


@router.delete("/triggers/{trigger_id}", status_code=204)
def delete_trigger(trigger_id: str, svc: Service) -> None:
    if not svc.triggers.delete(trigger_id):
        raise AppError(404, "not_found", "Trigger not found")


@router.post("/hooks/{trigger_id}/{token}", status_code=202)
async def fire_webhook(
    trigger_id: str, token: str, request: Request, svc: Service
) -> dict[str, str]:
    """Starts the workflow; a JSON body becomes the run input. The URL itself is the credential."""
    raw = await request.body()
    if len(raw) > MAX_HOOK_BODY:
        raise AppError(413, "body_too_large", "The request body is too large")
    body: Any = None
    if raw.strip():
        try:
            body = await request.json()
        except ValueError as e:
            raise AppError(422, "invalid_json", "The request body must be JSON") from e
    return {"run_id": await svc.fire_webhook(trigger_id, token, body)}
