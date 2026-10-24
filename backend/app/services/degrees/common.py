"""Shared plumbing of the Phase 18 services — on the Phase 07 ``StudentServiceBase`` (tenant, audit, outbox,
notifications, settings, institution-local ``today``).

* ``enrolment(id)`` — a visible enrolment (``degree_scope.enrollment_predicate``; 404 otherwise);
* ``refs(ids)`` — ``EnrollmentRef`` rows (student name, registration number, programme, batch);
* ``mine()`` — the caller's own (and wards') enrolment ids;
* ``qr_token`` / ``internal_credential`` — the QR registry: every degree / provisional certificate gets a
  ``digital_credentials`` row on channel ``internal`` whose ``payload.token`` is what ``/verify/{token}`` resolves
  (``dg`` + 46 hex for degrees, ``pv`` + 46 hex for provisionals), so no extra table is needed.
"""

import hashlib
import json
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.core.errors import APIError, ErrorCode
from app.models.academic import Batch, Program
from app.models.degrees import DigitalCredential
from app.models.students import Student, StudentProgramEnrollment
from app.repositories.degree_scope import enrollment_predicate
from app.repositories.fee_scope import own_enrollment_ids
from app.schemas.degrees import EnrollmentRef
from app.services.students.common import StudentServiceBase


def now_utc() -> datetime:
    return datetime.now(UTC)


def rule(message: str, code: str, status: int = 409, **details: Any) -> APIError:
    return APIError(status, ErrorCode.RULE_VIOLATION, message, {"code": code, **details})


def payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def mask_name(name: str | None) -> str | None:
    if not name:
        return None
    return " ".join(p[0] + "*" * max(len(p) - 2, 1) + (p[-1] if len(p) > 1 else "") for p in name.split())


def full_name(s: Student | None) -> str | None:
    return " ".join(x for x in (s.first_name, s.middle_name, s.last_name) if x) if s else None


class DegreeBase(StudentServiceBase):
    audit_module = "degrees"

    async def enrolment(self, enrollment_id: uuid.UUID, *, for_update: bool = False) -> StudentProgramEnrollment:
        q = select(StudentProgramEnrollment).where(
            StudentProgramEnrollment.id == enrollment_id,
            StudentProgramEnrollment.institution_id == self.inst,
            enrollment_predicate(self.principal, StudentProgramEnrollment.id),
        )
        if for_update:
            q = q.with_for_update()
        row = (await self.db.execute(q)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Enrolment not found")
        return row

    async def mine(self) -> list[uuid.UUID]:
        if self.principal is None:
            return []
        return list((await self.db.execute(own_enrollment_ids(self.principal, advisees=False))).scalars().all())

    async def refs(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, EnrollmentRef]:
        if not ids:
            return {}
        rows = (
            await self.db.execute(
                select(StudentProgramEnrollment, Student, Program.code, Batch.code)
                .join(Student, Student.id == StudentProgramEnrollment.student_id)
                .join(Program, Program.id == StudentProgramEnrollment.program_id)
                .join(Batch, Batch.id == StudentProgramEnrollment.batch_id)
                .where(StudentProgramEnrollment.id.in_(list(set(ids))))
            )
        ).all()
        return {
            e.id: EnrollmentRef(
                id=e.id,
                student_id=s.id,
                student_name=full_name(s),
                registration_number=s.registration_number,
                program_code=pc,
                batch_code=bc,
                status=e.status,
            )
            for e, s, pc, bc in rows
        }

    async def ref(self, enrollment_id: uuid.UUID) -> EnrollmentRef:
        return (await self.refs([enrollment_id])).get(enrollment_id) or EnrollmentRef(id=enrollment_id)

    # ---- QR registry ------------------------------------------------------------------------------------------------
    async def internal_credential(self, entity_type: str, entity_id: uuid.UUID) -> DigitalCredential | None:
        return (
            await self.db.execute(
                select(DigitalCredential).where(
                    DigitalCredential.institution_id == self.inst,
                    DigitalCredential.entity_type == entity_type,
                    DigitalCredential.entity_id == entity_id,
                    DigitalCredential.channel == "internal",
                )
            )
        ).scalar_one_or_none()

    async def register_qr(
        self, entity_type: str, entity_id: uuid.UUID, prefix: str, data: dict[str, Any]
    ) -> DigitalCredential:
        row = await self.internal_credential(entity_type, entity_id)
        token = prefix + secrets.token_hex(23)
        payload = {**data, "token": token, "issued_at": now_utc().isoformat()}
        if row is None:
            row = DigitalCredential(
                institution_id=self.inst,
                entity_type=entity_type,
                entity_id=entity_id,
                channel="internal",
                payload_hash=payload_hash({k: v for k, v in payload.items() if k != "token"}),
                payload=payload,
                status="acknowledged",
                pushed_at=now_utc(),
            )
            self.db.add(row)
        else:
            row.payload = payload
            row.payload_hash = payload_hash({k: v for k, v in payload.items() if k != "token"})
            row.status = "acknowledged"
        await self.db.flush()
        return row
