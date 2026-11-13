"""Credential helpers shared with the runtime (contract section 17)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.credentials.cipher import get_cipher
from app.database.models import Credential


async def resolve_credential(
    session: AsyncSession, organization_id: uuid.UUID, credential_id: uuid.UUID | str
) -> str | None:
    """Decrypt a `credential_ref` scoped to the org. Returns None if missing / other tenant / malformed id."""
    try:
        cid = credential_id if isinstance(credential_id, uuid.UUID) else uuid.UUID(str(credential_id))
    except ValueError:
        return None
    row = (
        await session.execute(
            select(Credential).where(Credential.id == cid, Credential.organization_id == organization_id)
        )
    ).scalar_one_or_none()
    return get_cipher().decrypt(row.encrypted_value) if row else None
