"""Pydantic models for the canonical workflow definition (API_CONTRACTS §8.1)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

NodeType = Literal["start", "end", "agent", "tool", "llm", "rag", "api", "condition"]
NODE_TYPES: tuple[str, ...] = ("start", "end", "agent", "tool", "llm", "rag", "api", "condition")
HTTP_METHODS: tuple[str, ...] = ("GET", "POST", "PUT", "PATCH", "DELETE")


class ValidationIssue(BaseModel):
    node_id: str | None = None
    edge_id: str | None = None
    code: str
    message: str


class Position(BaseModel):
    x: float = 0
    y: float = 0


class NodeData(BaseModel):
    model_config = ConfigDict(extra="allow")
    label: str = ""
    config: dict[str, Any] = Field(default_factory=dict)


class WorkflowNode(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = Field(min_length=1)
    type: NodeType
    position: Position = Field(default_factory=Position)
    data: NodeData = Field(default_factory=NodeData)


class WorkflowEdge(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = Field(min_length=1)
    source: str
    target: str
    source_handle: str | None = None


class Viewport(BaseModel):
    x: float = 0
    y: float = 0
    zoom: float = 1


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: str = "1.0"
    nodes: list[WorkflowNode] = Field(default_factory=list)
    edges: list[WorkflowEdge] = Field(default_factory=list)
    viewport: Viewport = Field(default_factory=Viewport)


# --- per-type config models (used for validation and by the compiler) ---


class AgentNodeConfig(BaseModel):
    agent_id: str = Field(min_length=1)
    agent_version: int | None = None
    input_template: str = "{{input}}"


class ToolNodeConfig(BaseModel):
    tool_id: str = Field(min_length=1)
    tool_version: int | None = None
    input_mapping: dict[str, Any] | None = None


class LLMNodeConfig(BaseModel):
    provider_id: str | None = None
    model: str | None = None
    prompt_template: str = Field(min_length=1)
    temperature: float | None = Field(default=None, ge=0, le=2)


class RAGNodeConfig(BaseModel):
    query_template: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)


class APINodeConfig(BaseModel):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    url: str = Field(min_length=1)
    headers: dict[str, str] | None = None
    body_template: str | None = None
    credential_ref: str | None = None
    timeout_seconds: float = Field(default=30, gt=0, le=120)


class ConditionNodeConfig(BaseModel):
    expression: str = Field(min_length=1)


class EndNodeConfig(BaseModel):
    output_key: str | None = None


class StartNodeConfig(BaseModel):
    input_schema: dict[str, Any] | None = None


CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "start": StartNodeConfig,
    "end": EndNodeConfig,
    "agent": AgentNodeConfig,
    "tool": ToolNodeConfig,
    "llm": LLMNodeConfig,
    "rag": RAGNodeConfig,
    "api": APINodeConfig,
    "condition": ConditionNodeConfig,
}
