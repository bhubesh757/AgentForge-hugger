"""LLM providers (BYOK) router — contract section 4. API keys are never returned."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field
from sqlalchemy import update

from app.audit.service import audit
from app.core.deps import OrgContext, PageDep, SessionDep, get_owned, org_select, paginate, require
from app.core.errors import AppError
from app.core.permissions import LLM_MANAGE, RESOURCE_READ
from app.core.schemas import ERROR_RESPONSES, ORMModel, Page
from app.core.security import key_hint
from app.credentials.cipher import get_cipher
from app.database.models import LLMProvider
from app.llm.manager import provider_impl

router = APIRouter(prefix="/llm/providers", tags=["llm"], responses=ERROR_RESPONSES)


class ConnectProvider(BaseModel):
    provider: Literal["gemini", "azure_openai"]
    name: str | None = Field(default=None, max_length=200)
    api_key: str = Field(min_length=1, max_length=4096)
    endpoint: str | None = None
    deployment_name: str | None = None
    api_version: str | None = None
    default_model: str | None = None


class ActivateBody(BaseModel):
    default_model: str | None = None


class LLMProviderOut(ORMModel):
    id: uuid.UUID
    provider: str
    name: str
    status: str
    is_default: bool
    default_model: str | None
    key_hint: str
    config: dict[str, Any]
    last_validated_at: datetime | None
    created_at: datetime


class ValidateResult(BaseModel):
    valid: bool
    message: str
    provider: LLMProviderOut


class ModelInfo(BaseModel):
    id: str
    display_name: str


class ModelsOut(BaseModel):
    models: list[ModelInfo]


def _key(p: LLMProvider) -> str:
    return get_cipher().decrypt(p.encrypted_api_key)


async def _run_validation(p: LLMProvider) -> tuple[bool, str]:
    try:
        outcome = await provider_impl(p.provider, _key(p)).validate(_key(p), p.config or {})
        ok, msg = outcome.valid, outcome.message
    except Exception as exc:  # noqa: BLE001 - provider SDK errors must not leak keys
        ok, msg = False, f"Validation failed: {type(exc).__name__}"
    p.last_validated_at = datetime.now(UTC)
    if ok:
        p.status = "active" if p.is_default else "valid"
    else:
        p.status = "invalid"
        p.is_default = False
    return ok, msg


@router.get("", response_model=Page[LLMProviderOut], summary="List providers")
async def list_providers(
    session: SessionDep, params: PageDep, ctx: OrgContext = require(RESOURCE_READ)
) -> Page[LLMProviderOut]:
    rows, total = await paginate(
        session, org_select(LLMProvider, ctx).order_by(LLMProvider.created_at.desc()), params
    )
    return Page(
        items=[LLMProviderOut.model_validate(r) for r in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post("/connect", response_model=LLMProviderOut, status_code=201, summary="Connect a BYOK provider")
async def connect_provider(
    body: ConnectProvider, session: SessionDep, ctx: OrgContext = require(LLM_MANAGE)
) -> LLMProvider:
    config: dict[str, Any] = {}
    if body.provider == "azure_openai":
        missing = [f for f in ("endpoint", "deployment_name", "api_version") if not getattr(body, f)]
        if missing:
            raise AppError(422, "VALIDATION_ERROR", "Missing Azure OpenAI fields", {"missing": missing})
        config = {
            "endpoint": body.endpoint,
            "deployment_name": body.deployment_name,
            "api_version": body.api_version,
        }
    p = LLMProvider(
        organization_id=ctx.organization_id,
        provider=body.provider,
        name=body.name or body.provider,
        status="pending_validation",
        is_default=False,
        default_model=body.default_model,
        encrypted_api_key=get_cipher().encrypt(body.api_key),
        key_hint=key_hint(body.api_key),
        config=config,
        created_by=ctx.user_id,
    )
    session.add(p)
    await session.flush()
    ok, _ = await _run_validation(p)
    audit(
        session,
        "llm_provider.connected",
        organization_id=ctx.organization_id,
        actor_id=ctx.user_id,
        resource_type="llm_provider",
        resource_id=p.id,
        metadata={"provider": body.provider, "valid": ok},
    )
    await session.commit()
    await session.refresh(p)
    return p


@router.post("/{provider_id}/validate", response_model=ValidateResult, summary="Re-validate provider key")
async def validate_provider(
    provider_id: uuid.UUID, session: SessionDep, ctx: OrgContext = require(LLM_MANAGE)
) -> ValidateResult:
    p = await get_owned(session, LLMProvider, provider_id, ctx)
    ok, msg = await _run_validation(p)
    await session.commit()
    await session.refresh(p)
    return ValidateResult(valid=ok, message=msg, provider=LLMProviderOut.model_validate(p))


@router.get("/{provider_id}/models", response_model=ModelsOut, summary="List models for provider")
async def list_models(
    provider_id: uuid.UUID, session: SessionDep, ctx: OrgContext = require(RESOURCE_READ)
) -> ModelsOut:
    p = await get_owned(session, LLMProvider, provider_id, ctx)
    try:
        models = await provider_impl(p.provider, _key(p)).list_models(_key(p), p.config or {})
    except Exception as exc:  # noqa: BLE001
        raise AppError(502, "PROVIDER_ERROR", f"Could not list models: {type(exc).__name__}") from exc
    return ModelsOut(models=[ModelInfo(**m) for m in models])


@router.post("/{provider_id}/activate", response_model=LLMProviderOut, summary="Make org default provider")
async def activate_provider(
    provider_id: uuid.UUID,
    session: SessionDep,
    body: ActivateBody | None = None,
    ctx: OrgContext = require(LLM_MANAGE),
) -> LLMProvider:
    p = await get_owned(session, LLMProvider, provider_id, ctx)
    if p.status not in {"valid", "active", "inactive"} or p.last_validated_at is None:
        raise AppError(422, "VALIDATION_ERROR", "Provider must be validated before activation")
    await session.execute(
        update(LLMProvider)
        .where(
            LLMProvider.organization_id == ctx.organization_id,
            LLMProvider.id != p.id,
            LLMProvider.is_default.is_(True),
        )
        .values(is_default=False, status="valid")
    )
    p.is_default, p.status = True, "active"
    if body and body.default_model:
        p.default_model = body.default_model
    audit(
        session,
        "llm_provider.activated",
        organization_id=ctx.organization_id,
        actor_id=ctx.user_id,
        resource_type="llm_provider",
        resource_id=p.id,
    )
    await session.commit()
    await session.refresh(p)
    return p


@router.post("/{provider_id}/deactivate", response_model=LLMProviderOut, summary="Deactivate provider")
async def deactivate_provider(
    provider_id: uuid.UUID, session: SessionDep, ctx: OrgContext = require(LLM_MANAGE)
) -> LLMProvider:
    p = await get_owned(session, LLMProvider, provider_id, ctx)
    p.is_default, p.status = False, "inactive"
    audit(
        session,
        "llm_provider.deactivated",
        organization_id=ctx.organization_id,
        actor_id=ctx.user_id,
        resource_type="llm_provider",
        resource_id=p.id,
    )
    await session.commit()
    await session.refresh(p)
    return p


@router.delete("/{provider_id}", status_code=204, response_class=Response, summary="Delete provider")
async def delete_provider(
    provider_id: uuid.UUID, session: SessionDep, ctx: OrgContext = require(LLM_MANAGE)
) -> Response:
    p = await get_owned(session, LLMProvider, provider_id, ctx)
    await session.delete(p)
    audit(
        session,
        "llm_provider.deleted",
        organization_id=ctx.organization_id,
        actor_id=ctx.user_id,
        resource_type="llm_provider",
        resource_id=provider_id,
    )
    await session.commit()
    return Response(status_code=204)
