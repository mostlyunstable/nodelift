"""Credentials: names in the database, values in the system keychain. Values are write-only."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.errors import AppError
from app.domain.records import CredentialRecord
from app.domain.secrets import MIN_SECRET_LENGTH, NAME, SecretStore, SecretsUnavailable
from app.storage.repositories import SqlCredentialRepository

router = APIRouter(prefix="/credentials", tags=["credentials"])


def get_repo(request: Request) -> SqlCredentialRepository:
    return SqlCredentialRepository(request.app.state.session_factory)


def get_store(request: Request) -> SecretStore:
    store: SecretStore = request.app.state.secrets
    return store


Repo = Annotated[SqlCredentialRepository, Depends(get_repo)]
Store = Annotated[SecretStore, Depends(get_store)]


def _check_value(value: str) -> str:
    if len(value) < MIN_SECRET_LENGTH:
        raise AppError(
            422, "secret_too_short", f"A secret must be at least {MIN_SECRET_LENGTH} characters"
        )
    if "\r" in value or "\n" in value:
        raise AppError(422, "invalid_secret", "A secret cannot contain line breaks")
    return value


class NewCredential(BaseModel):
    name: str = Field(max_length=64)
    value: str = Field(max_length=8192, repr=False)
    kind: str = Field(default="other", max_length=32)
    description: str = Field(default="", max_length=200)


class RotateCredential(BaseModel):
    value: str = Field(max_length=8192, repr=False)
    description: str | None = Field(default=None, max_length=200)


def _unavailable(e: SecretsUnavailable) -> AppError:
    return AppError(503, "secrets_unavailable", str(e))


@router.get("", response_model=list[CredentialRecord])
def list_credentials(repo: Repo) -> list[CredentialRecord]:
    return repo.list_all()


@router.post("", response_model=CredentialRecord, status_code=201)
def create_credential(body: NewCredential, repo: Repo, store: Store) -> CredentialRecord:
    if not NAME.match(body.name):
        raise AppError(
            422, "invalid_name", "Names may use letters, digits, dot, dash and underscore (max 64)"
        )
    _check_value(body.value)
    if repo.get(body.name) is not None:
        raise AppError(409, "credential_exists", f"A credential named {body.name!r} already exists")
    try:
        store.set(body.name, body.value)
    except SecretsUnavailable as e:
        raise _unavailable(e) from e
    try:
        return repo.create(body.name, body.kind, body.description)
    except Exception:
        store.delete(body.name)  # do not leave an orphaned secret behind
        raise


@router.put("/{name}", response_model=CredentialRecord)
def rotate_credential(
    name: str, body: RotateCredential, repo: Repo, store: Store
) -> CredentialRecord:
    if repo.get(name) is None:
        raise AppError(404, "not_found", "Credential not found")
    _check_value(body.value)
    try:
        store.set(name, body.value)
    except SecretsUnavailable as e:
        raise _unavailable(e) from e
    rec = repo.touch(name, body.description)
    assert rec is not None
    return rec


@router.delete("/{name}", status_code=204)
def delete_credential(name: str, repo: Repo, store: Store) -> None:
    if repo.get(name) is None:
        raise AppError(404, "not_found", "Credential not found")
    try:
        store.delete(name)
    except SecretsUnavailable as e:
        raise _unavailable(e) from e
    repo.delete(name)
