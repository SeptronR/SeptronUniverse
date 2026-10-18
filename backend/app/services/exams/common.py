"""Shared plumbing of the Phase 14 services — on the Phase 07 ``StudentServiceBase`` (tenant, audit, outbox,
notifications, institution-local ``today``, settings, terms).

``session(id)`` reads a session the caller may see (staff with ``exams:view|view_all|configure|manage``: every
session of the tenant, college-scoped holders only central sessions and their college's; learners: sessions of their
college / central ones), ``locked`` sessions refuse writes (409 ``RECORD_LOCKED``); ``fee_for`` applies the
session's ``fee_rules`` (per course / per arrear / practical / cap / late fee).
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.core.errors import APIError, ErrorCode
from app.models.exams import ExamPaper, ExamSession
from app.models.students import Student
from app.services.students.common import StudentServiceBase

DEFAULT_FEE_RULES = {
    "per_course_paise": 30000,
    "per_arrear_paise": 50000,
    "practical_paise": 20000,
    "max_paise": 300000,
    "late_fee_paise": 50000,
}


def rule(message: str, code: str, status: int = 409, **details: Any) -> APIError:
    return APIError(status, ErrorCode.RULE_VIOLATION, message, {"code": code, **details})


def now_utc() -> datetime:
    return datetime.now(UTC)


def student_name(s: Student | None) -> str | None:
    return " ".join(p for p in (s.first_name, s.last_name) if p) if s else None


def mask(name: str | None) -> str | None:
    if not name:
        return None
    return " ".join(w[0] + "*" * max(1, len(w) - 1) for w in name.split())


class ExamBase(StudentServiceBase):
    audit_module = "exams"

    def _college_ids(self) -> list[uuid.UUID]:
        return [sid for st, sid in getattr(self.principal, "scopes", []) if st == "college" and sid is not None]

    async def session(self, sid: uuid.UUID, *, for_update: bool = False, write: bool = False) -> ExamSession:
        q = select(ExamSession).where(
            ExamSession.id == sid, ExamSession.institution_id == self.inst, ExamSession.deleted_at.is_(None)
        )
        if for_update:
            q = q.with_for_update()
        s = (await self.db.execute(q)).scalar_one_or_none()
        if s is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Exam session not found")
        colleges = self._college_ids()
        institution = (
            self.principal is None
            or getattr(self.principal, "is_super_admin", False)
            or any(st == "institution" for st, _ in getattr(self.principal, "scopes", []))
        )
        if not institution and colleges and s.college_id is not None and s.college_id not in colleges:
            raise APIError(404, ErrorCode.NOT_FOUND, "Exam session not found")
        if write and s.is_locked:
            raise APIError(409, ErrorCode.RECORD_LOCKED, "The exam session is locked")
        return s

    async def paper(self, pid: uuid.UUID, *, for_update: bool = False) -> tuple[ExamPaper, ExamSession]:
        q = select(ExamPaper).where(ExamPaper.id == pid, ExamPaper.institution_id == self.inst)
        if for_update:
            q = q.with_for_update()
        p = (await self.db.execute(q)).scalar_one_or_none()
        if p is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Exam paper not found")
        return p, await self.session(p.exam_session_id)

    @staticmethod
    def fee_rules(s: ExamSession) -> dict[str, int]:
        return {
            **DEFAULT_FEE_RULES,
            **{k: int(v) for k, v in (s.fee_rules or {}).items() if isinstance(v, int | float)},
        }

    def item_fee(self, s: ExamSession, paper_type: str, attempt_type: str) -> int:
        r = self.fee_rules(s)
        if attempt_type == "arrear":
            return r["per_arrear_paise"]
        if paper_type in ("practical", "project_viva", "dissertation"):
            return r["practical_paise"]
        return r["per_course_paise"]

    def total_fee(self, s: ExamSession, fees: list[int], *, late: bool) -> tuple[int, int]:
        r = self.fee_rules(s)
        total = min(sum(fees), r["max_paise"]) if r.get("max_paise") else sum(fees)
        late_fee = r["late_fee_paise"] if late and total > 0 else 0
        return total + late_fee, late_fee
