import io
import tarfile
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.errors import AppError
from app.explorer.archive import Limits, extract_tarball, safe_relative_path
from app.explorer.urls import InvalidRepoUrl, parse_github_url
from app.main import create_app

SHA = "a" * 40
SHA2 = "b" * 40


# ---- URL parsing ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,expected",
    [
        ("https://github.com/psf/requests", ("psf", "requests", None)),
        ("https://github.com/psf/requests.git", ("psf", "requests", None)),
        ("github.com/psf/requests/", ("psf", "requests", None)),
        ("https://www.github.com/psf/requests/tree/main", ("psf", "requests", "main")),
        ("https://github.com/o/r/tree/feature/x", ("o", "r", "feature/x")),
    ],
)
def test_parse_accepts(text: str, expected: tuple[str, str, str | None]) -> None:
    r = parse_github_url(text)
    assert (r.owner, r.repo, r.ref) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "http://github.com/o/r",
        "https://gitlab.com/o/r",
        "https://github.com.evil.com/o/r",
        "https://evil.com/github.com/o/r",
        "https://user:pw@github.com/o/r",
        "https://github.com:8443/o/r",
        "https://github.com/o",
        "https://github.com/o/..",
        "https://github.com/-bad/r",
        "https://github.com/o/r/blob/main/x.py",
        "https://github.com/o/r/tree/../../etc",
        "https://github.com/o/r with space",
        "file:///etc/passwd",
        "git@github.com:o/r.git",
    ],
)
def test_parse_rejects(text: str) -> None:
    with pytest.raises(InvalidRepoUrl):
        parse_github_url(text)


# ---- archive extraction --------------------------------------------------------------------
def make_tar(
    path: Path, entries: dict[str, bytes | None], links: dict[str, str] | None = None
) -> Path:
    with tarfile.open(path, "w:gz") as tf:
        top = tarfile.TarInfo("o-r-abc/")
        top.type = tarfile.DIRTYPE
        tf.addfile(top)
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            payload = data or b""
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))
        for name, target in (links or {}).items():
            info = tarfile.TarInfo(name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            tf.addfile(info)
    return path


def test_safe_relative_path() -> None:
    assert safe_relative_path("o-r-abc/src/a.py") == "src/a.py"
    assert safe_relative_path("o-r-abc/") is None
    assert safe_relative_path("o-r-abc/../evil") is None
    assert safe_relative_path("o-r-abc/a/../../evil") is None
    assert safe_relative_path("o-r-abc/a\\b") is None
    assert safe_relative_path("o-r-abc/" + "x" * 400) is None


def test_extract_stores_text_and_flags_the_rest(tmp_path: Path) -> None:
    tar = make_tar(
        tmp_path / "a.tgz",
        {
            "o-r-abc/main.py": b"print('hi')\n",
            "o-r-abc/img.png": b"\x89PNG\x00\x00binary",
            "o-r-abc/big.txt": b"x" * 2000,
            "o-r-abc/latin.txt": "café".encode("latin-1"),
            "o-r-abc/../evil.py": b"boom",
            "o-r-abc/src/../../evil2.py": b"boom",
            "o-r-abc/empty.txt": b"",
        },
        links={"o-r-abc/link": "/etc/passwd"},
    )
    out = tmp_path / "out"
    files = {f.path: f for f in extract_tarball(tar, out, Limits(max_file_bytes=1000))}
    assert set(files) == {"main.py", "img.png", "big.txt", "latin.txt", "empty.txt"}
    assert (
        files["main.py"].stored
        and files["main.py"].language == "python"
        and files["main.py"].lines == 1
    )
    assert files["img.png"].binary and not files["img.png"].stored
    assert files["big.txt"].skip_reason == "too_large" and not files["big.txt"].stored
    assert files["latin.txt"].skip_reason == "not_utf8"
    assert (out / "main.py").read_text() == "print('hi')\n"
    assert not (out / "img.png").exists() and not (out / "link").exists()
    assert not (tmp_path / "evil.py").exists() and not (tmp_path / "evil2.py").exists()


def test_extract_enforces_file_and_total_limits(tmp_path: Path) -> None:
    tar = make_tar(tmp_path / "a.tgz", {f"o-r-abc/f{i}.txt": b"x" for i in range(5)})
    with pytest.raises(AppError) as e:
        extract_tarball(tar, tmp_path / "o1", Limits(max_files=3))
    assert e.value.code == "repo_too_large"
    big = make_tar(tmp_path / "b.tgz", {"o-r-abc/a.txt": b"x" * 600, "o-r-abc/b.txt": b"x" * 600})
    with pytest.raises(AppError) as e2:
        extract_tarball(big, tmp_path / "o2", Limits(max_total_bytes=1000))
    assert e2.value.code == "repo_too_large"


def test_extract_rejects_garbage(tmp_path: Path) -> None:
    bad = tmp_path / "bad.tgz"
    bad.write_bytes(b"not a tarball at all")
    with pytest.raises(AppError) as e:
        extract_tarball(bad, tmp_path / "o", Limits())
    assert e.value.code == "bad_archive"


# ---- API against a fake GitHub -------------------------------------------------------------
class FakeGitHub:
    """Records every request; answers like api.github.com / codeload.github.com."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.sha = SHA
        self.tarball = b""
        self.repo_status = 200
        self.rate_limited = False
        self.redirect_to: str | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host, path = request.url.host, request.url.path
        if self.rate_limited:
            return httpx.Response(
                403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1999999999"}
            )
        if host == "api.github.com" and path == "/repos/octo/hello":
            if self.repo_status != 200:
                return httpx.Response(self.repo_status)
            return httpx.Response(
                200,
                json={"full_name": "octo/hello", "default_branch": "main", "description": "demo"},
            )
        if host == "api.github.com" and path.startswith("/repos/octo/hello/commits/"):
            ref = path.rsplit("/", 1)[1]
            if ref == "nope":
                return httpx.Response(422)
            return httpx.Response(200, text=self.sha)
        if host == "codeload.github.com" and path == f"/octo/hello/tar.gz/{self.sha}":
            if self.redirect_to:
                return httpx.Response(302, headers={"location": self.redirect_to})
            return httpx.Response(200, content=self.tarball)
        return httpx.Response(404)


def sample_tar(tmp_path: Path) -> bytes:
    p = make_tar(
        tmp_path / "s.tgz",
        {
            "octo-hello-aaaa/main.py": b"import utils\nprint(utils.x)\n",
            "octo-hello-aaaa/utils.py": b"x = 1\n",
            "octo-hello-aaaa/templates/index.html": b"<h1>hi</h1>\n",
            "octo-hello-aaaa/logo.png": b"\x89PNG\x00",
            "octo-hello-aaaa/config.json": b'{"a": 1}',
        },
    )
    return p.read_bytes()


@pytest.fixture
def gh(tmp_path: Path) -> FakeGitHub:
    fake = FakeGitHub()
    fake.tarball = sample_tar(tmp_path)
    return fake


@pytest.fixture
def api(tmp_path: Path, gh: FakeGitHub) -> Iterator[TestClient]:
    settings = Settings(data_dir=tmp_path / "data", secret_backend="memory")
    app = create_app(f"sqlite:///{tmp_path / 't.db'}", settings)
    app.state.github_transport = httpx.MockTransport(gh)
    app.state.test_settings = settings
    with TestClient(app) as c:
        yield c


def wait_ready(c: TestClient, rid: str, want: str = "ready") -> dict:
    for _ in range(100):
        r = c.get(f"/api/v1/explorer/revisions/{rid}").json()
        if r["status"] == want:
            return r
        time.sleep(0.05)
    raise AssertionError(f"never reached {want}: {r}")


def test_import_end_to_end(api: TestClient, gh: FakeGitHub) -> None:
    r = api.post("/api/v1/explorer/imports", json={"url": "https://github.com/octo/hello"})
    assert r.status_code == 202, r.text
    rev = r.json()
    assert rev["commit_sha"] == SHA and rev["branch"] == "main" and rev["full_name"] == "octo/hello"
    done = wait_ready(api, rev["id"])
    assert done["file_count"] == 5 and done["text_count"] == 4 and done["binary_count"] == 1

    files = {f["path"]: f for f in api.get(f"/api/v1/explorer/revisions/{rev['id']}/files").json()}
    assert set(files) == {"main.py", "utils.py", "templates/index.html", "logo.png", "config.json"}
    assert files["main.py"]["language"] == "python" and files["main.py"]["lines"] == 2
    assert files["templates/index.html"]["language"] == "html"
    assert files["logo.png"]["binary"] is True

    src = api.get(f"/api/v1/explorer/revisions/{rev['id']}/file", params={"path": "main.py"}).json()
    assert src["content"] == "import utils\nprint(utils.x)\n"
    png = api.get(
        f"/api/v1/explorer/revisions/{rev['id']}/file", params={"path": "logo.png"}
    ).json()
    assert png["content"] is None and png["reason"] == "binary"

    # Only GitHub's two hosts were ever contacted, over https, anonymously.
    assert {(q.url.scheme, q.url.host) for q in gh.requests} <= {
        ("https", "api.github.com"),
        ("https", "codeload.github.com"),
    }
    assert all("authorization" not in q.headers for q in gh.requests)
    # The archive was fetched for the pinned commit, never a moving branch name.
    assert any(q.url.path == f"/octo/hello/tar.gz/{SHA}" for q in gh.requests)


def test_same_commit_is_cached_new_commit_is_separate(api: TestClient, gh: FakeGitHub) -> None:
    first = api.post("/api/v1/explorer/imports", json={"url": "github.com/octo/hello"}).json()
    wait_ready(api, first["id"])
    n = sum(1 for q in gh.requests if q.url.host == "codeload.github.com")
    again = api.post("/api/v1/explorer/imports", json={"url": "github.com/octo/hello"})
    assert again.status_code == 200 and again.json()["id"] == first["id"]
    assert sum(1 for q in gh.requests if q.url.host == "codeload.github.com") == n

    gh.sha = SHA2  # the branch moved: a deliberate refresh makes a different revision
    newer = api.post("/api/v1/explorer/imports", json={"url": "github.com/octo/hello"})
    assert newer.status_code == 202 and newer.json()["id"] != first["id"]
    assert newer.json()["commit_sha"] == SHA2
    ids = {r["id"] for r in api.get("/api/v1/explorer/revisions").json()}
    assert {first["id"], newer.json()["id"]} <= ids


def test_errors_are_specific(api: TestClient, gh: FakeGitHub) -> None:
    def post(url: str) -> httpx.Response:
        return api.post("/api/v1/explorer/imports", json={"url": url})

    bad = post("https://evil.com/o/r")
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_repo_url"
    gh.repo_status = 404
    nf = post("https://github.com/octo/hello")
    assert nf.status_code == 404 and nf.json()["error"]["code"] == "repo_not_found"
    gh.repo_status = 200
    ref = post("https://github.com/octo/hello/tree/nope")
    assert ref.status_code == 404 and ref.json()["error"]["code"] == "ref_not_found"
    gh.rate_limited = True
    rl = post("https://github.com/octo/hello")
    assert rl.status_code == 429 and rl.json()["error"]["code"] == "rate_limited"


def test_redirect_to_other_host_is_refused(api: TestClient, gh: FakeGitHub) -> None:
    gh.redirect_to = "https://evil.example/steal.tgz"
    rev = api.post("/api/v1/explorer/imports", json={"url": "github.com/octo/hello"}).json()
    failed = wait_ready(api, rev["id"], "failed")
    assert failed["error_code"] == "unexpected_host"


def test_oversized_download_fails_cleanly(api: TestClient, gh: FakeGitHub) -> None:
    api.app.state.settings.explorer_max_download_mb = 0  # any archive is too large
    rev = api.post("/api/v1/explorer/imports", json={"url": "github.com/octo/hello"}).json()
    failed = wait_ready(api, rev["id"], "failed")
    assert failed["error_code"] == "repo_too_large"
    assert api.get(f"/api/v1/explorer/revisions/{rev['id']}/files").status_code == 409


def test_cannot_read_unindexed_or_traversal_paths(api: TestClient) -> None:
    rev = api.post("/api/v1/explorer/imports", json={"url": "github.com/octo/hello"}).json()
    wait_ready(api, rev["id"])
    for path in ["../../nodecraft.db", "/etc/passwd", "nope.py", "files/../archive.tgz"]:
        r = api.get(f"/api/v1/explorer/revisions/{rev['id']}/file", params={"path": path})
        assert r.status_code == 404, path


def test_delete_revision(api: TestClient) -> None:
    rev = api.post("/api/v1/explorer/imports", json={"url": "github.com/octo/hello"}).json()
    wait_ready(api, rev["id"])
    assert api.delete(f"/api/v1/explorer/revisions/{rev['id']}").status_code == 204
    assert api.get(f"/api/v1/explorer/revisions/{rev['id']}").status_code == 404


def test_import_never_executes_repository_code(
    tmp_path: Path, api: TestClient, gh: FakeGitHub
) -> None:
    marker = tmp_path / "ran"
    evil = f"open({str(marker)!r}, 'w').write('x')\n".encode()
    gh.tarball = make_tar(
        tmp_path / "e.tgz",
        {"octo-hello-aaaa/setup.py": evil, "octo-hello-aaaa/conftest.py": evil},
    ).read_bytes()
    rev = api.post("/api/v1/explorer/imports", json={"url": "github.com/octo/hello"}).json()
    wait_ready(api, rev["id"])
    assert not marker.exists()
