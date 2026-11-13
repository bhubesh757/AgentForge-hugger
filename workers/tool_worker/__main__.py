"""Tool worker: runs tool code in the hardened Docker sandbox. python -m workers.tool_worker

Handles two request shapes on ``tool.execution.requested``:
  * kind=tool_test (no payload.request_id): a standalone execution — owns its status/events.
  * payload.request_id set: a tool call from a workflow/agent run — result is RPUSHed to
    Redis ``tool:result:<request_id>`` for the waiting runtime (BLPOP).
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

from workers.kafka_consumer.runner import main

from app.messaging import topics  # noqa: E402
from app.messaging.consumer import BaseConsumer, PermanentError  # noqa: E402
from app.messaging.kafka import EventEnvelope  # noqa: E402
from app.messaging.redis_client import TOOL_RESULT_KEY, get_redis  # noqa: E402

RESULT_TTL_S = 300
_runner: Any = None


def get_runner():
    global _runner
    if _runner is None:
        from sandbox.executor.host import SandboxRunner

        _runner = SandboxRunner()
    return _runner


async def load_tool_code(session, env: EventEnvelope, version: int | None) -> str:
    from sqlalchemy import select

    from app.database.models import Tool, ToolVersion  # type: ignore[import-not-found]

    tool = await session.get(Tool, env.resource_id)
    if tool is None or tool.organization_id != env.organization_id:
        raise PermanentError(f"tool {env.resource_id} not found in organization")
    ver = version or getattr(tool, "current_version", None)
    row = None
    if ver:
        row = (await session.execute(select(ToolVersion).where(
            ToolVersion.tool_id == tool.id, ToolVersion.version == ver))).scalar_one_or_none()
    code = getattr(row, "code", None) if row is not None else getattr(tool, "code", None)
    if not code:
        raise PermanentError("tool has no code")
    return code


async def run_in_sandbox(code: str, tool_input: Any) -> dict:
    return await asyncio.to_thread(get_runner().run, code, tool_input)


def tool_handler_factory(consumer: BaseConsumer):
    from app.database.session import async_session_factory  # type: ignore[import-not-found]
    from app.executions.events import append_event, set_status  # type: ignore[import-not-found]

    async def publish_event(env: EventEnvelope, payload: dict) -> None:
        out = env.derive("tool.execution.completed" if payload.get("ok") else "tool.execution.failed", payload)
        try:
            await consumer._producer.send_and_wait(topics.TOOL_EXECUTION_EVENTS, value=out.to_bytes(), key=out.key)
        except Exception:  # noqa: BLE001, S110 - observability only
            pass

    async def handle(env: EventEnvelope) -> None:
        request_id = env.payload.get("request_id")
        version = env.payload.get("tool_version") or env.resource_version or None
        if request_id:
            uuid.UUID(str(request_id))
            async with async_session_factory() as session:
                try:
                    code = await load_tool_code(session, env, version)
                    result = await run_in_sandbox(code, env.payload.get("input"))
                except PermanentError as exc:
                    result = {"ok": False, "error": str(exc)}
            key = TOOL_RESULT_KEY.format(request_id=request_id)
            redis = get_redis()
            await redis.rpush(key, json.dumps(result, default=str))
            await redis.expire(key, RESULT_TTL_S)
            await publish_event(env, {"request_id": request_id, "ok": result.get("ok")})
            return

        # standalone tool_test execution
        from app.database.models import Execution  # type: ignore[import-not-found]

        async with async_session_factory() as session:
            execution = await session.get(Execution, env.execution_id)
            if execution is None or execution.status != "queued":
                return  # idempotency: already handled / cancelled
            await set_status(session, execution.id, "running")
            await append_event(session, execution.id, "execution.started", {"kind": "tool_test"})
            await session.commit()
            t0 = time.monotonic()
            try:
                code = await load_tool_code(session, env, version)
                result = await run_in_sandbox(code, execution.input)
            except PermanentError as exc:
                result = {"ok": False, "error": str(exc)}
            ms = int((time.monotonic() - t0) * 1000)
            if result.get("logs"):
                await append_event(session, execution.id, "log",
                                   {"level": "info", "message": result["logs"][-4000:]})
            if result.get("ok"):
                await set_status(session, execution.id, "succeeded", output=result.get("output"))
                await append_event(session, execution.id, "execution.completed",
                                   {"status": "succeeded", "output": result.get("output"), "duration_ms": ms})
            else:
                await set_status(session, execution.id, "failed", error=result.get("error"))
                await append_event(session, execution.id, "execution.failed",
                                   {"status": "failed", "error": result.get("error"),
                                    "error_type": result.get("error_type")})
            await session.commit()
        await publish_event(env, {"ok": result.get("ok"), "duration_ms": ms})

    return handle


def run() -> None:
    main("tool-worker", [topics.TOOL_EXECUTION_REQUESTED], topics.GROUP_TOOL_WORKER, tool_handler_factory)


if __name__ == "__main__":
    run()
