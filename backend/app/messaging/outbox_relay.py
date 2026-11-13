"""Transactional-outbox relay: polls ``outbox_events`` and publishes to Kafka (at-least-once).

Multiple API replicas are safe: rows are claimed with ``SELECT ... FOR UPDATE SKIP LOCKED``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import structlog

from app.messaging.kafka import EventEnvelope, create_producer

log = structlog.get_logger(__name__)

BATCH_SIZE = 100
POLL_INTERVAL_S = 0.5
MAX_BACKOFF_S = 30.0

_task: asyncio.Task | None = None
_stop: asyncio.Event | None = None


async def relay_once(session_factory, producer, batch_size: int = BATCH_SIZE) -> int:
    """Claim & publish one batch. Returns number published. Rows marked only after broker ack."""
    from sqlalchemy import select

    from app.database.models import OutboxEvent  # type: ignore[import-not-found]

    cols = OutboxEvent.__table__.columns.keys()
    published = 0
    failure: Exception | None = None
    async with session_factory() as session, session.begin():
        stmt = select(OutboxEvent).where(OutboxEvent.published_at.is_(None))
        if "created_at" in cols:
            stmt = stmt.order_by(OutboxEvent.created_at)
        stmt = stmt.limit(batch_size).with_for_update(skip_locked=True)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            try:
                env = EventEnvelope.model_validate(row.payload)
                await producer.send_and_wait(row.topic, value=env.to_bytes(), key=env.key)
            except Exception as exc:
                if "attempts" in cols:
                    row.attempts = (row.attempts or 0) + 1
                if "last_error" in cols:
                    row.last_error = str(exc)[:1000]
                log.warning("outbox.publish_failed", outbox_id=str(row.id), error=str(exc))
                failure = exc
                break  # commit progress so far (already-acked rows stay published)
            row.published_at = datetime.now(UTC)
            published += 1
    if failure is not None:
        raise failure
    return published


async def _run(stop: asyncio.Event, session_factory: Any = None, producer: Any = None) -> None:
    if session_factory is None:
        from app.database.session import async_session_factory  # type: ignore[import-not-found]

        session_factory = async_session_factory
    backoff = 1.0
    own_producer = producer is None
    while not stop.is_set():
        try:
            if producer is None:
                producer = create_producer()
                await producer.start()
            n = await relay_once(session_factory, producer)
            backoff = 1.0
            if n == 0:
                await _sleep_or_stop(stop, POLL_INTERVAL_S)
        except asyncio.CancelledError:
            break
        except Exception as exc:  # noqa: BLE001 - relay must survive broker/DB outages
            log.warning("outbox.relay_error", error=str(exc), retry_in_s=backoff)
            if own_producer and producer is not None:
                try:
                    await producer.stop()
                except Exception:  # noqa: BLE001, S110
                    pass
                producer = None
            await _sleep_or_stop(stop, backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_S)
    if own_producer and producer is not None:
        await producer.stop()


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass


async def start_relay() -> None:
    global _task, _stop
    if _task is not None and not _task.done():
        return
    _stop = asyncio.Event()
    _task = asyncio.create_task(_run(_stop), name="outbox-relay")
    log.info("outbox.relay_started")


async def stop_relay() -> None:
    global _task, _stop
    if _stop is not None:
        _stop.set()
    if _task is not None:
        try:
            await asyncio.wait_for(_task, timeout=10)
        except (TimeoutError, asyncio.CancelledError):
            _task.cancel()
    _task, _stop = None, None
    log.info("outbox.relay_stopped")
