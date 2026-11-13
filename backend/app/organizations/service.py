"""Organization helpers."""

from __future__ import annotations

import re
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import audit
from app.core.errors import conflict
from app.database.models import Membership, Organization, Role


def slugify(value: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return s[:80] or "org"


async def role_id(session: AsyncSession, name: str) -> uuid.UUID:
    return (await session.execute(select(Role.id).where(Role.name == name))).scalar_one()


async def create_organization(
    session: AsyncSession, name: str, owner_id: uuid.UUID, slug: str | None = None
) -> Organization:
    base = slugify(slug or name)
    if slug:
        if (await session.execute(select(Organization.id).where(Organization.slug == base))).first():
            raise conflict("Organization slug already in use")
        final = base
    else:
        final = base
        while (await session.execute(select(Organization.id).where(Organization.slug == final))).first():
            final = f"{base}-{secrets.token_hex(3)}"
    org = Organization(name=name, slug=final, status="active")
    session.add(org)
    await session.flush()
    session.add(Membership(organization_id=org.id, user_id=owner_id, role_id=await role_id(session, "owner")))
    audit(
        session,
        "organization.created",
        organization_id=org.id,
        actor_id=owner_id,
        resource_type="organization",
        resource_id=org.id,
    )
    return org
