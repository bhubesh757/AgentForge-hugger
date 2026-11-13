"""Tools API (contract section 7).

Code is statically analyzed only; execution happens in the sandbox worker."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.audit.service import audit
from app.core.deps import OrgContext, PageDep, SessionDep, get_owned, org_select, paginate, require
from app.core.errors import AppError, conflict
from app.core.permissions import EXECUTION_RUN, RESOURCE_READ, RESOURCE_WRITE
from app.core.schemas import ERROR_RESPONSES, ORMModel, Page
from app.database.models import Tool, ToolVersion
from app.executions.schemas import ExecutionOut
from app.executions.service import create_execution
from app.llm.generate import generate_json
from app.tools.static_analysis import analyze

router = APIRouter(prefix="/tools", tags=["tools"], responses=ERROR_RESPONSES)
NAME = r"^[A-Za-z_][A-Za-z0-9_]{0,99}$"


class ToolCreate(BaseModel):
    name: str = Field(pattern=NAME)
    description: str | None = None
    source_code: str = Field(min_length=1, max_length=100_000)
    input_schema: dict[str, Any] = {}
    output_schema: dict[str, Any] = {}
    requirements: list[str] = []


class ToolUpdate(BaseModel):
    name: str | None = Field(default=None, pattern=NAME)
    description: str | None = None
    source_code: str | None = Field(default=None, min_length=1, max_length=100_000)
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    requirements: list[str] | None = None


class ToolOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str
    status: str
    current_version: int
    source_code: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    requirements: list[str]
    created_at: datetime
    updated_at: datetime


class ToolVersionOut(ORMModel):
    id: uuid.UUID
    version: int
    source_code: str
    created_at: datetime


class GenerateBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    provider_id: uuid.UUID | None = None


class TestBody(BaseModel):
    input: dict[str, Any] = {}


def _ensure_safe(source: str, reqs: list[str]) -> None:
    res = analyze(source, reqs)
    if not res.ok:
        raise AppError(422, "VALIDATION_ERROR", "Tool code failed static analysis", {"issues": res.issues})


def _snapshot(session, t: Tool, ctx: OrgContext) -> None:
    session.add(
        ToolVersion(
            organization_id=ctx.organization_id,
            tool_id=t.id,
            version=t.current_version,
            source_code=t.source_code,
            input_schema=t.input_schema,
            output_schema=t.output_schema,
            requirements=t.requirements,
            created_by=ctx.user_id,
        )
    )


async def _name_taken(session, ctx: OrgContext, name: str, exclude: uuid.UUID | None = None) -> bool:
    stmt = org_select(Tool, ctx).where(Tool.name == name)
    if exclude:
        stmt = stmt.where(Tool.id != exclude)
    return (await session.execute(stmt)).first() is not None


@router.post("/generate", summary="Generate tool draft (not saved) + static analysis")
async def generate_tool(
    body: GenerateBody, session: SessionDep, ctx: OrgContext = require(RESOURCE_WRITE)
) -> dict[str, Any]:
    data = (
        await generate_json(
            session,
            ctx.organization_id,
            body.provider_id,
            "Return ONLY JSON {name, description, source_code, input_schema, output_schema, "
            "requirements, tests}. source_code must define `def run(input: dict) -> dict:` "
            "and only import json/math/re/datetime/httpx.",
            body.prompt,
        )
        or {}
    )
    slug = "_".join(re.findall(r"[a-z0-9]+", body.prompt.lower())[:4]) or "generated_tool"
    name = str(data.get("name") or slug)
    if not re.match(NAME, name):
        name = slug if re.match(NAME, slug) else "generated_tool"
    source = str(
        data.get("source_code")
        or f'def run(input: dict) -> dict:\n    """{body.prompt[:200]!s}"""\n    return {{"echo": input}}\n'
    )
    reqs = [str(r) for r in data.get("requirements") or []]
    res = analyze(source, reqs)
    draft = {
        "name": name,
        "description": str(data.get("description") or body.prompt[:500]),
        "source_code": source,
        "input_schema": data.get("input_schema") or {"type": "object"},
        "output_schema": data.get("output_schema") or {"type": "object"},
        "requirements": reqs,
        "tests": data.get("tests") or [],
    }
    return {"draft": draft, "static_analysis": {"ok": res.ok, "issues": res.issues}}


@router.post("", response_model=ToolOut, status_code=201, summary="Create tool (static analysis enforced)")
async def create_tool(
    body: ToolCreate, session: SessionDep, ctx: OrgContext = require(RESOURCE_WRITE)
) -> Tool:
    _ensure_safe(body.source_code, body.requirements)
    if await _name_taken(session, ctx, body.name):
        raise conflict("Tool name already exists")
    t = Tool(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        name=body.name,
        description=body.description or "",
        status="draft",
        current_version=1,
        source_code=body.source_code,
        input_schema=body.input_schema,
        output_schema=body.output_schema,
        requirements=body.requirements,
        created_by=ctx.user_id,
    )
    session.add(t)
    await session.flush()
    _snapshot(session, t, ctx)
    audit(
        session,
        "tool.created",
        organization_id=ctx.organization_id,
        actor_id=ctx.user_id,
        resource_type="tool",
        resource_id=t.id,
    )
    await session.commit()
    await session.refresh(t)
    return t


@router.get("", response_model=Page[ToolOut], summary="List tools")
async def list_tools(
    session: SessionDep, params: PageDep, ctx: OrgContext = require(RESOURCE_READ), search: str | None = None
) -> Page[ToolOut]:
    stmt = org_select(Tool, ctx)
    if search:
        stmt = stmt.where(Tool.name.ilike(f"%{search}%"))
    rows, total = await paginate(session, stmt.order_by(Tool.updated_at.desc()), params)
    return Page(
        items=[ToolOut.model_validate(r) for r in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.get("/{tool_id}", response_model=ToolOut, summary="Get tool")
async def get_tool(tool_id: uuid.UUID, session: SessionDep, ctx: OrgContext = require(RESOURCE_READ)) -> Tool:
    return await get_owned(session, Tool, tool_id, ctx)


@router.put("/{tool_id}", response_model=ToolOut, summary="Update tool (new version)")
async def update_tool(
    tool_id: uuid.UUID, body: ToolUpdate, session: SessionDep, ctx: OrgContext = require(RESOURCE_WRITE)
) -> Tool:
    t = await get_owned(session, Tool, tool_id, ctx)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if "name" in changes and await _name_taken(session, ctx, changes["name"], exclude=t.id):
        raise conflict("Tool name already exists")
    _ensure_safe(changes.get("source_code", t.source_code), changes.get("requirements", t.requirements))
    for k, v in changes.items():
        setattr(t, k, v)
    if set(changes) & {"source_code", "input_schema", "output_schema", "requirements"}:
        t.current_version += 1
        t.status = "draft"
        _snapshot(session, t, ctx)
    audit(
        session,
        "tool.updated",
        organization_id=ctx.organization_id,
        actor_id=ctx.user_id,
        resource_type="tool",
        resource_id=t.id,
    )
    await session.commit()
    await session.refresh(t)
    return t


@router.post("/{tool_id}/test", response_model=ExecutionOut, status_code=202, summary="Test tool in sandbox")
async def test_tool(
    tool_id: uuid.UUID, body: TestBody, session: SessionDep, ctx: OrgContext = require(EXECUTION_RUN)
):
    t = await get_owned(session, Tool, tool_id, ctx)
    return await create_execution(
        session, ctx, kind="tool_test", resource_id=t.id, resource_version=t.current_version, input=body.input
    )


@router.post("/{tool_id}/publish", response_model=ToolOut, summary="Publish tool")
async def publish_tool(
    tool_id: uuid.UUID, session: SessionDep, ctx: OrgContext = require(RESOURCE_WRITE)
) -> Tool:
    t = await get_owned(session, Tool, tool_id, ctx)
    _ensure_safe(t.source_code, t.requirements)
    t.status = "published"
    audit(
        session,
        "tool.published",
        organization_id=ctx.organization_id,
        actor_id=ctx.user_id,
        resource_type="tool",
        resource_id=t.id,
    )
    await session.commit()
    await session.refresh(t)
    return t


@router.get("/{tool_id}/versions", response_model=Page[ToolVersionOut], summary="List tool versions")
async def list_versions(
    tool_id: uuid.UUID, session: SessionDep, params: PageDep, ctx: OrgContext = require(RESOURCE_READ)
) -> Page[ToolVersionOut]:
    await get_owned(session, Tool, tool_id, ctx)
    stmt = (
        org_select(ToolVersion, ctx)
        .where(ToolVersion.tool_id == tool_id)
        .order_by(ToolVersion.version.desc())
    )
    rows, total = await paginate(session, stmt, params)
    return Page(
        items=[ToolVersionOut.model_validate(r) for r in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )
