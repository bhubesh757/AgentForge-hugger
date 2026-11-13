"""Execution runtime: load execution → compile LangGraph → run with events, cancellation, timeouts."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog

from app.messaging.kafka import EventEnvelope, get_setting
from app.messaging.redis_client import CANCEL_KEY, TOOL_RESULT_KEY, get_redis
from app.messaging.topics import (
    AGENT_EXECUTION_COMPLETED,
    AGENT_EXECUTION_FAILED,
    AGENT_EXECUTION_STARTED,
    TOOL_EXECUTION_REQUESTED,
    WORKFLOW_EXECUTION_EVENTS,
)
from app.orchestrator.compiler import (
    AgentSpec,
    ExecutionCancelled,
    NodeExecutionError,
    compile_workflow,
    single_agent_definition,
)

log = structlog.get_logger(__name__)

DEFAULT_EXECUTION_TIMEOUT_S = 300.0
DEFAULT_TOOL_TIMEOUT_S = 60.0
TERMINAL = {"succeeded", "failed", "cancelled"}

# Workers inject a started aiokafka producer; None → lifecycle events are only persisted in Postgres.
_lifecycle_producer: Any = None


def set_lifecycle_producer(producer: Any) -> None:
    global _lifecycle_producer
    _lifecycle_producer = producer


def _uuid(v: Any) -> uuid.UUID:
    return v if isinstance(v, uuid.UUID) else uuid.UUID(str(v))


def _get(obj: Any, *names: str, default: Any = None) -> Any:
    """Read the first present attribute/key among ``names`` (tolerates model field naming)."""
    cfg = getattr(obj, "config", None)
    for n in names:
        val = getattr(obj, n, None)
        if val is None and isinstance(cfg, dict):
            val = cfg.get(n)
        if val is not None:
            return val
    return default


def _input_text(value: Any) -> Any:
    if isinstance(value, dict):
        for k in ("message", "content", "input", "query", "text"):
            if isinstance(value.get(k), str):
                return value[k]
    return value


async def _publish_lifecycle(env: EventEnvelope | None, event_type: str, payload: dict) -> None:
    if _lifecycle_producer is None or env is None:
        return
    topic = WORKFLOW_EXECUTION_EVENTS if event_type.startswith("workflow.") else event_type
    try:
        out = env.derive(event_type, payload)
        await _lifecycle_producer.send_and_wait(topic, value=out.to_bytes(), key=out.key)
    except Exception as exc:  # noqa: BLE001 - observability events are best-effort
        log.warning("lifecycle.publish_failed", event_type=event_type, error=str(exc))


class DbRuntimeContext:
    """RuntimeContext implementation backed by Postgres/Redis/Kafka (Agent 2 modules)."""

    def __init__(self, session_factory, execution: Any, envelope: EventEnvelope | None):
        self.session_factory = session_factory
        self.execution_id = str(execution.id)
        self.organization_id = str(execution.organization_id)
        self._execution_uuid = execution.id
        self._org_uuid = _uuid(execution.organization_id)
        self._envelope = envelope

    async def emit(self, event_type: str, payload: dict, node_id: str | None = None) -> None:
        from app.executions.events import append_event  # type: ignore[import-not-found]

        async with self.session_factory() as session:
            await append_event(session, self._execution_uuid, event_type, payload, node_id=node_id)
            await session.commit()
        if event_type.startswith("node.") and self._envelope is not None:
            await _publish_lifecycle(self._envelope, "workflow.node." + event_type.split(".", 1)[1],
                                     {"node_id": node_id, **payload})

    async def get_chat_model(self, provider_id: str | None, model: str | None) -> Any:
        from app.llm.manager import get_chat_model  # type: ignore[import-not-found]

        async with self.session_factory() as session:
            return await get_chat_model(session, self._org_uuid,
                                        _uuid(provider_id) if provider_id else None, model)

    async def load_agent(self, agent_id: str, version: int | None) -> AgentSpec:
        from sqlalchemy import select

        from app.database.models import Agent, AgentVersion, Tool  # type: ignore[import-not-found]

        async with self.session_factory() as session:
            agent = await session.get(Agent, _uuid(agent_id))
            if agent is None or str(agent.organization_id) != self.organization_id:
                raise NodeExecutionError("agent", f"agent {agent_id} not found")
            ver = version or _get(agent, "current_version", "version", default=None)
            row = None
            if ver is not None:
                row = (await session.execute(select(AgentVersion).where(
                    AgentVersion.agent_id == agent.id, AgentVersion.version == ver))).scalar_one_or_none()
            src = row if row is not None else agent
            tools: list[dict] = []
            for tid in _get(src, "tool_ids", "tools", default=[]) or []:
                tool = await session.get(Tool, _uuid(tid if not isinstance(tid, dict) else tid["id"]))
                if tool is None or str(tool.organization_id) != self.organization_id:
                    continue
                tools.append({"id": str(tool.id), "name": _safe_tool_name(tool.name),
                              "description": _get(tool, "description", default="") or "",
                              "input_schema": _get(tool, "input_schema", default=None),
                              "version": _get(tool, "current_version", default=None)})
            provider = _get(src, "provider_id", "llm_provider_id")
            return AgentSpec(
                instructions=_get(src, "instructions", "system_prompt", default="") or "",
                provider_id=str(provider) if provider else None,
                model=_get(src, "model"),
                temperature=_get(src, "temperature"),
                tools=tools,
            )

    async def invoke_tool(self, tool_id: str, version: int | None, payload: Any) -> Any:
        if str(get_setting("EXECUTION_DISPATCH", "kafka")).lower() == "inline" or _lifecycle_producer is None:
            raise RuntimeError("tool execution requires the sandboxed tool-worker (EXECUTION_DISPATCH=kafka)")
        request_id = str(uuid.uuid4())
        env = EventEnvelope(
            event_type=TOOL_EXECUTION_REQUESTED, organization_id=self._org_uuid,
            execution_id=self._execution_uuid,
            correlation_id=self._envelope.correlation_id if self._envelope else uuid.uuid4(),
            resource_type="tool", resource_id=_uuid(tool_id), resource_version=int(version or 0),
            kind=self._envelope.kind if self._envelope else "workflow",
            payload={"request_id": request_id, "input": payload, "tool_version": version},
        )
        await _lifecycle_producer.send_and_wait(TOOL_EXECUTION_REQUESTED, value=env.to_bytes(), key=env.key)
        timeout = float(get_setting("SANDBOX_TIMEOUT_SECONDS", 30)) + DEFAULT_TOOL_TIMEOUT_S
        res = await get_redis().blpop([TOOL_RESULT_KEY.format(request_id=request_id)], timeout=int(timeout))
        if res is None:
            raise TimeoutError(f"tool {tool_id} did not respond within {int(timeout)}s")
        result = json.loads(res[1])
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "tool failed")
        return result.get("output")

    async def rag_search(self, query: str, top_k: int) -> list[dict]:
        from sqlalchemy import select

        from app.database.models import DocumentChunk  # type: ignore[import-not-found]
        from app.llm.manager import get_embeddings  # type: ignore[import-not-found]

        async with self.session_factory() as session:
            embeddings = await get_embeddings(session, self._org_uuid)
            vector = await embeddings.aembed_query(query)
            stmt = (select(DocumentChunk, DocumentChunk.embedding.cosine_distance(vector).label("distance"))
                    .where(DocumentChunk.organization_id == self._org_uuid)
                    .order_by("distance").limit(top_k))
            rows = (await session.execute(stmt)).all()
        return [{"content": _get(c, "content", "text", default=""), "score": round(1 - float(d), 4),
                 "metadata": _get(c, "metadata_", "meta", default={}) or {},
                 "document_id": str(_get(c, "document_id", default="")) or None} for c, d in rows]

    async def resolve_credential(self, ref: str) -> dict[str, str]:
        # Contract §17: app.credentials.service.resolve_credential(session, org_id, credential_id)
        from app.credentials.service import resolve_credential

        try:
            credential_id = uuid.UUID(str(ref))
        except ValueError as exc:
            raise ValueError(f"invalid credential_ref: {ref!r}") from exc
        async with self.session_factory() as session:
            secret: Any = await resolve_credential(session, self._org_uuid, credential_id)
        if secret is None or secret == "":
            # Fail closed: never send "Bearer None" or call the API unauthenticated.
            raise LookupError(f"credential {credential_id} not found in this organization")
        if isinstance(secret, dict):
            return {str(k): str(v) for k, v in secret.items()}
        return {"Authorization": f"Bearer {secret}"}

    async def is_cancelled(self) -> bool:
        try:
            return bool(await get_redis().exists(CANCEL_KEY.format(execution_id=self.execution_id)))
        except Exception as exc:  # noqa: BLE001
            log.warning("cancel_check_failed", error=str(exc))
            return False

    def allow_private_network(self) -> bool:
        return str(get_setting("APP_ENV", "development")).lower() == "development"


def _safe_tool_name(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "_-" else "_" for c in (name or "tool"))
    return cleaned[:64] or "tool"


async def _load_definition(session, execution: Any) -> dict:
    kind = str(execution.kind)
    target = _get(execution, "target_type", "resource_type")
    if kind == "workflow" or (kind == "chat" and target == "workflow"):
        from sqlalchemy import select

        from app.database.models import WorkflowVersion  # type: ignore[import-not-found]

        row = (await session.execute(select(WorkflowVersion).where(
            WorkflowVersion.workflow_id == execution.resource_id,
            WorkflowVersion.version == execution.resource_version))).scalar_one_or_none()
        if row is None:
            raise RuntimeError("workflow version not found")
        return row.definition
    if kind in ("agent", "agent_test", "chat"):
        return single_agent_definition(str(execution.resource_id), execution.resource_version)
    raise RuntimeError(f"execution kind {kind} is handled by the tool-worker")


async def _checkpointer():
    """MemorySaver by default; Postgres saver when LANGGRAPH_CHECKPOINTER=postgres and the extra is installed."""
    if str(get_setting("LANGGRAPH_CHECKPOINTER", "memory")).lower() == "postgres":
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # type: ignore[import-not-found]

            dsn = str(get_setting("DATABASE_URL", "")).replace("+asyncpg", "")
            cm = AsyncPostgresSaver.from_conn_string(dsn)
            saver = await cm.__aenter__()
            await saver.setup()
            return saver, cm
        except ImportError:
            log.warning("checkpointer.postgres_unavailable_fallback_memory")
    from langgraph.checkpoint.memory import MemorySaver

    return MemorySaver(), None


async def run_execution(execution_id: uuid.UUID, envelope: EventEnvelope | None = None,
                        session_factory: Any = None) -> None:
    """Run one queued execution to a terminal state. Idempotent: non-queued executions are skipped."""
    from app.executions.events import append_event, set_status  # type: ignore[import-not-found]

    if session_factory is None:
        from app.database.session import async_session_factory  # type: ignore[import-not-found]

        session_factory = async_session_factory
    from app.database.models import Execution  # type: ignore[import-not-found]

    execution_id = _uuid(execution_id)
    structlog.contextvars.bind_contextvars(execution_id=str(execution_id))
    async with session_factory() as session:
        execution = await session.get(Execution, execution_id)
        if execution is None:
            log.warning("runtime.execution_missing")
            return
        if execution.status != "queued":
            log.info("runtime.skip_not_queued", status=execution.status)
            return
        structlog.contextvars.bind_contextvars(correlation_id=str(execution.correlation_id))
        if await get_redis().exists(CANCEL_KEY.format(execution_id=execution_id)):
            await set_status(session, execution_id, "cancelled")
            await append_event(session, execution_id, "execution.cancelled", {})
            await session.commit()
            return
        await set_status(session, execution_id, "running")
        await append_event(session, execution_id, "execution.started", {"kind": str(execution.kind)})
        await session.commit()
        try:
            definition = await _load_definition(session, execution)
        except Exception as exc:  # noqa: BLE001
            await _finish(session_factory, execution, "failed", error=str(exc))
            return
        state_input = execution.input
        if str(execution.kind) in ("agent", "agent_test", "chat"):
            state_input = _input_text(execution.input)

    await _publish_lifecycle(envelope, AGENT_EXECUTION_STARTED, {"kind": str(execution.kind)})
    ctx = DbRuntimeContext(session_factory, execution, envelope)
    saver, cm = await _checkpointer()
    timeout = float(get_setting("EXECUTION_TIMEOUT_SECONDS", DEFAULT_EXECUTION_TIMEOUT_S))
    try:
        graph = compile_workflow(definition, ctx, checkpointer=saver)
        final = await asyncio.wait_for(
            graph.ainvoke({"input": state_input, "last_output": state_input, "outputs": {},
                           "execution_id": str(execution_id), "organization_id": ctx.organization_id,
                           "trace": []},
                          config={"configurable": {"thread_id": str(execution_id)}, "recursion_limit": 100}),
            timeout=timeout)
        await _finish(session_factory, execution, "succeeded", output=final.get("last_output"),
                      trace=final.get("trace"))
        await _publish_lifecycle(envelope, AGENT_EXECUTION_COMPLETED, {})
    except ExecutionCancelled:
        await _finish(session_factory, execution, "cancelled")
    except TimeoutError:
        await _finish(session_factory, execution, "failed", error=f"execution timed out after {int(timeout)}s")
        await _publish_lifecycle(envelope, AGENT_EXECUTION_FAILED, {"error": "timeout"})
    except Exception as exc:  # noqa: BLE001
        err = str(exc)[:4000]
        log.exception("runtime.execution_failed")
        await _finish(session_factory, execution, "failed", error=err,
                      node_id=getattr(exc, "node_id", None))
        await _publish_lifecycle(envelope, AGENT_EXECUTION_FAILED, {"error": err})
    finally:
        if cm is not None:
            await cm.__aexit__(None, None, None)


async def _finish(session_factory, execution: Any, status: str, *, output: Any = None, error: str | None = None,
                  node_id: str | None = None, trace: list | None = None) -> None:
    from app.executions.events import append_event, set_status  # type: ignore[import-not-found]

    async with session_factory() as session:
        await set_status(session, execution.id, status, output=_jsonable(output), error=error)
        payload: dict[str, Any] = {"status": status}
        if status == "succeeded":
            payload.update(output=_jsonable(output), trace=trace or [])
        elif error:
            payload.update(error=error, node_id=node_id)
        await append_event(session, execution.id, f"execution.{'completed' if status == 'succeeded' else status}",
                           payload)
        if status == "succeeded" and str(execution.kind) == "chat":
            await _write_chat_message(session, execution, output)
        await session.commit()
    log.info("runtime.execution_finished", status=status, finished_at=datetime.now(UTC).isoformat())


async def _write_chat_message(session, execution: Any, output: Any) -> None:
    from app.database.models import ChatMessage  # type: ignore[import-not-found]

    from app.messaging.dispatch import model_kwargs

    session_id = _get(execution, "chat_session_id", "session_id")
    if session_id is None and isinstance(execution.input, dict):
        session_id = execution.input.get("session_id")
    if session_id is None:
        log.warning("runtime.chat_session_unknown")
        return
    content = output if isinstance(output, str) else json.dumps(output, default=str)
    session.add(ChatMessage(**model_kwargs(ChatMessage, id=uuid.uuid4(), session_id=_uuid(session_id),
                                           role="assistant", content=content, execution_id=execution.id)))


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return json.loads(json.dumps(value, default=str))
