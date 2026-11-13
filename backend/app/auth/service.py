"""Token issuance / refresh rotation with reuse detection."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import audit
from app.auth.schemas import TokenPair
from app.core.config import settings
from app.core.errors import unauthenticated
from app.core.security import create_access_token, hash_token, new_refresh_token
from app.database.models import RefreshToken, User
from app.monitoring.metrics import AUTH_EVENTS


async def issue_tokens(
    session: AsyncSession, user: User, family_id: uuid.UUID | None = None
) -> tuple[TokenPair, RefreshToken]:
    raw = new_refresh_token()
    rt = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(raw),
        family_id=family_id or uuid.uuid4(),
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.REFRESH_TOKEN_TTL_SECONDS),
    )
    session.add(rt)
    await session.flush()
    pair = TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=raw,
        expires_in=settings.ACCESS_TOKEN_TTL_SECONDS,
    )
    return pair, rt


async def rotate_refresh(session: AsyncSession, raw: str) -> TokenPair:
    now = datetime.now(UTC)
    rt = (
        await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)).with_for_update()
        )
    ).scalar_one_or_none()
    if rt is None:
        raise unauthenticated("Invalid refresh token")
    if rt.revoked_at is not None:
        # Reuse of a rotated/revoked token → revoke entire family (possible theft).
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == rt.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        audit(
            session,
            "auth.refresh_reuse_detected",
            organization_id=None,
            actor_id=rt.user_id,
            resource_type="refresh_token_family",
            resource_id=rt.family_id,
        )
        AUTH_EVENTS.labels("refresh_reuse").inc()
        await session.commit()
        raise unauthenticated("Refresh token reuse detected; session revoked")
    if rt.expires_at <= now:
        raise unauthenticated("Refresh token expired", code="TOKEN_EXPIRED")
    user = await session.get(User, rt.user_id)
    if user is None or user.status != "active":
        raise unauthenticated("User not found or disabled")
    pair, new_rt = await issue_tokens(session, user, family_id=rt.family_id)
    rt.revoked_at = now
    rt.replaced_by_id = new_rt.id
    AUTH_EVENTS.labels("refresh").inc()
    await session.commit()
    return pair
