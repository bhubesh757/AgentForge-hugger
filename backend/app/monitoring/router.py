"""Health / readiness / metrics / org summary (contract section 12)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import func, select, text

from app.core.config import settings
from app.core.deps import OrgContext, SessionDep, require
from app.core.permissions import RESOURCE_READ
from app.core.redis import get_redis
from app.database.models import Agent, Execution, LLMProvider, Tool, Workflow
from app.database.session import async_session_factory
from app.llm.router import LLMProviderOut

VERSION = "1.0.1"
health_router = APIRouter(tags=["monitoring"])
router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@health_router.get("/health", summary="Liveness")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": VERSION, "api_version": "v1"}


async def _check_kafka() -> str:
    if settings.EXECUTION_DISPATCH != "kafka":
        return "disabled"
    host, _, port = settings.KAFKA_BOOTSTRAP_SERVERS.split(",")[0].rpartition(":")
    try:
        _, w = await asyncio.wait_for(asyncio.open_connection(host, int(port)), timeout=2)
        w.close()
        return "ok"
    except Exception:  # noqa: BLE001
        return "error"


@health_router.get("/ready", summary="Readiness (database, redis, kafka)")
async def ready() -> JSONResponse:
    checks: dict[str, str] = {}
    try:
        async with async_session_factory() as s:
            await asyncio.wait_for(s.execute(text("SELECT 1")), timeout=3)
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001
        checks["database"] = "error"
    try:
        await asyncio.wait_for(get_redis().ping(), timeout=3)
        checks["redis"] = "ok"
    except Exception:  # noqa: BLE001
        checks["redis"] = "error"
    checks["kafka"] = await _check_kafka()
    ok = all(v in {"ok", "disabled"} for v in checks.values())
    return JSONResponse(
        {"status": "ready" if ok else "not_ready", "checks": checks}, status_code=200 if ok else 503
    )


@health_router.get("/metrics", summary="Prometheus metrics", response_class=Response)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/summary", summary="Org dashboard summary")
async def summary(session: SessionDep, ctx: OrgContext = require(RESOURCE_READ)) -> dict:
    org = ctx.organization_id
    since = datetime.now(UTC) - timedelta(hours=24)
    recent = (Execution.organization_id == org, Execution.created_at >= since)
    by_status = dict(
        (
            await session.execute(
                select(Execution.status, func.count()).where(*recent).group_by(Execution.status)
            )
        ).all()
    )
    by_kind = dict(
        (
            await session.execute(
                select(Execution.kind, func.count()).where(*recent).group_by(Execution.kind)
            )
        ).all()
    )
    avg = (await session.execute(select(func.avg(Execution.duration_ms)).where(*recent))).scalar()

    async def count(model) -> int:
        return int(
            (
                await session.execute(
                    select(func.count()).select_from(model).where(model.organization_id == org)
                )
            ).scalar_one()
        )

    provider = (
        await session.execute(
            select(LLMProvider).where(LLMProvider.organization_id == org, LLMProvider.is_default.is_(True))
        )
    ).scalar_one_or_none()
    return {
        "executions_24h": sum(by_status.values()),
        "succeeded_24h": by_status.get("succeeded", 0),
        "failed_24h": by_status.get("failed", 0),
        "avg_duration_ms": float(avg) if avg is not None else None,
        "by_status": by_status,
        "by_kind": by_kind,
        "agents": await count(Agent),
        "tools": await count(Tool),
        "workflows": await count(Workflow),
        "active_provider": LLMProviderOut.model_validate(provider).model_dump(mode="json")
        if provider
        else None,
    }
