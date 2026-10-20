import threading
from pathlib import Path

import pytest

from app.domain.records import RepoFileRecord
from app.explorer.analysis.runner import AnalysisResult, analyze_files
from app.explorer.archive import Cancelled
from app.explorer.languages import detect_language


def build(tmp_path: Path, tree: dict[str, str]) -> tuple[Path, list[RepoFileRecord]]:
    root = tmp_path / "files"
    files = []
    for rel, text in tree.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        files.append(
            RepoFileRecord(
                path=rel, language=detect_language(rel), size=len(text), lines=text.count("\n") + 1,
                binary=False, stored=True, skip_reason=None, analysis_status="not_analyzed",
            )
        )  # fmt: skip
    return root, files


def run(tmp_path: Path, tree: dict[str, str]) -> AnalysisResult:
    root, files = build(tmp_path, tree)
    return analyze_files(root, files)


def edges(res: AnalysisResult, src: str) -> set[tuple[str | None, str, str]]:
    return {(e.dst, e.kind, e.confidence) for e in res.edges if e.src == src}


PY_TREE = {
    "app/__init__.py": "",
    "app/utils.py": "def helper():\n    return 1\n",
    "app/models.py": (
        "class User:\n    def name(self):\n        return 'x'\n\ndef _private():\n    pass\n"
    ),
    "app/config.py": "settings = {}\n",
    "app/main.py": (
        "import os\n"
        "import importlib\n"
        "from typing import TYPE_CHECKING\n"
        "from . import utils\n"
        "from .models import User\n"
        "from app.config import settings\n"
        "import requests\n"
        "try:\n"
        "    import ujson\n"
        "except ImportError:\n"
        "    ujson = None\n"
        "if TYPE_CHECKING:\n"
        "    from .models import User as U2\n"
        "importlib.import_module('app.utils')\n"
        "name = 'x'\n"
        "importlib.import_module(name)\n"
        "from .nope import thing\n"
    ),
    "app/bad.py": "def broken(:\n    pass\n",
    "scripts/run.py": "import helper\n",
    "scripts/helper.py": "x = 1\n",
    "src/pkg/__init__.py": "",
    "src/pkg/core.py": "def go():\n    pass\n",
    "tests/test_main.py": "from app import main\nfrom pkg.core import go\n",
    "tests/test_utils.py": "def test_x():\n    assert True\n",
    "tests/test_config.py": "from app.config import settings\n",
}


def test_python_imports_are_resolved_to_real_files(tmp_path: Path) -> None:
    res = run(tmp_path, PY_TREE)
    got = edges(res, "app/main.py")
    assert ("app/utils.py", "import", "resolved") in got  # from . import utils
    assert ("app/models.py", "import", "resolved") in got  # from .models import User
    assert ("app/config.py", "import", "resolved") in got
    assert ("app/utils.py", "dynamic_import", "resolved") in got  # literal import_module
    # outside the repository
    assert (None, "import", "external") in got  # os / requests / ujson
    externals = {
        e.raw: e.note for e in res.edges if e.src == "app/main.py" and e.confidence == "external"
    }
    assert externals["os"] == "standard library"
    assert "not found in the repository" in (externals["requests"] or "")


def test_python_notes_optional_and_type_only_imports(tmp_path: Path) -> None:
    res = run(tmp_path, PY_TREE)
    notes = {e.raw: e.note for e in res.edges if e.src == "app/main.py" and e.note}
    assert "optional" in notes["ujson"]
    tc = [e for e in res.edges if e.src == "app/main.py" and e.line == 13]
    assert tc and all("type-checking" in (e.note or "") for e in tc)


def test_python_does_not_invent_dynamic_or_missing_targets(tmp_path: Path) -> None:
    res = run(tmp_path, PY_TREE)
    unresolved = [e for e in res.edges if e.src == "app/main.py" and e.confidence == "unresolved"]
    kinds = {(e.kind, e.note) for e in unresolved}
    assert any(k == "dynamic_import" and "runtime" in (n or "") for k, n in kinds)
    assert any("relative import target not found" in (e.note or "") for e in unresolved)
    assert all(e.dst is None for e in unresolved)
    diag = [d for d in res.diagnostics if d.code == "unresolved_import"]
    assert diag and diag[0].path == "app/main.py" and diag[0].line == 17


def test_python_package_roots_and_script_style_imports(tmp_path: Path) -> None:
    res = run(tmp_path, PY_TREE)
    assert ("scripts/helper.py", "import", "resolved") in edges(res, "scripts/run.py")
    got = edges(res, "tests/test_main.py")
    assert ("app/__init__.py", "import", "resolved") in got
    assert ("app/main.py", "import", "resolved") in got  # `from app import main` is a submodule
    assert ("src/pkg/core.py", "import", "resolved") in got  # found through the src/ layout


def test_python_syntax_error_is_a_diagnostic_with_a_line(tmp_path: Path) -> None:
    res = run(tmp_path, PY_TREE)
    d = [x for x in res.diagnostics if x.path == "app/bad.py"]
    assert d and d[0].code == "syntax_error" and d[0].line == 1 and d[0].severity == "error"
    assert res.statuses["app/bad.py"] == "analyzed"


def test_python_symbols(tmp_path: Path) -> None:
    res = run(tmp_path, PY_TREE)
    syms = {
        (s.name, s.kind, s.parent, s.exported) for s in res.symbols if s.path == "app/models.py"
    }
    assert ("User", "class", None, True) in syms
    assert ("name", "method", "User", True) in syms
    assert ("_private", "function", None, False) in syms


def test_test_files_link_by_import_and_by_name_only_when_needed(tmp_path: Path) -> None:
    res = run(tmp_path, PY_TREE)
    named = [e for e in res.edges if e.kind == "tests"]
    assert [(e.src, e.dst, e.confidence) for e in named] == [
        ("tests/test_utils.py", "app/utils.py", "heuristic")
    ]
    assert "name only" in (named[0].note or "")
    # test_config.py imports config, so no guessed edge is added on top of the real one
    assert not any(e.src == "tests/test_config.py" and e.kind == "tests" for e in res.edges)


JS_TREE = {
    "web/index.js": (
        "import a from './a.js'\n"
        "import { b } from './lib'\n"
        "import React from 'react'\n"
        "import x from '@/alias/thing'\n"
        "import './missing'\n"
        "import fs from 'node:fs'\n"
        "const c = require('./c')\n"
        "const lazy = () => import('./lazy')\n"
        "const d = (n) => import(n)\n"
        "export * from './re'\n"
        "export function f() {}\n"
        "export class K { m() {} }\n"
        "export const g = () => 1\n"
        "const hidden = () => 2\n"
    ),
    "web/a.ts": "export const a = 1\n",
    "web/lib/index.ts": "export const b = 1\n",
    "web/c.js": "module.exports = 1\n",
    "web/lazy.js": "export default 1\n",
    "web/re.js": "export const r = 1\n",
    "web/bad.js": "function ( {\n",
    "web/page.tsx": "import a from './a'\nexport const P = () => <div/>\n",
}


def test_javascript_imports_requires_and_reexports(tmp_path: Path) -> None:
    res = run(tmp_path, JS_TREE)
    got = edges(res, "web/index.js")
    assert ("web/a.ts", "import", "resolved") in got  # './a.js' -> a.ts (TypeScript ESM style)
    assert ("web/lib/index.ts", "import", "resolved") in got  # directory index
    assert ("web/c.js", "import", "resolved") in got  # require
    assert ("web/lazy.js", "dynamic_import", "resolved") in got
    assert ("web/re.js", "reexport", "resolved") in got
    assert ("web/a.ts", "import", "resolved") in edges(res, "web/page.tsx")


def test_javascript_external_unresolved_and_dynamic(tmp_path: Path) -> None:
    res = run(tmp_path, JS_TREE)
    by_raw = {e.raw: e for e in res.edges if e.src == "web/index.js"}
    assert by_raw["react"].confidence == "external" and by_raw["react"].dst is None
    assert by_raw["node:fs"].note == "Node.js built-in"
    assert by_raw["@/alias/thing"].confidence == "unresolved" and "alias" in (
        by_raw["@/alias/thing"].note or ""
    )
    assert by_raw["./missing"].confidence == "unresolved" and by_raw["./missing"].dst is None
    dyn = [
        e
        for e in res.edges
        if e.src == "web/index.js" and e.raw == "" and e.kind == "dynamic_import"
    ]
    assert len(dyn) == 1 and dyn[0].confidence == "unresolved" and dyn[0].dst is None


def test_javascript_symbols_and_syntax_diagnostic(tmp_path: Path) -> None:
    res = run(tmp_path, JS_TREE)
    syms = {(s.name, s.kind, s.parent, s.exported) for s in res.symbols if s.path == "web/index.js"}
    assert ("f", "function", None, True) in syms
    assert ("K", "class", None, True) in syms
    assert ("m", "method", "K", True) in syms
    assert ("g", "function", None, True) in syms
    assert ("hidden", "function", None, False) in syms
    bad = [d for d in res.diagnostics if d.path == "web/bad.js"]
    assert bad and bad[0].code == "syntax_error" and bad[0].severity == "warning"


WEB_TREE = {
    "site/index.html": (
        '<html><head><link rel="stylesheet" href="css/site.css">'
        '<script src="main.js"></script><script src="https://cdn.example/x.js"></script>'
        '<script>var inline = 1</script></head><body><img src="missing.png"></body></html>'
    ),
    "site/main.js": "console.log(1)\n",
    "site/css/site.css": '@import "base.css";\nbody { background: url(../img/logo.png); }\n',
    "site/css/base.css": "p { color: red }\n",
    "site/img/logo.png": "x",
}


def test_html_and_css_references(tmp_path: Path) -> None:
    res = run(tmp_path, WEB_TREE)
    html = {e.raw: e for e in res.edges if e.src == "site/index.html"}
    assert (
        html["css/site.css"].dst == "site/css/site.css"
        and html["css/site.css"].note == "stylesheet"
    )
    assert html["main.js"].dst == "site/main.js"
    assert html["https://cdn.example/x.js"].confidence == "external"
    assert html["missing.png"].confidence == "unresolved" and html["missing.png"].dst is None
    css = {e.raw: e for e in res.edges if e.src == "site/css/site.css"}
    assert css["base.css"].dst == "site/css/base.css" and css["base.css"].kind == "style_import"
    assert (
        css["../img/logo.png"].dst == "site/img/logo.png"
        and css["../img/logo.png"].kind == "reference"
    )


def test_unsupported_and_unreadable_files_are_reported_not_analyzed(tmp_path: Path) -> None:
    root, files = build(tmp_path, {"README.md": "# hi\n", "a.py": "x = 1\n"})
    files.append(
        RepoFileRecord(
            path="logo.png", language="plaintext", size=5, lines=0, binary=True, stored=False,
            skip_reason="binary", analysis_status="not_analyzed",
        )
    )  # fmt: skip
    res = analyze_files(root, files)
    assert res.statuses == {"README.md": "unsupported", "a.py": "analyzed", "logo.png": "skipped"}


def test_one_bad_file_does_not_stop_the_run(tmp_path: Path) -> None:
    root, files = build(tmp_path, {"good.py": "import os\n", "gone.py": "x = 1\n"})
    (root / "gone.py").unlink()  # the cached copy disappeared
    res = analyze_files(root, files)
    assert res.statuses == {"good.py": "analyzed", "gone.py": "failed"}
    assert any(d.code == "analysis_failed" for d in res.diagnostics)


def test_cancel_and_time_budget(tmp_path: Path) -> None:
    root, files = build(tmp_path, {f"m{i}.py": "x = 1\n" for i in range(5)})
    ev = threading.Event()
    ev.set()
    with pytest.raises(Cancelled):
        analyze_files(root, files, ev)
    res = analyze_files(root, files, budget_seconds=-1)
    assert res.partial and set(res.statuses.values()) == {"timeout"}


def test_path_escape_in_an_index_is_refused(tmp_path: Path) -> None:
    root, files = build(tmp_path, {"a.py": "x = 1\n"})
    (tmp_path / "secret.py").write_text("import os\n")
    files.append(
        RepoFileRecord(
            path="../secret.py", language="python", size=1, lines=1, binary=False, stored=True,
            skip_reason=None, analysis_status="not_analyzed",
        )
    )  # fmt: skip
    res = analyze_files(root, files)
    assert res.statuses["../secret.py"] == "failed"
