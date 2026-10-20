"""Optional OS-level confinement for child processes (macOS Seatbelt via `sandbox-exec`).

What it enforces, in the kernel, on the process and everything it spawns:
  - no network (unless explicitly allowed),
  - writes only inside one scratch folder (plus /dev/null and the terminal),
  - no reads of the user's home folder, except the scratch folder and the interpreter's own files.

What it does not do: hide that files exist (metadata stays readable), limit CPU/memory (rlimits
and a watchdog do that), or stop reads outside the home folder (system files, /tmp).
`sandbox-exec` is deprecated by Apple but still enforced by the kernel. It is confinement, not a
VM or container.
"""

import functools
import subprocess
import sys
from pathlib import Path

SANDBOX_EXEC = "/usr/bin/sandbox-exec"


class UnsafePath(ValueError):
    pass


def _q(path: Path | str) -> str:
    s = str(path)
    if '"' in s or "\\" in s or "\n" in s:
        raise UnsafePath(f"cannot place {s!r} in a sandbox profile")
    return f'"{s}"'


@functools.lru_cache(maxsize=1)
def available() -> bool:
    """True only if this machine can really run a sandboxed process (probed once)."""
    if sys.platform != "darwin":
        return False
    try:
        r = subprocess.run(
            [SANDBOX_EXEC, "-p", "(version 1)(allow default)(deny network*)", "/usr/bin/true"],
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def build_profile(
    scratch: Path,
    read_roots: list[Path],
    allow_network: bool = False,
    write_roots: list[Path] | None = None,
    protect_home: bool = True,
) -> str:
    home = Path.home().resolve()
    lines = ["(version 1)", "(allow default)"]
    if not allow_network:
        lines.append("(deny network*)")
    lines.append("(deny file-write*)")
    writes = [scratch.resolve(), *(p.resolve() for p in (write_roots or []))]
    lines.append(
        "(allow file-write* "
        + " ".join(f"(subpath {_q(p)})" for p in writes)
        + ' (literal "/dev/null") (literal "/dev/dtracehelper") (regex #"^/dev/tty"))'
    )
    if protect_home:
        lines.append(f"(deny file-read* (subpath {_q(home)}))")
        lines.append("(allow file-read-metadata)")  # path resolution needs stat() on parents
        allowed = [*writes, *(p.resolve() for p in read_roots)]
        lines.append("(allow file-read* " + " ".join(f"(subpath {_q(p)})" for p in allowed) + ")")
    return "\n".join(lines) + "\n"


def wrap(argv: list[str], profile: str) -> list[str]:
    return [SANDBOX_EXEC, "-p", profile, *argv]


def python_read_roots() -> list[Path]:
    """What a stdlib-only Python worker needs to read: its interpreter and the worker script."""
    roots = {Path(sys.prefix), Path(sys.base_prefix), Path(sys.executable).resolve().parent}
    return sorted(r.resolve() for r in roots)
