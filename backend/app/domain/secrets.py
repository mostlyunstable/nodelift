"""Secrets: where values live, how nodes reference them, and how they stay out of results.

Workflows never contain secret values, only references like {{credential:github}} inside HTTP
header values. A value is read from the SecretStore when a node runs, and every place it could
leak (logs, output, error text) is scrubbed before the result is stored or shown.

Limits, stated honestly: scrubbing recognises the value and its URL-encoded and JSON-escaped
forms. A node that deliberately transforms a secret (hashes or base64-encodes it) defeats it,
and code nodes run unsandboxed in trusted mode, so a malicious workflow can still go looking
for secrets on your machine.
"""

import json
import re
from typing import Any, Protocol
from urllib.parse import quote

from app.domain.ports import CodeRunResult, NodeError

REFERENCE = re.compile(r"\{\{credential:([A-Za-z0-9_.-]{1,64})\}\}")
NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
MIN_SECRET_LENGTH = 8  # shorter values cannot be scrubbed without mangling unrelated text
MASK = "••••••"


class SecretsUnavailable(Exception):
    """The secret store cannot be used (for example the system keychain is locked or missing)."""


class MissingCredential(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"Credential {name!r} does not exist")
        self.name = name


class SecretStore(Protocol):
    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...


class MemorySecretStore:
    """Tests and throw-away runs only: nothing survives a restart."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self._values.get(name)

    def set(self, name: str, value: str) -> None:
        self._values[name] = value

    def delete(self, name: str) -> None:
        self._values.pop(name, None)


class Redactor:
    """Remembers the secret values used during one run and masks them wherever they appear."""

    def __init__(self) -> None:
        self._needles: list[str] = []

    def register(self, value: str) -> None:
        if len(value) < MIN_SECRET_LENGTH:
            return
        for form in (value, quote(value, safe=""), json.dumps(value)[1:-1]):
            if form and form not in self._needles:
                self._needles.append(form)
        self._needles.sort(key=len, reverse=True)  # mask the longest form first

    @property
    def active(self) -> bool:
        return bool(self._needles)

    def text(self, s: str) -> str:
        for needle in self._needles:
            if needle in s:
                s = s.replace(needle, MASK)
        return s

    def data(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.data(v) for v in value]
        if isinstance(value, dict):
            return {self.text(str(k)): self.data(v) for k, v in value.items()}
        return value

    def result(self, res: CodeRunResult) -> CodeRunResult:
        """A node result with every known secret masked out of its output, logs and error."""
        if not self.active:
            return res
        error = res.error
        if error is not None:
            error = NodeError(
                type=error.type,
                message=self.text(error.message),
                line=error.line,
                column=error.column,
                traceback=self.text(error.traceback) if error.traceback else None,
            )
        logs = [log.model_copy(update={"text": self.text(log.text)}) for log in res.logs]
        return res.model_copy(
            update={"output": self.data(res.output), "logs": logs, "error": error}
        )


class SecretResolver:
    """Turns {{credential:NAME}} references into values for the node that is running."""

    def __init__(self, store: SecretStore, redactor: Redactor) -> None:
        self._store = store
        self._redactor = redactor

    def resolve(self, text: str) -> str:
        def swap(match: re.Match[str]) -> str:
            name = match.group(1)
            value = self._store.get(name)
            if value is None:
                raise MissingCredential(name)
            self._redactor.register(value)
            return value

        return REFERENCE.sub(swap, text)


def references(text: str) -> list[str]:
    return REFERENCE.findall(text)
