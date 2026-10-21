"""Workflow import/export. Imported files are untrusted: validated, previewed, never auto-run."""

import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from pydantic import BaseModel, ValidationError

from app.api.errors import AppError
from app.api.v1.nodes import Registry
from app.api.v1.stored import Service
from app.domain.migrations import migrate_definition
from app.domain.records import WorkflowRecord
from app.domain.secrets import references
from app.domain.workflow import ValidationIssue, WorkflowDefinition, validate_workflow
from app.examples import load_examples
from app.nodes.builtin.data_nodes import safe_path

router = APIRouter(tags=["portability"])

WORKFLOW_FORMAT = "nodecraft-workflow"
BACKUP_FORMAT = "nodecraft-backup"
FORMAT_VERSION = 1


class WorkflowFile(BaseModel):
    format: str
    format_version: int
    exported_at: str | None = None
    workflow: dict[str, Any]


class ImportSummary(BaseModel):
    name: str
    nodes: int
    edges: int
    node_types: dict[str, int]
    code_nodes: int
    http_hosts: list[str]
    credentials: list[str]
    warnings: list[str]


class ImportPreview(BaseModel):
    valid: bool
    issues: list[ValidationIssue]
    summary: ImportSummary


def _export_file(rec: WorkflowRecord) -> dict[str, Any]:
    return {
        "format": WORKFLOW_FORMAT,
        "format_version": FORMAT_VERSION,
        "exported_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "workflow": {"name": rec.name, "definition": rec.draft.model_dump(mode="json")},
    }


def _clean_layout(ui: dict[str, Any]) -> dict[str, Any]:
    """Keep only node positions made of finite numbers; layout is all an import may carry."""
    positions: dict[str, dict[str, float]] = {}
    raw = ui.get("positions") if isinstance(ui, dict) else None
    if isinstance(raw, dict):
        for node_id, pos in raw.items():
            if isinstance(pos, dict) and all(
                isinstance(pos.get(k), int | float)
                and not isinstance(pos.get(k), bool)
                and math.isfinite(pos[k])
                for k in ("x", "y")
            ):
                positions[str(node_id)] = {"x": float(pos["x"]), "y": float(pos["y"])}
    return {"positions": positions}


def _parse(
    file: WorkflowFile, registry: Registry
) -> tuple[str, WorkflowDefinition, list[ValidationIssue]]:
    if file.format != WORKFLOW_FORMAT:
        raise AppError(422, "not_a_workflow_file", "This is not a Nodecraft workflow file")
    if file.format_version > FORMAT_VERSION:
        raise AppError(
            422,
            "unsupported_format_version",
            f"This file was made by a newer Nodecraft (file format {file.format_version}). "
            "Update Nodecraft to import it.",
        )
    raw = file.workflow.get("definition")
    if not isinstance(raw, dict):
        raise AppError(422, "invalid_file", "The file has no workflow definition")
    raw = migrate_definition(raw)
    raw["ui"] = _clean_layout(raw.get("ui", {}))
    raw["id"] = ""  # a new workflow gets a new id
    try:
        definition = WorkflowDefinition.model_validate(raw)
    except ValidationError as e:
        details = [
            {"path": ".".join(str(p) for p in err["loc"]), "message": err["msg"]}
            for err in e.errors()[:20]
        ]
        raise AppError(422, "invalid_file", "The workflow definition is malformed", details) from e
    name = str(file.workflow.get("name") or definition.name or "Imported workflow")[:200]
    return name, definition, validate_workflow(definition, registry)


def _summary(name: str, wf: WorkflowDefinition) -> ImportSummary:
    types: dict[str, int] = {}
    hosts: set[str] = set()
    needed: set[str] = set()
    for n in wf.nodes:
        types[n.type] = types.get(n.type, 0) + 1
        headers = n.config.get("headers") if n.type == "http.request" else None
        if isinstance(headers, dict):
            for value in headers.values():
                if isinstance(value, str):
                    needed.update(references(value))
        url = n.config.get("url") if n.type == "http.request" else None
        if isinstance(url, str) and (host := urlsplit(url).hostname):
            hosts.add(host)
    warnings: list[str] = []
    code = types.get("code.python", 0)
    if code:
        warnings.append(
            f"{code} code node(s) run Python as you on this computer. Read them before running."
        )
    if hosts:
        warnings.append("HTTP nodes will contact: " + ", ".join(sorted(hosts)))
    if needed:
        warnings.append(
            "Needs credentials: "
            + ", ".join(sorted(needed))
            + ". Add them under Credentials; no secret is in the file."
        )
    return ImportSummary(
        name=name, nodes=len(wf.nodes), edges=len(wf.edges), node_types=types, code_nodes=code,
        http_hosts=sorted(hosts), credentials=sorted(needed), warnings=warnings,
    )  # fmt: skip


@router.get("/workflows/{workflow_id}/export")
def export_workflow(workflow_id: str, svc: Service) -> dict[str, Any]:
    rec = svc.workflows.get(workflow_id)
    if rec is None:
        raise AppError(404, "not_found", "Workflow not found")
    return _export_file(rec)


@router.post("/workflows/import/preview", response_model=ImportPreview)
def preview_import(file: WorkflowFile, registry: Registry) -> ImportPreview:
    """What would be imported, and what it can do, without creating anything."""
    name, definition, issues = _parse(file, registry)
    return ImportPreview(valid=not issues, issues=issues, summary=_summary(name, definition))


@router.post("/workflows/import", response_model=WorkflowRecord, status_code=201)
def import_workflow(file: WorkflowFile, registry: Registry, svc: Service) -> WorkflowRecord:
    """Create a NEW workflow from a file. Never overwrites, never runs."""
    name, definition, issues = _parse(file, registry)
    if issues:
        raise AppError(
            422, "validation_failed", "The workflow is not valid", [i.model_dump() for i in issues]
        )
    return svc.workflows.create(name, definition)


@router.get("/system/export")
def export_everything(svc: Service) -> dict[str, Any]:
    """All workflows (drafts) in one file, for backups. Runs and history are not included."""
    files = []
    for summary in svc.workflows.list_all():
        rec = svc.workflows.get(summary.id)
        if rec is not None:
            files.append(_export_file(rec))
    return {
        "format": BACKUP_FORMAT,
        "format_version": FORMAT_VERSION,
        "exported_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "workflows": files,
    }


class ExampleInfo(BaseModel):
    id: str
    title: str
    description: str
    nodes: int


@router.get("/examples", response_model=list[ExampleInfo])
def list_examples() -> list[ExampleInfo]:
    return [
        ExampleInfo(
            id=e["id"],
            title=e["title"],
            description=e["description"],
            nodes=len(e["definition"]["nodes"]),
        )
        for e in load_examples().values()
    ]


def _seed_files(request: Request, files: dict[str, str]) -> None:
    """Sample inputs an example needs (notes, a messy CSV); never overwrites your own files."""
    if not files:
        return
    base: Path = request.app.state.settings.data_dir / "files"
    for rel, text in files.items():
        target = safe_path(base, rel)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")


@router.post("/examples/{example_id}/create", response_model=WorkflowRecord, status_code=201)
def create_example(
    example_id: str, registry: Registry, svc: Service, request: Request
) -> WorkflowRecord:
    """A fresh copy of a built-in example as a new workflow (it is not run)."""
    example = load_examples().get(example_id)
    if example is None:
        raise AppError(404, "not_found", "Example not found")
    definition = WorkflowDefinition.model_validate(migrate_definition(example["definition"]))
    issues = validate_workflow(definition, registry)
    if issues:  # a shipped example must always be valid; fail loudly if it ever is not
        raise AppError(
            500, "bad_example", "The built-in example is invalid", [i.model_dump() for i in issues]
        )
    _seed_files(request, example.get("files", {}))
    return svc.workflows.create(example["name"], definition)
