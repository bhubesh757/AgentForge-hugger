from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.core.schemas import ORMModel


class ExecutionOut(ORMModel):
    id: uuid.UUID
    kind: str
    status: str
    resource_id: uuid.UUID
    resource_version: int
    input: Any = None
    output: Any = None
    error: str | None = None
    correlation_id: str
    created_by: uuid.UUID | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None


class ExecutionEventOut(ORMModel):
    id: uuid.UUID
    execution_id: uuid.UUID
    sequence: int
    event_type: str
    node_id: str | None
    payload: dict[str, Any]
    created_at: datetime


class EventList(BaseModel):
    items: list[ExecutionEventOut]


class LogLine(BaseModel):
    timestamp: datetime
    level: str
    message: str
    node_id: str | None


class LogList(BaseModel):
    items: list[LogLine]
