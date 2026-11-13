"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import install_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.redis import close_redis
from app.monitoring.router import VERSION, health, metrics, ready

log = structlog.get_logger(__name__)

TAGS = [
    {"name": n}
    for n in (
        "auth",
        "organizations",
        "llm",
        "credentials",
        "agents",
        "tools",
        "workflows",
        "executions",
        "chat",
        "rag",
        "deployments",
        "audit",
        "monitoring",
    )
]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    relay = settings.EXECUTION_DISPATCH == "kafka"
    if relay:
        try:
            from app.messaging.outbox_relay import start_relay

            await start_relay()
        except Exception as exc:  # noqa: BLE001 - API must still serve; /ready reports kafka state
            log.error("outbox_relay.start_failed", error=str(exc))
            relay = False
    try:
        yield
    finally:
        if relay:
            try:
                from app.messaging.outbox_relay import stop_relay

                await stop_relay()
            except Exception as exc:  # noqa: BLE001
                log.error("outbox_relay.stop_failed", error=str(exc))
        await close_redis()


def create_app() -> FastAPI:
    configure_logging(settings.LOG_LEVEL)
    app = FastAPI(
        title="AgentForge AI API",
        version=VERSION,
        openapi_tags=TAGS,
        lifespan=lifespan,
        description="Multi-tenant platform for building, running and monitoring AI agents and workflows.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)
    install_exception_handlers(app)
    app.include_router(api_router)
    for path, fn in (("/health", health), ("/ready", ready), ("/metrics", metrics)):
        app.add_api_route(path, fn, methods=["GET"], include_in_schema=False)
    return app


app = create_app()
