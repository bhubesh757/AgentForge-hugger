"""agent worker: python -m workers.agent_worker (run from repo root; backend/ is added to sys.path)."""

from workers.kafka_consumer.handlers import execution_handler_factory
from workers.kafka_consumer.runner import main

from app.messaging import topics  # noqa: E402


def run() -> None:
    main("agent-worker", [topics.AGENT_EXECUTION_REQUESTED], topics.GROUP_AGENT_WORKER, execution_handler_factory)


if __name__ == "__main__":
    run()
