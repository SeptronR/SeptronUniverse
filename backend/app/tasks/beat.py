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

# ---- Phase 12 fees (app/tasks/fees.py) — UTC crontab ≈ IST times in the comments ------------------------------------------
register_beat("fees.late_fees", "beat.fees.late_fees", crontab(hour=19, minute=10))  # 00:40 IST
register_beat("fees.due_reminders", "beat.fees.due_reminders", crontab(hour=2, minute=30))  # 08:00 IST
register_beat("fees.overdue_holds", "beat.fees.overdue_holds", crontab(hour=19, minute=20))  # 00:50 IST
register_beat("fees.day_book_close_reminder", "beat.fees.day_book_close_reminder", crontab(hour=12, minute=30))  # 18:00
register_beat("fees.gateway_status_poll", "beat.fees.gateway_status_poll", 600.0)

# ---- Phase 13 assessment / LMS (app/tasks/assessment.py) ---------------------------------------------------------------------
register_beat(
    "assessment.deadline_reminders", "beat.assessment.deadline_reminders", crontab(hour=3, minute=30)
)  # 09:00 IST
register_beat("assessment.auto_lock", "beat.assessment.auto_lock", crontab(hour=19, minute=30))  # 01:00 IST
register_beat("assignments.close_due", "beat.assignments.close_due", crontab(minute=12))
register_beat("quizzes.auto_submit", "beat.quizzes.auto_submit", 60.0)

# ---- Phase 14 exams (app/tasks/exams.py) ---------------------------------------------------------------------------------
register_beat("exams.session_auto_status", "beat.exams.session_auto_status", crontab(hour=0, minute=45))  # 06:15 IST
register_beat("exams.lapse_fee_pending", "beat.exams.lapse_fee_pending", crontab(minute=37))
register_beat("exams.duty_reminders", "beat.exams.duty_reminders", crontab(hour=2, minute=30))  # 08:00 IST

# ---- Phase 15 results (app/tasks/results.py) -----------------------------------------------------------------------------
register_beat("valuation.due_reminders", "beat.valuation.due_reminders", crontab(hour=3, minute=0))  # 08:30 IST
register_beat("results.publish_notifications_retry", "beat.results.publish_notifications_retry", 600.0)
register_beat("scripts.retention_check", "beat.scripts.retention_check", crontab(day_of_week=0, hour=20, minute=15))

# ---- Phase 16 post-result services (app/tasks/post_result.py) ----------------------------------------------------------------
register_beat("reval.window_close", "beat.reval.window_close", crontab(hour=19, minute=5))  # 00:35 IST
register_beat("reval.due_reminders", "beat.reval.due_reminders", crontab(hour=3, minute=10))  # 08:40 IST
register_beat(
    "malpractice.hearing_reminders", "beat.malpractice.hearing_reminders", crontab(hour=2, minute=40)
)  # 08:10
register_beat("withheld.auto_release", "beat.withheld.auto_release", crontab(minute=23))
register_beat("transcripts.reminders", "beat.transcripts.reminders", crontab(hour=4, minute=0))  # 09:30 IST

# ---- Phase 17 OBE attainment (app/tasks/obe.py) --------------------------------------------------------------------------------
register_beat("cqi.due_reminders", "beat.cqi.due_reminders", crontab(day_of_week=1, hour=3, minute=20))  # Mon 08:50 IST
register_beat(
    "obe.coverage_digest", "beat.obe.coverage_digest", crontab(day_of_month=1, hour=3, minute=40)
)  # 1st 09:10

# ---- Phase 18 degrees & credentials (app/tasks/degrees.py) -------------------------------------------------------------------------
register_beat("credentials.retry_failed", "beat.credentials.retry_failed", crontab(minute=37))
register_beat("abc.push_pending", "beat.abc.push_pending", crontab(hour=20, minute=50))  # 02:20 IST
register_beat("convocation.reminders", "beat.convocation.reminders", crontab(hour=3, minute=30))  # 09:00 IST

# ---- Phase 19 library (app/tasks/library.py) ---------------------------------------------------------------------------------------
register_beat("library.overdue_scan", "beat.library.overdue_scan", crontab(hour=19, minute=30))  # 01:00 IST
register_beat("library.reservation_expiry", "beat.library.reservation_expiry", crontab(minute=12))
register_beat(
    "library.eresource_expiry_reminders", "beat.library.eresource_expiry_reminders", crontab(hour=3, minute=45)
)
register_beat("library.membership_expiry", "beat.library.membership_expiry", crontab(hour=20, minute=10))  # 01:40 IST

# ---- Phase 20 hostel & mess (app/tasks/hostel.py) -------------------------------------------------------------------------------
register_beat("hostel.roll_call_autoclose", "beat.hostel.roll_call_autoclose", crontab(hour=17, minute=45))  # 23:15 IST
register_beat("hostel.absconding_scan", "beat.hostel.absconding_scan", crontab(minute=27))
register_beat("hostel.allotment_lapse", "beat.hostel.allotment_lapse", crontab(hour=20, minute=25))  # 01:55 IST
register_beat("hostel.waitlist_promote", "beat.hostel.waitlist_promote", crontab(hour=20, minute=40))  # 02:10 IST
register_beat("mess.bill_run", "beat.mess.bill_run", crontab(day_of_month=1, hour=21, minute=0))  # 1st 02:30 IST
register_beat("hostel.leave_reminders", "beat.hostel.leave_reminders", crontab(minute="*/30"))

# ---- Phase 21 transport (app/tasks/transport.py) ---------------------------------------------------------------------------
register_beat(
    "transport.document_expiry_scan", "beat.transport.document_expiry_scan", crontab(hour=1, minute=15)
)  # 06:45 IST
register_beat(
    "transport.gps_partition_maintenance",
    "beat.transport.gps_partition_maintenance",
    crontab(day_of_month=25, hour=21, minute=30),
)
register_beat("transport.trip_autoclose", "beat.transport.trip_autoclose", crontab(hour=18, minute=50))  # 00:20 IST
register_beat("transport.fee_suspension", "beat.transport.fee_suspension", crontab(hour=19, minute=5))  # 00:35 IST
register_beat("transport.live_cache_cleanup", "beat.transport.live_cache_cleanup", crontab(minute=12))
register_beat("transport.schedule_ahead", "beat.transport.schedule_ahead", crontab(hour=19, minute=20))  # 00:50 IST

# ---- Phase 22 inventory & procurement (app/tasks/inventory.py) ----------------------------------------------------------------
register_beat("inventory.low_stock_scan", "beat.inventory.low_stock_scan", crontab(hour=1, minute=30))  # 07:00 IST
register_beat(
    "inventory.chemical_expiry_scan", "beat.inventory.chemical_expiry_scan", crontab(day_of_week=1, hour=2, minute=0)
)
register_beat("inventory.po_overdue_scan", "beat.inventory.po_overdue_scan", crontab(hour=2, minute=15))
register_beat("inventory.bill_due_reminders", "beat.inventory.bill_due_reminders", crontab(hour=2, minute=45))
register_beat("inventory.audit_due", "beat.inventory.audit_due", crontab(day_of_month=1, hour=3, minute=0))
register_beat("inventory.warranty_expiry", "beat.inventory.warranty_expiry", crontab(day_of_week=1, hour=3, minute=15))

# ---- Phase 23 accounting (app/tasks/accounting.py) --------------------------------------------------------------------------------
register_beat(
    "accounting.budget_threshold_scan", "beat.accounting.budget_threshold_scan", crontab(hour=2, minute=30)
)  # 08:00 IST
register_beat(
    "accounting.reconciliation_reminder",
    "beat.accounting.reconciliation_reminder",
    crontab(day_of_month=3, hour=3, minute=30),
)
register_beat(
    "accounting.posting_gap_check", "beat.accounting.posting_gap_check", crontab(hour=19, minute=40)
)  # 01:10 IST

# ---- Phase 24 communication advanced (app/tasks/comms_advanced.py) -----------------------------------------------------------
register_beat("campaign.scheduler", "beat.campaign.scheduler", crontab(minute="*"))
register_beat("campaign.deferred_quiet_hours_flush", "beat.campaign.deferred_flush", crontab(minute="*/5"))
register_beat("bot.session_expiry", "beat.bot.session_expiry", crontab(minute=7))
register_beat(
    "assistant.conversation_retention", "beat.assistant.conversation_retention", crontab(hour=20, minute=55)
)  # 02:25 IST
register_beat("comms.provider_health_probe", "beat.comms.provider_health_probe", crontab(minute="*/5"))

# ---- Phase 25 calendar / events / facilities (app/tasks/facilities.py) ------------------------------------------------------
register_beat("calendar.reminders", "beat.calendar.reminders", crontab(minute="*/15"))
register_beat("event.reminders", "beat.event.reminders", crontab(hour=3, minute=0))
register_beat("service_desk.sla_scan", "beat.service_desk.sla_scan", crontab(minute="*/10"))
register_beat("service_desk.auto_close", "beat.service_desk.auto_close", crontab(hour=20, minute=0))
register_beat("amc.expiry_scan", "beat.amc.expiry_scan", crontab(hour=3, minute=20))
register_beat("visitor.expire_passes", "beat.visitor.expire_passes", crontab(minute=5))
register_beat("visitor.pii_purge", "beat.visitor.pii_purge", crontab(hour=20, minute=30))
register_beat("emergency.escalation", "beat.emergency.escalation", crontab())
register_beat("equipment.overdue_scan", "beat.equipment.overdue_scan", crontab(hour=3, minute=40))
register_beat("insurance.expiry_scan", "beat.insurance.expiry_scan", crontab(day_of_week=1, hour=3, minute=50))
register_beat("counselling.no_show_mark", "beat.counselling.no_show_mark", crontab(minute=25))
register_beat("wallet.limits_reset", "beat.wallet.limits_reset", crontab(hour=18, minute=35))

# ---- Phase 26 documents (app/tasks/documents.py) ---------------------------------------------------------------------------
register_beat("documents.request_sla_scan", "beat.documents.request_sla_scan", crontab(hour=3, minute=10))
register_beat("documents.pickup_reminders", "beat.documents.pickup_reminders", crontab(day_of_week=1, hour=4, minute=0))
register_beat("documents.signed_link_cleanup", "beat.documents.signed_link_cleanup", crontab(minute=17))
register_beat("documents.preview_cleanup", "beat.documents.preview_cleanup", crontab(hour=20, minute=45))

# ---- Phase 27 mentoring / grievances / discipline / surveys (app/tasks/student_support.py) --------------------------------
register_beat(
    "mentoring.follow_up_reminders", "beat.mentoring.follow_up_reminders", crontab(hour=2, minute=45)
)  # 08:15 IST
register_beat(
    "mentoring.min_sessions_check", "beat.mentoring.min_sessions_check", crontab(day_of_month=1, hour=3, minute=0)
)
register_beat("risk.compute_weekly", "beat.risk.compute_weekly", crontab(day_of_week=0, hour=20, minute=15))
register_beat("grievances.sla_scan", "beat.grievances.sla_scan", crontab(minute=35))
register_beat("grievances.auto_close", "beat.grievances.auto_close", crontab(hour=20, minute=10))
register_beat("surveys.reminders", "beat.surveys.reminders", crontab(hour=3, minute=30))
register_beat("surveys.auto_close", "beat.surveys.auto_close", crontab(minute=40))
register_beat("discipline.appeal_window", "beat.discipline.appeal_window", crontab(hour=20, minute=20))

# ---- Phase 28 placement / training (app/tasks/placement.py) ------------------------------------------------------------------
register_beat("placement.deadline_close", "beat.placement.deadline_close", crontab(minute=5))
register_beat(
    "placement.joining_followup", "beat.placement.joining_followup", crontab(day_of_week=1, hour=3, minute=15)
)
register_beat("placement.offer_reminders", "beat.placement.offer_reminders", crontab(hour=3, minute=45))  # 09:15 IST
register_beat("placement.blacklist_expiry", "beat.placement.blacklist_expiry", crontab(hour=20, minute=30))
register_beat("training.session_reminders", "beat.training.session_reminders", crontab(hour=2, minute=30))

# ---- Phase 29 alumni / fundraising (app/tasks/alumni.py) --------------------------------------------------------------------
register_beat("alumni.engagement_nightly", "beat.alumni.engagement_nightly", crontab(hour=21, minute=10))
register_beat("alumni.jobs_expiry", "beat.alumni.jobs_expiry", crontab(hour=20, minute=40))
register_beat("campaign.milestone_check", "beat.campaign.milestone_check", crontab(minute=25))
register_beat("alumni.pledge_reminders", "beat.alumni.pledge_reminders", crontab(day_of_week=1, hour=4, minute=30))
register_beat(
    "alumni.annual_update_campaign",
    "beat.alumni.annual_update_campaign",
    crontab(month_of_year=7, day_of_month=1, hour=4, minute=0),
)

# ---- Phase 30 research & faculty development (app/tasks/research.py) ----------------------------------------------------------
register_beat(
    "research.publication_sync", "beat.research.publication_sync", crontab(day_of_week=0, hour=20, minute=30)
)  # Mon 02:00 IST
register_beat(
    "research.project_report_reminders",
    "beat.research.project_report_reminders",
    crontab(day_of_week=1, hour=3, minute=0),
)  # Mon 08:30 IST
register_beat("research.mou_expiry_scan", "beat.research.mou_expiry_scan", crontab(hour=2, minute=50))  # 08:20 IST
register_beat(
    "research.incentive_cap_reset",
    "beat.research.incentive_cap_reset",
    crontab(month_of_year=1, day_of_month=1, hour=0, minute=5),
)
register_beat(
    "research.patent_renewal_reminders",
    "beat.research.patent_renewal_reminders",
    crontab(day_of_month=1, hour=3, minute=15),
)

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

# ---- Phase 12 fees (app/tasks/fees.py) — UTC crontab ≈ IST times in the comments ------------------------------------------
register_beat("fees.late_fees", "beat.fees.late_fees", crontab(hour=19, minute=10))  # 00:40 IST
register_beat("fees.due_reminders", "beat.fees.due_reminders", crontab(hour=2, minute=30))  # 08:00 IST
register_beat("fees.overdue_holds", "beat.fees.overdue_holds", crontab(hour=19, minute=20))  # 00:50 IST
register_beat("fees.day_book_close_reminder", "beat.fees.day_book_close_reminder", crontab(hour=12, minute=30))  # 18:00
register_beat("fees.gateway_status_poll", "beat.fees.gateway_status_poll", 600.0)

celery.conf.beat_schedule = BEAT_SCHEDULE
