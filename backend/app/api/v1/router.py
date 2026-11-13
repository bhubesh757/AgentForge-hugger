"""Aggregates all v1 routers under /api/v1."""

from fastapi import APIRouter

from app.agents.router import router as agents
from app.audit.router import router as audit
from app.auth.router import router as auth
from app.chat.router import router as chat
from app.credentials.router import router as credentials
from app.deployments.router import router as deployments
from app.executions.router import router as executions
from app.llm.router import router as llm
from app.monitoring.router import health_router
from app.monitoring.router import router as monitoring
from app.organizations.router import router as organizations
from app.rag.router import router as rag
from app.tools.router import router as tools
from app.workflows.router import router as workflows

api_router = APIRouter(prefix="/api/v1")
for r in (
    auth,
    organizations,
    llm,
    credentials,
    agents,
    tools,
    workflows,
    executions,
    chat,
    rag,
    deployments,
    audit,
    monitoring,
    health_router,
):
    api_router.include_router(r)
