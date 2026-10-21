"""Builds services from application state.

This is the one place (besides `main.py`) that knows which concrete repositories back the
services, so the API layer depends on services and domain protocols only.
"""

from typing import Any

from app.domain.nodes import NodeRegistry
from app.domain.repositories import CredentialRepository
from app.services.command_service import CommandRuns
from app.services.explorer_service import ExplorerService
from app.services.triggers import TriggerService
from app.services.workflow_service import WorkflowService
from app.storage.db import current_revision, head_revision
from app.storage.repositories import (
    SqlCredentialRepository,
    SqlRepoRepository,
    SqlRunRepository,
    SqlTriggerRepository,
    SqlWorkflowRepository,
)


def workflow_service(state: Any, registry: NodeRegistry) -> WorkflowService:
    sf = state.session_factory
    return WorkflowService(
        SqlWorkflowRepository(sf),
        SqlRunRepository(sf),
        registry,
        state.run_hub,
        state.gate,
        state.settings.max_run_seconds,
        state.settings.keep_runs_per_workflow,
        state.secrets,
    )


def explorer_service(state: Any) -> ExplorerService:
    return ExplorerService(
        SqlRepoRepository(state.session_factory),
        state.settings,
        state.import_jobs,
        getattr(state, "github_transport", None),
        state.secrets,
    )


def command_runs(state: Any) -> CommandRuns:
    runs: CommandRuns = state.command_runs
    return runs


def credential_repository(state: Any) -> CredentialRepository:
    return SqlCredentialRepository(state.session_factory)


def schema_status(database_url: str) -> tuple[str | None, str]:
    """(revision the database is at, latest revision this version of Nodecraft knows)."""
    return current_revision(database_url), head_revision()


def trigger_service(state: Any) -> TriggerService:
    return TriggerService(
        SqlTriggerRepository(state.session_factory), workflow_service(state, state.registry)
    )
