"""Basic fixed-window rate limiting backed by Redis (auth endpoints)."""

from __future__ import annotations

import structlog
from fastapi import Request

from app.core.config import settings
from app.core.errors import AppError
from app.core.redis import get_redis

log = structlog.get_logger(__name__)


def rate_limit(scope: str, per_minute: int | None = None):
    async def _dep(request: Request) -> None:
        limit = per_minute or settings.AUTH_RATE_LIMIT_PER_MINUTE
        ip = request.client.host if request.client else "unknown"
        key = f"rl:{scope}:{ip}"
        try:
            r = get_redis()
            count = await r.incr(key)
            if count == 1:
                await r.expire(key, 60)
        except Exception as exc:  # fail-open: Redis outage must not lock users out (documented)
            log.warning("rate_limit_unavailable", error=type(exc).__name__)
            return
        if count > limit:
            raise AppError(429, "RATE_LIMITED", "Too many requests, try again later", {"retry_after": 60})

    return _dep
