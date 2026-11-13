"""Chat API (contract section 10). Execution input = {"session_id", "message"} (section 17)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.deps import OrgContext, PageDep, SessionDep, get_owned, org_select, paginate, require
from app.core.errors import AppError
from app.core.permissions import EXECUTION_RUN, RESOURCE_READ
from app.core.schemas import ERROR_RESPONSES, ORMModel, Page
from app.database.models import Agent, ChatMessage, ChatSession, Workflow
from app.executions.schemas import ExecutionOut
from app.executions.service import create_execution

router = APIRouter(prefix="/chat/sessions", tags=["chat"], responses=ERROR_RESPONSES)


class SessionCreate(BaseModel):
    target_type: Literal["agent", "workflow"]
    target_id: uuid.UUID
    title: str | None = Field(default=None, max_length=300)


class SessionOut(ORMModel):
    id: uuid.UUID
    title: str
    target_type: str
    target_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class MessageOut(ORMModel):
    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    execution_id: uuid.UUID | None
    created_at: datetime


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=32_000)


class SendOut(BaseModel):
    user_message: MessageOut
    execution: ExecutionOut


def _target_model(t: str):
    return Agent if t == "agent" else Workflow


@router.post("", response_model=SessionOut, status_code=201, summary="Create chat session")
async def create_session(
    body: SessionCreate, session: SessionDep, ctx: OrgContext = require(EXECUTION_RUN)
) -> ChatSession:
    target = await get_owned(session, _target_model(body.target_type), body.target_id, ctx)
    s = ChatSession(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        title=body.title or f"Chat with {target.name}",
        target_type=body.target_type,
        target_id=body.target_id,
        created_by=ctx.user_id,
    )
    session.add(s)
    await session.commit()
    await session.refresh(s)
    return s


@router.get("", response_model=Page[SessionOut], summary="List chat sessions")
async def list_sessions(
    session: SessionDep, params: PageDep, ctx: OrgContext = require(RESOURCE_READ)
) -> Page[SessionOut]:
    rows, total = await paginate(
        session, org_select(ChatSession, ctx).order_by(ChatSession.updated_at.desc()), params
    )
    return Page(
        items=[SessionOut.model_validate(r) for r in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.get("/{session_id}/messages", response_model=Page[MessageOut], summary="List messages")
async def list_messages(
    session_id: uuid.UUID, session: SessionDep, params: PageDep, ctx: OrgContext = require(RESOURCE_READ)
) -> Page[MessageOut]:
    await get_owned(session, ChatSession, session_id, ctx)
    stmt = (
        org_select(ChatMessage, ctx)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    rows, total = await paginate(session, stmt, params)
    return Page(
        items=[MessageOut.model_validate(r) for r in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post("/{session_id}/messages", response_model=SendOut, status_code=202, summary="Send message")
async def send_message(
    session_id: uuid.UUID, body: MessageCreate, session: SessionDep, ctx: OrgContext = require(EXECUTION_RUN)
) -> SendOut:
    s = await get_owned(session, ChatSession, session_id, ctx)
    target = await get_owned(session, _target_model(s.target_type), s.target_id, ctx)
    if target.status == "archived":
        raise AppError(422, "VALIDATION_ERROR", "Chat target is archived")
    msg = ChatMessage(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        session_id=s.id,
        role="user",
        content=body.content,
    )
    session.add(msg)
    await session.flush()
    ex = await create_execution(
        session,
        ctx,
        kind="chat",
        resource_id=s.target_id,
        resource_version=target.current_version,
        input={"session_id": str(s.id), "message": body.content},
    )
    msg.execution_id = ex.id
    await session.commit()
    await session.refresh(msg)
    return SendOut(user_message=MessageOut.model_validate(msg), execution=ExecutionOut.model_validate(ex))
