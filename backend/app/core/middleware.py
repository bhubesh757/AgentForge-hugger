"""Request-id + access log + Prometheus metrics middleware (pure ASGI)."""

from __future__ import annotations

import time

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.request_context import set_request_id
from app.monitoring.metrics import HTTP_LATENCY, HTTP_REQUESTS

log = structlog.get_logger("access")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        incoming = headers.get(b"x-request-id")
        rid = set_request_id(incoming.decode("latin-1") if incoming else None)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=rid)
        start = time.perf_counter()
        status_holder = {"status": 500}

        async def _send(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                hdrs = list(message.get("headers") or [])
                hdrs.append((b"x-request-id", rid.encode()))
                message["headers"] = hdrs
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            elapsed = time.perf_counter() - start
            route = scope.get("route")
            path = getattr(route, "path", None) or "unmatched"
            method = scope.get("method", "GET")
            HTTP_REQUESTS.labels(method, path, str(status_holder["status"])).inc()
            HTTP_LATENCY.labels(method, path).observe(elapsed)
            if path not in {"/health", "/metrics", "/api/v1/health", "/api/v1/metrics"}:
                log.info(
                    "http_request",
                    method=method,
                    path=path,
                    status=status_holder["status"],
                    duration_ms=round(elapsed * 1000, 2),
                )
