"""Generic entry: python -m workers.kafka_consumer <agent|workflow|tool>."""

import sys

from workers.kafka_consumer import runner  # noqa: F401  (sets sys.path for backend)

WORKERS = {"agent": "workers.agent_worker.__main__", "workflow": "workers.workflow_worker.__main__",
           "tool": "workers.tool_worker.__main__"}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in WORKERS:
        sys.exit("usage: python -m workers.kafka_consumer agent|workflow|tool")
    import importlib

    importlib.import_module(WORKERS[sys.argv[1]]).run()
