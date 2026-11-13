from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.deps import OrgContext, SessionDep, require
from app.core.permissions import RESOURCE_READ
from app.core.schemas import ERROR_RESPONSES
from app.rag.service import similarity_search

router = APIRouter(prefix="/rag", tags=["rag"], responses=ERROR_RESPONSES)


class SearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=50)


@router.post("/search", summary="Similarity search over org documents (pgvector)")
async def search(body: SearchBody, session: SessionDep, ctx: OrgContext = require(RESOURCE_READ)) -> dict:
    return {"items": await similarity_search(session, ctx.organization_id, body.query, body.top_k)}
