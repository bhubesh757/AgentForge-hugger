"""Execution event log + status transitions (contract sections 9, 13, 17).

`append_event` inserts the next-sequence row; after the caller commits, the event JSON is PUBLISHed to
Redis channel `execution-events:<execution_id>` so SSE streams receive it live.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import event as sa_event
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Execution, ExecutionEvent

log = structlog.get_logger(__name__)
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
TERMINAL_EVENTS = frozenset({"execution.completed", "execution.failed", "execution.cancelled"})
_pending_tasks: set[asyncio.Task[Any]] = set()


def channel(execution_id: uuid.UUID | str) -> str:
    return f"execution-events:{execution_id}"


def event_to_dict(ev: ExecutionEvent) -> dict[str, Any]:
    return {
        "id": str(ev.id),
        "execution_id": str(ev.execution_id),
        "sequence": ev.sequence,
        "event_type": ev.event_type,
        "node_id": ev.node_id,
        "payload": ev.payload or {},
        "created_at": (ev.created_at or datetime.now(UTC)).isoformat(),
    }


async def _publish(messages: list[tuple[str, str]]) -> None:
    from app.core.redis import get_redis

    try:
        r = get_redis()
        for ch, data in messages:
            await r.publish(ch, data)
    except Exception as exc:  # noqa: BLE001 - live push is best-effort; DB is source of truth
        log.warning("execution_event.publish_failed", error=str(exc))


def _queue_publish(session: AsyncSession, ch: str, data: str) -> None:
    sync = session.sync_session
    pending: list[tuple[str, str]] | None = sync.info.get("_exec_pub")
    if pending is None:
        pending = sync.info["_exec_pub"] = []
        loop = asyncio.get_running_loop()

        def _after_commit(sess: Any) -> None:
            msgs = sess.info.pop("_exec_pub", [])
            if msgs:
                task = loop.create_task(_publish(msgs))
                _pending_tasks.add(task)
                task.add_done_callback(_pending_tasks.discard)

        def _after_rollback(sess: Any) -> None:
            sess.info.pop("_exec_pub", None)

        sa_event.listen(sync, "after_commit", _after_commit, once=True)
        sa_event.listen(sync, "after_soft_rollback", _after_rollback, once=True)
    pending.append((ch, data))


async def append_event(
    session: AsyncSession,
    execution_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
    node_id: str | None = None,
) -> ExecutionEvent:
    execution = await session.get(Execution, execution_id, with_for_update=True)
    if execution is None:
        raise LookupError(f"execution {execution_id} not found")
    seq = (
        await session.execute(
            select(func.coalesce(func.max(ExecutionEvent.sequence), 0)).where(
                ExecutionEvent.execution_id == execution_id
            )
        )
    ).scalar_one()
    ev = ExecutionEvent(
        id=uuid.uuid4(),
        organization_id=execution.organization_id,
        execution_id=execution_id,
        sequence=int(seq) + 1,
        event_type=event_type,
        node_id=node_id,
        payload=payload or {},
        created_at=datetime.now(UTC),
    )
    session.add(ev)
    await session.flush()
    _queue_publish(session, channel(execution_id), json.dumps(event_to_dict(ev), default=str))
    return ev


async def set_status(
    session: AsyncSession,
    execution_id: uuid.UUID,
    status: str,
    *,
    output: Any = None,
    error: str | None = None,
) -> None:
    execution = await session.get(Execution, execution_id)
    if execution is None:
        raise LookupError(f"execution {execution_id} not found")
    now = datetime.now(UTC)
    execution.status = status
    if status == "running" and execution.started_at is None:
        execution.started_at = now
    if status in TERMINAL_STATUSES:
        execution.finished_at = now
        start = execution.started_at or execution.created_at or now
        execution.duration_ms = max(0, int((now - start).total_seconds() * 1000))
    if output is not None:
        execution.output = output
    if error is not None:
        execution.error = error
    await session.flush()
