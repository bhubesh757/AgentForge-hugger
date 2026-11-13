"""Structured JSON logging via structlog. Never log secrets."""

from __future__ import annotations

import logging
import sys

import structlog

_SENSITIVE = {
    "password",
    "api_key",
    "value",
    "token",
    "refresh_token",
    "access_token",
    "secret",
    "authorization",
}


def _redact(_: object, __: str, event_dict: dict) -> dict:
    for k in list(event_dict):
        if k.lower() in _SENSITIVE:
            event_dict[k] = "***"
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    lvl = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=lvl)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(lvl),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
