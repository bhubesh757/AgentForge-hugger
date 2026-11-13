"""Compile a workflow definition into a LangGraph ``StateGraph``.

Node executors are side-effect free with respect to infrastructure: everything external
(LLMs, tools, RAG, credentials, events, cancellation) goes through a :class:`RuntimeContext`,
which the runtime implements against DB/Redis/Kafka and tests implement with fakes.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import operator
import socket
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, Protocol, TypedDict
from urllib.parse import urlparse

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from app.orchestrator.safe_eval import evaluate_condition
from app.orchestrator.schemas import (
    AgentNodeConfig,
    APINodeConfig,
    ConditionNodeConfig,
    EndNodeConfig,
    LLMNodeConfig,
    RAGNodeConfig,
    ToolNodeConfig,
    WorkflowDefinition,
)
from app.orchestrator.templates import render_template, render_value

MAX_AGENT_TOOL_ITERATIONS = 5
TOKEN_FLUSH_CHARS = 64


def _merge_outputs(left: dict | None, right: dict | None) -> dict:
    return {**(left or {}), **(right or {})}


class WorkflowState(TypedDict, total=False):
    input: Any
    last_output: Any
    outputs: Annotated[dict[str, Any], _merge_outputs]
    execution_id: str
    organization_id: str
    trace: Annotated[list[str], operator.add]


class ExecutionCancelled(Exception):
    """Raised between nodes when the cancel flag is set."""


class NodeExecutionError(Exception):
    def __init__(self, node_id: str, message: str):
        super().__init__(message)
        self.node_id = node_id


@dataclass
class AgentSpec:
    """Resolved agent version (runtime loads it from DB)."""

    instructions: str = ""
    provider_id: str | None = None
    model: str | None = None
    temperature: float | None = None
    tools: list[dict[str, Any]] = field(default_factory=list)  # [{id, name, description, input_schema}]


class RuntimeContext(Protocol):
    execution_id: str
    organization_id: str

    async def emit(self, event_type: str, payload: dict, node_id: str | None = None) -> None: ...
    async def get_chat_model(self, provider_id: str | None, model: str | None) -> Any: ...
    async def load_agent(self, agent_id: str, version: int | None) -> AgentSpec: ...
    async def invoke_tool(self, tool_id: str, version: int | None, payload: Any) -> Any: ...
    async def rag_search(self, query: str, top_k: int) -> list[dict]: ...
    async def resolve_credential(self, ref: str) -> dict[str, str]: ...
    async def is_cancelled(self) -> bool: ...
    def allow_private_network(self) -> bool: ...


NodeFn = Callable[[WorkflowState], Awaitable[dict]]


# ---------------------------------------------------------------- helpers


async def stream_llm(ctx: RuntimeContext, model: Any, messages: list[BaseMessage], node_id: str | None) -> str:
    """Stream tokens from a LangChain chat model, emitting batched ``llm.token`` events."""
    parts: list[str] = []
    buf = ""
    try:
        async for chunk in model.astream(messages):
            text = chunk.content if isinstance(chunk.content, str) else _content_text(chunk.content)
            if not text:
                continue
            parts.append(text)
            buf += text
            if len(buf) >= TOKEN_FLUSH_CHARS:
                await ctx.emit("llm.token", {"text": buf}, node_id)
                buf = ""
    except NotImplementedError:
        msg = await model.ainvoke(messages)
        parts = [_content_text(msg.content)]
        buf = parts[0]
    if buf:
        await ctx.emit("llm.token", {"text": buf}, node_id)
    return "".join(parts)


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
    return str(content or "")


def maybe_json(text: Any) -> Any:
    """LLM output that is a JSON object/array is parsed so conditions can use ``.get()``."""
    if isinstance(text, str):
        s = text.strip()
        if s.startswith("```"):
            s = s.strip("`")
            s = s[4:] if s.lower().startswith("json") else s
            s = s.strip()
        if s[:1] in ("{", "["):
            try:
                return json.loads(s)
            except ValueError:
                return text
    return text


async def run_agent(ctx: RuntimeContext, spec: AgentSpec, user_input: str, node_id: str | None) -> str:
    """Run an agent: system instructions + optional tool-calling loop; tools go through the sandbox path."""
    model = await ctx.get_chat_model(spec.provider_id, spec.model)
    if spec.temperature is not None:
        try:
            model = model.bind(temperature=spec.temperature)
        except Exception:  # noqa: BLE001 - some fakes/models don't support bind
            pass
    messages: list[BaseMessage] = []
    if spec.instructions:
        messages.append(SystemMessage(content=spec.instructions))
    messages.append(HumanMessage(content=user_input))
    if not spec.tools:
        return await stream_llm(ctx, model, messages, node_id)

    by_name = {t["name"]: t for t in spec.tools}
    tool_defs = [
        {"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                          "parameters": t.get("input_schema") or {"type": "object"}}}
        for t in spec.tools
    ]
    try:
        bound = model.bind_tools(tool_defs)
    except (NotImplementedError, AttributeError):
        await ctx.emit("log", {"level": "warning", "message": "model does not support tool calling"}, node_id)
        return await stream_llm(ctx, model, messages, node_id)

    for _ in range(MAX_AGENT_TOOL_ITERATIONS):
        reply: AIMessage = await bound.ainvoke(messages)
        messages.append(reply)
        calls = getattr(reply, "tool_calls", None) or []
        if not calls:
            text = _content_text(reply.content)
            if text:
                await ctx.emit("llm.token", {"text": text}, node_id)
            return text
        for call in calls:
            tool = by_name.get(call["name"])
            if tool is None:
                result: Any = {"error": f"unknown tool {call['name']}"}
            else:
                await ctx.emit("log", {"level": "info", "message": f"calling tool {call['name']}"}, node_id)
                try:
                    result = await ctx.invoke_tool(tool["id"], tool.get("version"), call.get("args") or {})
                except Exception as exc:  # noqa: BLE001 - surface tool errors to the model
                    result = {"error": str(exc)}
            messages.append(ToolMessage(content=json.dumps(result, default=str), tool_call_id=call.get("id") or ""))
    raise NodeExecutionError(node_id or "agent", "agent exceeded maximum tool-calling iterations")


def check_url_allowed(url: str, allow_private: bool) -> None:
    """SSRF mitigation: http(s) only; reject private/loopback/link-local/reserved targets."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("only absolute http(s) URLs are allowed")
    if allow_private:
        return
    host = parsed.hostname
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise ValueError(f"cannot resolve host {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            raise ValueError(f"destination {host} resolves to a non-public address")


# ---------------------------------------------------------------- node executors


def _cfg(node, model):
    return model.model_validate(node.data.config or {})


def build_node_fn(node, ctx: RuntimeContext, http_client_factory=None) -> NodeFn:  # noqa: C901
    nid, ntype = node.id, node.type

    async def body(state: WorkflowState) -> Any:
        if ntype == "start":
            return state.get("input")
        if ntype == "end":
            cfg = _cfg(node, EndNodeConfig)
            last = state.get("last_output")
            if cfg.output_key:
                return {cfg.output_key: last}
            return last
        if ntype == "condition":
            cfg = _cfg(node, ConditionNodeConfig)
            return evaluate_condition(cfg.expression, dict(state))
        if ntype == "llm":
            cfg = _cfg(node, LLMNodeConfig)
            model = await ctx.get_chat_model(cfg.provider_id, cfg.model)
            if cfg.temperature is not None:
                try:
                    model = model.bind(temperature=cfg.temperature)
                except Exception:  # noqa: BLE001
                    pass
            prompt = render_template(cfg.prompt_template, dict(state))
            return maybe_json(await stream_llm(ctx, model, [HumanMessage(content=prompt)], nid))
        if ntype == "agent":
            cfg = _cfg(node, AgentNodeConfig)
            spec = await ctx.load_agent(cfg.agent_id, cfg.agent_version)
            text = await run_agent(ctx, spec, render_template(cfg.input_template, dict(state)), nid)
            return maybe_json(text)
        if ntype == "tool":
            cfg = _cfg(node, ToolNodeConfig)
            payload = render_value(cfg.input_mapping, dict(state)) if cfg.input_mapping else state.get("last_output")
            return await ctx.invoke_tool(cfg.tool_id, cfg.tool_version, payload)
        if ntype == "rag":
            cfg = _cfg(node, RAGNodeConfig)
            query = render_template(cfg.query_template, dict(state))
            return {"query": query, "documents": await ctx.rag_search(query, cfg.top_k)}
        if ntype == "api":
            return await _run_api(_cfg(node, APINodeConfig), state, ctx, http_client_factory)
        raise NodeExecutionError(nid, f"unsupported node type {ntype}")

    async def fn(state: WorkflowState) -> dict:
        if await ctx.is_cancelled():
            raise ExecutionCancelled()
        await ctx.emit("node.started", {"type": ntype}, nid)
        t0 = time.monotonic()
        try:
            result = await body(state)
        except ExecutionCancelled:
            raise
        except Exception as exc:
            await ctx.emit("node.failed", {"type": ntype, "error": str(exc)[:2000]}, nid)
            if isinstance(exc, NodeExecutionError):
                raise
            raise NodeExecutionError(nid, f"{ntype} node failed: {exc}") from exc
        duration_ms = int((time.monotonic() - t0) * 1000)
        await ctx.emit("node.completed", {"type": ntype, "duration_ms": duration_ms,
                                          "output": _preview(result)}, nid)
        update: dict[str, Any] = {"outputs": {nid: result}, "trace": [nid]}
        if ntype != "condition":
            update["last_output"] = result
        return update

    return fn


def _preview(value: Any, limit: int = 4000) -> Any:
    try:
        text = json.dumps(value, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return value if len(text) <= limit else text[:limit] + "…"


async def _run_api(cfg: APINodeConfig, state: WorkflowState, ctx: RuntimeContext, http_client_factory) -> Any:
    import httpx

    st = dict(state)
    url = render_template(cfg.url, st)
    await asyncio.to_thread(check_url_allowed, url, ctx.allow_private_network())
    headers = {k: render_template(v, st) for k, v in (cfg.headers or {}).items()}
    if cfg.credential_ref:
        headers.update(await ctx.resolve_credential(cfg.credential_ref))
    body = render_template(cfg.body_template, st) if cfg.body_template else None
    factory = http_client_factory or (lambda: httpx.AsyncClient(follow_redirects=False))
    async with factory() as client:
        resp = await client.request(cfg.method, url, headers=headers, content=body, timeout=cfg.timeout_seconds)
    try:
        data: Any = resp.json()
    except ValueError:
        data = resp.text[:100_000]
    if resp.status_code >= 400:
        raise ValueError(f"HTTP {resp.status_code} from {urlparse(url).hostname}")
    return {"status_code": resp.status_code, "body": data}


# ---------------------------------------------------------------- compile


def graph_node_name(node_id: str) -> str:
    """Prefix ids so user node ids can never collide with state keys or LangGraph reserved names."""
    return "node_" + node_id.replace(":", "_").replace("|", "_")


def compile_workflow(definition: dict | WorkflowDefinition, ctx: RuntimeContext, *, checkpointer=None,
                     http_client_factory=None):
    """Build and compile the LangGraph graph. Definition must already be valid."""
    wf = definition if isinstance(definition, WorkflowDefinition) else WorkflowDefinition.model_validate(definition)
    graph = StateGraph(WorkflowState)
    nodes = {n.id: n for n in wf.nodes}
    for n in wf.nodes:
        graph.add_node(graph_node_name(n.id), build_node_fn(n, ctx, http_client_factory))

    start = next(n for n in wf.nodes if n.type == "start")
    graph.add_edge(START, graph_node_name(start.id))
    by_source: dict[str, list] = {}
    for e in wf.edges:
        by_source.setdefault(e.source, []).append(e)

    for nid, node in nodes.items():
        outs = by_source.get(nid, [])
        if node.type == "end":
            graph.add_edge(graph_node_name(nid), END)
        elif node.type == "condition":
            mapping = {e.source_handle: e.target for e in outs}

            def route(state: WorkflowState, _nid: str = nid) -> str:
                return "true" if state["outputs"].get(_nid) else "false"

            graph.add_conditional_edges(graph_node_name(nid), route, {
                "true": graph_node_name(mapping["true"]), "false": graph_node_name(mapping["false"])})
        else:
            for e in outs:
                graph.add_edge(graph_node_name(nid), graph_node_name(e.target))
    return graph.compile(checkpointer=checkpointer)


def single_agent_definition(agent_id: str, version: int | None) -> dict:
    """Synthetic start→agent→end definition used for agent/agent_test/chat executions."""
    return {
        "schema_version": "1.0",
        "nodes": [
            {"id": "start", "type": "start", "data": {"label": "Start", "config": {}}},
            {"id": "agent", "type": "agent",
             "data": {"label": "Agent", "config": {"agent_id": agent_id, "agent_version": version,
                                                   "input_template": "{{input}}"}}},
            {"id": "end", "type": "end", "data": {"label": "End", "config": {}}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "agent"},
                  {"id": "e2", "source": "agent", "target": "end"}],
    }
