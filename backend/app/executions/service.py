"""Create + dispatch executions (used by agents/tools/workflows/chat routers)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import OrgContext
from app.core.request_context import get_request_id
from app.database.models import Execution
from app.executions.events import append_event
from app.monitoring.metrics import EXECUTIONS_CREATED


async def create_execution(
    session: AsyncSession,
    ctx: OrgContext,
    *,
    kind: str,
    resource_id: uuid.UUID,
    resource_version: int,
    input: Any,
) -> Execution:
    """Insert a queued execution, its `execution.queued` event and the dispatch intent, then commit."""
    from app.messaging.dispatch import enqueue_execution  # lazy: owned by Agent 3

    ex = Execution(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        kind=kind,
        status="queued",
        resource_id=resource_id,
        resource_version=resource_version,
        input=input,
        correlation_id=get_request_id() or str(uuid.uuid4()),
        created_by=ctx.user_id,
    )
    session.add(ex)
    await session.flush()
    await append_event(session, ex.id, "execution.queued", {"kind": kind})
    await enqueue_execution(session, ex)
    await session.commit()
    await session.refresh(ex)
    EXECUTIONS_CREATED.labels(kind=kind).inc()
    return ex
