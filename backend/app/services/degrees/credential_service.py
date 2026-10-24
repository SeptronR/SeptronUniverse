"""Digital credentials and ABC credit push — Prompts/18 §18.6 ``credential_service`` (features ``degrees.digilocker_nad``
/ ``degrees.abc_push``).

``push``: one ``digital_credentials`` row per (entity, channel) — DigiLocker issuer payload (document type, holder
APAAR id, metadata, document URL) hashed into ``payload_hash``; adapters come from the registry (``digilocker`` for
DigiLocker, ``nad_abc`` for NAD / ABC; ``mock`` acknowledges). ``pending → pushed → acknowledged`` or ``failed``
(attempts counted; Beat ``credentials.retry_failed`` retries up to 5 attempts); students without an APAAR id are
skipped (``SKIPPED_NO_APAAR``). Revoking an award revokes its credentials (``award_service``) and the adapter is told
(``credentials.revoked`` consumer → ``revoke``).

``abc_push``: pending ``abc_credit_ledger`` rows (Phase 15 writes them on publication) grouped per student into
batches (``push_batch_id``) → ``nad_abc.push_credits``; ``results.version_created`` revokes the ledger row of the
superseded result and queues the new version.
"""

import contextlib
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import select

from app.core.errors import APIError, ErrorCode
from app.integrations.registry import get_adapter
from app.models.degrees import DegreeAwarded, DigitalCredential
from app.models.post_result import Transcript
from app.models.results import AbcCreditLedger, GradeCard, StudentCourseResult, StudentTermResult
from app.models.students import Student, StudentProgramEnrollment, StudentTermRecord
from app.schemas.degrees import (
    AbcLedgerRow,
    AbcPushRequest,
    AbcPushSummary,
    CredentialPushRequest,
    CredentialStatusResponse,
    PushSummary,
)
from app.services.degrees.common import DegreeBase, full_name, now_utc, payload_hash

ADAPTER = {"digilocker": "digilocker", "nad": "nad_abc", "internal": "digilocker"}
DOC_TYPE = {"degree": "DGCER", "provisional_certificate": "PVCER", "grade_card": "GRDCR", "transcript": "TRNCR"}
MAX_ATTEMPTS = 5


class CredentialService(DegreeBase):
    def require_issue(self) -> None:
        if not self.can("degrees", "issue"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "degrees:issue required")

    async def _entities(self, body: CredentialPushRequest) -> list[tuple[uuid.UUID, uuid.UUID, dict[str, Any]]]:
        """``(entity_id, enrolment_id, metadata)`` for the requested entities."""
        out: list[tuple[uuid.UUID, uuid.UUID, dict[str, Any]]] = []
        if body.entity_type == "degree":
            q = select(DegreeAwarded).where(DegreeAwarded.institution_id == self.inst, DegreeAwarded.status == "issued")
            if body.entity_ids:
                q = q.where(DegreeAwarded.id.in_(body.entity_ids))
            if body.batch_id:
                q = q.join(
                    StudentProgramEnrollment, StudentProgramEnrollment.id == DegreeAwarded.student_program_enrollment_id
                ).where(StudentProgramEnrollment.batch_id == body.batch_id)
            for a in (await self.db.execute(q)).scalars().all():
                out.append(
                    (
                        a.id,
                        a.student_program_enrollment_id,
                        {
                            "award": a.degree_name,
                            "class": a.result_class,
                            "cgpa": str(a.cgpa) if a.cgpa is not None else None,
                            "certificate_number": a.certificate_number,
                            "serial_no": a.serial_no,
                            "date_of_award": a.date_of_award.isoformat() if a.date_of_award else None,
                            "document": a.pdf_url,
                        },
                    )
                )
        elif body.entity_type == "provisional_certificate":
            for c in (
                (
                    await self.db.execute(
                        select(DigitalCredential).where(
                            DigitalCredential.institution_id == self.inst,
                            DigitalCredential.entity_type == "provisional_certificate",
                            DigitalCredential.channel == "internal",
                            *([DigitalCredential.entity_id.in_(body.entity_ids)] if body.entity_ids else []),
                        )
                    )
                )
                .scalars()
                .all()
            ):
                out.append((c.entity_id, c.entity_id, {"document_number": (c.payload or {}).get("document_number")}))
        elif body.entity_type == "transcript":
            q2 = select(Transcript).where(Transcript.institution_id == self.inst, Transcript.status == "issued")
            if body.entity_ids:
                q2 = q2.where(Transcript.id.in_(body.entity_ids))
            for t in (await self.db.execute(q2)).scalars().all():
                out.append(
                    (
                        t.id,
                        t.student_program_enrollment_id,
                        {"document_number": t.document_number, "document": t.pdf_url},
                    )
                )
        else:
            q3 = (
                select(GradeCard.id, StudentTermRecord.student_program_enrollment_id, GradeCard.document_number)
                .join(StudentTermResult, StudentTermResult.id == GradeCard.student_term_result_id)
                .join(StudentTermRecord, StudentTermRecord.id == StudentTermResult.student_term_record_id)
                .where(GradeCard.institution_id == self.inst)
            )
            if body.entity_ids:
                q3 = q3.where(GradeCard.id.in_(body.entity_ids))
            for gid, eid, number in (await self.db.execute(q3)).all():
                out.append((gid, eid, {"document_number": number}))
        return out

    async def push(self, body: CredentialPushRequest) -> PushSummary:
        self.require_issue()
        entities = await self._entities(body)
        holders = {
            e.id: s
            for e, s in (
                await self.db.execute(
                    select(StudentProgramEnrollment, Student)
                    .join(Student, Student.id == StudentProgramEnrollment.student_id)
                    .where(StudentProgramEnrollment.id.in_({x[1] for x in entities} or {uuid.uuid4()}))
                )
            ).all()
        }
        summary = PushSummary()
        skipped: dict[str, int] = defaultdict(int)
        for entity_id, enrol_id, meta in entities:
            st = holders.get(enrol_id)
            if st is None or not st.apaar_id:
                skipped["SKIPPED_NO_APAAR"] += 1
                continue
            payload = {
                "doc_type": DOC_TYPE.get(body.entity_type, "OTHER"),
                "holder": {
                    "apaar_id": st.apaar_id,
                    "name": full_name(st),
                    "registration_number": st.registration_number,
                },
                "metadata": meta,
                "issuer": str(self.inst),
            }
            row = (
                await self.db.execute(
                    select(DigitalCredential).where(
                        DigitalCredential.entity_type == body.entity_type,
                        DigitalCredential.entity_id == entity_id,
                        DigitalCredential.channel == body.channel,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                row = DigitalCredential(
                    institution_id=self.inst,
                    entity_type=body.entity_type,
                    entity_id=entity_id,
                    channel=body.channel,
                    payload_hash=payload_hash(payload),
                    payload=payload,
                    status="pending",
                )
                self.db.add(row)
                await self.db.flush()
            elif row.status in ("acknowledged", "pushed") and row.payload_hash == payload_hash(payload):
                skipped["ALREADY_PUSHED"] += 1
                continue
            else:
                row.payload, row.payload_hash, row.status = payload, payload_hash(payload), "pending"
            summary.queued += 1
            await self._send(row)
            if row.status == "acknowledged":
                summary.acknowledged += 1
            elif row.status == "failed":
                summary.failed += 1
            else:
                summary.pushed += 1
            if body.entity_type == "degree":
                a = (await self.db.execute(select(DegreeAwarded).where(DegreeAwarded.id == entity_id))).scalar_one()
                a.digital_credential_id = a.digital_credential_id or row.id
        summary.skipped = dict(skipped)
        await self.db.flush()
        await self._audit(
            "credentials_push", "digital_credential", None, None, {**summary.model_dump(), "channel": body.channel}
        )
        return summary

    async def _send(self, row: DigitalCredential) -> None:
        row.attempts += 1
        try:
            res = await get_adapter(ADAPTER.get(row.channel, "digilocker")).push_credential(
                document_type=(row.payload or {}).get("doc_type"), payload=row.payload, payload_hash=row.payload_hash
            )
        except Exception as exc:  # noqa: BLE001 - adapter failure → failed row, retried by Beat
            row.status, row.response = "failed", {"error": str(exc)[:500]}
            await self._emit("credentials.failed", {"credential_id": str(row.id)}, "digital_credential", row.id)
            return
        row.pushed_at = now_utc()
        row.response = res if isinstance(res, dict) else {"result": str(res)}
        ok = isinstance(res, dict) and res.get("status") in ("sent", "acknowledged", "ok", "success")
        row.status = "acknowledged" if ok else "pushed"
        row.ack_ref = str(res.get("reference") or "")[:120] if isinstance(res, dict) else None
        await self._emit(
            "credentials.acknowledged" if ok else "credentials.pushed",
            {"credential_id": str(row.id)},
            "digital_credential",
            row.id,
        )

    async def outs(self, rows: list[DigitalCredential]) -> list[CredentialStatusResponse]:
        return [
            CredentialStatusResponse(
                id=r.id,
                entity_type=r.entity_type,
                entity_id=r.entity_id,
                channel=r.channel,
                status=r.status,
                ack_ref=r.ack_ref,
                attempts=r.attempts,
                pushed_at=r.pushed_at,
                payload_hash=r.payload_hash,
                response=r.response,
                holder=((r.payload or {}).get("holder") or {}).get("name"),
                updated_at=r.updated_at,
            )
            for r in rows
        ]

    async def list_credentials(self, entity_type: str | None, status: str | None) -> list[CredentialStatusResponse]:
        q = select(DigitalCredential).where(
            DigitalCredential.institution_id == self.inst, DigitalCredential.channel != "internal"
        )
        if entity_type:
            q = q.where(DigitalCredential.entity_type == entity_type)
        if status:
            q = q.where(DigitalCredential.status == status)
        rows = list(
            (await self.db.execute(q.order_by(DigitalCredential.updated_at.desc()).limit(2000))).scalars().all()
        )
        return await self.outs(rows)

    async def _get(self, cid: uuid.UUID) -> DigitalCredential:
        row = (
            await self.db.execute(
                select(DigitalCredential).where(
                    DigitalCredential.id == cid, DigitalCredential.institution_id == self.inst
                )
            )
        ).scalar_one_or_none()
        if row is None or row.channel == "internal":
            raise APIError(404, ErrorCode.NOT_FOUND, "Credential not found")
        return row

    async def get(self, cid: uuid.UUID) -> CredentialStatusResponse:
        return (await self.outs([await self._get(cid)]))[0]

    async def retry(self, cid: uuid.UUID) -> CredentialStatusResponse:
        self.require_issue()
        row = await self._get(cid)
        if row.status not in ("failed", "pending", "pushed"):
            raise APIError(409, ErrorCode.RULE_VIOLATION, f"Credential is {row.status}", {"code": "NOT_RETRYABLE"})
        await self._send(row)
        await self.db.flush()
        await self.db.refresh(row)
        return (await self.outs([row]))[0]

    async def revoke(self, cid: uuid.UUID, reason: str = "revoked") -> CredentialStatusResponse:
        self.require_issue()
        row = await self._get(cid)
        await self._revoke(row, reason)
        await self.db.refresh(row)
        return (await self.outs([row]))[0]

    async def _revoke(self, row: DigitalCredential, reason: str) -> None:
        with contextlib.suppress(Exception):  # the local row is revoked regardless
            await get_adapter(ADAPTER.get(row.channel, "digilocker")).revoke_credential(
                reference=row.ack_ref, reason=reason
            )
        row.status = "revoked"
        row.response = {**(row.response or {}), "revoked_reason": reason}
        await self.db.flush()

    async def on_revoked(self, cid: uuid.UUID) -> None:
        row = (await self.db.execute(select(DigitalCredential).where(DigitalCredential.id == cid))).scalar_one_or_none()
        if row is not None and row.channel != "internal":
            await self._revoke(row, "award revoked")

    async def me(self) -> list[CredentialStatusResponse]:
        mine = await self.mine()
        awards = select(DegreeAwarded.id).where(DegreeAwarded.student_program_enrollment_id.in_(mine or [uuid.uuid4()]))
        rows = list(
            (
                await self.db.execute(
                    select(DigitalCredential).where(
                        DigitalCredential.channel != "internal",
                        (DigitalCredential.entity_id.in_(awards))
                        | (DigitalCredential.entity_id.in_(mine or [uuid.uuid4()])),
                    )
                )
            )
            .scalars()
            .all()
        )
        return await self.outs(rows)

    async def retry_failed(self) -> int:
        rows = (
            (
                await self.db.execute(
                    select(DigitalCredential).where(
                        DigitalCredential.institution_id == self.inst,
                        DigitalCredential.status == "failed",
                        DigitalCredential.attempts < MAX_ATTEMPTS,
                    )
                )
            )
            .scalars()
            .all()
        )
        for r in rows:
            await self._send(r)
        await self.db.flush()
        return len(rows)

    # ---- ABC --------------------------------------------------------------------------------------------------------
    async def abc_push(self, body: AbcPushRequest) -> AbcPushSummary:
        q = select(AbcCreditLedger).where(
            AbcCreditLedger.institution_id == self.inst, AbcCreditLedger.status.in_(("pending", "failed"))
        )
        if body.student_ids:
            q = q.where(AbcCreditLedger.student_id.in_(body.student_ids))
        if body.term_id:
            q = q.where(AbcCreditLedger.term_id == body.term_id)
        rows = list((await self.db.execute(q.order_by(AbcCreditLedger.student_id))).scalars().all())
        summary = AbcPushSummary()
        by_student: dict[uuid.UUID, list[AbcCreditLedger]] = defaultdict(list)
        apaar: dict[Any, Any] = dict(
            (  # type: ignore[arg-type]
                await self.db.execute(
                    select(Student.id, Student.apaar_id).where(
                        Student.id.in_({r.student_id for r in rows} or {uuid.uuid4()})
                    )
                )
            ).all()
        )
        for r in rows:
            r.apaar_id = r.apaar_id or apaar.get(r.student_id)
            if not r.apaar_id:
                summary.skipped_no_apaar += 1
                continue
            by_student[r.student_id].append(r)
        adapter = get_adapter("nad_abc")
        for sid, items in by_student.items():
            batch = uuid.uuid4()
            summary.batches += 1
            credits = [
                {
                    "course_code": i.course_code,
                    "course_title": i.course_title,
                    "credits": str(i.credits),
                    "grade": i.letter_grade,
                    "grade_point": str(i.grade_point) if i.grade_point is not None else None,
                    "academic_year": i.academic_year,
                }
                for i in items
            ]
            try:
                res = await adapter.push_credits(apaar_id=items[0].apaar_id, credits=credits, batch_id=str(batch))
                ok = isinstance(res, dict) and res.get("status") in ("sent", "acknowledged", "ok", "success")
                status = "acknowledged" if ok else "pushed"
            except Exception as exc:  # noqa: BLE001
                res, status = {"error": str(exc)[:500]}, "failed"
            for i in items:
                i.push_batch_id, i.status, i.response, i.attempts = (
                    batch,
                    status,
                    res if isinstance(res, dict) else None,
                    i.attempts + 1,
                )
            if status == "acknowledged":
                summary.acknowledged += len(items)
            elif status == "failed":
                summary.failed += len(items)
            else:
                summary.pushed += len(items)
            await self._emit(
                {"acknowledged": "abc.acknowledged", "failed": "abc.failed"}.get(status, "abc.pushed"),
                {"student_id": str(sid), "batch_id": str(batch), "rows": len(items)},
                "student",
                sid,
            )
        await self.db.flush()
        return summary

    async def ledger(
        self, student_id: uuid.UUID | None, status: str | None, *, mine: bool = False
    ) -> list[AbcLedgerRow]:
        q = select(AbcCreditLedger).where(AbcCreditLedger.institution_id == self.inst)
        if mine:
            sids = select(StudentProgramEnrollment.student_id).where(
                StudentProgramEnrollment.id.in_(await self.mine() or [uuid.uuid4()])
            )
            q = q.where(AbcCreditLedger.student_id.in_(sids))
        if student_id:
            q = q.where(AbcCreditLedger.student_id == student_id)
        if status:
            q = q.where(AbcCreditLedger.status == status)
        rows = (await self.db.execute(q.order_by(AbcCreditLedger.created_at.desc()).limit(5000))).scalars().all()
        return [
            AbcLedgerRow(
                id=r.id,
                student_id=r.student_id,
                apaar_id=r.apaar_id,
                course_code=r.course_code,
                course_title=r.course_title,
                credits=float(r.credits),
                letter_grade=r.letter_grade,
                grade_point=float(r.grade_point) if r.grade_point is not None else None,
                academic_year=r.academic_year,
                status=r.status,
                push_batch_id=r.push_batch_id,
                attempts=r.attempts,
                updated_at=r.updated_at,
            )
            for r in rows
        ]

    async def ledger_retry(self, row_id: uuid.UUID) -> AbcPushSummary:
        self.require_issue()
        row = (
            await self.db.execute(
                select(AbcCreditLedger).where(AbcCreditLedger.id == row_id, AbcCreditLedger.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Ledger row not found")
        row.status = "pending"
        await self.db.flush()
        return await self.abc_push(AbcPushRequest(student_ids=[row.student_id]))

    async def on_version_created(self, result_run_id: uuid.UUID) -> int:
        """A newer result version supersedes older rows → revoke their ledger rows, queue the new version."""
        new_rows = (
            (
                await self.db.execute(
                    select(StudentCourseResult).where(
                        StudentCourseResult.run_id == result_run_id, StudentCourseResult.supersedes_id.is_not(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        n = 0
        for r in new_rows:
            old = (
                await self.db.execute(
                    select(AbcCreditLedger).where(AbcCreditLedger.student_course_result_id == r.supersedes_id)
                )
            ).scalar_one_or_none()
            if old is None:
                continue
            old.status = "revoked"
            exists = (
                await self.db.execute(
                    select(AbcCreditLedger.id).where(AbcCreditLedger.student_course_result_id == r.id)
                )
            ).first()
            if not exists and r.result_status in ("pass", "credit_transfer"):
                self.db.add(
                    AbcCreditLedger(
                        institution_id=self.inst,
                        student_id=old.student_id,
                        apaar_id=old.apaar_id,
                        student_course_result_id=r.id,
                        term_id=r.term_id,
                        course_code=old.course_code,
                        course_title=old.course_title,
                        credits=r.credits,
                        letter_grade=r.letter_grade,
                        grade_point=r.grade_point,
                        academic_year=old.academic_year,
                        status="pending",
                    )
                )
            n += 1
        await self.db.flush()
        return n
