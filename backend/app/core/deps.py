"""Shared FastAPI dependencies: auth, tenant context (fail-closed), RBAC, pagination."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated, Any, TypeVar

from fastapi import Depends, Header, Path, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, forbidden, not_found, unauthenticated
from app.core.permissions import ROLE_PERMISSIONS
from app.core.security import decode_access_token
from app.database.models import Membership, User
from app.database.session import get_session

SessionDep = Annotated[AsyncSession, Depends(get_session)]
_bearer = HTTPBearer(auto_error=False)
T = TypeVar("T")


async def get_current_user(
    session: SessionDep,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise unauthenticated()
    user_id = decode_access_token(creds.credentials)
    user = await session.get(User, user_id)
    if user is None or user.status != "active":
        raise unauthenticated("User not found or disabled")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


@dataclass(frozen=True)
class OrgContext:
    organization_id: uuid.UUID
    user: User
    role: str

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id

    def has(self, permission: str) -> bool:
        return permission in ROLE_PERMISSIONS.get(self.role, frozenset())

    def require(self, permission: str) -> None:
        if not self.has(permission):
            raise forbidden(f"Missing permission: {permission}")


async def _membership_ctx(session: AsyncSession, user: User, org_id: uuid.UUID) -> OrgContext:
    m = (
        await session.execute(
            select(Membership).where(Membership.organization_id == org_id, Membership.user_id == user.id)
        )
    ).scalar_one_or_none()
    if m is None or m.organization.status != "active":
        raise AppError(403, "ORG_FORBIDDEN", "Not a member of this organization")
    return OrgContext(organization_id=org_id, user=user, role=m.role.name)


async def get_org_context(
    session: SessionDep,
    user: CurrentUser,
    x_organization_id: Annotated[str | None, Header(alias="X-Organization-ID")] = None,
) -> OrgContext:
    if not x_organization_id:
        raise AppError(400, "ORG_HEADER_REQUIRED", "X-Organization-ID header is required")
    try:
        org_id = uuid.UUID(x_organization_id)
    except ValueError as exc:
        raise AppError(403, "ORG_FORBIDDEN", "Not a member of this organization") from exc
    return await _membership_ctx(session, user, org_id)


async def get_path_org_context(
    session: SessionDep, user: CurrentUser, organization_id: Annotated[uuid.UUID, Path()]
) -> OrgContext:
    return await _membership_ctx(session, user, organization_id)


Org = Annotated[OrgContext, Depends(get_org_context)]
PathOrg = Annotated[OrgContext, Depends(get_path_org_context)]


def require(permission: str):
    async def _dep(ctx: Org) -> OrgContext:
        ctx.require(permission)
        return ctx

    return Depends(_dep)


@dataclass
class PageParams:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def page_params(
    page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 20
) -> PageParams:
    return PageParams(page, page_size)


PageDep = Annotated[PageParams, Depends(page_params)]


async def paginate(session: AsyncSession, stmt: Select[Any], params: PageParams) -> tuple[list[Any], int]:
    total = (
        await session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    ).scalar_one()
    rows = (await session.execute(stmt.offset(params.offset).limit(params.page_size))).scalars().all()
    return list(rows), int(total)


async def get_owned[T](session: AsyncSession, model: type[T], obj_id: uuid.UUID, ctx: OrgContext) -> T:
    """Org-filtered fetch. Missing OR other-tenant → 404 (no existence leak)."""
    stmt = select(model).where(model.id == obj_id, model.organization_id == ctx.organization_id)  # type: ignore[attr-defined]
    obj = (await session.execute(stmt)).scalar_one_or_none()
    if obj is None:
        raise not_found(getattr(model, "__name__", "Resource"))
    return obj


def org_select[T](model: type[T], ctx: OrgContext) -> Select[tuple[T]]:
    return select(model).where(model.organization_id == ctx.organization_id)  # type: ignore[attr-defined]
