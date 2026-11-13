from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import Field
from sqlalchemy import select

from app.core.deps import OrgContext, PageDep, SessionDep, paginate, require
from app.core.permissions import ORG_MANAGE
from app.core.schemas import ERROR_RESPONSES, ORMModel, Page
from app.database.models import AuditLog

router = APIRouter(prefix="/audit-logs", tags=["audit"], responses=ERROR_RESPONSES)


class AuditLogOut(ORMModel):
    id: uuid.UUID
    actor_id: uuid.UUID | None
    action: str
    resource_type: str | None
    resource_id: str | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    created_at: datetime


@router.get("", response_model=Page[AuditLogOut], summary="List audit logs (org.manage)")
async def list_audit_logs(
    session: SessionDep, params: PageDep, ctx: OrgContext = require(ORG_MANAGE)
) -> Page[AuditLogOut]:
    stmt = (
        select(AuditLog)
        .where(AuditLog.organization_id == ctx.organization_id)
        .order_by(AuditLog.created_at.desc())
    )
    rows, total = await paginate(session, stmt, params)
    return Page(
        items=[AuditLogOut.model_validate(r) for r in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )
