"""SQLAlchemy 2.0 typed models for every AgentForge entity.

Tenancy rule: every org-owned table mixes in ``OrgScoped`` (organization_id NOT NULL + index).
System tables without a tenant: organizations, users, roles, permissions, role_permissions,
refresh_tokens (user-owned), outbox_events (transport), audit_logs (organization_id nullable for
user-level events such as login).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.database.base import Base, CreatedAt, OrgScoped, Timestamps, UUIDPk, utcnow

TZ = DateTime(timezone=True)


# ---------------------------------------------------------------- identity / tenancy
class Organization(UUIDPk, Timestamps, Base):
    __tablename__ = "organizations"
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active")


class User(UUIDPk, Timestamps, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active")
    last_login_at: Mapped[datetime | None] = mapped_column(TZ)


class Role(UUIDPk, Base):
    __tablename__ = "roles"
    name: Mapped[str] = mapped_column(String(50), unique=True)
    description: Mapped[str] = mapped_column(String(255), default="")


class Permission(UUIDPk, Base):
    __tablename__ = "permissions"
    code: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(String(255), default="")


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )


class Membership(UUIDPk, OrgScoped, CreatedAt, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("organization_id", "user_id"),)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("roles.id"))
    role: Mapped[Role] = relationship(lazy="joined")
    user: Mapped[User] = relationship(lazy="joined")
    organization: Mapped[Organization] = relationship(lazy="joined")


class RefreshToken(UUIDPk, CreatedAt, Base):
    __tablename__ = "refresh_tokens"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    expires_at: Mapped[datetime] = mapped_column(TZ)
    revoked_at: Mapped[datetime | None] = mapped_column(TZ)
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class ApiKey(UUIDPk, OrgScoped, CreatedAt, Base):
    __tablename__ = "api_keys"
    name: Mapped[str] = mapped_column(String(200))
    prefix: Mapped[str] = mapped_column(String(16), index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    last_used_at: Mapped[datetime | None] = mapped_column(TZ)
    revoked_at: Mapped[datetime | None] = mapped_column(TZ)


# ---------------------------------------------------------------- BYOK / secrets
class LLMProvider(UUIDPk, OrgScoped, Timestamps, Base):
    __tablename__ = "llm_providers"
    provider: Mapped[str] = mapped_column(String(30))  # gemini | azure_openai
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="pending_validation")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    default_model: Mapped[str | None] = mapped_column(String(200))
    encrypted_api_key: Mapped[str] = mapped_column(Text)
    key_hint: Mapped[str] = mapped_column(String(16))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    last_validated_at: Mapped[datetime | None] = mapped_column(TZ)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))


class Credential(UUIDPk, OrgScoped, CreatedAt, Base):
    __tablename__ = "credentials"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(30))
    description: Mapped[str] = mapped_column(Text, default="")
    encrypted_value: Mapped[str] = mapped_column(Text)
    key_hint: Mapped[str] = mapped_column(String(16))
    rotated_at: Mapped[datetime | None] = mapped_column(TZ)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))


# ---------------------------------------------------------------- builder resources
class Agent(UUIDPk, OrgScoped, Timestamps, Base):
    __tablename__ = "agents"
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="draft")
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))


class AgentVersion(UUIDPk, OrgScoped, CreatedAt, Base):
    __tablename__ = "agent_versions"
    __table_args__ = (UniqueConstraint("agent_id", "version"),)
    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))


class Tool(UUIDPk, OrgScoped, Timestamps, Base):
    __tablename__ = "tools"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="draft")
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    source_code: Mapped[str] = mapped_column(Text)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    requirements: Mapped[list[str]] = mapped_column(JSONB, default=list)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))


class ToolVersion(UUIDPk, OrgScoped, CreatedAt, Base):
    __tablename__ = "tool_versions"
    __table_args__ = (UniqueConstraint("tool_id", "version"),)
    tool_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tools.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    source_code: Mapped[str] = mapped_column(Text)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    requirements: Mapped[list[str]] = mapped_column(JSONB, default=list)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))


class Workflow(UUIDPk, OrgScoped, Timestamps, Base):
    __tablename__ = "workflows"
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="draft")
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))


class WorkflowVersion(UUIDPk, OrgScoped, CreatedAt, Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (UniqueConstraint("workflow_id", "version"),)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))


# ---------------------------------------------------------------- runtime
class Execution(UUIDPk, OrgScoped, CreatedAt, Base):
    __tablename__ = "executions"
    __table_args__ = (
        Index("ix_executions_org_created", "organization_id", "created_at"),
        Index("ix_executions_org_status", "organization_id", "status"),
    )
    kind: Mapped[str] = mapped_column(String(20))  # agent|agent_test|workflow|tool_test|chat
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    resource_version: Mapped[int] = mapped_column(Integer, default=1)
    input: Mapped[Any] = mapped_column(JSONB, nullable=True)
    output: Mapped[Any] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str] = mapped_column(String(128))
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    started_at: Mapped[datetime | None] = mapped_column(TZ)
    finished_at: Mapped[datetime | None] = mapped_column(TZ)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)


class ExecutionEvent(UUIDPk, OrgScoped, CreatedAt, Base):
    __tablename__ = "execution_events"
    __table_args__ = (UniqueConstraint("execution_id", "sequence"),)
    execution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("executions.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(50))
    node_id: Mapped[str | None] = mapped_column(String(200))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class OutboxEvent(UUIDPk, Base):
    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_unpublished", "created_at", postgresql_where="published_at IS NULL"),)
    topic: Mapped[str] = mapped_column(String(200))
    key: Mapped[str | None] = mapped_column(String(200))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(TZ)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)


class ChatSession(UUIDPk, OrgScoped, Timestamps, Base):
    __tablename__ = "chat_sessions"
    title: Mapped[str] = mapped_column(String(300), default="New chat")
    target_type: Mapped[str] = mapped_column(String(20))  # agent | workflow
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))


class ChatMessage(UUIDPk, OrgScoped, CreatedAt, Base):
    __tablename__ = "chat_messages"
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))  # user | assistant | system
    content: Mapped[str] = mapped_column(Text)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("executions.id", ondelete="SET NULL")
    )


# ---------------------------------------------------------------- RAG
class Document(UUIDPk, OrgScoped, CreatedAt, Base):
    __tablename__ = "documents"
    title: Mapped[str] = mapped_column(String(300))
    source: Mapped[str | None] = mapped_column(String(1000))
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))


class DocumentChunk(UUIDPk, OrgScoped, CreatedAt, Base):
    __tablename__ = "document_chunks"
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.EMBEDDING_DIM))
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)


# ---------------------------------------------------------------- ops
class Deployment(UUIDPk, OrgScoped, CreatedAt, Base):
    __tablename__ = "deployments"
    resource_type: Mapped[str] = mapped_column(String(20))
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    resource_version: Mapped[int] = mapped_column(Integer)
    environment: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="recorded")
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))


class AuditLog(UUIDPk, CreatedAt, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_org_created", "organization_id", "created_at"),)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(100))
    resource_type: Mapped[str | None] = mapped_column(String(50))
    resource_id: Mapped[str | None] = mapped_column(String(100))
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(128))


class UsageRecord(UUIDPk, OrgScoped, CreatedAt, Base):
    __tablename__ = "usage_records"
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("executions.id", ondelete="SET NULL"), index=True
    )
    provider: Mapped[str | None] = mapped_column(String(30))
    model: Mapped[str | None] = mapped_column(String(200))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"))
