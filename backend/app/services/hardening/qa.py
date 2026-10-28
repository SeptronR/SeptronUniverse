"""QA suites, golden runs, access matrix, load results — Prompts/43 §43.6 (non-production only).

``qa:run`` (institution admin / security officer). Suites run as ``background_jobs`` (``job_type='qa.suite'``) that
call ``scripts/verify/run_all.py``; reports (JUnit + Markdown) land in ``backend/reports/qa/…`` and the job result keeps
the summary. Every route answers 404 when ``APP_ENV=production``.
"""

from __future__ import annotations

import builtins
import csv
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.core.audit import log_audit
from app.core.config import settings
from app.core.errors import APIError, ErrorCode
from app.services.hardening.common import HardeningBase

ROOT = Path(__file__).resolve().parents[4]
SUITES = ("static", "golden", "visibility", "immutability", "api_all", "all", *(f"api_round_{n}" for n in range(6)))


def assert_non_production() -> None:
    if settings.is_production:
        raise APIError(404, ErrorCode.NOT_FOUND, "Not found")


class QaService(HardeningBase):
    def _guard(self, run: bool = False) -> None:
        assert_non_production()
        if run:
            self.require("qa:run", "security:manage")
        else:
            self.require("qa:run", "security:manage", "security:view_all")

    async def run_suite(self, suite: str, env: str) -> dict[str, Any]:
        self._guard(run=True)
        if suite not in SUITES:
            raise APIError(422, ErrorCode.VALIDATION, "Unknown suite", {"suite": suite, "allowed": list(SUITES)})
        from app.core.jobs import enqueue

        job = await enqueue(self.db, self.principal, "qa.suite", {"suite": suite, "env": env}, queue="reports")
        await log_audit(
            self.db,
            principal=self.principal,
            module="qa",
            action="suite_run",
            record_type="background_job",
            record_id=job.id,
            new={"suite": suite, "env": env},
            request=self.request,
        )
        return {"job_id": str(job.id), "suite": suite, "status": job.status}

    async def runs(self) -> builtins.list[dict[str, Any]]:
        self._guard()
        rows = (
            (
                await self.db.execute(
                    text(
                        "SELECT id, params, status, result, created_at, finished_at FROM background_jobs "
                        "WHERE institution_id = :i AND job_type IN ('qa.suite', 'qa.golden_run') ORDER BY created_at DESC LIMIT 50"
                    ),
                    {"i": self.inst},
                )
            )
            .mappings()
            .all()
        )
        return [dict(r) for r in rows]

    async def report(self, job_id: str) -> dict[str, Any]:
        self._guard()
        row = (
            await self.db.execute(
                text(
                    "SELECT result FROM background_jobs WHERE id = CAST(:j AS uuid) AND institution_id = :i AND job_type = 'qa.suite'"
                ),
                {"j": job_id, "i": self.inst},
            )
        ).first()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Run not found")
        result = dict(row[0] or {})
        path = result.get("report_dir")
        if path and (ROOT / "backend" / path / "summary.md").exists():
            result["markdown"] = (ROOT / "backend" / path / "summary.md").read_text(encoding="utf-8")
        return result

    async def golden(self) -> dict[str, Any]:
        self._guard(run=True)
        from app.services.hardening.golden import run_all

        result = run_all()
        if result["failed"]:
            from app.core import events

            await events.emit(
                self.db,
                institution_id=self.inst,
                event_type="qa.golden_diff",
                payload={"failed": [f["name"] for f in result["failed"]]},
                aggregate_type="qa",
                aggregate_id=None,
                actor_user_id=self.principal.id,
            )
        await log_audit(
            self.db,
            principal=self.principal,
            module="qa",
            action="golden_run",
            record_type="qa",
            record_id=None,
            new={"total": result["total"], "passed": result["passed"]},
            request=self.request,
        )
        return result

    async def access_matrix(self) -> dict[str, Any]:
        self._guard()
        path = ROOT / "docs" / "Access_Matrix.csv"
        if not path.exists():
            return {"generated_at": None, "routes": 0, "roles": 0, "csv_url": None, "diff_vs_docs": []}
        with path.open(encoding="utf-8") as fh:
            reader = csv.reader(fh)
            header = next(reader)
            routes = sum(1 for _ in reader)
        import subprocess
        import sys

        p = subprocess.run(
            [sys.executable, str(ROOT / "backend" / "scripts" / "check_access_matrix.py")],  # noqa: S603
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        diff = [
            ln.strip().removeprefix("UNEXPECTED ")
            for ln in p.stdout.splitlines()
            if ln.strip().startswith("UNEXPECTED")
        ]
        return {
            "generated_at": path.stat().st_mtime,
            "routes": routes,
            "roles": len(header) - 6,
            "csv_url": "docs/Access_Matrix.csv",
            "diff_vs_docs": diff,
        }

    async def regenerate_access_matrix(self) -> dict[str, Any]:
        self._guard(run=True)
        from app.core.jobs import enqueue

        job = await enqueue(self.db, self.principal, "qa.access_matrix", {}, queue="reports")
        return {"job_id": str(job.id)}

    async def load_results(self) -> dict[str, Any]:
        self._guard()
        return dict(
            await self.platform_value("qa.load_results", None) or {"scenarios": [], "thresholds": LOAD_THRESHOLDS}
        )


LOAD_THRESHOLDS = {
    "registration_rush": {"p95_ms": 1000, "errors_5xx": 0, "over_allocations": 0},
    "result_publish": {"notifications_per_min": 20000, "outbox_lag_s": 30},
    "hall_tickets": {"pdfs": 10000, "max_minutes": 15},
    "lists": {"p95_ms": 300, "detail_p95_ms": 150, "search_p95_ms": 500},
    "dashboard": {"p95_ms": 300},
    "attendance_fan_in": {"queues": 2000, "max_minutes": 5},
    "website": {"rps": 1000},
}
