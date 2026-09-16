"""Beat schedule catalogue — docs/Technical_Architecture.md §8.

Phases append entries to ``BEAT_SCHEDULE`` (``"<module>.<job>": {"task": ..., "schedule": ...}``). Phase 01 adds
``jobs.cleanup``, ``read_only.expire``, ``integrations.health`` and ``partitions.ensure_next_month``.
"""

from typing import Any

from celery.schedules import crontab  # noqa: F401  (used by phase entries)

from app.tasks.celery_app import celery

BEAT_SCHEDULE: dict[str, dict[str, Any]] = {
    "outbox.relay": {"task": "outbox.relay", "schedule": 5.0, "options": {"queue": "scheduled"}},
}


def register_beat(name: str, task: str, schedule: Any, queue: str = "scheduled", **kwargs: Any) -> None:
    BEAT_SCHEDULE[name] = {"task": task, "schedule": schedule, "options": {"queue": queue}, **kwargs}
    celery.conf.beat_schedule = BEAT_SCHEDULE


celery.conf.beat_schedule = BEAT_SCHEDULE
