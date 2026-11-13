"""Minimal pgvector similarity search, always scoped by organization."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Document, DocumentChunk
from app.llm.manager import get_embeddings


async def similarity_search(
    session: AsyncSession, organization_id: uuid.UUID, query: str, top_k: int = 5
) -> list[dict[str, Any]]:
    emb = await get_embeddings(session, organization_id)
    vector = await emb.aembed_query(query)
    dist = DocumentChunk.embedding.cosine_distance(vector).label("distance")
    stmt = (
        select(DocumentChunk, Document.title, dist)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.organization_id == organization_id, Document.organization_id == organization_id)
        .order_by(dist)
        .limit(max(1, min(top_k, 50)))
    )
    rows = (await session.execute(stmt)).all()
    return [
        {"content": c.content, "document_id": str(c.document_id), "title": title, "score": 1 - float(d)}
        for c, title, d in rows
    ]
