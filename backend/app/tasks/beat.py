"""Beat schedule catalogue — docs/Technical_Architecture.md §8.

Phases append entries with ``register_beat("<module>.<job>", task, schedule)``. Phase 01 registers the platform jobs
(``app/tasks/platform.py``): ``jobs.cleanup`` (daily 03:00 UTC), ``read_only.expire`` (1 min), ``integrations.health``
(15 min) and ``partitions.ensure_next_month`` (monthly on the 25th, 02:00 UTC — creates the current and next month's
partitions ahead of time; the default partitions catch anything that arrives before it runs). Phase 02 adds the auth
and entitlement jobs (``app/tasks/auth.py``): ``auth.cleanup_sessions`` (hourly), ``auth.expire_time_boxed_accounts``
(daily 01:00), ``subscriptions.reminders`` (daily 06:00) and ``usage.meter`` (monthly, 1st 02:30).
"""

from typing import Any

from celery.schedules import crontab

from app.tasks.celery_app import celery

BEAT_SCHEDULE: dict[str, dict[str, Any]] = {
    "outbox.relay": {"task": "outbox.relay", "schedule": 5.0, "options": {"queue": "scheduled"}},
}


def register_beat(name: str, task: str, schedule: Any, queue: str = "scheduled", **kwargs: Any) -> None:
    BEAT_SCHEDULE[name] = {"task": task, "schedule": schedule, "options": {"queue": queue}, **kwargs}
    celery.conf.beat_schedule = BEAT_SCHEDULE


# ---- Phase 01 platform jobs ------------------------------------------------------------------------------------------
register_beat("jobs.cleanup", "beat.jobs.cleanup", crontab(hour=3, minute=0))
register_beat("read_only.expire", "beat.read_only.expire", 60.0)
register_beat("integrations.health", "beat.integrations.health", crontab(minute="*/15"))
register_beat(
    "partitions.ensure_next_month", "beat.partitions.ensure_next_month", crontab(day_of_month="25", hour=2, minute=0)
)

# ---- Phase 02 auth / entitlement jobs (app/tasks/auth.py) --------------------------------------------------------------
register_beat("auth.cleanup_sessions", "beat.auth.cleanup_sessions", crontab(minute=5))
register_beat("auth.expire_time_boxed_accounts", "beat.auth.expire_time_boxed_accounts", crontab(hour=1, minute=0))
register_beat("subscriptions.reminders", "beat.subscriptions.reminders", crontab(hour=6, minute=0))
register_beat("usage.meter", "beat.usage.meter", crontab(day_of_month="1", hour=2, minute=30))

celery.conf.beat_schedule = BEAT_SCHEDULE
