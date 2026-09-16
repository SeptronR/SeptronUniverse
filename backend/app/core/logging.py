"""JSON logging with request/tenant/user ids (structlog) and optional Sentry — docs/Technical_Architecture.md §13."""

import logging
import sys

import structlog

from app.core.config import settings


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
