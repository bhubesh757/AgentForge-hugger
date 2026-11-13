"""Shared worker runner: logging, health server, consumer lifecycle, graceful shutdown."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import Awaitable, Callable

import structlog

# Allow `python -m workers.x` from repo root without PYTHONPATH=backend.
_BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "backend")
if os.path.isdir(_BACKEND) and _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from app.messaging.consumer import BaseConsumer  # noqa: E402
from app.messaging.kafka import EventEnvelope  # noqa: E402

log = structlog.get_logger(__name__)


def configure_logging() -> None:
    level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    logging.basicConfig(level=level, stream=sys.stdout, format="%(message)s")
    structlog.configure(
        processors=[structlog.contextvars.merge_contextvars, structlog.processors.add_log_level,
                    structlog.processors.TimeStamper(fmt="iso"), structlog.processors.format_exc_info,
                    structlog.processors.JSONRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(level),
    )


class HealthServer:
    """Minimal HTTP/1.1 health endpoint (stdlib asyncio). 200 when the consumer is running, else 503."""

    def __init__(self, is_healthy: Callable[[], bool], port: int | None = None, host: str = "0.0.0.0"):  # noqa: S104
        self.is_healthy = is_healthy
        self.port = int(port if port is not None else os.getenv("WORKER_HEALTH_PORT", "8081"))
        self.host = host
        self._server: asyncio.base_events.Server | None = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await asyncio.wait_for(reader.readline(), timeout=5)
            ok = self.is_healthy()
            body = b'{"status":"ok"}' if ok else b'{"status":"unavailable"}'
            status = b"200 OK" if ok else b"503 Service Unavailable"
            writer.write(b"HTTP/1.1 " + status + b"\r\nContent-Type: application/json\r\nContent-Length: "
                         + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
            await writer.drain()
        except (TimeoutError, ConnectionError):
            pass
        finally:
            writer.close()

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        log.info("health.started", port=self.port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()


async def run_worker(name: str, topics: list[str], group_id: str,
                     handler_factory: Callable[[BaseConsumer], Callable[[EventEnvelope], Awaitable[None]]]) -> None:
    configure_logging()
    structlog.contextvars.bind_contextvars(worker=name)
    async def handler(env: EventEnvelope) -> None:
        await real_handler(env)

    consumer = BaseConsumer(topics, group_id, handler)
    real_handler = handler_factory(consumer)
    consumer.install_signal_handlers()
    health = HealthServer(lambda: consumer.running)
    await health.start()
    try:
        await consumer.run()
    finally:
        await health.stop()
        try:
            from app.messaging.redis_client import close_redis

            await close_redis()
        except Exception:  # noqa: BLE001, S110
            pass
        log.info("worker.exited", worker=name)


def main(name: str, topics: list[str], group_id: str, handler_factory) -> None:
    asyncio.run(run_worker(name, topics, group_id, handler_factory))
