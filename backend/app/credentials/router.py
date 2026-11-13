from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from app.audit.service import audit
from app.core.deps import OrgContext, PageDep, SessionDep, get_owned, org_select, paginate, require
from app.core.errors import conflict
from app.core.permissions import LLM_MANAGE, RESOURCE_READ
from app.core.schemas import ERROR_RESPONSES, ORMModel, Page
from app.core.security import key_hint
from app.credentials.cipher import get_cipher
from app.credentials.service import resolve_credential  # noqa: F401 - re-export
from app.database.models import Credential

router = APIRouter(prefix="/credentials", tags=["credentials"], responses=ERROR_RESPONSES)
Kind = Literal["api_key", "bearer_token", "basic_auth", "generic"]


class CredentialCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: Kind
    value: str = Field(min_length=1, max_length=10000)
    description: str | None = None


class CredentialRotate(BaseModel):
    value: str = Field(min_length=1, max_length=10000)


class CredentialOut(ORMModel):
    id: uuid.UUID
    name: str
    kind: str
    description: str
    key_hint: str
    created_at: datetime
    rotated_at: datetime | None


class ValidateOut(BaseModel):
    valid: bool
    message: str


@router.post("", response_model=CredentialOut, status_code=201, summary="Create credential (value encrypted)")
async def create_credential(
    body: CredentialCreate, session: SessionDep, ctx: OrgContext = require(LLM_MANAGE)
) -> Credential:
    if (await session.execute(org_select(Credential, ctx).where(Credential.name == body.name))).first():
        raise conflict("Credential name already exists")
    c = Credential(
        organization_id=ctx.organization_id,
        name=body.name,
        kind=body.kind,
        description=body.description or "",
        encrypted_value=get_cipher().encrypt(body.value),
        key_hint=key_hint(body.value),
        created_by=ctx.user_id,
    )
    session.add(c)
    await session.flush()
    audit(
        session,
        "credential.created",
        organization_id=ctx.organization_id,
        actor_id=ctx.user_id,
        resource_type="credential",
        resource_id=c.id,
        metadata={"kind": body.kind},
    )
    await session.commit()
    return c


@router.get("", response_model=Page[CredentialOut], summary="List credentials (no values)")
async def list_credentials(
    session: SessionDep, params: PageDep, ctx: OrgContext = require(RESOURCE_READ)
) -> Page[CredentialOut]:
    rows, total = await paginate(
        session, org_select(Credential, ctx).order_by(Credential.created_at.desc()), params
    )
    return Page(
        items=[CredentialOut.model_validate(r) for r in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post("/{credential_id}/validate", response_model=ValidateOut, summary="Format check")
async def validate_credential(
    credential_id: uuid.UUID, session: SessionDep, ctx: OrgContext = require(LLM_MANAGE)
) -> ValidateOut:
    c = await get_owned(session, Credential, credential_id, ctx)
    value = get_cipher().decrypt(c.encrypted_value)
    if c.kind == "basic_auth" and ":" not in value:
        return ValidateOut(valid=False, message="basic_auth value must be 'username:password'")
    if any(ch.isspace() for ch in value) and c.kind in {"api_key", "bearer_token"}:
        return ValidateOut(valid=False, message="Value must not contain whitespace")
    return ValidateOut(valid=True, message="Format OK")


@router.post("/{credential_id}/rotate", response_model=CredentialOut, summary="Rotate credential value")
async def rotate_credential(
    credential_id: uuid.UUID,
    body: CredentialRotate,
    session: SessionDep,
    ctx: OrgContext = require(LLM_MANAGE),
) -> Credential:
    c = await get_owned(session, Credential, credential_id, ctx)
    c.encrypted_value = get_cipher().encrypt(body.value)
    c.key_hint = key_hint(body.value)
    c.rotated_at = datetime.now(UTC)
    audit(
        session,
        "credential.rotated",
        organization_id=ctx.organization_id,
        actor_id=ctx.user_id,
        resource_type="credential",
        resource_id=c.id,
    )
    await session.commit()
    return c


@router.delete("/{credential_id}", status_code=204, response_class=Response, summary="Delete credential")
async def delete_credential(
    credential_id: uuid.UUID, session: SessionDep, ctx: OrgContext = require(LLM_MANAGE)
) -> Response:
    c = await get_owned(session, Credential, credential_id, ctx)
    await session.delete(c)
    audit(
        session,
        "credential.deleted",
        organization_id=ctx.organization_id,
        actor_id=ctx.user_id,
        resource_type="credential",
        resource_id=credential_id,
    )
    await session.commit()
    return Response(status_code=204)
