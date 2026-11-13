"""Prometheus metrics registry."""

from prometheus_client import Counter, Histogram

HTTP_REQUESTS = Counter("agentforge_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram("agentforge_http_request_duration_seconds", "HTTP latency", ["method", "route"])
EXECUTIONS_CREATED = Counter("agentforge_executions_created_total", "Executions created", ["kind"])
AUTH_EVENTS = Counter("agentforge_auth_events_total", "Auth events", ["event"])
