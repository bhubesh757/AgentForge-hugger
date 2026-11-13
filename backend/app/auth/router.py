from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select

from app.audit.service import audit
from app.auth.schemas import LoginRequest, MembershipOut, MeOut, RefreshRequest, RegisterRequest, TokenPair
from app.auth.service import issue_tokens, rotate_refresh
from app.core.deps import CurrentUser, SessionDep
from app.core.errors import conflict, unauthenticated
from app.core.ratelimit import rate_limit
from app.core.schemas import ERROR_RESPONSES
from app.core.security import hash_password, hash_token, verify_password
from app.database.models import Membership, RefreshToken, User
from app.monitoring.metrics import AUTH_EVENTS
from app.organizations.service import create_organization

router = APIRouter(prefix="/auth", tags=["auth"], responses=ERROR_RESPONSES)


@router.post(
    "/register",
    response_model=TokenPair,
    status_code=201,
    summary="Register a user",
    dependencies=[Depends(rate_limit("register"))],
)
async def register(body: RegisterRequest, session: SessionDep) -> TokenPair:
    email = body.email.lower()
    if (await session.execute(select(User.id).where(User.email == email))).first():
        raise conflict("Email already registered")
    user = User(email=email, password_hash=hash_password(body.password), full_name=body.full_name)
    session.add(user)
    await session.flush()
    if body.organization_name:
        await create_organization(session, body.organization_name, user.id)
    audit(
        session,
        "auth.registered",
        organization_id=None,
        actor_id=user.id,
        resource_type="user",
        resource_id=user.id,
    )
    pair, _ = await issue_tokens(session, user)
    await session.commit()
    AUTH_EVENTS.labels("register").inc()
    return pair


@router.post(
    "/login",
    response_model=TokenPair,
    summary="Log in with email/password",
    dependencies=[Depends(rate_limit("login"))],
)
async def login(body: LoginRequest, session: SessionDep) -> TokenPair:
    user = (await session.execute(select(User).where(User.email == body.email.lower()))).scalar_one_or_none()
    if not verify_password(body.password, user.password_hash if user else None) or user is None:
        audit(
            session,
            "auth.login_failed",
            organization_id=None,
            actor_id=user.id if user else None,
            metadata={"email_domain": body.email.split("@")[-1]},
        )
        await session.commit()
        AUTH_EVENTS.labels("login_failed").inc()
        raise unauthenticated("Invalid email or password")
    if user.status != "active":
        raise unauthenticated("User disabled")
    user.last_login_at = datetime.now(UTC)
    pair, _ = await issue_tokens(session, user)
    audit(
        session,
        "auth.login",
        organization_id=None,
        actor_id=user.id,
        resource_type="user",
        resource_id=user.id,
    )
    await session.commit()
    AUTH_EVENTS.labels("login").inc()
    return pair


@router.post(
    "/refresh",
    response_model=TokenPair,
    summary="Rotate refresh token",
    dependencies=[Depends(rate_limit("refresh", 60))],
)
async def refresh(body: RefreshRequest, session: SessionDep) -> TokenPair:
    return await rotate_refresh(session, body.refresh_token)


@router.post("/logout", status_code=204, summary="Revoke a refresh token", response_class=Response)
async def logout(body: RefreshRequest, session: SessionDep) -> Response:
    rt = (
        await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(body.refresh_token))
        )
    ).scalar_one_or_none()
    if rt is not None and rt.revoked_at is None:
        rt.revoked_at = datetime.now(UTC)
        audit(session, "auth.logout", organization_id=None, actor_id=rt.user_id)
        await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=MeOut, summary="Current user with memberships")
async def me(user: CurrentUser, session: SessionDep) -> MeOut:
    rows = (await session.execute(select(Membership).where(Membership.user_id == user.id))).scalars().all()
    return MeOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        status=user.status,
        created_at=user.created_at,
        memberships=[
            MembershipOut(
                organization_id=m.organization_id,
                organization_name=m.organization.name,
                organization_slug=m.organization.slug,
                role=m.role.name,
            )  # type: ignore[arg-type]
            for m in rows
            if m.organization.status == "active"
        ],
    )
