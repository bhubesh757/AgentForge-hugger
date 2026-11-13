"""Execution dispatch: transactional outbox (kafka mode) or in-process background task (inline mode)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import structlog

from app.messaging.kafka import EventEnvelope, get_setting
from app.messaging.topics import request_topic_for, resource_type_for

log = structlog.get_logger(__name__)
_background_tasks: set[asyncio.Task] = set()

INLINE_UNSUPPORTED_ERROR = "sandbox requires tool-worker"


def _target_type(execution: Any) -> str | None:
    for attr in ("target_type", "resource_type"):
        val = getattr(execution, attr, None)
        if val:
            return str(val)
    inp = getattr(execution, "input", None)
    if isinstance(inp, dict) and inp.get("target_type"):
        return str(inp["target_type"])
    return None


def build_request_envelope(execution: Any) -> tuple[str, EventEnvelope]:
    kind = str(execution.kind)
    target = _target_type(execution)
    topic = request_topic_for(kind, target)
    env = EventEnvelope(
        event_type=topic,
        organization_id=execution.organization_id,
        execution_id=execution.id,
        correlation_id=getattr(execution, "correlation_id", None) or uuid.uuid4(),
        resource_type=resource_type_for(kind, target),
        resource_id=execution.resource_id,
        resource_version=int(getattr(execution, "resource_version", 0) or 0),
        kind=kind,
        payload={"target_type": target} if target else {},
    )
    return topic, env


def model_kwargs(model: Any, **values: Any) -> dict[str, Any]:
    """Keep only kwargs that are mapped columns on ``model`` (tolerates schema drift)."""
    cols = set(model.__table__.columns.keys())
    return {k: v for k, v in values.items() if k in cols}


def build_outbox_row(execution: Any, topic: str, env: EventEnvelope):
    from app.database.models import OutboxEvent  # type: ignore[import-not-found]

    payload = env.model_dump(mode="json")
    return OutboxEvent(**model_kwargs(
        OutboxEvent,
        id=uuid.uuid4(),
        topic=topic,
        key=str(execution.id),
        event_id=env.event_id,
        event_type=env.event_type,
        aggregate_id=execution.id,
        execution_id=execution.id,
        organization_id=execution.organization_id,
        payload=payload,
        attempts=0,
    ))


async def enqueue_execution(session, execution: Any) -> None:
    """Persist dispatch intent in the caller's transaction (caller commits)."""
    mode = str(get_setting("EXECUTION_DISPATCH", "kafka")).lower()
    topic, env = build_request_envelope(execution)
    if mode != "inline":
        session.add(build_outbox_row(execution, topic, env))
        await session.flush()
        log.info("execution.enqueued", execution_id=str(execution.id), topic=topic, mode="kafka")
        return

    if str(execution.kind) == "tool_test":
        from app.executions.events import append_event, set_status  # type: ignore[import-not-found]

        await set_status(session, execution.id, "failed", error=INLINE_UNSUPPORTED_ERROR)
        await append_event(session, execution.id, "execution.failed", {"error": INLINE_UNSUPPORTED_ERROR})
        return

    execution_id = execution.id
    _schedule_after_commit(session, execution_id)
    log.info("execution.enqueued", execution_id=str(execution_id), mode="inline")


def _schedule_after_commit(session, execution_id: uuid.UUID) -> None:
    from sqlalchemy import event

    loop = asyncio.get_running_loop()
    sync_session = getattr(session, "sync_session", session)

    def _after_commit(_sess) -> None:
        loop.call_soon_threadsafe(_spawn, execution_id)

    event.listen(sync_session, "after_commit", _after_commit, once=True)


def _spawn(execution_id: uuid.UUID) -> None:
    from app.orchestrator.runtime import run_execution

    task = asyncio.get_running_loop().create_task(run_execution(execution_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
