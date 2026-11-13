"""AST-based static analysis for user/LLM tool code. NEVER executes the code."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

from app.core.config import settings

BLOCKED_MODULES = frozenset(
    {
        "os",
        "sys",
        "subprocess",
        "shutil",
        "socket",
        "ctypes",
        "importlib",
        "builtins",
        "pickle",
        "marshal",
        "multiprocessing",
        "threading",
        "signal",
        "pty",
        "resource",
        "inspect",
        "gc",
        "code",
        "codeop",
        "pathlib",
        "tempfile",
        "glob",
        "io",
        "fcntl",
        "posix",
        "nt",
        "asyncio",
        "sqlite3",
        "shelve",
        "dbm",
        "webbrowser",
    }
)
SAFE_STDLIB = frozenset(
    {
        "json",
        "math",
        "re",
        "datetime",
        "time",
        "typing",
        "dataclasses",
        "decimal",
        "fractions",
        "statistics",
        "random",
        "string",
        "collections",
        "itertools",
        "functools",
        "operator",
        "uuid",
        "base64",
        "hashlib",
        "hmac",
        "urllib",
        "html",
        "enum",
        "copy",
        "textwrap",
        "difflib",
        "zoneinfo",
        "calendar",
        "bisect",
        "heapq",
    }
)
BLOCKED_CALLS = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "open",
        "input",
        "breakpoint",
        "globals",
        "locals",
        "vars",
        "getattr",
        "setattr",
        "delattr",
        "memoryview",
    }
)
PKG_IMPORT_NAMES = {"python-dateutil": "dateutil"}


@dataclass
class AnalysisResult:
    ok: bool
    issues: list[str] = field(default_factory=list)


def _allowed_modules() -> set[str]:
    allowed = set(SAFE_STDLIB)
    for pkg in settings.allowed_packages:
        allowed.add(PKG_IMPORT_NAMES.get(pkg, pkg.replace("-", "_")))
    return allowed


def analyze(source: str, requirements: list[str] | None = None) -> AnalysisResult:
    issues: list[str] = []
    for req in requirements or []:
        name = req.split("==")[0].split(">=")[0].split("<")[0].strip().lower()
        if name not in settings.allowed_packages:
            issues.append(f"Requirement not allowed: {name}")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return AnalysisResult(False, [*issues, f"Syntax error: {exc.msg} (line {exc.lineno})"])
    allowed = _allowed_modules()
    has_run = False
    for node in ast.walk(tree):
        mods: list[str] = []
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                issues.append(f"Relative import not allowed (line {node.lineno})")
            mods = [node.module or ""]
        for m in mods:
            root = m.split(".")[0]
            if root in BLOCKED_MODULES or root not in allowed:
                issues.append(f"Blocked import: {m} (line {node.lineno})")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALLS:
            issues.append(f"Blocked call: {node.func.id}() (line {node.lineno})")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr.endswith("__"):
            issues.append(f"Dunder attribute access not allowed: {node.attr} (line {node.lineno})")
        if isinstance(node, ast.Name) and node.id in {"__builtins__", "__loader__", "__spec__"}:
            issues.append(f"Access to {node.id} not allowed (line {node.lineno})")
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            issues.append(f"global/nonlocal not allowed (line {node.lineno})")
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "run" and len(node.args.args) == 1:
            has_run = True
    if not has_run:
        issues.append("Tool must define top-level `def run(input: dict) -> dict:`")
    return AnalysisResult(not issues, issues)
