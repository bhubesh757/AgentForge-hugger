"""Deployments (records only in 1.0.1) — contract section 11."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.audit.service import audit
from app.core.deps import OrgContext, PageDep, SessionDep, get_owned, org_select, paginate, require
from app.core.permissions import RESOURCE_READ, RESOURCE_WRITE
from app.core.schemas import ERROR_RESPONSES, ORMModel, Page
from app.database.models import Agent, Deployment, Workflow

router = APIRouter(prefix="/deployments", tags=["deployments"], responses=ERROR_RESPONSES)


class DeploymentCreate(BaseModel):
    resource_type: Literal["agent", "workflow"]
    resource_id: uuid.UUID
    environment: Literal["dev", "staging", "production"]


class DeploymentOut(ORMModel):
    id: uuid.UUID
    resource_type: str
    resource_id: uuid.UUID
    resource_version: int
    environment: str
    status: str
    created_by: uuid.UUID | None
    created_at: datetime


@router.get("", response_model=Page[DeploymentOut], summary="List deployments")
async def list_deployments(
    session: SessionDep, params: PageDep, ctx: OrgContext = require(RESOURCE_READ)
) -> Page[DeploymentOut]:
    rows, total = await paginate(
        session, org_select(Deployment, ctx).order_by(Deployment.created_at.desc()), params
    )
    return Page(
        items=[DeploymentOut.model_validate(r) for r in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post("", response_model=DeploymentOut, status_code=201, summary="Record a deployment")
async def create_deployment(
    body: DeploymentCreate, session: SessionDep, ctx: OrgContext = require(RESOURCE_WRITE)
) -> Deployment:
    target = await get_owned(
        session, Agent if body.resource_type == "agent" else Workflow, body.resource_id, ctx
    )
    d = Deployment(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        resource_type=body.resource_type,
        resource_id=body.resource_id,
        resource_version=target.current_version,
        environment=body.environment,
        status="recorded",
        created_by=ctx.user_id,
    )
    session.add(d)
    audit(
        session,
        "deployment.recorded",
        organization_id=ctx.organization_id,
        actor_id=ctx.user_id,
        resource_type="deployment",
        resource_id=d.id,
        metadata={"environment": body.environment},
    )
    await session.commit()
    await session.refresh(d)
    return d


@router.get("/{deployment_id}", response_model=DeploymentOut, summary="Get deployment")
async def get_deployment(
    deployment_id: uuid.UUID, session: SessionDep, ctx: OrgContext = require(RESOURCE_READ)
) -> Deployment:
    return await get_owned(session, Deployment, deployment_id, ctx)
