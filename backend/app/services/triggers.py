"""Schedules and webhooks: ways for a workflow to start without anyone pressing Run.

Schedules fire only while Nodecraft is open (there is no background service), and a run missed
while it was closed is not made up afterwards: the next one is simply the next time on the clock.
A webhook is a private URL on this computer; its token is shown once and stored only as a hash.
"""

import asyncio
import contextlib
import hashlib
import hmac
import logging
import re
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from app.domain.errors import AppError
from app.domain.records import TriggerRecord
from app.domain.repositories import TriggerRepository
from app.services.workflow_service import WorkflowService

log = logging.getLogger("nodecraft.triggers")

MIN_EVERY_MINUTES = 1
MAX_EVERY_MINUTES = 7 * 24 * 60
_DAILY = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
RUN_TIMEOUT_S = 30.0
MAX_HOOK_BODY = 1_000_000


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def next_after(every_minutes: int | None, daily_at: str | None, now: datetime) -> datetime:
    """The next time a schedule is due after `now` (UTC in, UTC out); `daily_at` is local time."""
    if every_minutes is not None:
        return now + timedelta(minutes=every_minutes)
    assert daily_at is not None
    hh, mm = int(daily_at[:2]), int(daily_at[3:])
    here = now.astimezone().replace(hour=hh, minute=mm, second=0, microsecond=0)
    if here.astimezone(UTC) <= now:
        here += timedelta(days=1)
    return here.astimezone(UTC)


class TriggerService:
    def __init__(self, triggers: TriggerRepository, workflows: WorkflowService) -> None:
        self.triggers = triggers
        self.workflows = workflows

    def _need_workflow(self, workflow_id: str) -> None:
        if self.workflows.workflows.get(workflow_id) is None:
            raise AppError(404, "not_found", "Workflow not found")

    def add_schedule(
        self, workflow_id: str, every_minutes: int | None, daily_at: str | None
    ) -> TriggerRecord:
        self._need_workflow(workflow_id)
        if (every_minutes is None) == (daily_at is None):
            raise AppError(
                422, "invalid_schedule", "Choose either 'every N minutes' or a daily time"
            )
        if (
            every_minutes is not None
            and not MIN_EVERY_MINUTES <= every_minutes <= MAX_EVERY_MINUTES
        ):
            raise AppError(
                422,
                "invalid_schedule",
                f"Run every {MIN_EVERY_MINUTES} to {MAX_EVERY_MINUTES} minutes",
            )
        if daily_at is not None and not _DAILY.match(daily_at):
            raise AppError(422, "invalid_schedule", "Use a 24-hour time such as 08:30")
        due = next_after(every_minutes, daily_at, datetime.now(UTC))
        return self.triggers.create(workflow_id, "schedule", every_minutes, daily_at, None, due)

    def add_webhook(self, workflow_id: str) -> tuple[TriggerRecord, str]:
        """Returns the trigger and its token. The token cannot be read again."""
        self._need_workflow(workflow_id)
        token = secrets.token_urlsafe(24)
        rec = self.triggers.create(workflow_id, "webhook", None, None, hash_token(token), None)
        return rec, token

    def set_enabled(self, trigger_id: str, enabled: bool) -> TriggerRecord:
        rec = self.triggers.get(trigger_id)
        if rec is None:
            raise AppError(404, "not_found", "Trigger not found")
        due = (
            next_after(rec.every_minutes, rec.daily_at, datetime.now(UTC))
            if enabled and rec.kind == "schedule"
            else None
        )
        out = self.triggers.set_enabled(trigger_id, enabled, due)
        assert out is not None
        return out

    async def fire_webhook(self, trigger_id: str, token: str, body: Any) -> str:
        rec = self.triggers.get(trigger_id)
        stored = self.triggers.token_hash(trigger_id)
        ok = (
            rec is not None
            and rec.kind == "webhook"
            and stored is not None
            and hmac.compare_digest(stored, hash_token(token))
        )
        if not ok or rec is None:
            raise AppError(404, "not_found", "No such webhook")  # same answer for a bad id or token
        if not rec.enabled:
            raise AppError(409, "trigger_disabled", "This webhook is switched off")
        run = await self.workflows.start_run(rec.workflow_id, None, body, RUN_TIMEOUT_S)
        self.triggers.mark_fired(trigger_id, run.id, datetime.now(UTC), None)
        return run.id

    async def fire_due(self, now: datetime | None = None) -> int:
        """Start every schedule that is due. A workflow that is already running is skipped."""
        now = now or datetime.now(UTC)
        fired = 0
        for rec in self.triggers.list_due(now):
            nxt = next_after(rec.every_minutes, rec.daily_at, now)
            recent = self.workflows.runs.list_for_workflow(rec.workflow_id)[:5]
            if any(r.status == "running" for r in recent):
                self.triggers.mark_fired(rec.id, rec.last_run_id, rec.last_run_at or now, nxt)
                continue
            try:
                run = await self.workflows.start_run(rec.workflow_id, None, None, RUN_TIMEOUT_S)
                self.triggers.mark_fired(rec.id, run.id, now, nxt)
                fired += 1
            except Exception:
                log.exception("scheduled run could not start")
                self.triggers.mark_fired(rec.id, None, now, nxt)
        return fired


class Scheduler:
    """Checks for due schedules twice a minute while the application is open."""

    def __init__(
        self, service_factory: Callable[[], TriggerService], interval_s: float = 20.0
    ) -> None:
        self.factory = service_factory
        self.interval = interval_s
        self.task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self.task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self.interval)
                await self.factory().fire_due()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("scheduler pass failed")
