"""Handler factories shared by agent and workflow workers."""

from __future__ import annotations

from workers.kafka_consumer import runner  # noqa: F401  (sys.path setup)

from app.messaging.consumer import BaseConsumer  # noqa: E402
from app.messaging.kafka import EventEnvelope  # noqa: E402


def execution_handler_factory(consumer: BaseConsumer):
    """Run the LangGraph runtime for an execution; runtime itself skips non-queued executions."""
    from app.orchestrator import runtime

    async def handle(env: EventEnvelope) -> None:
        runtime.set_lifecycle_producer(consumer._producer)
        await runtime.run_execution(env.execution_id, env)

    return handle
