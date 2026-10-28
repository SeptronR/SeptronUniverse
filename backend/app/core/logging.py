"""JSON logging with request/tenant/user ids (structlog) and optional Sentry — docs/Technical_Architecture.md §13."""

import logging
import re
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

from app.core.config import settings

# Phase 43: inventory field names (identifier / financial / health / biometric) never reach the logs
REDACT_KEYS = frozenset(
    {
        "aadhaar",
        "aadhaar_number",
        "aadhaar_encrypted",
        "pan",
        "pan_number",
        "passport_number",
        "bank_details",
        "account_number",
        "ifsc",
        "salary",
        "password",
        "new_password",
        "otp",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "diagnosis",
        "prescription",
        "counselling_notes",
        "notes_encrypted",
    }
)
_AADHAAR = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")
_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")


def _scrub(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return value
    if isinstance(value, dict):
        return {k: ("[redacted]" if str(k).lower() in REDACT_KEYS else _scrub(v, depth + 1)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_scrub(v, depth + 1) for v in value]
    if isinstance(value, str):
        return _PAN.sub("[pan]", _AADHAAR.sub("[aadhaar]", value))
    return value


def redact_pii(_logger: Any, _method: str, event_dict: MutableMapping[str, Any]) -> dict[str, Any]:
    """structlog processor: drops values of PII keys and Aadhaar / PAN patterns in strings."""
    return dict(_scrub(event_dict))


def configure_logging() -> None:
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    renderer = (
        structlog.processors.JSONRenderer() if settings.APP_ENV != "development" else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            redact_pii,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    if settings.SENTRY_DSN:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.SENTRY_DSN, environment=settings.APP_ENV, traces_sample_rate=0.1, send_default_pii=False
        )
