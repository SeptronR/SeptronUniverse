"""Beat schedule catalogue — docs/Technical_Architecture.md §8.

Phases append entries with ``register_beat("<module>.<job>", task, schedule)``. Phase 01 registers the platform jobs
(``app/tasks/platform.py``): ``jobs.cleanup`` (daily 03:00 UTC), ``read_only.expire`` (1 min), ``integrations.health``
(15 min) and ``partitions.ensure_next_month`` (monthly on the 25th, 02:00 UTC — creates the current and next month's
partitions ahead of time; the default partitions catch anything that arrives before it runs). Phase 02 adds the auth
and entitlement jobs (``app/tasks/auth.py``): ``auth.cleanup_sessions`` (hourly), ``auth.expire_time_boxed_accounts``
(daily 01:00), ``subscriptions.reminders`` (daily 06:00) and ``usage.meter`` (monthly, 1st 02:30). Phase 03 adds
``sequences.reset`` (daily 00:05) and ``terms.auto_status`` (daily 00:15) — ``app/tasks/institution.py``; Phase 04
``workflow.escalate`` (15 min), ``notifications.retry_failed`` (10 min) and ``notifications.digest`` (daily 08:00,
weekly Mondays 08:05) — ``app/tasks/notifications.py``; Phase 06 ``hr.leave_accrual`` (1st 01:00), ``hr.leave_carry_forward``
(1st 01:30, acts on the leave-year start month), ``hr.document_expiry`` (Mondays 07:00), ``attendance.auto_mark_holidays``
(daily 00:10) and ``payroll.reminder`` (daily 06:30, acts on the ``payroll.reminder_day``) — ``app/tasks/hr.py``;
Phase 07 ``students.document_expiry`` (Mondays 07:10) and ``students.undertaking_reminders`` (daily 07:20, acts on the
academic year's first day and weekly for four weeks) — ``app/tasks/students.py``.
"""

from typing import Any

from celery.schedules import crontab

from app.tasks.celery_app import celery

BEAT_SCHEDULE: dict[str, dict[str, Any]] = {
    "outbox.relay": {"task": "outbox.relay", "schedule": 5.0, "options": {"queue": "scheduled"}},
}


def register_beat(name: str, task: str, schedule: Any, queue: str = "scheduled", **kwargs: Any) -> None:
    BEAT_SCHEDULE[name] = {"task": task, "schedule": schedule, "options": {"queue": queue}, **kwargs}
    # ---- Phase 08 admissions (app/tasks/admissions.py) -----------------------------------------------------------------------


register_beat("admissions.lapse_allotments", "beat.admissions.lapse_allotments", crontab(minute=7))
register_beat("admissions.close_cycles", "beat.admissions.close_cycles", crontab(hour=0, minute=20))
register_beat("enquiries.follow_up_reminders", "beat.enquiries.follow_up_reminders", crontab(hour=9, minute=0))

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

# ---- Phase 03 institution structure / sessions (app/tasks/institution.py) ------------------------------------------------
register_beat("sequences.reset", "beat.sequences.reset", crontab(hour=0, minute=5))
register_beat("terms.auto_status", "beat.terms.auto_status", crontab(hour=0, minute=15))

# ---- Phase 04 communication core / workflow engine (app/tasks/notifications.py) ------------------------------------------
register_beat("workflow.escalate", "beat.workflow.escalate", crontab(minute="*/15"))
register_beat("notifications.retry_failed", "beat.notifications.retry_failed", crontab(minute="*/10"))
register_beat(
    "notifications.digest", "beat.notifications.digest", crontab(hour=8, minute=0), kwargs={"period": "daily"}
)
register_beat(
    "notifications.digest_weekly", "beat.notifications.digest", crontab(hour=8, minute=5), kwargs={"period": "weekly"}
)

# ---- Phase 06 HR (app/tasks/hr.py) --------------------------------------------------------------------------------------
register_beat("hr.leave_accrual", "beat.hr.leave_accrual", crontab(day_of_month="1", hour=1, minute=0))
register_beat("hr.leave_carry_forward", "beat.hr.leave_carry_forward", crontab(day_of_month="1", hour=1, minute=30))
register_beat("hr.document_expiry", "beat.hr.document_expiry", crontab(day_of_week="1", hour=7, minute=0))
register_beat("attendance.auto_mark_holidays", "beat.attendance.auto_mark_holidays", crontab(hour=0, minute=10))
register_beat("payroll.reminder", "beat.payroll.reminder", crontab(hour=6, minute=30))

# ---- Phase 07 students (app/tasks/students.py) -------------------------------------------------------------------------
register_beat("students.document_expiry", "beat.students.document_expiry", crontab(day_of_week="1", hour=7, minute=10))
register_beat("students.undertaking_reminders", "beat.students.undertaking_reminders", crontab(hour=7, minute=20))

# ---- Phase 08 admissions (app/tasks/admissions.py) -----------------------------------------------------------------------
register_beat("admissions.lapse_allotments", "beat.admissions.lapse_allotments", crontab(minute=7))
register_beat("admissions.close_cycles", "beat.admissions.close_cycles", crontab(hour=0, minute=20))
register_beat("enquiries.follow_up_reminders", "beat.enquiries.follow_up_reminders", crontab(hour=9, minute=0))

# ---- Phase 09 registration (app/tasks/registration.py) -------------------------------------------------------------------
register_beat("registration.window_status", "beat.registration.window_status", 300.0)
register_beat("registration.lock_windows", "beat.registration.lock_windows", crontab(minute=17))
register_beat("waitlist.expire", "beat.waitlist.expire", crontab(minute=27))
register_beat("registration.reminders", "beat.registration.reminders", crontab(hour=8, minute=30))

# ---- Phase 10 timetable (app/tasks/timetable.py) ------------------------------------------------------------------------
register_beat("sessions.mark_missed", "beat.sessions.mark_missed", crontab(hour=23, minute=40))

# ---- Phase 11 attendance (app/tasks/attendance.py) — crontab in UTC like the rest; institution-local "today" inside -----
register_beat("attendance.auto_finalize", "beat.attendance.auto_finalize", crontab(hour=19, minute=0))
register_beat(
    "attendance.missing_sessions_digest", "beat.attendance.missing_sessions_digest", crontab(hour=12, minute=30)
)
register_beat("attendance.checkpoints", "beat.attendance.checkpoints", crontab(hour=1, minute=30))
register_beat("attendance.streak_alerts", "beat.attendance.streak_alerts", crontab(hour=18, minute=25))

celery.conf.beat_schedule = BEAT_SCHEDULE
