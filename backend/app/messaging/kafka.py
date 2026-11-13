"""Kafka envelope model and aiokafka producer/consumer factories (API_CONTRACTS §14)."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1.0"
ResourceType = Literal["agent", "workflow", "tool"]
ExecutionKind = Literal["agent", "agent_test", "workflow", "tool_test", "chat"]


class EventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: str = Field(min_length=1, max_length=200)
    schema_version: str = SCHEMA_VERSION
    organization_id: uuid.UUID
    execution_id: uuid.UUID
    correlation_id: uuid.UUID
    resource_type: ResourceType
    resource_id: uuid.UUID
    resource_version: int = Field(ge=0)
    kind: ExecutionKind
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    attempt: int = Field(default=1, ge=1)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("schema_version")
    @classmethod
    def _major_supported(cls, v: str) -> str:
        if v.split(".")[0] != SCHEMA_VERSION.split(".")[0]:
            raise ValueError(f"unsupported schema_version {v}")
        return v

    def to_bytes(self) -> bytes:
        return self.model_dump_json().encode("utf-8")

    @property
    def key(self) -> bytes:
        return str(self.execution_id).encode("utf-8")

    @classmethod
    def from_bytes(cls, raw: bytes | str) -> EventEnvelope:
        return cls.model_validate_json(raw)

    def derive(self, event_type: str, payload: dict | None = None) -> EventEnvelope:
        """New envelope (new event_id) for a follow-up lifecycle event of the same execution."""
        return self.model_copy(update={"event_id": uuid.uuid4(), "event_type": event_type,
                                       "timestamp": datetime.now(UTC), "attempt": 1,
                                       "payload": payload or {}})


def get_setting(name: str, default: Any = None) -> Any:
    """Read a setting from Agent 2's ``app.core.config.settings`` with env fallback."""
    try:
        from app.core.config import settings  # type: ignore[import-not-found]

        for attr in (name, name.lower()):
            if hasattr(settings, attr):
                val = getattr(settings, attr)
                return val.get_secret_value() if hasattr(val, "get_secret_value") else val
    except Exception:  # noqa: BLE001 - config import must never break messaging
        pass
    return os.getenv(name, default)


def bootstrap_servers() -> str:
    return str(get_setting("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"))


def create_producer(**overrides: Any):
    from aiokafka import AIOKafkaProducer

    opts: dict[str, Any] = {
        "bootstrap_servers": bootstrap_servers(),
        "acks": "all",
        "enable_idempotence": True,
        "linger_ms": 5,
        "client_id": "agentforge-" + os.getenv("HOSTNAME", "producer"),
    }
    opts.update(overrides)
    return AIOKafkaProducer(**opts)


def create_consumer(*topics: str, group_id: str, **overrides: Any):
    from aiokafka import AIOKafkaConsumer

    opts: dict[str, Any] = {
        "bootstrap_servers": bootstrap_servers(),
        "group_id": group_id,
        "enable_auto_commit": False,
        "auto_offset_reset": "earliest",
        "max_poll_records": 1,
        "max_poll_interval_ms": 15 * 60 * 1000,
        "session_timeout_ms": 30_000,
        "heartbeat_interval_ms": 3_000,
    }
    opts.update(overrides)
    return AIOKafkaConsumer(*topics, **opts)


async def publish(producer, topic: str, envelope: EventEnvelope) -> None:
    await producer.send_and_wait(topic, value=envelope.to_bytes(), key=envelope.key)


def dumps(obj: Any) -> bytes:
    return json.dumps(obj, default=str).encode("utf-8")
