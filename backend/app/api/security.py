"""Request gatekeeping for a local API that executes code.

Three independent checks, applied to every HTTP request:
1. Host header must be a known loopback name. This defeats DNS rebinding: a page on attacker.example
   that resolves to 127.0.0.1 still sends `Host: attacker.example`.
2. If an Origin header is present it must be on the allowlist (blocks cross-site browser requests).
3. If an API token is configured, `Authorization: Bearer <token>` is required (except /health).
"""

import hmac
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

HEALTH_PATH = "/api/v1/health"


def hostname(host_header: str) -> str:
    """'127.0.0.1:8000' -> '127.0.0.1'; '[::1]:8000' -> '[::1]'."""
    value = host_header.strip().lower()
    if value.startswith("["):
        return value[: value.find("]") + 1] if "]" in value else value
    return value.rsplit(":", 1)[0] if ":" in value else value


def _normalize_origin(origin: str) -> str:
    return origin.strip().lower().rstrip("/")


class SecurityMiddleware:
    def __init__(
        self, app: ASGIApp, hosts: list[str], origins: list[str], token: str | None
    ) -> None:
        self.app = app
        self.hosts = {h.strip().lower() for h in hosts}
        self.origins = {_normalize_origin(o) for o in origins}
        self.token = token.encode() if token else None

    @staticmethod
    def _reject(status: int, code: str, message: str) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
        return JSONResponse(
            status_code=status,
            content={"error": {"code": code, "message": message, "details": []}},
            headers=headers,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers: dict[bytes, bytes] = dict(scope["headers"])
        rejection = self._check(scope, headers)
        if rejection is not None:
            await rejection(scope, receive, send)
            return
        await self.app(scope, receive, send)

    def _check(self, scope: Scope, headers: dict[bytes, bytes]) -> Any:
        host = hostname(headers.get(b"host", b"").decode("latin-1"))
        if host not in self.hosts:
            return self._reject(403, "forbidden_host", "Host not allowed")
        origin = headers.get(b"origin")
        if origin is not None and _normalize_origin(origin.decode("latin-1")) not in self.origins:
            return self._reject(403, "forbidden_origin", "Origin not allowed")
        if self.token is not None and scope["path"] != HEALTH_PATH:
            supplied = headers.get(b"authorization", b"")
            scheme, _, value = supplied.partition(b" ")
            ok = scheme.lower() == b"bearer" and hmac.compare_digest(value.strip(), self.token)
            if not ok:
                return self._reject(401, "unauthorized", "Missing or invalid API token")
        return None
