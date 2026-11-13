"""Shared async Redis client for runtime/messaging (cancel flags, idempotency, tool results)."""

from __future__ import annotations

from typing import Any

from app.messaging.kafka import get_setting

_client: Any = None

CANCEL_KEY = "exec:cancel:{execution_id}"
EVENT_DONE_KEY = "evt:done:{event_id}"
TOOL_RESULT_KEY = "tool:result:{request_id}"
TOOL_RESULT_CHANNEL = "tool-results:{request_id}"


def get_redis():
    global _client
    if _client is None:
        import redis.asyncio as aioredis

        _client = aioredis.from_url(
            str(get_setting("REDIS_URL", "redis://redis:6379/0")), decode_responses=True
        )
    return _client


def set_redis(client: Any) -> None:
    """Test hook / DI."""
    global _client
    _client = client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
