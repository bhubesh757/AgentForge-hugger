from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from app.audit.service import audit
from app.auth.schemas import RoleName
from app.core.deps import CurrentUser, PageDep, PathOrg, SessionDep, paginate
from app.core.errors import conflict, forbidden, not_found
from app.core.permissions import ORG_MANAGE
from app.core.schemas import ERROR_RESPONSES, ORMModel, Page
from app.database.models import Membership, Organization, Role, User
from app.organizations.service import create_organization, role_id

router = APIRouter(prefix="/organizations", tags=["organizations"], responses=ERROR_RESPONSES)


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)


class OrganizationOut(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    status: str
    created_at: datetime


class OrganizationWithRole(OrganizationOut):
    role: RoleName


class MemberCreate(BaseModel):
    email: EmailStr
    role: RoleName


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str
    role: RoleName
    joined_at: datetime


def _member(m: Membership) -> MemberOut:
    return MemberOut(
        user_id=m.user_id,
        email=m.user.email,
        full_name=m.user.full_name,
        role=m.role.name,
        joined_at=m.created_at,
    )  # type: ignore[arg-type]


@router.post(
    "", response_model=OrganizationOut, status_code=201, summary="Create organization (caller = owner)"
)
async def create_org(body: OrganizationCreate, user: CurrentUser, session: SessionDep) -> Organization:
    org = await create_organization(session, body.name, user.id, body.slug)
    await session.commit()
    return org


@router.get("", response_model=Page[OrganizationWithRole], summary="List caller's organizations")
async def list_orgs(user: CurrentUser, session: SessionDep, params: PageDep) -> Page[OrganizationWithRole]:
    stmt = (
        select(Membership)
        .join(Organization, Organization.id == Membership.organization_id)
        .where(Membership.user_id == user.id, Organization.status == "active")
        .order_by(Organization.created_at)
    )
    rows, total = await paginate(session, stmt, params)
    items = [
        OrganizationWithRole(**OrganizationOut.model_validate(m.organization).model_dump(), role=m.role.name)
        for m in rows
    ]
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)


@router.get("/{organization_id}", response_model=OrganizationOut, summary="Get organization")
async def get_org(ctx: PathOrg, session: SessionDep) -> Organization | None:
    return await session.get(Organization, ctx.organization_id)


@router.put("/{organization_id}", response_model=OrganizationOut, summary="Update organization")
async def update_org(body: OrganizationUpdate, ctx: PathOrg, session: SessionDep) -> Organization:
    ctx.require(ORG_MANAGE)
    org = await session.get(Organization, ctx.organization_id)
    assert org is not None
    if body.name:
        org.name = body.name
    audit(
        session,
        "organization.updated",
        organization_id=org.id,
        actor_id=ctx.user_id,
        resource_type="organization",
        resource_id=org.id,
    )
    await session.commit()
    return org


@router.get("/{organization_id}/members", response_model=Page[MemberOut], summary="List members")
async def list_members(ctx: PathOrg, session: SessionDep, params: PageDep) -> Page[MemberOut]:
    stmt = (
        select(Membership)
        .where(Membership.organization_id == ctx.organization_id)
        .order_by(Membership.created_at)
    )
    rows, total = await paginate(session, stmt, params)
    return Page(items=[_member(m) for m in rows], total=total, page=params.page, page_size=params.page_size)


@router.post("/{organization_id}/members", response_model=MemberOut, status_code=201, summary="Add member")
async def add_member(body: MemberCreate, ctx: PathOrg, session: SessionDep) -> MemberOut:
    ctx.require(ORG_MANAGE)
    if body.role == "owner" and ctx.role != "owner":
        raise forbidden("Only owners can grant the owner role")
    target = (
        await session.execute(select(User).where(User.email == body.email.lower()))
    ).scalar_one_or_none()
    if target is None:
        raise not_found("User")
    exists = (
        await session.execute(
            select(Membership.id).where(
                Membership.organization_id == ctx.organization_id, Membership.user_id == target.id
            )
        )
    ).first()
    if exists:
        raise conflict("User is already a member")
    m = Membership(
        organization_id=ctx.organization_id, user_id=target.id, role_id=await role_id(session, body.role)
    )
    session.add(m)
    audit(
        session,
        "membership.added",
        organization_id=ctx.organization_id,
        actor_id=ctx.user_id,
        resource_type="user",
        resource_id=target.id,
        metadata={"role": body.role},
    )
    await session.commit()
    m = (await session.execute(select(Membership).where(Membership.id == m.id))).scalar_one()
    return _member(m)


@router.delete(
    "/{organization_id}/members/{user_id}", status_code=204, response_class=Response, summary="Remove member"
)
async def remove_member(user_id: uuid.UUID, ctx: PathOrg, session: SessionDep) -> Response:
    ctx.require(ORG_MANAGE)
    m = (
        await session.execute(
            select(Membership).where(
                Membership.organization_id == ctx.organization_id, Membership.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if m is None:
        raise not_found("Member")
    if m.role.name == "owner":
        if ctx.role != "owner":
            raise forbidden("Only owners can remove owners")
        owners = (
            await session.execute(
                select(func.count())
                .select_from(Membership)
                .join(Role)
                .where(Membership.organization_id == ctx.organization_id, Role.name == "owner")
            )
        ).scalar_one()
        if owners <= 1:
            raise conflict("Cannot remove the last owner")
    await session.delete(m)
    audit(
        session,
        "membership.removed",
        organization_id=ctx.organization_id,
        actor_id=ctx.user_id,
        resource_type="user",
        resource_id=user_id,
    )
    await session.commit()
    return Response(status_code=204)
