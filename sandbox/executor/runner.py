"""In-container tool runner. Reads {"code": str, "input": any} from stdin (or $AGENTFORGE_PAYLOAD,
base64-encoded JSON), loads the code as an isolated module, calls ``run(input)`` and prints exactly one
JSON line on stdout: {"ok": true, "output": ...} or {"ok": false, "error": "...", "error_type": "..."}.

Stdlib only — this file runs inside the minimal sandbox image.
"""

import base64
import contextlib
import io
import json
import os
import sys
import traceback
import types

MAX_OUTPUT_BYTES = 1_000_000
RESULT_MARKER = "__AGENTFORGE_RESULT__"


def _read_payload():
    raw = os.environ.pop("AGENTFORGE_PAYLOAD", "")
    if raw:
        return json.loads(base64.b64decode(raw).decode("utf-8"))
    data = sys.stdin.read()
    return json.loads(data or "{}")


def _emit(result):
    text = json.dumps(result, default=str)
    if len(text) > MAX_OUTPUT_BYTES:
        text = json.dumps({"ok": False, "error": "tool output exceeds 1MB", "error_type": "OutputTooLarge"})
    sys.__stdout__.write(RESULT_MARKER + text + "\n")
    sys.__stdout__.flush()


def main():
    try:
        payload = _read_payload()
        code = payload.get("code")
        if not isinstance(code, str) or not code.strip():
            raise ValueError("payload.code must be a non-empty string")
        module = types.ModuleType("agentforge_tool")
        module.__file__ = "<tool>"
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            exec(compile(code, "<tool>", "exec"), module.__dict__)  # noqa: S102 - isolated container
            run = getattr(module, "run", None)
            if not callable(run):
                raise AttributeError("tool code must define a callable run(input)")
            output = run(payload.get("input"))
        logs = captured.getvalue()[-10_000:]
        _emit({"ok": True, "output": output, "logs": logs})
    except BaseException as exc:  # noqa: BLE001 - report everything, including SystemExit
        _emit({"ok": False, "error": str(exc)[:2000], "error_type": type(exc).__name__,
               "traceback": traceback.format_exc(limit=5)[-4000:]})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
