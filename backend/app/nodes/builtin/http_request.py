"""HTTP request node. Outbound traffic goes through the SSRF guard (see runtime/net_guard.py).

Redirects are NOT followed (the target would bypass URL review); 3xx is returned as the response.
Secrets belong in Credentials: reference one in a header value as {{credential:NAME}}. The value is
read from the system keychain when the node runs and masked out of everything that is stored.
"""

import asyncio
import json
import re
import ssl
import time
from typing import Any, ClassVar
from urllib.parse import urlsplit

import certifi
import httpcore

from app.domain.nodes import NodeContext, NodeDefinition, NodeResult
from app.domain.ports import JsonValue, LogLine, NodeError
from app.domain.secrets import REFERENCE, MissingCredential, SecretsUnavailable
from app.runtime.net_guard import BlockedAddress, GuardedBackend

METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}
BODY_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
MAX_REQUEST_BYTES = 1 << 20
MAX_RESPONSE_KB = 5120
FORBIDDEN_HEADERS = {"host", "content-length", "transfer-encoding", "connection", "upgrade"}
RETURNED_HEADERS = {"content-type", "content-length", "date", "etag", "last-modified", "location"}
_HEADER_NAME = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+$")


class HttpRequestNode:
    definition: ClassVar[NodeDefinition] = NodeDefinition(
        type="http.request",
        title="HTTP request",
        category="Integrations",
        description="Call a public HTTP(S) API. Private, loopback and metadata hosts are blocked.",
        config_schema={
            "type": "object",
            "required": ["url"],
            "properties": {
                "url": {"type": "string"},
                "method": {"enum": sorted(METHODS), "default": "GET"},
                "headers": {"type": "object", "additionalProperties": {"type": "string"}},
                "body": {"description": "JSON value or string sent as the body"},
                "send_input_as_body": {"type": "boolean", "default": False},
                "timeout_s": {"type": "number", "minimum": 0.1, "maximum": 30, "default": 10},
                "max_response_kb": {"type": "integer", "maximum": MAX_RESPONSE_KB, "default": 1024},
                "fail_on_error_status": {"type": "boolean", "default": True},
            },
        },
        default_config={"url": "https://", "method": "GET"},
    )

    def __init__(
        self, allow_private: bool = False, ssl_context: ssl.SSLContext | None = None
    ) -> None:
        self.allow_private = allow_private  # dev/test only: lets nodes reach localhost
        self._ssl_context = ssl_context  # tests inject a private CA; production uses certifi

    # ------------------------------------------------------------------ validation
    def validate_config(self, config: dict[str, Any]) -> list[str]:
        problems: list[str] = []
        url = config.get("url")
        if not isinstance(url, str):
            problems.append("config.url must be a string")
        else:
            parts = urlsplit(url)
            if "{{credential:" in url:
                problems.append("credentials can only be used in header values, not in the URL")
            elif parts.scheme not in ("http", "https") or not parts.hostname:
                problems.append("config.url must be an absolute http(s) URL")
            elif parts.username or parts.password:
                problems.append("config.url must not contain credentials")
        if config.get("method", "GET") not in METHODS:
            problems.append(f"config.method must be one of {sorted(METHODS)}")
        headers = config.get("headers", {})
        if not isinstance(headers, dict) or len(headers) > 20:
            problems.append("config.headers must be an object with at most 20 entries")
        else:
            for k, v in headers.items():
                if not isinstance(v, str) or not _HEADER_NAME.match(k) or "\r" in v or "\n" in v:
                    problems.append(f"invalid header {k!r}")
                elif k.lower() in FORBIDDEN_HEADERS:
                    problems.append(f"header {k!r} cannot be set")
                elif v.count("{{credential:") != len(REFERENCE.findall(v)):
                    problems.append(
                        f"header {k!r} has a malformed credential reference "
                        "(use {{credential:NAME}})"
                    )
        timeout = config.get("timeout_s", 10)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, int | float)
            or not 0.1 <= timeout <= 30
        ):
            problems.append("config.timeout_s must be between 0.1 and 30")
        cap = config.get("max_response_kb", 1024)
        if isinstance(cap, bool) or not isinstance(cap, int) or not 1 <= cap <= MAX_RESPONSE_KB:
            problems.append(f"config.max_response_kb must be 1-{MAX_RESPONSE_KB}")
        for flag in ("send_input_as_body", "fail_on_error_status"):
            if flag in config and not isinstance(config[flag], bool):
                problems.append(f"config.{flag} must be a boolean")
        return problems

    # ------------------------------------------------------------------ execution
    async def execute(
        self, ctx: NodeContext, input_data: JsonValue, config: dict[str, Any]
    ) -> NodeResult:
        start = time.monotonic()

        def fail(kind: Any, message: str, logs: list[LogLine] | None = None) -> NodeResult:
            return NodeResult(
                status="failed",
                logs=logs or [],
                duration_ms=int((time.monotonic() - start) * 1000),
                error=NodeError(type=kind, message=message),
            )

        method = config.get("method", "GET")
        body: bytes | None = None
        headers = {str(k): v for k, v in config.get("headers", {}).items()}
        if method in BODY_METHODS and (config.get("send_input_as_body") or "body" in config):
            payload = input_data if config.get("send_input_as_body") else config["body"]
            if isinstance(payload, str):
                body = payload.encode()
            else:
                body = json.dumps(payload).encode()
                if not any(k.lower() == "content-type" for k in headers):
                    headers["Content-Type"] = "application/json"
            if len(body) > MAX_REQUEST_BYTES:
                return fail("invalid_config", "Request body exceeds 1 MB")

        try:
            if any(REFERENCE.search(v) for v in headers.values()):
                if ctx.secrets is None:
                    return fail(
                        "missing_credential", "Credentials cannot be resolved in this context"
                    )
                headers = {k: ctx.secrets.resolve(v) for k, v in headers.items()}
        except MissingCredential as e:
            return fail(
                "missing_credential",
                f"Credential {e.name!r} does not exist. Add it under Credentials.",
            )
        except SecretsUnavailable as e:
            return fail("secrets_unavailable", str(e))

        timeout = min(float(config.get("timeout_s", 10)), ctx.timeout_s)
        cap = int(config.get("max_response_kb", 1024)) * 1024
        task = asyncio.ensure_future(
            self._request(method, config["url"], headers, body, timeout, cap)
        )
        cancel_wait = asyncio.ensure_future(ctx.cancel.wait()) if ctx.cancel else None
        try:
            waiting: set[asyncio.Future[Any]] = {task}
            if cancel_wait:
                waiting.add(cancel_wait)
            done, _ = await asyncio.wait(
                waiting, timeout=timeout + 1, return_when=asyncio.FIRST_COMPLETED
            )
            if task not in done:
                task.cancel()
                if cancel_wait and cancel_wait in done:
                    return fail("cancelled", "Cancelled by user")
                return fail("timeout", f"No response within {timeout:g}s")
            try:
                status, resp_headers, raw = task.result()
            except BlockedAddress as e:
                return fail("blocked_request", f"Blocked by network policy: {e}")
            except _TooLarge:
                return fail("response_too_large", f"Response exceeds {cap // 1024} KB")
            except (httpcore.TimeoutException, TimeoutError):
                return fail("timeout", f"No response within {timeout:g}s")
            except (
                httpcore.NetworkError,
                httpcore.ProtocolError,
                httpcore.ProxyError,
                OSError,
            ) as e:
                return fail("network_error", f"{type(e).__name__}: {e}")
        finally:
            if cancel_wait:
                cancel_wait.cancel()

        parts = urlsplit(config["url"])
        # query strings often carry secrets, so they are never logged
        log = LogLine(
            stream="stdout",
            text=f"{method} {parts.scheme}://{parts.netloc}{parts.path} -> {status}",
        )
        output = {
            "status": status,
            "ok": 200 <= status < 300,
            "headers": {k: v for k, v in resp_headers.items() if k in RETURNED_HEADERS},
            "body": _decode_body(resp_headers.get("content-type", ""), raw),
        }
        duration = int((time.monotonic() - start) * 1000)
        if status >= 400 and config.get("fail_on_error_status", True):
            snippet = raw[:300].decode("utf-8", "replace")
            return NodeResult(
                status="failed", output=None, logs=[log], duration_ms=duration,
                error=NodeError(type="http_error", message=f"HTTP {status}: {snippet}"),
            )  # fmt: skip
        return NodeResult(status="succeeded", output=output, logs=[log], duration_ms=duration)

    async def _request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
        cap: int,
    ) -> tuple[int, dict[str, str], bytes]:
        ssl_ctx = self._ssl_context or ssl.create_default_context(cafile=certifi.where())
        wire = [(b"User-Agent", b"Nodecraft/0.1"), (b"Accept-Encoding", b"identity")]
        wire += [(k.encode(), v.encode()) for k, v in headers.items()]
        t = {"connect": timeout, "read": timeout, "write": timeout, "pool": timeout}
        async with httpcore.AsyncConnectionPool(
            network_backend=GuardedBackend(self.allow_private),
            ssl_context=ssl_ctx,
            max_connections=1,
            retries=0,
        ) as pool:
            async with pool.stream(
                method, url, headers=wire, content=body, extensions={"timeout": t}
            ) as resp:
                chunks: list[bytes] = []
                size = 0
                async for chunk in resp.aiter_stream():
                    size += len(chunk)
                    if size > cap:
                        raise _TooLarge
                    chunks.append(chunk)
                hdrs = {k.decode().lower(): v.decode("latin-1") for k, v in resp.headers}
                return resp.status, hdrs, b"".join(chunks)


class _TooLarge(Exception):
    pass


def _decode_body(content_type: str, raw: bytes) -> Any:
    text = raw.decode("utf-8", "replace")
    if "json" in content_type.lower():
        try:
            return json.loads(text)
        except ValueError:
            pass
    return text
