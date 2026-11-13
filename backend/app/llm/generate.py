"""Best-effort JSON generation via the org's LLM; returns None when unavailable/unparseable."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

_JSON = re.compile(r"\{.*\}", re.S)


async def generate_json(
    session: AsyncSession, org_id: uuid.UUID, provider_id: uuid.UUID | None, system: str, prompt: str
) -> dict[str, Any] | None:
    from app.core.errors import AppError
    from app.llm.manager import get_chat_model

    try:
        model = await get_chat_model(session, org_id, provider_id)
        msg = await model.ainvoke([("system", system), ("human", prompt)])
    except AppError:
        raise
    except Exception:  # noqa: BLE001
        return None
    m = _JSON.search(str(getattr(msg, "content", "")))
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None
