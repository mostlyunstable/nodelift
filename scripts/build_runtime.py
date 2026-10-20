#!/usr/bin/env python3
"""Build the self-contained Python runtime the desktop app ships with.

Result (default: apps/web/src-tauri/resources/runtime):
    python/         a relocatable CPython (python-build-standalone via uv) with the FULL standard library,
                    because user code nodes must be able to import csv, datetime, sqlite3, ...
    site-packages/  the backend's dependencies and the `app` package

Run with any Python 3.9+:  python3 scripts/build_runtime.py [--out DIR] [--version 3.12]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DEFAULT_OUT = ROOT / "apps" / "web" / "src-tauri" / "resources" / "runtime"

# Not needed at runtime; removing them keeps the app small. Everything user code might import stays.
PRUNE = [
    "lib/python{v}/test",
    "lib/python{v}/idlelib",
    "lib/python{v}/tkinter",
    "lib/python{v}/turtledemo",
    "lib/python{v}/turtle.py",
    "lib/python{v}/lib2to3",
    "lib/python{v}/ensurepip",
    "lib/python{v}/site-packages",
    "lib/python{v}/config-{v}-darwin",
    "lib/libpython{v}.a",
    "lib/tcl9.0",
    "lib/tk9.0",
    "lib/itcl4.3.4",
    "lib/tcl9",
    "include",
    "share",
]


def run(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, check=True, text=True, **kw)  # type: ignore[call-overload]


def find_python(version: str) -> Path:
    run(["uv", "python", "install", version])
    out = run(["uv", "python", "find", version], capture_output=True).stdout.strip()
    exe = Path(out).resolve()
    return exe.parent.parent  # <install>/bin/python3.x -> <install>


def dir_size_mb(path: Path) -> float:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1e6


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--version", default="3.12")
    args = ap.parse_args()
    out: Path = args.out.resolve()
    v = args.version

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    src = find_python(v)
    py_dir = out / "python"
    print(f"copying {src} -> {py_dir}")
    shutil.copytree(src, py_dir, symlinks=True)
    for pattern in PRUNE:
        target = py_dir / pattern.format(v=v)
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists() or target.is_symlink():
            target.unlink()
    (py_dir / "EXTERNALLY-MANAGED").unlink(missing_ok=True)

    python = py_dir / "bin" / f"python{v}"
    if not python.exists():
        print(f"missing {python}", file=sys.stderr)
        return 1

    site = out / "site-packages"
    requirements = out / "requirements.txt"
    run(
        ["uv", "export", "--project", str(BACKEND), "--no-dev", "--no-hashes", "--no-emit-project",
         "-o", str(requirements)],
        capture_output=True,
    )  # fmt: skip
    run(["uv", "pip", "install", "--python", str(python), "--target", str(site), "-r", str(requirements),
         "--quiet"])  # fmt: skip
    requirements.unlink()

    shutil.copytree(
        BACKEND / "app", site / "app",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests"),
    )  # fmt: skip
    for cache in site.rglob("__pycache__"):  # stale caches from the install step
        shutil.rmtree(cache, ignore_errors=True)
    run([str(python), "-m", "compileall", "-q", str(site), str(py_dir / "lib")], capture_output=True)

    # smoke: the stdlib user code needs, plus the backend importing from a different directory
    check = (
        "import csv, datetime, sqlite3, ssl, json, statistics, decimal, zoneinfo, re, math, hashlib;"
        "ssl.create_default_context(); import app.main; print('runtime ok', __import__('sys').version.split()[0])"
    )
    env = {"PYTHONPATH": str(site), "PATH": "/usr/bin:/bin"}
    run([str(python), "-s", "-c", check], cwd="/", env=env)

    print(f"runtime built at {out} ({dir_size_mb(out):.0f} MB: python {dir_size_mb(py_dir):.0f}, "
          f"packages {dir_size_mb(site):.0f})")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
