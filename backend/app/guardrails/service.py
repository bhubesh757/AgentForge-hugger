"""Simple output guardrails: PII regex redaction + max chars."""

from __future__ import annotations

import re

PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "EMAIL": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "CARD": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "PHONE": re.compile(r"(?<!\w)\+?\d[\d\s().-]{8,}\d\b"),
}


def redact_pii(text: str) -> str:
    for label, pat in PII_PATTERNS.items():
        text = pat.sub(f"[REDACTED_{label}]", text)
    return text


def apply_guardrails(text: str, *, block_pii: bool = False, max_output_chars: int | None = None) -> str:
    if block_pii:
        text = redact_pii(text)
    if max_output_chars is not None and len(text) > max_output_chars:
        text = text[:max_output_chars]
    return text
