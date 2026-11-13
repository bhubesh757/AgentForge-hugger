"""Request-scoped context (request id / correlation id)."""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_SAFE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def get_request_id() -> str | None:
    return _request_id.get()


def set_request_id(value: str | None) -> str:
    rid = value if value and _SAFE.match(value) else str(uuid.uuid4())
    _request_id.set(rid)
    return rid
