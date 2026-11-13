"""Workflows API (contract section 8). Structural validation is Agent 3's validator; DB refs checked here."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.audit.service import audit
from app.core.deps import OrgContext, PageDep, SessionDep, get_owned, org_select, paginate, require
from app.core.errors import AppError
from app.core.permissions import EXECUTION_RUN, RESOURCE_READ, RESOURCE_WRITE
from app.core.schemas import ERROR_RESPONSES, ORMModel, Page
from app.database.models import Agent, Tool, Workflow, WorkflowVersion
from app.executions.schemas import ExecutionOut
from app.executions.service import create_execution
from app.orchestrator.schemas import ValidationIssue
from app.orchestrator.validator import validate_definition

router = APIRouter(prefix="/workflows", tags=["workflows"], responses=ERROR_RESPONSES)
EMPTY_DEFINITION: dict[str, Any] = {
    "schema_version": "1.0",
    "nodes": [],
    "edges": [],
    "viewport": {"x": 0, "y": 0, "zoom": 1},
}


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    definition: dict[str, Any] = Field(default_factory=lambda: dict(EMPTY_DEFINITION))


class WorkflowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    definition: dict[str, Any] | None = None


class WorkflowOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str
    status: str
    current_version: int
    definition: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class WorkflowVersionOut(ORMModel):
    id: uuid.UUID
    version: int
    definition: dict[str, Any]
    created_at: datetime


class ValidateBody(BaseModel):
    definition: dict[str, Any] | None = None


class ValidationResult(BaseModel):
    valid: bool
    issues: list[ValidationIssue]


class ExecuteBody(BaseModel):
    input: Any = None


def _uuid(v: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(v))
    except (ValueError, TypeError):
        return None


async def validate_full(session, ctx: OrgContext, definition: dict[str, Any]) -> list[ValidationIssue]:
    issues = list(validate_definition(definition))
    nodes = definition.get("nodes") or [] if isinstance(definition, dict) else []
    for model, ntype, key in ((Agent, "agent", "agent_id"), (Tool, "tool", "tool_id")):
        refs = {}
        for n in nodes:
            if isinstance(n, dict) and n.get("type") == ntype:
                raw = ((n.get("data") or {}).get("config") or {}).get(key)
                if raw is not None:
                    refs[n.get("id")] = (raw, _uuid(raw))
        ids = [u for _, u in refs.values() if u]
        found = set()
        if ids:
            found = set(
                (
                    await session.execute(
                        select(model.id).where(
                            model.organization_id == ctx.organization_id, model.id.in_(ids)
                        )
                    )
                ).scalars()
            )
        for node_id, (raw, u) in refs.items():
            if u is None or u not in found:
                issues.append(
                    ValidationIssue(
                        node_id=node_id,
                        edge_id=None,
                        code=f"{ntype.upper()}_NOT_FOUND",
                        message=f"{ntype} '{raw}' does not exist in this organization",
                    )
                )
    return issues


def _snapshot(session, w: Workflow, ctx: OrgContext) -> None:
    session.add(
        WorkflowVersion(
            organization_id=ctx.organization_id,
            workflow_id=w.id,
            version=w.current_version,
            definition=w.definition,
            created_by=ctx.user_id,
        )
    )


@router.post("", response_model=WorkflowOut, status_code=201, summary="Create workflow")
async def create_workflow(
    body: WorkflowCreate, session: SessionDep, ctx: OrgContext = require(RESOURCE_WRITE)
) -> Workflow:
    w = Workflow(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        name=body.name,
        description=body.description or "",
        status="draft",
        current_version=1,
        definition=body.definition,
        created_by=ctx.user_id,
    )
    session.add(w)
    await session.flush()
    _snapshot(session, w, ctx)
    audit(
        session,
        "workflow.created",
        organization_id=ctx.organization_id,
        actor_id=ctx.user_id,
        resource_type="workflow",
        resource_id=w.id,
    )
    await session.commit()
    await session.refresh(w)
    return w


@router.get("", response_model=Page[WorkflowOut], summary="List workflows")
async def list_workflows(
    session: SessionDep, params: PageDep, ctx: OrgContext = require(RESOURCE_READ), search: str | None = None
) -> Page[WorkflowOut]:
    stmt = org_select(Workflow, ctx)
    if search:
        stmt = stmt.where(Workflow.name.ilike(f"%{search}%"))
    rows, total = await paginate(session, stmt.order_by(Workflow.updated_at.desc()), params)
    return Page(
        items=[WorkflowOut.model_validate(r) for r in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.get("/{workflow_id}", response_model=WorkflowOut, summary="Get workflow")
async def get_workflow(
    workflow_id: uuid.UUID, session: SessionDep, ctx: OrgContext = require(RESOURCE_READ)
) -> Workflow:
    return await get_owned(session, Workflow, workflow_id, ctx)


@router.put(
    "/{workflow_id}", response_model=WorkflowOut, summary="Update workflow (definition → new version)"
)
async def update_workflow(
    workflow_id: uuid.UUID,
    body: WorkflowUpdate,
    session: SessionDep,
    ctx: OrgContext = require(RESOURCE_WRITE),
) -> Workflow:
    w = await get_owned(session, Workflow, workflow_id, ctx)
    if body.name is not None:
        w.name = body.name
    if body.description is not None:
        w.description = body.description
    if body.definition is not None and body.definition != w.definition:
        w.definition, w.current_version, w.status = body.definition, w.current_version + 1, "draft"
        _snapshot(session, w, ctx)
    audit(
        session,
        "workflow.updated",
        organization_id=ctx.organization_id,
        actor_id=ctx.user_id,
        resource_type="workflow",
        resource_id=w.id,
    )
    await session.commit()
    await session.refresh(w)
    return w


@router.post(
    "/{workflow_id}/validate", response_model=ValidationResult, summary="Validate workflow definition"
)
async def validate_workflow(
    workflow_id: uuid.UUID,
    session: SessionDep,
    body: ValidateBody | None = None,
    ctx: OrgContext = require(RESOURCE_READ),
) -> ValidationResult:
    w = await get_owned(session, Workflow, workflow_id, ctx)
    stored = body is None or body.definition is None
    issues = await validate_full(session, ctx, w.definition if stored else body.definition)
    if stored and not issues and w.status == "draft" and ctx.has(RESOURCE_WRITE):
        w.status = "valid"
        await session.commit()
    return ValidationResult(valid=not issues, issues=issues)


async def _require_valid(session, ctx: OrgContext, w: Workflow) -> None:
    issues = await validate_full(session, ctx, w.definition)
    if issues:
        raise AppError(
            422,
            "VALIDATION_ERROR",
            "Workflow definition is invalid",
            {"issues": [i.model_dump() for i in issues]},
        )


@router.post("/{workflow_id}/publish", response_model=WorkflowOut, summary="Publish workflow (must validate)")
async def publish_workflow(
    workflow_id: uuid.UUID, session: SessionDep, ctx: OrgContext = require(RESOURCE_WRITE)
) -> Workflow:
    w = await get_owned(session, Workflow, workflow_id, ctx)
    await _require_valid(session, ctx, w)
    w.status = "published"
    audit(
        session,
        "workflow.published",
        organization_id=ctx.organization_id,
        actor_id=ctx.user_id,
        resource_type="workflow",
        resource_id=w.id,
        metadata={"version": w.current_version},
    )
    await session.commit()
    await session.refresh(w)
    return w


@router.post(
    "/{workflow_id}/execute", response_model=ExecutionOut, status_code=202, summary="Execute workflow"
)
async def execute_workflow(
    workflow_id: uuid.UUID, body: ExecuteBody, session: SessionDep, ctx: OrgContext = require(EXECUTION_RUN)
):
    w = await get_owned(session, Workflow, workflow_id, ctx)
    await _require_valid(session, ctx, w)
    return await create_execution(
        session, ctx, kind="workflow", resource_id=w.id, resource_version=w.current_version, input=body.input
    )


@router.get(
    "/{workflow_id}/versions", response_model=Page[WorkflowVersionOut], summary="List workflow versions"
)
async def list_versions(
    workflow_id: uuid.UUID, session: SessionDep, params: PageDep, ctx: OrgContext = require(RESOURCE_READ)
) -> Page[WorkflowVersionOut]:
    await get_owned(session, Workflow, workflow_id, ctx)
    stmt = (
        org_select(WorkflowVersion, ctx)
        .where(WorkflowVersion.workflow_id == workflow_id)
        .order_by(WorkflowVersion.version.desc())
    )
    rows, total = await paginate(session, stmt, params)
    return Page(
        items=[WorkflowVersionOut.model_validate(r) for r in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )
