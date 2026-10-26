"""Affiliation gates consumed by earlier phases (Prompts/34 §34.6) — plain async functions on a session so Phases 08 /
09 / 13 / 14 / 15 call them without importing the services:

* ``check_intake`` — Phase 08 seat matrix: per (programme, college) the total seats of a cycle's academic year must not
  exceed ``sanctioned_intake + lateral_intake`` of the approval (409 ``INTAKE_EXCEEDED``); a closed programme refuses
  new admissions (409 ``PROGRAM_CLOSED``); affiliated / autonomous colleges need an approval row (409
  ``PROGRAM_NOT_APPROVED``). Constituent / main colleges are not gated.
* ``check_registration`` — Phase 09: registrations only in programmes approved for the year or continuing batches of a
  programme approved earlier (closures keep existing batches).
* ``submission_locked`` — Phase 13 / 11 / 14: a ``locked`` college data submission freezes the college's source data
  for the term (409 ``LOCKED``).
* ``session_gating`` — Phase 15: per-college gating status for a central session (required submission types must be
  ``accepted | locked``).

Every gate is a no-op while its feature key is off (standalone tenants never pay for the checks).
"""

import uuid
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.enums.affiliation import AUTONOMOUS_SUBMISSIONS, DEFAULT_AFFILIATION_SETTINGS
from app.models.affiliation import AffiliationProgramApproval, CollegeDataSubmission

GATED_TYPES = ("affiliated", "autonomous")


async def _on(inst: uuid.UUID, key: str) -> bool:
    from app.core.features import is_enabled

    try:
        return await is_enabled(inst, key)
    except KeyError:
        return False


async def _setting(db: Any, inst: uuid.UUID, key: str) -> Any:
    from app.services.settings_service import SettingsService

    v = await SettingsService(db).value(inst, "affiliation", key, None)
    return DEFAULT_AFFILIATION_SETTINGS.get(f"affiliation.{key}") if v is None else v


def _err(status: int, code: str, message: str, **details: Any) -> APIError:
    return APIError(status, ErrorCode.RULE_VIOLATION, message, {"code": code, **details})


async def approval_for(
    db: Any, inst: uuid.UUID, college_id: uuid.UUID, program_id: uuid.UUID, year_id: uuid.UUID | None
) -> AffiliationProgramApproval | None:
    stmt = select(AffiliationProgramApproval).where(
        AffiliationProgramApproval.institution_id == inst,
        AffiliationProgramApproval.college_id == college_id,
        AffiliationProgramApproval.program_id == program_id,
    )
    if year_id is not None:
        stmt = stmt.where(AffiliationProgramApproval.academic_year_id == year_id)
    row: AffiliationProgramApproval | None = (
        await db.execute(stmt.order_by(AffiliationProgramApproval.created_at.desc()).limit(1))
    ).scalar_one_or_none()
    return row


def _closed(a: AffiliationProgramApproval | None, program_status: str | None) -> bool:
    if program_status == "closed":
        return True
    return bool(a is not None and a.approval_status == "withdrawn" and (a.conditions or {}).get("closure"))


async def check_intake(
    db: Any, inst: uuid.UUID, year_id: uuid.UUID, totals: dict[tuple[uuid.UUID, uuid.UUID], int]
) -> None:
    """``totals``: (program_id, college_id) → seats requested for the cycle's academic year."""
    if not totals or not await _on(inst, "affiliation.core"):
        return
    from app.models.academic import Program
    from app.models.platform import College

    colleges = {
        c.id: c
        for c in (await db.execute(select(College).where(College.id.in_(list({k[1] for k in totals}))))).scalars()
    }
    programs = {
        p.id: p
        for p in (await db.execute(select(Program).where(Program.id.in_(list({k[0] for k in totals}))))).scalars()
    }
    for (pid, cid), seats in totals.items():
        c, p = colleges.get(cid), programs.get(pid)
        if c is None or c.college_type not in GATED_TYPES:
            continue
        a = await approval_for(db, inst, cid, pid, year_id)
        code = p.code if p else str(pid)
        if _closed(a, p.status if p else None):
            raise _err(409, "PROGRAM_CLOSED", f"{code} at {c.code} is closed for new admissions", program_id=str(pid))
        if a is None or a.approval_status == "withdrawn":
            raise _err(
                409,
                "PROGRAM_NOT_APPROVED",
                f"{code} at {c.code} has no affiliation approval for the year",
                program_id=str(pid),
                college_id=str(cid),
            )
        cap = int(a.sanctioned_intake) + int(a.lateral_intake or 0)
        if seats > cap:
            raise _err(
                409,
                "INTAKE_EXCEEDED",
                f"{code} at {c.code}: {seats} seats exceed the sanctioned intake {cap}",
                program_id=str(pid),
                college_id=str(cid),
                sanctioned_intake=int(a.sanctioned_intake),
                lateral_intake=int(a.lateral_intake or 0),
                requested=seats,
            )


async def check_registration(
    db: Any, inst: uuid.UUID, college_id: uuid.UUID, program_id: uuid.UUID, year_id: uuid.UUID | None
) -> None:
    if not await _on(inst, "affiliation.core"):
        return
    from app.models.platform import College

    c = (await db.execute(select(College).where(College.id == college_id))).scalar_one_or_none()
    if c is None or c.college_type not in GATED_TYPES:
        return
    current = await approval_for(db, inst, college_id, program_id, year_id)
    if current is not None and current.approval_status != "withdrawn":
        return
    if current is not None and (current.conditions or {}).get("closure"):
        return  # programme closure: existing batches continue
    earlier = (
        await db.execute(
            select(func.count())
            .select_from(AffiliationProgramApproval)
            .where(
                AffiliationProgramApproval.institution_id == inst,
                AffiliationProgramApproval.college_id == college_id,
                AffiliationProgramApproval.program_id == program_id,
                AffiliationProgramApproval.approval_status != "withdrawn",
            )
        )
    ).scalar_one()
    if current is None and earlier:
        return  # continuing batch of a programme approved in an earlier year
    raise _err(
        409,
        "PROGRAM_NOT_APPROVED",
        "The programme is not approved for this college and year",
        program_id=str(program_id),
        college_id=str(college_id),
    )


async def submission_locked(
    db: Any, inst: uuid.UUID, college_id: uuid.UUID | None, term_id: uuid.UUID | None, submission_type: str
) -> bool:
    if college_id is None or term_id is None or not await _on(inst, "affiliation.data_submissions"):
        return False
    row = (
        await db.execute(
            select(CollegeDataSubmission.status).where(
                CollegeDataSubmission.institution_id == inst,
                CollegeDataSubmission.college_id == college_id,
                CollegeDataSubmission.term_id == term_id,
                CollegeDataSubmission.submission_type == submission_type,
            )
        )
    ).scalar_one_or_none()
    return bool(row == "locked")


async def require_unlocked(
    db: Any, inst: uuid.UUID, college_id: uuid.UUID | None, term_id: uuid.UUID | None, submission_type: str
) -> None:
    if await submission_locked(db, inst, college_id, term_id, submission_type):
        raise APIError(
            409,
            ErrorCode.RECORD_LOCKED,
            f"The college's {submission_type.replace('_', ' ')} submission to the university is locked",
            {"code": "LOCKED", "submission_type": submission_type},
        )


async def session_gating(db: Any, inst: uuid.UUID, session: Any) -> dict[uuid.UUID, dict[str, Any]]:
    """college_id → ``{status: ready|gated|not_applicable, missing[], by_type{}, registrations}`` for a central session
    (``exam_sessions.college_id IS NULL``); empty while ``affiliation.data_submissions`` is off or for college sessions."""
    if getattr(session, "college_id", None) is not None or not await _on(inst, "affiliation.data_submissions"):
        return {}
    from app.models.exams import ExamRegistration
    from app.models.platform import College

    required = [str(x) for x in (await _setting(db, inst, "results_require_accepted") or [])]
    regs = dict(
        (
            await db.execute(
                select(ExamRegistration.college_id, func.count())
                .where(
                    ExamRegistration.exam_session_id == session.id,
                    ExamRegistration.status.in_(("confirmed", "submitted")),
                )
                .group_by(ExamRegistration.college_id)
            )
        ).all()
    )
    if not regs:
        return {}
    colleges = {c.id: c for c in (await db.execute(select(College).where(College.id.in_(list(regs))))).scalars()}
    subs: dict[uuid.UUID, dict[str, str]] = {}
    for cid, st, status in (
        await db.execute(
            select(
                CollegeDataSubmission.college_id,
                CollegeDataSubmission.submission_type,
                CollegeDataSubmission.status,
            ).where(
                CollegeDataSubmission.institution_id == inst,
                CollegeDataSubmission.term_id == session.term_id,
                CollegeDataSubmission.college_id.in_(list(regs)),
            )
        )
    ).all():
        subs.setdefault(cid, {})[st] = status
    out: dict[uuid.UUID, dict[str, Any]] = {}
    for cid, n in regs.items():
        c = colleges.get(cid)
        by_type = subs.get(cid, {})
        if c is None or c.college_type not in ("affiliated",):
            types = [t for t in required if t in AUTONOMOUS_SUBMISSIONS] if c and c.college_type == "autonomous" else []
            if not types:
                out[cid] = {"status": "not_applicable", "missing": [], "by_type": by_type, "registrations": int(n)}
                continue
        else:
            types = required
        missing = [t for t in types if by_type.get(t) not in ("accepted", "locked")]
        out[cid] = {
            "status": "gated" if missing else "ready",
            "missing": missing,
            "by_type": by_type,
            "registrations": int(n),
        }
    return out
