"""workflow worker: python -m workers.workflow_worker (run from repo root; backend/ is added to sys.path)."""

from workers.kafka_consumer.handlers import execution_handler_factory
from workers.kafka_consumer.runner import main

from app.messaging import topics  # noqa: E402


def run() -> None:
    main("workflow-worker", [topics.WORKFLOW_EXECUTION_REQUESTED], topics.GROUP_WORKFLOW_WORKER, execution_handler_factory)


if __name__ == "__main__":
    run()
