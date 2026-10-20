# ruff: noqa: E501
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


def test_python_dunder_methods_are_not_marked_private(tmp_path: Path) -> None:
    res = run(
        tmp_path,
        {
            "a.py": (
                "class A:\n    def __init__(self):\n        pass\n    def _x(self):\n        pass\n"
            )
        },
    )
    got = {(s.name, s.exported) for s in res.symbols}
    assert got == {("A", True), ("__init__", True), ("_x", False)}


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
    assert (
        bad and bad[0].code == "parser_note" and bad[0].severity == "info"
    )  # a parser limitation is a note, not a problem


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
    root, files = build(tmp_path, {"notes.txt": "hi\n", "a.py": "x = 1\n"})
    files.append(
        RepoFileRecord(
            path="logo.png", language="plaintext", size=5, lines=0, binary=True, stored=False,
            skip_reason="binary", analysis_status="not_analyzed",
        )
    )  # fmt: skip
    res = analyze_files(root, files)
    assert res.statuses == {"notes.txt": "unsupported", "a.py": "analyzed", "logo.png": "skipped"}


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


# ---- call relationships -------------------------------------------------------------------------
CALL_PY = {
    "pkg/__init__.py": "",
    "pkg/util.py": "def helper():\n    return 1\n\nclass Tool:\n    def run(self):\n        return self.step()\n    def step(self):\n        return helper()\n    @staticmethod\n    def make():\n        return Tool()\n",
    "pkg/other.py": "def far():\n    pass\n",
    "app.py": (
        "import pkg.util\n"
        "import pkg.other as o\n"
        "from pkg import util\n"
        "from pkg.util import helper, Tool as T\n"
        "from pkg.other import far\n"
        "\n"
        "def local():\n"
        "    pass\n"
        "\n"
        "def main():\n"
        "    helper()\n"  # 11 resolved via from-import
        "    util.helper()\n"  # 12 resolved via `from pkg import util`
        "    pkg.util.helper()\n"  # 13 resolved via `import pkg.util`
        "    o.far()\n"  # 14 alias module
        "    far()\n"  # 15
        "    T.make()\n"  # 16 Class.method through alias
        "    local()\n"  # 17 same file
        "    unknown()\n"  # 18 not defined anywhere
        "    thing.method()\n"  # 19 call on a value
        "    getattr(o, 'far')()\n"  # 20 dynamic: not followed
        "\n"
        "class K:\n"
        "    def a(self):\n"
        "        self.b()\n"
        "    def b(self):\n"
        "        pass\n"
    ),
}


def refs(res: AnalysisResult, src: str) -> dict[int, tuple[str, str, str, str | None]]:
    return {
        r.line: (r.dst_path, r.dst_symbol, r.confidence, r.scope)
        for r in res.references
        if r.path == src
    }


def test_python_calls_resolve_through_imports_and_same_file(tmp_path: Path) -> None:
    got = refs(run(tmp_path, CALL_PY), "app.py")
    assert got[11] == ("pkg/util.py", "helper", "resolved", "main")
    assert got[12] == ("pkg/util.py", "helper", "resolved", "main")
    assert got[13] == ("pkg/util.py", "helper", "resolved", "main")
    assert got[14] == ("pkg/other.py", "far", "resolved", "main")
    assert got[15] == ("pkg/other.py", "far", "resolved", "main")
    assert got[16] == ("pkg/util.py", "Tool.make", "resolved", "main")
    assert got[17] == ("app.py", "local", "resolved", "main")


def test_python_calls_that_cannot_be_shown_are_left_out_not_guessed(tmp_path: Path) -> None:
    got = refs(run(tmp_path, CALL_PY), "app.py")
    for line in (18, 19, 20):
        assert line not in got  # undefined name, call on a value, getattr(...)()


def test_python_self_calls_are_heuristic_and_say_why(tmp_path: Path) -> None:
    res = run(tmp_path, CALL_PY)
    m = [r for r in res.references if r.path == "app.py" and r.line == 24][0]
    assert (m.dst_symbol, m.confidence, m.scope) == ("K.b", "heuristic", "K.a")
    assert "overrides" in (m.note or "")
    inner = refs(res, "pkg/util.py")
    assert inner[6][:3] == ("pkg/util.py", "Tool.step", "heuristic")
    assert inner[8][:3] == ("pkg/util.py", "helper", "resolved")


def test_reference_positions_point_at_the_called_name(tmp_path: Path) -> None:
    res = run(tmp_path, CALL_PY)
    r = [x for x in res.references if x.path == "app.py" and x.line == 12][0]
    line = CALL_PY["app.py"].splitlines()[11]
    assert line[r.column - 1 : r.end_column - 1] == "helper"
    r13 = [x for x in res.references if x.path == "app.py" and x.line == 13][0]
    assert CALL_PY["app.py"].splitlines()[12][r13.column - 1 : r13.end_column - 1] == "helper"


CALL_JS = {
    "lib/math.js": "export function add(a, b) { return a + b }\nexport const mul = (a, b) => a * b\nexport class Calc { static of() { return new Calc() } run() { return add(1, 2) } }\nexport default function def() {}\n",
    "main.js": (
        "import { add, mul as times } from './lib/math'\n"
        "import * as M from './lib/math'\n"
        "import dflt from './lib/math'\n"
        "const { Calc } = require('./lib/math')\n"
        "function local() {}\n"
        "function main() {\n"
        "  add(1, 2)\n"  # 7
        "  times(2, 3)\n"  # 8
        "  M.add(1, 2)\n"  # 9
        "  Calc.of()\n"  # 10
        "  local()\n"  # 11
        "  dflt()\n"  # 12 default export: not followed
        "  obj.method()\n"  # 13
        "  fn()()\n"  # 14
        "}\n"
    ),
}


def test_javascript_calls_resolve_through_named_namespace_and_require_bindings(
    tmp_path: Path,
) -> None:
    got = refs(run(tmp_path, CALL_JS), "main.js")
    assert got[7] == ("lib/math.js", "add", "resolved", "main")
    assert got[8] == (
        "lib/math.js",
        "mul",
        "resolved",
        "main",
    )  # aliased import resolves to the original name
    assert got[9] == ("lib/math.js", "add", "resolved", "main")
    assert got[10] == ("lib/math.js", "Calc.of", "resolved", "main")
    assert got[11] == ("main.js", "local", "resolved", "main")
    for line in (12, 13, 14):
        assert line not in got
    inner = refs(run(tmp_path / "x", CALL_JS), "lib/math.js")
    assert any(v[1] == "add" for v in inner.values())


# ---- more languages ---------------------------------------------------------------------------
def kinds(res: AnalysisResult, src: str) -> set[tuple[str | None, str]]:
    return {(e.dst, e.confidence) for e in res.edges if e.src == src}


def test_go_imports_resolve_through_go_mod_and_stdlib_is_external(tmp_path: Path) -> None:
    res = run(
        tmp_path,
        {
            "go.mod": "module example.com/app\n\ngo 1.22\n",
            "main.go": 'package main\n\nimport (\n\t"fmt"\n\tu "example.com/app/util"\n\t"github.com/x/y"\n)\n\nfunc Run() {}\n\ntype T struct{}\n\nfunc (t T) Method() {}\n',
            "util/a.go": "package util\n",
            "util/b.go": "package util\n",
            "util/b_test.go": "package util\n",
        },
    )
    got = kinds(res, "main.go")
    assert ("util/a.go", "resolved") in got and ("util/b.go", "resolved") in got
    assert not any(
        d == "util/b_test.go" for d, _ in got
    )  # test files are not part of the package import
    notes = {e.raw: e.note for e in res.edges if e.src == "main.go" and e.dst is None}
    assert notes["fmt"] == "standard library" and "not in the repository" in (
        notes["github.com/x/y"] or ""
    )
    syms = {(s.name, s.kind, s.parent, s.exported) for s in res.symbols if s.path == "main.go"}
    assert (
        ("Run", "function", None, True) in syms
        and ("Method", "method", "T", True) in syms
        and ("T", "class", None, True) in syms
    )


def test_java_imports_match_package_paths(tmp_path: Path) -> None:
    res = run(
        tmp_path,
        {
            "src/main/java/a/b/Main.java": "package a.b;\nimport a.c.Helper;\nimport java.util.List;\nimport a.c.*;\npublic class Main { public void run() {} private void x() {} }\n",
            "src/main/java/a/c/Helper.java": "package a.c;\npublic class Helper {}\n",
        },
    )
    got = kinds(res, "src/main/java/a/b/Main.java")
    assert ("src/main/java/a/c/Helper.java", "resolved") in got
    assert any(e.note == "Java standard library" for e in res.edges)
    syms = {
        (s.name, s.kind, s.parent, s.exported) for s in res.symbols if s.path.endswith("Main.java")
    }
    assert (
        ("Main", "class", None, True) in syms
        and ("run", "method", "Main", True) in syms
        and ("x", "method", "Main", False) in syms
    )


def test_rust_mod_and_crate_paths(tmp_path: Path) -> None:
    res = run(
        tmp_path,
        {
            "Cargo.toml": "[package]\nname='x'\n",
            "src/main.rs": "mod util;\nmod missing;\nuse crate::util::tools::go;\nuse std::io;\nuse serde::Serialize;\nfn main() {}\n",
            "src/util.rs": "pub mod tools;\npub fn helper() {}\n",
            "src/util/tools.rs": "pub fn go() {}\n",
        },
    )
    got = {(e.raw, e.dst, e.confidence) for e in res.edges if e.src == "src/main.rs"}
    assert ("util", "src/util.rs", "resolved") in got
    assert ("missing", None, "unresolved") in got
    assert ("crate::util::tools::go", "src/util/tools.rs", "resolved") in got
    assert ("std::io", None, "external") in got and ("serde::Serialize", None, "external") in got
    assert ("tools", "src/util/tools.rs", "resolved") in {
        (e.raw, e.dst, e.confidence) for e in res.edges if e.src == "src/util.rs"
    }


def test_ruby_requires(tmp_path: Path) -> None:
    res = run(
        tmp_path,
        {
            "app.rb": "require_relative 'lib/thing'\nrequire 'json'\nrequire 'helper'\nclass App\n  def go; end\nend\n",
            "lib/thing.rb": "class Thing; end\n",
            "lib/helper.rb": "module Helper; end\n",
        },
    )
    got = {(e.raw, e.dst, e.confidence) for e in res.edges if e.src == "app.rb"}
    assert ("lib/thing", "lib/thing.rb", "resolved") in got
    assert ("helper", "lib/helper.rb", "resolved") in got and ("json", None, "external") in got


def test_shell_source_is_heuristic_about_its_base_folder(tmp_path: Path) -> None:
    res = run(
        tmp_path,
        {
            "run.sh": 'source ./lib/common.sh\n. missing.sh\nbash scripts/build.sh\nsource "$DIR/x.sh"\nfoo() { echo; }\n',
            "lib/common.sh": "x=1\n",
            "scripts/build.sh": "echo\n",
        },
    )
    got = {(e.raw, e.dst, e.confidence) for e in res.edges if e.src == "run.sh"}
    assert ("./lib/common.sh", "lib/common.sh", "heuristic") in got
    assert ("scripts/build.sh", "scripts/build.sh", "heuristic") in got
    assert ("missing.sh", None, "unresolved") in got
    assert ("$DIR/x.sh", None, "unresolved") in got
    assert any(s.name == "foo" and s.kind == "function" for s in res.symbols)


def test_markdown_links_and_headings(tmp_path: Path) -> None:
    res = run(
        tmp_path,
        {
            "README.md": "# Title\n\nSee [guide](docs/guide.md#top), ![logo](img/logo.png), [site](https://x.dev), [gone](nope.md).\n\n## Usage\n",
            "docs/guide.md": "# Guide\n",
            "img/logo.png": "x",
        },
    )
    got = {(e.raw, e.dst, e.confidence) for e in res.edges if e.src == "README.md"}
    assert ("docs/guide.md#top", "docs/guide.md", "resolved") in got and (
        "img/logo.png",
        "img/logo.png",
        "resolved",
    ) in got
    assert ("https://x.dev", None, "external") in got and ("nope.md", None, "unresolved") in got
    assert [s.name for s in res.symbols if s.path == "README.md"] == ["Title", "Usage"]


def test_yaml_and_json_references(tmp_path: Path) -> None:
    res = run(
        tmp_path,
        {
            ".github/workflows/ci.yml": "jobs:\n  a:\n    steps:\n      - uses: ./.github/actions/setup\n      - uses: actions/checkout@v4\n      - run: echo\n",
            ".github/actions/setup/action.yml": "name: setup\n",
            "package.json": '{\n "name": "x",\n "main": "dist/index.js",\n "scripts": {"a": "b"}\n}',
            "dist/index.js": "module.exports = 1\n",
            "schema.json": '{"$ref": "./defs.json#/a"}',
            "defs.json": "{}",
            "broken.json": "{not json",
            "bad.yml": "a: [1, 2\n",
        },
    )
    assert ("./.github/actions/setup", ".github/actions/setup/action.yml", "resolved") in {
        (e.raw, e.dst, e.confidence) for e in res.edges if e.src == ".github/workflows/ci.yml"
    }
    assert not any(
        e.raw == "actions/checkout@v4" for e in res.edges
    )  # a remote action is not a file reference
    assert ("./dist/index.js", "dist/index.js", "resolved") in {
        (e.raw, e.dst, e.confidence) for e in res.edges if e.src == "package.json"
    }
    assert ("./defs.json", "defs.json", "resolved") in {
        (e.raw, e.dst, e.confidence) for e in res.edges if e.src == "schema.json"
    }
    bad = {d.path: d for d in res.diagnostics if d.code == "syntax_error"}
    assert (
        bad["broken.json"].severity == "error"
        and bad["bad.yml"].severity == "error"
        and bad["bad.yml"].line >= 1
    )


def test_sql_symbols_and_heuristic_table_references(tmp_path: Path) -> None:
    res = run(
        tmp_path,
        {
            "db/schema.sql": "CREATE TABLE users (id INT);\nCREATE VIEW active AS SELECT * FROM users;\n",
            "db/report.sql": "SELECT * FROM users JOIN orders ON 1=1;\n",
        },
    )
    syms = {(s.name, s.kind) for s in res.symbols if s.path == "db/schema.sql"}
    assert ("users", "class") in syms and ("active", "class") in syms
    got = [(e.dst, e.raw, e.confidence) for e in res.edges if e.src == "db/report.sql"]
    assert got == [
        ("db/schema.sql", "users", "heuristic")
    ]  # `orders` is created nowhere, so no edge is invented


# ---- false alarms we must not raise ------------------------------------------------------------
def test_flow_typed_javascript_is_not_reported_as_broken(tmp_path: Path) -> None:
    res = run(
        tmp_path,
        {
            "a.js": "/** @flow */\nexport function f(x: number): string { return String(x) }\n",
            "b.js": "function (( {\n",
        },
    )
    assert not [
        d for d in res.diagnostics if d.path == "a.js"
    ]  # @flow: syntax the parser does not know
    assert [d.severity for d in res.diagnostics if d.path == "b.js"] == [
        "info"
    ]  # unknown failures are notes
    assert res.statuses["a.js"] == "analyzed"  # still analysed for imports/symbols


def test_imports_of_build_output_and_packages_are_not_problems(tmp_path: Path) -> None:
    res = run(
        tmp_path,
        {
            "src/a.js": "import x from '../dist/out'\nimport y from '../../node_modules/pkg/index'\nimport z from './missing'\n",
            "src/p.py": "from .nope import thing\nfrom .generated.api import g\n",
        },
    )
    got = {
        (d.path, d.severity, d.message.split()[2])
        for d in res.diagnostics
        if d.code == "unresolved_import"
    }
    assert got == {
        ("src/a.js", "info", "./missing"),
        ("src/p.py", "warning", "nope"),
        ("src/p.py", "warning", "generated.api"),
    }
    codes = {(d.path, d.message) for d in res.diagnostics if d.code == "unresolved_import"}
    assert not any("dist" in m or "node_modules" in m for _, m in codes)
    assert ("src/a.js", "Cannot find ./missing in the repository") in codes
    assert [d.severity for d in res.diagnostics if d.path == "src/a.js"] == ["info"]  # JS: a note
    assert [
        d.severity for d in res.diagnostics if d.path == "src/p.py" and "nope" in d.message
    ] == ["warning"]  # Python relative: a warning


def test_json_with_comments_is_read_but_real_json_errors_stay_errors(tmp_path: Path) -> None:
    res = run(
        tmp_path,
        {
            "tsconfig.json": '{\n  // a comment\n  "extends": "./base.json", /* block */\n  "url": "http://x//y",\n  "list": [1, 2,],\n}\n',
            "base.json": "{}",
            "data.json": "{not json",
            ".eslintrc.json": "{ oops",
        },
    )
    assert not [
        d for d in res.diagnostics if d.path == "tsconfig.json"
    ]  # comments, trailing commas and `//` inside a string are fine
    assert ("./base.json", "base.json", "resolved") in {
        (e.raw, e.dst, e.confidence) for e in res.edges if e.src == "tsconfig.json"
    }
    sev = {d.path: d.severity for d in res.diagnostics if d.code == "syntax_error"}
    assert sev["data.json"] == "error"  # plain JSON must be valid
    assert sev[".eslintrc.json"] == "warning"  # tolerant file kinds are only warned about
