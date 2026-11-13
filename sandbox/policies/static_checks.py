"""Static pre-flight checks for tool code (defence in depth; the container is the real boundary)."""

from __future__ import annotations

import ast
import os

SAFE_STDLIB = frozenset({
    "json", "math", "re", "datetime", "time", "random", "string", "statistics", "decimal", "fractions",
    "itertools", "functools", "collections", "typing", "dataclasses", "enum", "uuid", "hashlib", "hmac",
    "base64", "urllib", "html", "textwrap", "copy", "operator", "heapq", "bisect", "csv", "io", "zoneinfo",
})
PACKAGE_IMPORT_NAMES = {"python-dateutil": "dateutil"}
FORBIDDEN_CALLS = frozenset({"eval", "exec", "compile", "__import__", "breakpoint", "globals", "vars",
                             "getattr", "setattr", "delattr", "open", "input"})
MAX_CODE_BYTES = 100_000


def allowed_modules(packages_csv: str | None = None) -> frozenset[str]:
    csv = packages_csv if packages_csv is not None else os.getenv(
        "SANDBOX_ALLOWED_PACKAGES", "requests,httpx,pydantic,python-dateutil")
    pkgs = {PACKAGE_IMPORT_NAMES.get(p.strip(), p.strip().replace("-", "_")) for p in csv.split(",") if p.strip()}
    return SAFE_STDLIB | frozenset(pkgs)


def check_tool_code(code: str, packages_csv: str | None = None) -> list[str]:
    """Return a list of violations (empty = OK)."""
    if len(code.encode("utf-8")) > MAX_CODE_BYTES:
        return ["code exceeds 100KB"]
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"syntax error: {exc.msg} (line {exc.lineno})"]
    allowed = allowed_modules(packages_csv)
    problems: list[str] = []
    has_run = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in allowed:
                    problems.append(f"import of '{alias.name}' is not allowed")
        elif isinstance(node, ast.ImportFrom):
            if node.level or (node.module or "").split(".")[0] not in allowed:
                problems.append(f"import from '{node.module}' is not allowed")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
            problems.append(f"call to '{node.func.id}' is not allowed")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr.endswith("__"):
            problems.append(f"dunder attribute access '{node.attr}' is not allowed")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run":
            has_run = True
    if not has_run:
        problems.append("tool code must define a function run(input)")
    return problems
