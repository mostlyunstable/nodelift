# ruff: noqa: E501
"""Turn one Python function of an imported repository into a workflow node draft.

This is a *copied implementation*: the function and what it visibly needs (same-file helpers, module constants,
standard-library imports) are copied into a code node. Nothing links the node back to the repository, anything that
could not be copied is listed as a warning, and the user reviews the source before a workflow is created.
"""

import ast
import builtins
import sys
from dataclasses import dataclass, field

MAX_COPIED = 12
_BUILTINS = set(dir(builtins))


class NotConvertible(ValueError):
    pass


@dataclass
class Draft:
    source: str
    function: str
    copied: list[dict[str, object]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    free_names: list[str] = field(default_factory=list)
    params: list[str] = field(default_factory=list)


def _loads(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def _stores(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.add(n.id)
        elif isinstance(n, ast.arg):
            out.add(n.arg)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n is not node:
            out.add(n.name)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            out.update((a.asname or a.name.split(".")[0]) for a in n.names)
    return out


def _lines(text: str, node: ast.stmt) -> str:
    start = min([node.lineno, *(d.lineno for d in getattr(node, "decorator_list", []))])
    return "\n".join(text.splitlines()[start - 1 : node.end_lineno])


def build_draft(text: str, function: str, origin: str) -> Draft:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError) as e:
        raise NotConvertible(f"The file could not be parsed: {type(e).__name__}") from e
    defs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef] = {}
    consts: dict[str, ast.Assign | ast.AnnAssign] = {}
    imports: dict[str, tuple[ast.Import | ast.ImportFrom, ast.alias]] = {}
    for st in tree.body:
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defs[st.name] = st
        elif (
            isinstance(st, ast.Assign)
            and len(st.targets) == 1
            and isinstance(st.targets[0], ast.Name)
        ):
            consts[st.targets[0].id] = st
        elif (
            isinstance(st, ast.AnnAssign)
            and isinstance(st.target, ast.Name)
            and st.value is not None
        ):
            consts[st.target.id] = st
        elif isinstance(st, (ast.Import, ast.ImportFrom)):
            for a in st.names:
                imports[a.asname or a.name.split(".")[0]] = (st, a)
    root = defs.get(function)
    if not isinstance(root, (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise NotConvertible(
            f"{function!r} is not a top-level function of this file (methods and classes are not supported)"
        )

    draft = Draft(source="", function=function)
    need_defs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef] = {function: root}
    need_consts: dict[str, ast.stmt] = {}
    need_imports: dict[tuple[int, str], tuple[ast.Import | ast.ImportFrom, ast.alias]] = {}
    free: set[str] = set()
    queue = [function]
    while queue:
        node = need_defs[queue.pop()]
        wanted = _loads(node) - (_stores(node) - {getattr(node, "name", "")})
        for name in sorted(wanted):
            if name in need_defs or name in need_consts:
                continue
            if name in defs:
                if len(need_defs) >= MAX_COPIED:
                    draft.warnings.append(
                        f"Stopped copying after {MAX_COPIED} definitions; {name!r} and what it uses were not copied."
                    )
                    free.add(name)
                    continue
                need_defs[name] = defs[name]
                queue.append(name)
            elif name in consts:
                need_consts[name] = consts[name]
                wanted |= _loads(consts[name])
            elif name in imports:
                st, alias = imports[name]
                need_imports[(st.lineno, alias.name)] = (st, alias)
            elif name not in _BUILTINS:
                free.add(name)

    # imports, pruned to the names actually used
    lines: list[str] = []
    dropped = False
    for (_, _), (st, alias) in sorted(need_imports.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        pruned: ast.stmt
        if isinstance(st, ast.Import):
            pruned = ast.Import(names=[alias])
            top = alias.name.split(".")[0]
        else:
            pruned = ast.ImportFrom(module=st.module, names=[alias], level=st.level)
            top = (st.module or "").split(".")[0]
        level = getattr(st, "level", 0)
        text_line = ast.unparse(pruned)
        if level:
            draft.warnings.append(
                f"`{text_line}` imports another file of the repository, which a code node cannot do. It is left as a comment."
            )
        elif top and top not in sys.stdlib_module_names:
            draft.warnings.append(
                f"`{text_line}` needs `{top}`, which is not in the Python standard library (code nodes only have the standard library). It is left as a comment."
            )
        else:
            lines.append(text_line)
            draft.copied.append(
                {"kind": "import", "name": alias.asname or alias.name, "line": st.lineno}
            )
            continue
        lines.append(f"# unavailable in a code node: {text_line}")
        dropped = True
    body: list[str] = []
    for name, st in sorted(need_consts.items(), key=lambda kv: kv[1].lineno):
        body.append(_lines(text, st))
        draft.copied.append({"kind": "constant", "name": name, "line": st.lineno})
    for name, node in sorted(need_defs.items(), key=lambda kv: kv[1].lineno):
        if name != function:
            body.append(_lines(text, node))
            draft.copied.append(
                {
                    "kind": "class" if isinstance(node, ast.ClassDef) else "function",
                    "name": name,
                    "line": node.lineno,
                }
            )
    body.append(_lines(text, root))
    draft.copied.append({"kind": "function", "name": function, "line": root.lineno})

    args = root.args
    positional = [a.arg for a in [*args.posonlyargs, *args.args]]
    draft.params = [
        *positional,
        *([f"*{args.vararg.arg}"] if args.vararg else []),
        *[a.arg for a in args.kwonlyargs],
        *([f"**{args.kwarg.arg}"] if args.kwarg else []),
    ]
    single = len(positional) == 1 and not args.kwonlyargs and not args.vararg and not args.kwarg
    call = f"{function}(input_data)" if single else f"{function}(**input_data)"
    is_async = isinstance(root, ast.AsyncFunctionDef)
    if is_async:
        lines.append("import asyncio")
        call = f"asyncio.run({call})"
    if not positional and not args.kwonlyargs:
        call = f"{function}()" if not is_async else "asyncio.run(" + f"{function}())"
    if not single and positional:
        draft.warnings.append(
            f"`{function}` takes {len(positional)} arguments: the node passes the input's fields as keyword arguments ({', '.join(positional)})."
        )
    for name in sorted(free):
        draft.warnings.append(
            f"`{name}` is used but could not be found in this file (a global, a decorator, or something imported with *). It was not copied."
        )
    draft.free_names = sorted(free)
    header = f"# Copied from {origin}\n# Generated by Nodecraft from an imported repository. Review it before you run it.\n"
    if dropped:  # annotations that mention an unavailable name must not be evaluated when the function is defined
        lines.insert(0, "from __future__ import annotations")
    draft.source = (
        header
        + ("\n".join(dict.fromkeys(lines)) + "\n\n" if lines else "\n")
        + "\n\n".join(body)
        + "\n\n\ndef main(input_data):\n"
        + f"    return {call}\n"
    )
    return draft
