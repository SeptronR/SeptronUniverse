"""Phase 36 reports — Prompts/36 §36.3. No persisted tables: report runs are ``background_jobs`` rows
(``job_type='report.run'`` / ``report.builder_run`` / ``report.statutory_generate`` / ``report.statutory_pack``),
schedules / saved builder reports / statutory generations live in ``institution_settings`` (category ``reports_meta``),
favourites and recent runs in ``users.preferences['reports']``, statutory files in ``issued_documents``.

The registry value objects (``ReportDef``, ``ReportModel``) are in ``app/core/reports.py``; the run / schedule records
below are the typed views over the job rows and side-store entries.
"""

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from app.models.platform import BackgroundJob

__all__ = ["BackgroundJob", "REPORT_JOB_TYPES", "ReportRun", "ScheduleDef"]

REPORT_JOB_TYPES: tuple[str, ...] = (
    "report.run",
    "report.builder_run",
    "report.statutory_generate",
    "report.statutory_pack",
    "report.schedule_deliver",
)


@dataclass
class ReportRun:
    job_id: uuid.UUID
    key: str
    params: dict[str, Any]
    format: str
    status: str
    rows: int | None = None
    checksum: str | None = None
    result_url: str | None = None
    requested_by: uuid.UUID | None = None
    created_at: datetime | None = None
    purged: bool = False

    @classmethod
    def from_job(cls, j: BackgroundJob) -> "ReportRun":
        p = dict(j.params or {})
        r = dict(j.result or {})
        return cls(
            job_id=j.id,
            key=str(p.get("key") or p.get("code") or p.get("model_key") or j.job_type),
            params=dict(p.get("params") or {}),
            format=str(p.get("format") or "xlsx"),
            status=j.status,
            rows=r.get("rows"),
            checksum=r.get("checksum"),
            result_url=None if r.get("purged") else j.result_url,
            requested_by=j.requested_by,
            created_at=j.created_at,
            purged=bool(r.get("purged")),
        )


@dataclass
class ScheduleDef:
    id: str
    key: str | None
    saved_report_id: str | None
    params: dict[str, Any]
    format: str
    cadence: str
    at: str
    weekday: int | None = None
    day_of_month: int | None = None
    cron: str | None = None
    recipients: dict[str, list[str]] = field(default_factory=lambda: {"roles": [], "user_ids": [], "emails": []})
    channels: list[str] = field(default_factory=lambda: ["email", "in_app"])
    is_active: bool = True
    paused_reason: str | None = None
    failures: int = 0
    owner: str | None = None
    name: str | None = None
    last_run_at: str | None = None
    next_run_at: str | None = None
    history: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ScheduleDef":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})
