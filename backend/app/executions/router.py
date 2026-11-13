"""Executions API (contract section 9) incl. SSE stream with replay + Redis pub/sub + heartbeat."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Header, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.audit.service import audit
from app.core.deps import OrgContext, PageDep, SessionDep, get_owned, org_select, paginate, require
from app.core.permissions import EXECUTION_RUN, RESOURCE_READ
from app.core.redis import get_redis
from app.core.schemas import ERROR_RESPONSES, Page
from app.database.models import Execution, ExecutionEvent
from app.database.session import async_session_factory
from app.executions.events import (
    TERMINAL_EVENTS,
    TERMINAL_STATUSES,
    append_event,
    channel,
    event_to_dict,
    set_status,
)
from app.executions.schemas import EventList, ExecutionEventOut, ExecutionOut, LogLine, LogList

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/executions", tags=["executions"], responses=ERROR_RESPONSES)
HEARTBEAT_SECONDS = 15.0
CANCEL_KEY = "exec:cancel:{execution_id}"


async def _events_after(session, execution_id: uuid.UUID, after: int) -> list[ExecutionEvent]:
    stmt = (
        select(ExecutionEvent)
        .where(ExecutionEvent.execution_id == execution_id, ExecutionEvent.sequence > after)
        .order_by(ExecutionEvent.sequence)
    )
    return list((await session.execute(stmt)).scalars().all())


@router.get("", response_model=Page[ExecutionOut], summary="List executions")
async def list_executions(
    session: SessionDep,
    params: PageDep,
    ctx: OrgContext = require(RESOURCE_READ),
    status: str | None = None,
    kind: Literal["agent", "agent_test", "workflow", "tool_test", "chat"] | None = None,
    resource_id: uuid.UUID | None = None,
) -> Page[ExecutionOut]:
    stmt = org_select(Execution, ctx)
    if status:
        stmt = stmt.where(Execution.status == status)
    if kind:
        stmt = stmt.where(Execution.kind == kind)
    if resource_id:
        stmt = stmt.where(Execution.resource_id == resource_id)
    rows, total = await paginate(session, stmt.order_by(Execution.created_at.desc()), params)
    return Page(
        items=[ExecutionOut.model_validate(r) for r in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.get("/{execution_id}", response_model=ExecutionOut, summary="Get execution")
async def get_execution(
    execution_id: uuid.UUID, session: SessionDep, ctx: OrgContext = require(RESOURCE_READ)
) -> Execution:
    return await get_owned(session, Execution, execution_id, ctx)


@router.get("/{execution_id}/events", response_model=EventList, summary="Execution events")
async def list_events(
    execution_id: uuid.UUID,
    session: SessionDep,
    ctx: OrgContext = require(RESOURCE_READ),
    after_sequence: Annotated[int, Query(ge=0)] = 0,
) -> EventList:
    await get_owned(session, Execution, execution_id, ctx)
    rows = await _events_after(session, execution_id, after_sequence)
    return EventList(items=[ExecutionEventOut.model_validate(r) for r in rows])


@router.get("/{execution_id}/logs", response_model=LogList, summary="Execution logs (derived from events)")
async def list_logs(
    execution_id: uuid.UUID, session: SessionDep, ctx: OrgContext = require(RESOURCE_READ)
) -> LogList:
    await get_owned(session, Execution, execution_id, ctx)
    rows = await _events_after(session, execution_id, 0)
    items = []
    for ev in rows:
        if ev.event_type == "log":
            items.append(
                LogLine(
                    timestamp=ev.created_at,
                    level=str(ev.payload.get("level", "info")),
                    message=str(ev.payload.get("message", "")),
                    node_id=ev.node_id,
                )
            )
        elif ev.event_type in {"node.failed", "execution.failed"}:
            items.append(
                LogLine(
                    timestamp=ev.created_at,
                    level="error",
                    message=str(ev.payload.get("error", ev.event_type)),
                    node_id=ev.node_id,
                )
            )
    return LogList(items=items)


def _sse(ev: dict) -> str:
    return f"id: {ev['sequence']}\nevent: {ev['event_type']}\ndata: {json.dumps(ev, default=str)}\n\n"


async def _stream(execution_id: uuid.UUID, after: int) -> AsyncIterator[str]:
    pubsub = get_redis().pubsub()
    await pubsub.subscribe(channel(execution_id))  # subscribe BEFORE replay so nothing is missed
    last = after
    try:
        async with async_session_factory() as session:
            replay = await _events_after(session, execution_id, after)
            ex = await session.get(Execution, execution_id)
            terminal = ex is not None and ex.status in TERMINAL_STATUSES
        for row in replay:
            ev = event_to_dict(row)
            last = ev["sequence"]
            yield _sse(ev)
            if ev["event_type"] in TERMINAL_EVENTS:
                return
        if terminal:
            return
        loop = asyncio.get_running_loop()
        next_ping = loop.time() + HEARTBEAT_SECONDS
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg and msg.get("type") == "message":
                ev = json.loads(msg["data"])
                if ev["sequence"] <= last:
                    continue
                last = ev["sequence"]
                yield _sse(ev)
                if ev["event_type"] in TERMINAL_EVENTS:
                    return
            if loop.time() >= next_ping:
                next_ping = loop.time() + HEARTBEAT_SECONDS
                yield ": ping\n\n"
    finally:
        try:
            await pubsub.unsubscribe(channel(execution_id))
            await pubsub.aclose()
        except Exception:  # noqa: BLE001,S110
            pass


@router.get(
    "/{execution_id}/stream",
    summary="SSE stream of execution events",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def stream_execution(
    execution_id: uuid.UUID,
    session: SessionDep,
    ctx: OrgContext = require(RESOURCE_READ),
    after_sequence: Annotated[int | None, Query(ge=0)] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    await get_owned(session, Execution, execution_id, ctx)
    after = after_sequence or 0
    if last_event_id and last_event_id.isdigit():
        after = max(after, int(last_event_id))
    return StreamingResponse(
        _stream(execution_id, after),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{execution_id}/cancel", response_model=ExecutionOut, summary="Cancel execution")
async def cancel_execution(
    execution_id: uuid.UUID, session: SessionDep, ctx: OrgContext = require(EXECUTION_RUN)
) -> Execution:
    ex = await get_owned(session, Execution, execution_id, ctx)
    if ex.status in TERMINAL_STATUSES:
        return ex
    try:
        await get_redis().set(CANCEL_KEY.format(execution_id=execution_id), "1", ex=86400)
    except Exception as exc:  # noqa: BLE001 - still mark queued executions cancelled in DB
        log.warning("execution.cancel_flag_failed", error=str(exc))
    if ex.status == "queued":
        await set_status(session, ex.id, "cancelled")
        await append_event(session, ex.id, "execution.cancelled", {"by": str(ctx.user_id)})
    audit(
        session,
        "execution.cancel_requested",
        organization_id=ctx.organization_id,
        actor_id=ctx.user_id,
        resource_type="execution",
        resource_id=ex.id,
    )
    await session.commit()
    await session.refresh(ex)
    return ex
