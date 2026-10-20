import re
from dataclasses import dataclass
from urllib.parse import urlsplit

_OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_REPO = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_REF = re.compile(r"^[A-Za-z0-9._/@+-]{1,200}$")
_HOSTS = {"github.com", "www.github.com"}


class InvalidRepoUrl(ValueError):
    pass


@dataclass(frozen=True)
class RepoRef:
    owner: str
    repo: str
    ref: str | None = None  # branch, tag or commit; None = the default branch

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


def _ref_ok(ref: str) -> bool:
    return (
        bool(_REF.match(ref))
        and ".." not in ref
        and not ref.startswith(("/", "-"))
        and "//" not in ref
        and not ref.endswith(("/", "."))
    )


def parse_github_url(text: str) -> RepoRef:
    """Accept https://github.com/owner/repo[.git][/tree/<ref>] (scheme optional). Nothing else."""
    raw = text.strip()
    if not raw or len(raw) > 300 or any(c.isspace() or ord(c) < 32 for c in raw):
        raise InvalidRepoUrl("Paste a GitHub repository URL such as https://github.com/owner/repo")
    if "://" not in raw:
        raw = "https://" + raw
    parts = urlsplit(raw)
    if parts.scheme != "https":
        raise InvalidRepoUrl("Only https://github.com URLs are supported")
    if parts.username or parts.password or parts.port:
        raise InvalidRepoUrl("The URL must not contain credentials or a port")
    if (parts.hostname or "").lower() not in _HOSTS:
        raise InvalidRepoUrl("Only github.com repositories are supported")
    segments = [s for s in parts.path.split("/") if s]
    if len(segments) < 2:
        raise InvalidRepoUrl("The URL must include an owner and a repository name")
    owner, repo = segments[0], segments[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not _OWNER.match(owner) or not _REPO.match(repo) or repo in {".", ".."}:
        raise InvalidRepoUrl("That does not look like a valid owner/repository name")
    ref: str | None = None
    rest = segments[2:]
    if rest:
        if rest[0] != "tree" or len(rest) < 2:
            raise InvalidRepoUrl("Use the repository root or a /tree/<branch> URL")
        ref = "/".join(rest[1:])
        if not _ref_ok(ref):
            raise InvalidRepoUrl("That branch or tag name is not valid")
    return RepoRef(owner, repo, ref)
