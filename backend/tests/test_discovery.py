# ruff: noqa: E501
from app.domain.records import RepoFileRecord
from app.explorer.discovery import discover, risk_notes


def f(path: str) -> RepoFileRecord:
    return RepoFileRecord(
        path=path, language="plaintext", size=1, lines=1, binary=False, stored=True,
        skip_reason=None, analysis_status="not_analyzed",
    )  # fmt: skip


def by_label(d):  # type: ignore[no-untyped-def]
    return {s.label: s for s in d.suggestions}


def test_pytest_from_pyproject_cites_the_file_and_line() -> None:
    toml = '[project]\nname="x"\n\n[tool.pytest.ini_options]\ntestpaths=["tests"]\n'
    d = discover([f("pyproject.toml"), f("tests/test_a.py")], {"pyproject.toml": toml})
    s = by_label(d)["python -m pytest"]
    assert s.argv == ["python3", "-m", "pytest"] and s.cwd == ""
    assert s.evidence.startswith("pyproject.toml:4")
    assert d.test_files == ["tests/test_a.py"] and d.frameworks == ["pytest"]


def test_npm_scripts_become_commands_with_evidence_and_install_warning() -> None:
    pkg = '{\n "scripts": {\n  "test": "vitest run",\n  "build": "vite build",\n  "start": "node x.js"\n }\n}'
    d = discover([f("web/package.json"), f("web/src/a.test.ts")], {"web/package.json": pkg})
    labels = by_label(d)
    assert set(labels) == {
        "npm run test",
        "npm run build",
    }  # `start` is not a check, so not suggested
    t = labels["npm run test"]
    assert t.cwd == "web" and t.kind == "test" and "package.json:3" in t.evidence
    assert any("never installs" in n for n in t.notes)
    assert d.test_files == ["web/src/a.test.ts"]


def test_makefile_targets_only_the_known_ones() -> None:
    mk = "all:\n\techo\ntest:\n\tpytest\nclean:\n\trm -rf x\nlint:\n\truff .\n"
    d = discover([f("Makefile")], {"Makefile": mk})
    assert set(by_label(d)) == {"make test", "make lint"}
    assert by_label(d)["make test"].evidence == "Makefile:3 target test"


def test_unittest_is_offered_only_as_a_guess_when_no_pytest_signals_exist() -> None:
    d = discover([f("tests/test_a.py")], {})
    s = by_label(d)["python -m unittest discover"]
    assert "guess" in s.evidence or "naming convention" in s.evidence


def test_pytest_is_inferred_from_conftest() -> None:
    d = discover([f("conftest.py"), f("test_a.py")], {"conftest.py": "import pytest\n"})
    assert "python -m pytest" in by_label(d)


def test_go_and_cargo_modules() -> None:
    d = discover([f("go.mod"), f("Cargo.toml")], {"go.mod": "module x", "Cargo.toml": "[package]"})
    assert {"go test ./...", "cargo test"} <= set(by_label(d))


def test_nothing_found_means_nothing_suggested() -> None:
    d = discover([f("README.md")], {})
    assert d.suggestions == [] and d.test_files == []


def test_malformed_config_files_do_not_crash() -> None:
    d = discover(
        [f("package.json"), f("pyproject.toml")],
        {"package.json": "{not json", "pyproject.toml": "= ="},
    )
    assert d.suggestions == []


def test_risk_notes_flag_installs_network_and_deletion() -> None:
    assert risk_notes(["pip", "install", "x"])
    assert risk_notes(["npm", "ci"])
    assert risk_notes(["curl", "http://x"])
    assert risk_notes(["rm", "-rf", "."])
    assert risk_notes(["pytest"]) == []
