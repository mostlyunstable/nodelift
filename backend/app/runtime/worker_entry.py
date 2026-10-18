"""Worker process entry point. Runs user code; stdlib only.

Protocol: argv[1] is the fd for the result; stdin carries {"source", "input"} as JSON.
Exactly one JSON object is written to the result fd. User prints go to stdout/stderr.
TRUSTED LOCAL MODE: this is not a sandbox.
"""

import json
import os
import sys
import traceback

USER_FILE = "<node>"


def _emit(fd: int, payload: dict[str, object]) -> None:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(payload))


def _user_traceback(exc: BaseException) -> str:
    tb = exc.__traceback__
    frames = [f for f in traceback.extract_tb(tb) if f.filename == USER_FILE]
    lines = ["Traceback (most recent call last):\n"]
    lines += traceback.format_list(frames)
    lines += traceback.format_exception_only(type(exc), exc)
    return "".join(lines)


def main() -> None:
    fd = int(sys.argv[1])
    req = json.loads(sys.stdin.read())
    try:
        code = compile(req["source"], USER_FILE, "exec")
    except SyntaxError as e:
        _emit(
            fd,
            {
                "ok": False,
                "error": {
                    "type": "syntax_error",
                    "message": e.msg,
                    "line": e.lineno,
                    "column": e.offset,
                },
            },
        )
        return
    ns: dict[str, object] = {"__name__": "__node__"}
    try:
        exec(code, ns)  # noqa: S102
        fn = ns.get("main")
        if not callable(fn):
            _emit(
                fd,
                {
                    "ok": False,
                    "error": {"type": "missing_main", "message": "Define `def main(input_data):`"},
                },
            )
            return
        result = fn(req["input"])
    except BaseException as e:  # noqa: BLE001
        _emit(
            fd,
            {
                "ok": False,
                "error": {
                    "type": "runtime_error",
                    "message": f"{type(e).__name__}: {e}",
                    "traceback": _user_traceback(e),
                },
            },
        )
        return
    try:
        encoded = json.dumps(result, allow_nan=False)
    except (TypeError, ValueError) as e:
        _emit(
            fd,
            {
                "ok": False,
                "error": {
                    "type": "invalid_output",
                    "message": f"Return value is not JSON-compatible: {e}",
                },
            },
        )
        return
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write('{"ok": true, "output": ' + encoded + "}")


if __name__ == "__main__":
    main()
