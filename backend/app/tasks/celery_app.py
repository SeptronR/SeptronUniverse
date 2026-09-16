"""Celery application — Prompts/00_PREREQUISITE_Project_Setup.md §3.21 (docs/Technical_Architecture.md §8).

Every task signature starts with ``institution_id``; the task opens ``tenant_session(institution_id)`` (RLS context)
and checks ``features.is_enabled(institution_id, key)`` before acting. Tasks are idempotent.
"""

from celery import Celery

from app.core.config import settings

celery = Celery(
    "universe",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.outbox",
        "app.tasks.beat",
        "app.tasks.platform",
        "app.tasks.notifications",
        "app.tasks.documents",
        "app.tasks.reports",
        "app.tasks.integrations",
    ],
)
celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
    task_default_queue="scheduled",
    task_routes={
        "notifications.*": {"queue": "notifications"},
        "emails.*": {"queue": "emails"},
        "documents.*": {"queue": "documents"},
        "reports.*": {"queue": "reports"},
        "integrations.*": {"queue": "integrations"},
        "outbox.*": {"queue": "scheduled"},
        "beat.*": {"queue": "scheduled"},
        "search.*": {"queue": "scheduled"},
        "webhooks.*": {"queue": "integrations"},
        "jobs.*": {"queue": "reports"},
    },
)
