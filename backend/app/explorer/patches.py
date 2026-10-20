"""Proposed changes as reviewable unified diffs. Pure text; nothing here touches the disk."""

import difflib


def unified_diff(path: str, old: str, new: str) -> str:
    """A diff `git apply` / `patch -p1` accept, with a/ and b/ prefixes."""
    lines = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=3,
    )
    out = []
    for line in lines:
        out.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    body = "".join(out)
    return f"diff --git a/{path} b/{path}\n{body}" if body else ""


def stats(old: str, new: str) -> tuple[int, int]:
    """(added lines, removed lines)."""
    add = rem = 0
    for line in difflib.ndiff(old.splitlines(), new.splitlines()):
        if line.startswith("+ "):
            add += 1
        elif line.startswith("- "):
            rem += 1
    return add, rem
