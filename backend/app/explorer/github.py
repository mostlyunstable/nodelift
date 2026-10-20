"""Minimal GitHub client: two fixed GitHub hosts, https only, bounded redirects."""

import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from app.domain.errors import AppError
from app.explorer.archive import Cancelled
from app.explorer.urls import RepoRef

API_HOST = "api.github.com"
ARCHIVE_HOST = "codeload.github.com"
ALLOWED_HOSTS = {API_HOST, ARCHIVE_HOST}
_SHA = re.compile(r"^[0-9a-f]{40}$")
MAX_REDIRECTS = 3
USER_AGENT = "Nodecraft-Repository-Explorer"


@dataclass(frozen=True)
class ResolvedRepo:
    full_name: str
    default_branch: str
    branch: str
    commit_sha: str
    description: str


class GitHubClient:
    def __init__(
        self, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 20.0
    ) -> None:
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(timeout, read=60.0),
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "GitHubClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def _send(self, url: str, accept: str, stream: bool = False) -> httpx.Response:
        for _ in range(MAX_REDIRECTS + 1):
            parts = urlsplit(url)
            if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
                raise AppError(502, "unexpected_host", "GitHub redirected to an unexpected address")
            req = self._client.build_request("GET", url, headers={"Accept": accept})
            try:
                resp = await self._client.send(req, stream=stream)
            except httpx.TimeoutException as e:
                raise AppError(504, "github_timeout", "GitHub did not respond in time") from e
            except httpx.HTTPError as e:
                raise AppError(502, "github_unreachable", "Could not reach GitHub") from e
            if resp.status_code in (301, 302, 307, 308) and "location" in resp.headers:
                loc = resp.headers["location"]
                if stream:
                    await resp.aclose()
                url = str(httpx.URL(url).join(loc))
                continue
            return resp
        raise AppError(502, "too_many_redirects", "GitHub redirected too many times")

    @staticmethod
    def _fail(resp: httpx.Response, what: str) -> AppError:
        s = resp.status_code
        if s in (403, 429) and (resp.headers.get("x-ratelimit-remaining") == "0" or s == 429):
            reset = resp.headers.get("x-ratelimit-reset")
            return AppError(
                429,
                "rate_limited",
                "GitHub's anonymous rate limit was reached. Try again later.",
                [{"reset_epoch": reset}] if reset else [],
            )
        if s == 404:
            return AppError(
                404,
                "repo_not_found",
                f"{what} was not found. It may not exist, or it may be private "
                "(private repositories are not supported yet).",
            )
        if s in (401, 403):
            return AppError(403, "repo_forbidden", f"GitHub denied access to {what}.")
        return AppError(502, "github_error", f"GitHub returned an unexpected status ({s}).")

    async def resolve(self, ref: RepoRef) -> ResolvedRepo:
        base = f"https://{API_HOST}/repos/{quote(ref.owner)}/{quote(ref.repo)}"
        r = await self._send(base, "application/vnd.github+json")
        if r.status_code != 200:
            raise self._fail(r, ref.full_name)
        info: Any = r.json()
        if not isinstance(info, dict) or not isinstance(info.get("default_branch"), str):
            raise AppError(502, "github_error", "GitHub returned an unexpected response")
        default = info["default_branch"]
        branch = ref.ref or default
        r2 = await self._send(
            f"{base}/commits/{quote(branch, safe='')}", "application/vnd.github.sha"
        )
        if r2.status_code in (404, 422):
            raise AppError(
                404,
                "ref_not_found",
                f"{branch!r} is not a branch, tag or commit in {ref.full_name}.",
            )
        if r2.status_code != 200:
            raise self._fail(r2, ref.full_name)
        sha = r2.text.strip()
        if not _SHA.match(sha):
            raise AppError(502, "github_error", "GitHub returned an unexpected commit id")
        return ResolvedRepo(
            full_name=str(info.get("full_name") or ref.full_name),
            default_branch=default,
            branch=branch,
            commit_sha=sha,
            description=str(info.get("description") or "")[:300],
        )

    async def download_tarball(
        self,
        owner: str,
        repo: str,
        sha: str,
        dest: Path,
        max_bytes: int,
        cancel: threading.Event | None = None,
    ) -> int:
        if not _SHA.match(sha):
            raise ValueError("commit sha required")
        url = f"https://{ARCHIVE_HOST}/{quote(owner)}/{quote(repo)}/tar.gz/{sha}"
        resp = await self._send(url, "application/x-gzip", stream=True)
        try:
            if resp.status_code != 200:
                raise self._fail(resp, f"{owner}/{repo}")
            written = 0
            try:
                with dest.open("wb") as fh:
                    async for chunk in resp.aiter_bytes(64 * 1024):
                        if cancel is not None and cancel.is_set():
                            raise Cancelled
                        written += len(chunk)
                        if written > max_bytes:
                            raise AppError(
                                413,
                                "repo_too_large",
                                "The repository download is too large to import",
                            )
                        fh.write(chunk)
            except httpx.HTTPError as e:
                raise AppError(502, "github_unreachable", "The download was interrupted") from e
            return written
        finally:
            await resp.aclose()
