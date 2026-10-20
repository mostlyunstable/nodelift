# ruff: noqa: E501
"""Find how a repository says it is tested, from its own files. Pure: reads text, runs nothing.

Every suggestion cites the file that justifies it. Nothing here is executed; running a command is a
separate, explicitly approved action.
"""

import json
import posixpath
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.domain.records import RepoFileRecord

PY_TEST_RE = re.compile(r"(^|/)(test_[^/]+\.py|[^/]+_test\.py)$")
JS_TEST_RE = re.compile(r"\.(test|spec)\.(m?[jt]sx?|cjs)$")


@dataclass
class Suggestion:
    id: str
    label: str
    argv: list[str]
    framework: str
    kind: str  # test | lint | build | other
    cwd: str  # folder inside the repository ('' = root)
    evidence: str  # which file/line says so
    notes: list[str] = field(default_factory=list)


@dataclass
class Discovery:
    suggestions: list[Suggestion]
    test_files: list[str]
    frameworks: list[str]


def risk_notes(argv: list[str]) -> list[str]:
    """Plain-language warnings about what a command is likely to do. Shown before approval."""
    joined = " ".join(argv)
    notes: list[str] = []
    low = joined.lower()
    if re.search(r"\b(pip3?|uv|poetry|pipenv|conda)\b.*\b(install|add|sync)\b", low) or re.search(
        r"\b(npm|yarn|pnpm|bun)\b.*\b(install|add|i|ci)\b", low
    ):
        notes.append(
            "Installs packages from the internet. Needs network access, which is off by default."
        )
    if re.search(r"\b(curl|wget|git\s+(clone|pull|fetch|push))\b", low):
        notes.append("Uses the network.")
    if re.search(r"\brm\b|\bdel\b|\bmkfs\b|\bdd\b|--force|\bsudo\b", low):
        notes.append("May delete files or needs elevated rights.")
    if re.search(r"\bdocker\b|\bkubectl\b|\bterraform\b|\bdeploy\b|\bpublish\b", low):
        notes.append("May change systems outside this machine.")
    return notes


def _line_of(text: str, needle: str) -> int:
    for i, line in enumerate(text.splitlines(), 1):
        if needle in line:
            return i
    return 1


def _make_targets(text: str) -> list[tuple[str, int]]:
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        m = re.match(r"^([A-Za-z0-9_.-]+)\s*:(?!=)", line)
        if m and m.group(1) in {"test", "tests", "check", "lint", "build", "ci"}:
            out.append((m.group(1), i))
    return out


def discover(files: list[RepoFileRecord], texts: Mapping[str, str]) -> Discovery:
    """`texts` maps path -> content for the config files worth reading (see CONFIG_NAMES)."""
    paths = [f.path for f in files]
    suggestions: list[Suggestion] = []
    frameworks: set[str] = set()
    seen: set[tuple[str, ...]] = set()

    def add(s: Suggestion) -> None:
        key = (s.cwd, *s.argv)
        if key in seen:
            return
        seen.add(key)
        suggestions.append(s)
        frameworks.add(s.framework)

    py_tests = [p for p in paths if PY_TEST_RE.search(p) and p.endswith(".py")]
    js_tests = [p for p in paths if JS_TEST_RE.search(p)]

    for path, text in sorted(texts.items()):
        folder = posixpath.dirname(path)
        name = posixpath.basename(path)
        if name == "package.json":
            try:
                scripts = (json.loads(text) or {}).get("scripts") or {}
            except (json.JSONDecodeError, AttributeError):
                scripts = {}
            for key, cmd in scripts.items():
                if not isinstance(cmd, str):
                    continue
                if key in {"test", "lint", "build", "typecheck", "check"} or key.startswith(
                    "test:"
                ):
                    kind = (
                        "test"
                        if key.startswith("test")
                        else "lint"
                        if key in {"lint", "typecheck"}
                        else "build"
                    )
                    ln = _line_of(text, '"' + key + '"')
                    add(
                        Suggestion(
                            id=f"npm:{folder}:{key}",
                            label=f"npm run {key}",
                            argv=["npm", "run", key],
                            framework="npm",
                            kind=kind,
                            cwd=folder,
                            evidence=f"{path}:{ln} scripts.{key} = {cmd}",
                            notes=[
                                "Needs dependencies (node_modules) installed; Nodecraft never installs packages."
                            ]
                            + risk_notes(cmd.split()),
                        )
                    )
        elif name in {"pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml"}:
            has_pytest = False
            line = 1
            if name == "pyproject.toml":
                try:
                    data = tomllib.loads(text)
                except tomllib.TOMLDecodeError:
                    data = {}
                has_pytest = "pytest" in (data.get("tool") or {})
                line = _line_of(text, "pytest")
            elif name == "pytest.ini":
                has_pytest, line = True, 1
            elif name == "setup.cfg":
                has_pytest, line = "[tool:pytest]" in text, _line_of(text, "[tool:pytest]")
            else:
                has_pytest = "[pytest]" in text or "pytest" in text
                line = _line_of(text, "pytest")
            if has_pytest:
                add(
                    Suggestion(
                        id=f"pytest:{folder}",
                        label="python -m pytest",
                        argv=["python3", "-m", "pytest"],
                        framework="pytest",
                        kind="test",
                        cwd=folder,
                        evidence=f"{path}:{line} configures pytest",
                        notes=[
                            "Needs pytest and the project's dependencies installed for the Python that runs it."
                        ],
                    )
                )
        elif name == "Makefile":
            for target, ln in _make_targets(text):
                add(
                    Suggestion(
                        id=f"make:{folder}:{target}",
                        label=f"make {target}",
                        argv=["make", target],
                        framework="make",
                        kind="test"
                        if target in {"test", "tests", "check", "ci"}
                        else "lint"
                        if target == "lint"
                        else "build",
                        cwd=folder,
                        evidence=f"{path}:{ln} target {target}",
                        notes=["Runs whatever the Makefile says; read it before approving."],
                    )
                )
        elif name == "go.mod":
            add(
                Suggestion(
                    id=f"go:{folder}",
                    label="go test ./...",
                    argv=["go", "test", "./..."],
                    framework="go",
                    kind="test",
                    cwd=folder,
                    evidence=f"{path} is a Go module",
                    notes=["May download modules, which needs network access."],
                )
            )
        elif name == "Cargo.toml":
            add(
                Suggestion(
                    id=f"cargo:{folder}",
                    label="cargo test",
                    argv=["cargo", "test"],
                    framework="cargo",
                    kind="test",
                    cwd=folder,
                    evidence=f"{path} is a Rust crate",
                    notes=["May download crates, which needs network access."],
                )
            )

    if py_tests and not any(s.framework == "pytest" for s in suggestions):
        uses_pytest = any(
            "pytest" in t
            for p, t in texts.items()
            if posixpath.basename(p)
            in {"conftest.py", "requirements.txt", "requirements-dev.txt", "tox.ini"}
        ) or any(posixpath.basename(p) == "conftest.py" for p in paths)
        if uses_pytest:
            add(
                Suggestion(
                    id="pytest:",
                    label="python -m pytest",
                    argv=["python3", "-m", "pytest"],
                    framework="pytest",
                    kind="test",
                    cwd="",
                    evidence=f"{len(py_tests)} test_*.py files and pytest in the project's files",
                    notes=["Needs pytest installed for the Python that runs it."],
                )
            )
        else:
            add(
                Suggestion(
                    id="unittest:",
                    label="python -m unittest discover",
                    argv=["python3", "-m", "unittest", "discover"],
                    framework="unittest",
                    kind="test",
                    cwd="",
                    evidence=f"{len(py_tests)} test files by naming convention (no pytest configuration found)",
                    notes=["A guess from file names; use pytest instead if the project does."],
                )
            )
    return Discovery(
        suggestions=suggestions,
        test_files=sorted(py_tests + js_tests),
        frameworks=sorted(frameworks),
    )


CONFIG_NAMES = {
    "package.json", "pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml", "Makefile", "go.mod",
    "Cargo.toml", "conftest.py", "requirements.txt", "requirements-dev.txt",
}  # fmt: skip
