"""Unified verification and graduation statistics — Prompts/18 §18.6 ``verification_service`` /
``graduation_stats_service``.

``verify_token(token)`` (public, tenant read from the token's registry row): degree (``dg…``) and provisional
(``pv…``) tokens live in the internal credential registry; grade-card / transcript / ID-card tokens fall through to the
Phase 07 / 15 / 16 verifiers (``GET /verify/{token}`` keeps answering them). Holder names are masked; revoked awards
answer ``valid=false, revoked=true``; reissued ones point at the newer version; provisionals are ``superseded`` once
the degree is issued.

Stats: GPH = enrolments of the batch with an issued degree dated within the programme's nominal duration from
admission ÷ admitted; GPHD = issued ``phd`` awards; median CGPA of issued awards.
"""

import statistics
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select

from app.models.academic import Batch, Program
from app.models.degrees import DegreeAwarded, DigitalCredential
from app.models.platform import Institution
from app.models.students import Student, StudentProgramEnrollment
from app.schemas.degrees import DegreeVerifyResponse, GraduationStatsResponse
from app.services.degrees.common import DegreeBase, full_name, mask_name

PREFIXES = {"dg": "degree", "pv": "provisional_certificate"}


async def verify_degree_token(token: str) -> DegreeVerifyResponse | None:
    """``None`` when the token is not a degree / provisional token (callers fall through to the older verifiers)."""
    if len(token) != 48 or token[:2] not in PREFIXES:
        return None
    from app.db.session import PlatformSessionLocal

    async with PlatformSessionLocal() as db:
        cred = (
            await db.execute(
                select(DigitalCredential).where(
                    DigitalCredential.channel == "internal", DigitalCredential.payload["token"].astext == token
                )
            )
        ).scalar_one_or_none()
        if cred is None:
            return DegreeVerifyResponse(
                valid=False, entity_type=PREFIXES[token[:2]], message="Unknown or tampered token"
            )
        inst = (
            await db.execute(select(Institution.name).where(Institution.id == cred.institution_id))
        ).scalar_one_or_none()
        p = cred.payload or {}
        if cred.entity_type == "degree":
            a = (await db.execute(select(DegreeAwarded).where(DegreeAwarded.id == cred.entity_id))).scalar_one()
            e = (
                await db.execute(
                    select(StudentProgramEnrollment).where(
                        StudentProgramEnrollment.id == a.student_program_enrollment_id
                    )
                )
            ).scalar_one()
            st = (await db.execute(select(Student).where(Student.id == e.student_id))).scalar_one()
            revoked = a.status == "cancelled" or cred.status == "revoked"
            note = None
            if a.status == "reissued":
                note = "Superseded by a reissued certificate" + (
                    f" ({p.get('reissued_as')})" if p.get("reissued_as") else ""
                )
            return DegreeVerifyResponse(
                valid=a.status == "issued" and not revoked,
                entity_type="degree",
                institution=inst,
                holder_masked=mask_name(p.get("holder_name") or full_name(st)),
                award={
                    "degree": a.degree_name,
                    "specialization": a.specialization,
                    "class": a.result_class,
                    "cgpa": float(a.cgpa) if a.cgpa is not None else None,
                    "date_of_award": a.date_of_award.isoformat() if a.date_of_award else None,
                    "certificate_number": a.certificate_number,
                    "serial_no": a.serial_no,
                },
                issued_at=cred.pushed_at,
                revoked=revoked,
                superseded=a.status == "reissued",
                hash=cred.payload_hash,
                version_note=note,
                message="Revoked: " + str(p.get("revoked_reason")) if revoked and p.get("revoked_reason") else None,
            )
        e = (
            await db.execute(select(StudentProgramEnrollment).where(StudentProgramEnrollment.id == cred.entity_id))
        ).scalar_one()
        st = (await db.execute(select(Student).where(Student.id == e.student_id))).scalar_one()
        program = (await db.execute(select(Program).where(Program.id == e.program_id))).scalar_one()
        issued = (
            await db.execute(
                select(DegreeAwarded.id).where(
                    DegreeAwarded.student_program_enrollment_id == e.id, DegreeAwarded.status == "issued"
                )
            )
        ).first()
        return DegreeVerifyResponse(
            valid=issued is None and cred.status != "revoked",
            entity_type="provisional_certificate",
            institution=inst,
            holder_masked=mask_name(full_name(st)),
            award={"programme": program.degree_name, "document_number": p.get("document_number")},
            issued_at=cred.pushed_at,
            revoked=cred.status == "revoked",
            superseded=issued is not None,
            hash=cred.payload_hash,
            version_note="Superseded by the degree certificate" if issued else None,
        )


async def verify_any(token: str) -> Any:
    """Single resolver behind ``/verify/{token}`` and the bulk endpoint."""
    from app.services.post_result.transcript_service import verify_transcript
    from app.services.results.grade_card_service import verify_grade_card
    from app.services.student_records_service import verify_token

    deg = await verify_degree_token(token)
    if deg is not None:
        return deg
    transcript = await verify_transcript(token)
    if transcript is not None:
        return transcript
    card = await verify_grade_card(token)
    if card is not None:
        return card
    return await verify_token(token)


class GraduationStatsService(DegreeBase):
    async def stats(self, program_id: uuid.UUID | None, batch_id: uuid.UUID | None) -> GraduationStatsResponse:
        q = (
            select(StudentProgramEnrollment, Program, Batch)
            .join(Program, Program.id == StudentProgramEnrollment.program_id)
            .join(Batch, Batch.id == StudentProgramEnrollment.batch_id)
            .where(StudentProgramEnrollment.institution_id == self.inst, StudentProgramEnrollment.deleted_at.is_(None))
        )
        if program_id:
            q = q.where(StudentProgramEnrollment.program_id == program_id)
        if batch_id:
            q = q.where(StudentProgramEnrollment.batch_id == batch_id)
        rows = (await self.db.execute(q)).all()
        awards = {
            a.student_program_enrollment_id: a
            for a in (
                await self.db.execute(
                    select(DegreeAwarded).where(
                        DegreeAwarded.institution_id == self.inst,
                        DegreeAwarded.status == "issued",
                        DegreeAwarded.student_program_enrollment_id.in_([r[0].id for r in rows] or [uuid.uuid4()]),
                    )
                )
            )
            .scalars()
            .all()
        }
        per: dict[str, dict[str, Any]] = {}
        cgpas: list[float] = []
        on_time = graduated = 0
        for e, p, _b in rows:
            d = per.setdefault(p.code, {"program": p.code, "admitted": 0, "graduated": 0, "on_time": 0})
            d["admitted"] += 1
            a = awards.get(e.id)
            if a is None:
                continue
            graduated += 1
            d["graduated"] += 1
            if a.cgpa is not None:
                cgpas.append(float(a.cgpa))
            limit = e.admission_date + timedelta(days=int(float(p.duration_years or 4) * 365.25) + 120)
            if a.date_of_award and a.date_of_award <= limit:
                on_time += 1
                d["on_time"] += 1
        for d in per.values():
            d["gph"] = round(d["on_time"] / d["admitted"] * 100, 2) if d["admitted"] else None
        phd = (
            await self.db.execute(
                select(func.count())
                .select_from(DegreeAwarded)
                .where(
                    DegreeAwarded.institution_id == self.inst,
                    DegreeAwarded.award_type == "phd",
                    DegreeAwarded.status == "issued",
                )
            )
        ).scalar_one()
        admitted = len(rows)
        return GraduationStatsResponse(
            gph=round(on_time / admitted * 100, 2) if admitted else None,
            gphd=int(phd),
            on_time_pct=round(on_time / graduated * 100, 2) if graduated else None,
            admitted=admitted,
            graduated=graduated,
            graduated_on_time=on_time,
            median_cgpa=round(statistics.median(cgpas), 2) if cgpas else None,
            by_program=sorted(per.values(), key=lambda x: x["program"]),
        )
