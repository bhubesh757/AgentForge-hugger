"""Audit log writer. Callers commit. Never put secrets in metadata."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.request_context import get_request_id
from app.database.models import AuditLog


def audit(
    session: AsyncSession,
    action: str,
    *,
    organization_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    resource_type: str | None = None,
    resource_id: Any = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditLog(
            organization_id=organization_id,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            metadata_=metadata or {},
            request_id=get_request_id(),
        )
    )
