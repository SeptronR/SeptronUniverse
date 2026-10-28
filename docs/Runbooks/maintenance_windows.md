# Runbook — Read-only / maintenance windows

* Schedule: `POST /platform/maintenance {reason, starts_at, ends_at, notice_hours}` (super admin) — creates the Phase 38 read-only window and the announcement; tenant windows are scheduled by institution admins on `/admin/settings`.
* During the window writes answer `503 READ_ONLY`, the web and app show the banner, the mobile write queue holds items and flushes afterwards.
* Exam days: no risky migrations; see `exam_day.md`.
* Extend / end early from `/super-admin/read-only`; the status page lists active and upcoming windows as maintenance.
