"""Minimal, safe template rendering: ``{{input}}``, ``{{last_output}}``, ``{{outputs.<node_id>}}``.

Dotted paths may descend into dicts (``{{input.question}}``, ``{{outputs.api-1.status}}``).
Unknown placeholders render as empty strings. No code execution.
"""

from __future__ import annotations

import json
import re
from typing import Any

_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][\w-]*(?:\.[\w-]+)*)\s*\}\}")
_ROOTS = ("input", "last_output", "outputs")
_MISSING = object()


def _to_text(value: Any) -> str:
    if value is None or value is _MISSING:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def resolve_path(path: str, state: dict[str, Any]) -> Any:
    parts = path.split(".")
    if parts[0] not in _ROOTS:
        return _MISSING
    current: Any = state.get(parts[0])
    rest = parts[1:]
    if parts[0] == "outputs" and rest:
        # node ids may contain dots? They don't per §8.1 (React Flow ids), so treat first segment as id.
        current = (current or {}).get(rest[0], _MISSING)
        rest = rest[1:]
    for part in rest:
        if isinstance(current, dict):
            current = current.get(part, _MISSING)
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return _MISSING
    return current


def render_template(template: str | None, state: dict[str, Any]) -> str:
    if not template:
        return ""
    return _PLACEHOLDER.sub(lambda m: _to_text(resolve_path(m.group(1), state)), template)


def render_value(value: Any, state: dict[str, Any]) -> Any:
    """Recursively render templates inside dicts/lists (used for tool ``input_mapping``).

    A string that is exactly one placeholder yields the raw (non-stringified) value.
    """
    if isinstance(value, str):
        m = _PLACEHOLDER.fullmatch(value.strip())
        if m:
            resolved = resolve_path(m.group(1), state)
            return None if resolved is _MISSING else resolved
        return render_template(value, state)
    if isinstance(value, dict):
        return {k: render_value(v, state) for k, v in value.items()}
    if isinstance(value, list):
        return [render_value(v, state) for v in value]
    return value
