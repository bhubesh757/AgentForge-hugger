"""Agents API (contract section 6)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.audit.service import audit
from app.core.deps import OrgContext, PageDep, SessionDep, get_owned, org_select, paginate, require
from app.core.errors import AppError, not_found
from app.core.permissions import EXECUTION_RUN, RESOURCE_READ, RESOURCE_WRITE
from app.core.schemas import ERROR_RESPONSES, ORMModel, Page
from app.database.models import Agent, AgentVersion, LLMProvider, Tool
from app.executions.schemas import ExecutionOut
from app.executions.service import create_execution
from app.llm.generate import generate_json

router = APIRouter(prefix="/agents", tags=["agents"], responses=ERROR_RESPONSES)


class Guardrails(BaseModel):
    block_pii: bool = False
    max_output_chars: int | None = Field(default=None, ge=1)


class AgentConfig(BaseModel):
    instructions: str = ""
    provider_id: uuid.UUID | None = None
    model: str | None = None
    temperature: float = Field(default=0.2, ge=0, le=2)
    tool_ids: list[uuid.UUID] = []
    memory: Literal["none", "conversation"] = "none"
    max_retries: int = Field(default=0, ge=0, le=5)
    timeout_seconds: int = Field(default=60, ge=1, le=600)
    guardrails: Guardrails = Guardrails()
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    config: AgentConfig = AgentConfig()


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    config: AgentConfig | None = None


class AgentOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str
    status: str
    current_version: int
    config: dict[str, Any]
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class AgentVersionOut(ORMModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    version: int
    config: dict[str, Any]
    created_at: datetime
    created_by: uuid.UUID | None


class GenerateBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    provider_id: uuid.UUID | None = None


class RunBody(BaseModel):
    input: Any = None
    stream: bool = False


class RollbackBody(BaseModel):
    version: int = Field(ge=1)


async def _check_refs(session, ctx: OrgContext, cfg: AgentConfig) -> None:
    if (
        cfg.provider_id
        and not (
            await session.execute(org_select(LLMProvider, ctx).where(LLMProvider.id == cfg.provider_id))
        ).first()
    ):
        raise AppError(422, "VALIDATION_ERROR", "provider_id not found in organization")
    if cfg.tool_ids:
        found = set(
            (
                await session.execute(
                    select(Tool.id).where(
                        Tool.organization_id == ctx.organization_id, Tool.id.in_(cfg.tool_ids)
                    )
                )
            ).scalars()
        )
        missing = [str(t) for t in cfg.tool_ids if t not in found]
        if missing:
            raise AppError(422, "VALIDATION_ERROR", "Unknown tool_ids", {"missing": missing})


def _add_version(session, agent: Agent, ctx: OrgContext, config: dict) -> None:
    session.add(
        AgentVersion(
            organization_id=ctx.organization_id,
            agent_id=agent.id,
            version=agent.current_version,
            config=config,
            created_by=ctx.user_id,
        )
    )


@router.post("", response_model=AgentOut, status_code=201, summary="Create agent (version 1)")
async def create_agent(
    body: AgentCreate, session: SessionDep, ctx: OrgContext = require(RESOURCE_WRITE)
) -> Agent:
    await _check_refs(session, ctx, body.config)
    cfg = body.config.model_dump(mode="json")
    a = Agent(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        name=body.name,
        description=body.description or "",
        status="configured" if body.config.instructions else "draft",
        current_version=1,
        config=cfg,
        created_by=ctx.user_id,
    )
    session.add(a)
    await session.flush()
    _add_version(session, a, ctx, cfg)
    audit(
        session,
        "agent.created",
        organization_id=ctx.organization_id,
        actor_id=ctx.user_id,
        resource_type="agent",
        resource_id=a.id,
    )
    await session.commit()
    await session.refresh(a)
    return a


@router.get("", response_model=Page[AgentOut], summary="List agents")
async def list_agents(
    session: SessionDep,
    params: PageDep,
    ctx: OrgContext = require(RESOURCE_READ),
    search: str | None = None,
    status: str | None = None,
) -> Page[AgentOut]:
    stmt = org_select(Agent, ctx)
    if search:
        stmt = stmt.where(Agent.name.ilike(f"%{search}%"))
    if status:
        stmt = stmt.where(Agent.status == status)
    rows, total = await paginate(session, stmt.order_by(Agent.updated_at.desc()), params)
    return Page(
        items=[AgentOut.model_validate(r) for r in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post("/generate", summary="Generate an agent draft (not saved)")
async def generate_agent(
    body: GenerateBody, session: SessionDep, ctx: OrgContext = require(RESOURCE_WRITE)
) -> dict[str, Any]:
    data = (
        await generate_json(
            session,
            ctx.organization_id,
            body.provider_id,
            "Return ONLY JSON {name, description, instructions} describing an AI agent "
            "for the user's request.",
            body.prompt,
        )
        or {}
    )
    words = re.findall(r"[A-Za-z0-9]+", body.prompt)[:5]
    name = str(data.get("name") or " ".join(w.capitalize() for w in words) or "New Agent")[:200]
    cfg = AgentConfig(
        instructions=str(data.get("instructions") or f"You are a helpful agent. Task: {body.prompt}"),
        provider_id=body.provider_id,
    )
    return {
        "draft": {
            "name": name,
            "description": str(data.get("description") or body.prompt[:500]),
            "config": cfg.model_dump(mode="json"),
        }
    }


@router.get("/{agent_id}", response_model=AgentOut, summary="Get agent")
async def get_agent(
    agent_id: uuid.UUID, session: SessionDep, ctx: OrgContext = require(RESOURCE_READ)
) -> Agent:
    return await get_owned(session, Agent, agent_id, ctx)


@router.put("/{agent_id}", response_model=AgentOut, summary="Update agent (config change → new version)")
async def update_agent(
    agent_id: uuid.UUID, body: AgentUpdate, session: SessionDep, ctx: OrgContext = require(RESOURCE_WRITE)
) -> Agent:
    a = await get_owned(session, Agent, agent_id, ctx)
    if body.name is not None:
        a.name = body.name
    if body.description is not None:
        a.description = body.description
    if body.config is not None:
        await _check_refs(session, ctx, body.config)
        cfg = body.config.model_dump(mode="json")
        if cfg != a.config:
            a.config, a.current_version = cfg, a.current_version + 1
            if a.status in {"draft", "published"}:
                a.status = "configured"
            _add_version(session, a, ctx, cfg)
    audit(
        session,
        "agent.updated",
        organization_id=ctx.organization_id,
        actor_id=ctx.user_id,
        resource_type="agent",
        resource_id=a.id,
    )
    await session.commit()
    await session.refresh(a)
    return a


async def _run(session, ctx: OrgContext, agent_id: uuid.UUID, kind: str, payload: Any):
    a = await get_owned(session, Agent, agent_id, ctx)
    if a.status == "archived":
        raise AppError(422, "VALIDATION_ERROR", "Agent is archived")
    return await create_execution(
        session, ctx, kind=kind, resource_id=a.id, resource_version=a.current_version, input=payload
    )


@router.post("/{agent_id}/test", response_model=ExecutionOut, status_code=202, summary="Test agent")
async def test_agent(
    agent_id: uuid.UUID, body: RunBody, session: SessionDep, ctx: OrgContext = require(EXECUTION_RUN)
):
    return await _run(session, ctx, agent_id, "agent_test", body.input)


@router.post("/{agent_id}/execute", response_model=ExecutionOut, status_code=202, summary="Execute agent")
async def execute_agent(
    agent_id: uuid.UUID, body: RunBody, session: SessionDep, ctx: OrgContext = require(EXECUTION_RUN)
):
    return await _run(session, ctx, agent_id, "agent", body.input)


@router.post("/{agent_id}/publish", response_model=AgentOut, summary="Publish agent")
async def publish_agent(
    agent_id: uuid.UUID, session: SessionDep, ctx: OrgContext = require(RESOURCE_WRITE)
) -> Agent:
    a = await get_owned(session, Agent, agent_id, ctx)
    if not (a.config or {}).get("instructions"):
        raise AppError(422, "VALIDATION_ERROR", "Agent needs instructions before publishing")
    a.status = "published"
    audit(
        session,
        "agent.published",
        organization_id=ctx.organization_id,
        actor_id=ctx.user_id,
        resource_type="agent",
        resource_id=a.id,
        metadata={"version": a.current_version},
    )
    await session.commit()
    await session.refresh(a)
    return a


@router.get("/{agent_id}/versions", response_model=Page[AgentVersionOut], summary="List agent versions")
async def list_versions(
    agent_id: uuid.UUID, session: SessionDep, params: PageDep, ctx: OrgContext = require(RESOURCE_READ)
) -> Page[AgentVersionOut]:
    await get_owned(session, Agent, agent_id, ctx)
    stmt = (
        org_select(AgentVersion, ctx)
        .where(AgentVersion.agent_id == agent_id)
        .order_by(AgentVersion.version.desc())
    )
    rows, total = await paginate(session, stmt, params)
    return Page(
        items=[AgentVersionOut.model_validate(r) for r in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post("/{agent_id}/rollback", response_model=AgentOut, summary="Rollback (new version copying target)")
async def rollback_agent(
    agent_id: uuid.UUID, body: RollbackBody, session: SessionDep, ctx: OrgContext = require(RESOURCE_WRITE)
) -> Agent:
    a = await get_owned(session, Agent, agent_id, ctx)
    v = (
        await session.execute(
            org_select(AgentVersion, ctx).where(
                AgentVersion.agent_id == agent_id, AgentVersion.version == body.version
            )
        )
    ).scalar_one_or_none()
    if v is None:
        raise not_found("AgentVersion")
    a.config, a.current_version = dict(v.config), a.current_version + 1
    _add_version(session, a, ctx, a.config)
    audit(
        session,
        "agent.rolled_back",
        organization_id=ctx.organization_id,
        actor_id=ctx.user_id,
        resource_type="agent",
        resource_id=a.id,
        metadata={"to_version": body.version},
    )
    await session.commit()
    await session.refresh(a)
    return a
