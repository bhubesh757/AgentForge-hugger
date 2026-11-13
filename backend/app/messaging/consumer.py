"""Base Kafka consumer: manual commits, idempotency, retry with backoff, DLQ, graceful shutdown."""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from app.messaging.kafka import EventEnvelope, create_consumer, create_producer, dumps
from app.messaging.redis_client import EVENT_DONE_KEY, get_redis
from app.messaging.topics import dlq_topic

log = structlog.get_logger(__name__)

RETRY_DELAYS_S: tuple[float, ...] = (1.0, 4.0, 16.0)
DONE_TTL_S = 24 * 3600

Handler = Callable[[EventEnvelope], Awaitable[None]]


class PermanentError(Exception):
    """Handler error that must not be retried (goes straight to DLQ)."""


class BaseConsumer:
    def __init__(
        self,
        topics: list[str] | tuple[str, ...],
        group_id: str,
        handler: Handler,
        *,
        consumer: Any = None,
        producer: Any = None,
        redis: Any = None,
        retry_delays: tuple[float, ...] = RETRY_DELAYS_S,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.topics = tuple(topics)
        self.group_id = group_id
        self.handler = handler
        self._consumer = consumer
        self._producer = producer
        self._redis = redis
        self.retry_delays = retry_delays
        self._sleep = sleep
        self._stop = asyncio.Event()
        self.running = False
        self.processed = 0
        self.dead_lettered = 0

    @property
    def redis(self):
        return self._redis if self._redis is not None else get_redis()

    # ------------------------------------------------------------ lifecycle
    def request_stop(self) -> None:
        self._stop.set()

    def install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self.request_stop)
            except (NotImplementedError, RuntimeError):  # pragma: no cover - non-unix
                pass

    async def start(self) -> None:
        if self._consumer is None:
            self._consumer = create_consumer(*self.topics, group_id=self.group_id)
        if self._producer is None:
            self._producer = create_producer()
        await self._producer.start()
        await self._consumer.start()
        self.running = True
        log.info("consumer.started", topics=self.topics, group_id=self.group_id)

    async def stop(self) -> None:
        self.running = False
        for client in (self._consumer, self._producer):
            if client is not None:
                try:
                    await client.stop()
                except Exception as exc:  # noqa: BLE001
                    log.warning("consumer.stop_error", error=str(exc))
        log.info("consumer.stopped", group_id=self.group_id)

    async def run(self) -> None:
        await self.start()
        try:
            while not self._stop.is_set():
                batch = await self._consumer.getmany(timeout_ms=1000, max_records=1)
                for _tp, messages in batch.items():
                    for msg in messages:
                        await self.process_message(msg)
                        await self._consumer.commit()
        finally:
            await self.stop()

    # ------------------------------------------------------------ processing
    async def process_message(self, msg: Any) -> str:
        """Process one record. Returns outcome: processed|skipped|dlq. Never raises (except cancel)."""
        structlog.contextvars.clear_contextvars()
        try:
            env = EventEnvelope.from_bytes(msg.value)
        except Exception as exc:  # noqa: BLE001 - poison message
            log.error("consumer.invalid_envelope", topic=msg.topic, error=str(exc)[:500])
            await self._dead_letter(msg.topic, msg.value, f"invalid envelope: {exc}", msg.key)
            return "dlq"

        structlog.contextvars.bind_contextvars(
            correlation_id=str(env.correlation_id), execution_id=str(env.execution_id),
            event_id=str(env.event_id), event_type=env.event_type)
        done_key = EVENT_DONE_KEY.format(event_id=env.event_id)
        try:
            if await self.redis.exists(done_key):
                log.info("consumer.duplicate_skipped")
                return "skipped"
        except Exception as exc:  # noqa: BLE001 - Redis down: DB status check in handler still guards
            log.warning("consumer.idempotency_check_failed", error=str(exc))

        last_error = ""
        for attempt in range(1, len(self.retry_delays) + 2):
            try:
                await self.handler(env.model_copy(update={"attempt": attempt}))
                last_error = ""
                break
            except asyncio.CancelledError:
                raise
            except PermanentError as exc:
                last_error = str(exc)
                attempt = len(self.retry_delays) + 1
                break
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
                log.warning("consumer.handler_failed", attempt=attempt, error=last_error[:500])
                if attempt <= len(self.retry_delays):
                    await self._sleep(self.retry_delays[attempt - 1])
        else:
            attempt = len(self.retry_delays) + 1

        if last_error:
            failed = env.model_copy(update={"attempt": attempt})
            await self._dead_letter(msg.topic, failed.to_bytes(), last_error, env.key)
            await self._mark_done(done_key)
            return "dlq"
        await self._mark_done(done_key)
        self.processed += 1
        return "processed"

    async def _mark_done(self, key: str) -> None:
        try:
            await self.redis.set(key, "1", ex=DONE_TTL_S)
        except Exception as exc:  # noqa: BLE001
            log.warning("consumer.mark_done_failed", error=str(exc))

    async def _dead_letter(self, topic: str, value: bytes, error: str, key: bytes | None) -> None:
        self.dead_lettered += 1
        body = dumps({"original_topic": topic, "error": error[:2000], "group_id": self.group_id,
                      "message": value.decode("utf-8", "replace") if isinstance(value, bytes) else value})
        try:
            await self._producer.send_and_wait(dlq_topic(topic), value=body, key=key)
            log.error("consumer.dead_lettered", dlq=dlq_topic(topic), error=error[:500])
        except Exception as exc:  # noqa: BLE001
            log.critical("consumer.dlq_publish_failed", error=str(exc))
            raise
