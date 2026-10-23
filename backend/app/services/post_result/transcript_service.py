"""Transcripts — Prompts/16 §16.6 ``transcript_service`` ({results.transcripts}).

Request (student / alumni / ward's guardian, or staff on behalf with ``enrollment_id``; Idempotency-Key at the route):
type × copies priced from setting ``exams.transcript_fees`` (paise per copy; defaults ``TRANSCRIPT_FEES``) → a linkage
invoice ``source_type='transcript'`` (head CERTIFICATE) → ``fee_pending``; the payment (consumer
``transcripts.fee_paid``) or a zero fee → ``requested`` and the ``transcripts.issue`` workflow (registrar). Approval
checks open ``transcript|all`` holds (409 ``HOLD_BLOCKED``) and, for ``final``, a cleared no-dues request (409
``NO_DUES_PENDING``) → ``approved``; ``generate`` renders every current published course row across terms with
SGPA / CGPA / class / credits (provisional until the degree is awarded; migration transcripts cite the transfer's
migration certificate) and a ``verification_token`` (``tr`` + 48 hex — distinct from grade-card tokens);
``issue`` → ``issued`` (``results.transcript_ready``). ``reissue`` creates a fresh row with a new token and marks the
old one ``superseded``; ``verify`` (public ``/verify/{token}``) also reports ``superseded`` when a newer result version
was published after the issue. Delivery / purpose live in the request's audit row and the workflow context.
"""

import contextlib
import secrets
import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select

from app.core.errors import APIError, ErrorCode
from app.core.workflow import engine as workflow_engine
from app.enums.post_result import TRANSCRIPT_FEES
from app.models.curriculum import Course
from app.models.fees import FeeInvoice, NoDuesRequest
from app.models.platform import WorkflowInstance
from app.models.post_result import Transcript
from app.models.results import StudentCourseResult, StudentTermResult
from app.models.students import Student, StudentHold, StudentProgramEnrollment, StudentTermRecord, StudentTransfer
from app.repositories.fee_scope import own_enrollment_ids
from app.schemas.post_result import (
    TranscriptIssueRequest,
    TranscriptRequestCreate,
    TranscriptResponse,
    TranscriptTypeOut,
    TranscriptVerifyResponse,
)
from app.services.exams.common import now_utc, rule
from app.services.post_result.common import PostResultBase

WF_TRANSCRIPT = "transcripts.issue"
ENTITY = "transcript"


class TranscriptService(PostResultBase):
    audit_module = "results"

    def _office(self) -> bool:
        # alumni hold ``results:transcript`` for their own requests — the office is the view_all / manage holders
        return any(self.can("results", a) for a in ("view_all", "manage"))

    def require_office(self) -> None:
        if not self._office():
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Transcript office action")

    async def _fees(self) -> dict[str, int]:
        configured = await self.setting("exams", "transcript_fees") or {}
        return {**TRANSCRIPT_FEES, **{k: int(v) for k, v in configured.items() if isinstance(v, int | float)}}

    async def types(self) -> list[TranscriptTypeOut]:
        fees = await self._fees()
        return [
            TranscriptTypeOut(transcript_type=t, fee_paise=fees.get(t, 0), requires_no_dues=t == "final")
            for t in TRANSCRIPT_FEES
        ]

    async def tr(self, tid: uuid.UUID, *, for_update: bool = False) -> Transcript:
        q = select(Transcript).where(Transcript.id == tid, Transcript.institution_id == self.inst)
        if for_update:
            q = q.with_for_update()
        t = (await self.db.execute(q)).scalar_one_or_none()
        if t is None or (not self._office() and not await self.mine(t.student_program_enrollment_id)):
            raise APIError(404, ErrorCode.NOT_FOUND, "Transcript not found")
        return t

    async def outs(self, rows: list[Transcript]) -> list[TranscriptResponse]:
        if not rows:
            return []
        people: dict[uuid.UUID, Student] = dict(
            (
                await self.db.execute(
                    select(StudentProgramEnrollment.id, Student)
                    .join(Student, Student.id == StudentProgramEnrollment.student_id)
                    .where(StudentProgramEnrollment.id.in_({t.student_program_enrollment_id for t in rows}))
                )
            )
            .tuples()
            .all()
        )
        invs = {
            i.id: i.status
            for i in (
                await self.db.execute(
                    select(FeeInvoice).where(
                        FeeInvoice.id.in_({t.fee_invoice_id for t in rows if t.fee_invoice_id} or {uuid.uuid4()})
                    )
                )
            ).scalars()
        }
        out = []
        for t in rows:
            o = TranscriptResponse.model_validate(t, from_attributes=True)
            st = people.get(t.student_program_enrollment_id)
            if st is not None:
                o.student_name = " ".join(x for x in (st.first_name, st.last_name) if x)
                o.registration_number = st.registration_number
            o.invoice_status = invs.get(t.fee_invoice_id) if t.fee_invoice_id else None
            o.superseded = t.status == "superseded" or (t.status == "issued" and await self._newer_results(t))
            if not self._office() and t.status not in ("issued",):
                o.verification_token = None
            out.append(o)
        return out

    async def _newer_results(self, t: Transcript) -> bool:
        if t.issued_at is None:
            return False
        return (
            await self.db.execute(
                select(StudentCourseResult.id).where(
                    StudentCourseResult.student_program_enrollment_id == t.student_program_enrollment_id,
                    StudentCourseResult.status == "published",
                    StudentCourseResult.published_at > t.issued_at,
                )
            )
        ).first() is not None

    # ---- request / pay -----------------------------------------------------------------------------------------------
    async def request_transcript(self, body: TranscriptRequestCreate) -> TranscriptResponse:
        from app.services.fees.invoice_service import InvoiceService

        if body.enrollment_id is not None:
            if not self._office() and not await self.mine(body.enrollment_id):
                raise APIError(404, ErrorCode.NOT_FOUND, "Enrolment not found")
            enrol_id = body.enrollment_id
        else:
            found = (
                await self.db.execute(
                    select(StudentProgramEnrollment.id)
                    .where(
                        StudentProgramEnrollment.id.in_(own_enrollment_ids(self.principal, wards=False, advisees=False))
                    )
                    .order_by(StudentProgramEnrollment.admission_date.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if found is None:
                raise APIError(404, ErrorCode.NOT_FOUND, "No enrolment to issue a transcript for")
            enrol_id = found
        e = (
            await self.db.execute(select(StudentProgramEnrollment).where(StudentProgramEnrollment.id == enrol_id))
        ).scalar_one()
        has_results = (
            await self.db.execute(
                select(StudentCourseResult.id).where(
                    StudentCourseResult.student_program_enrollment_id == e.id, StudentCourseResult.status == "published"
                )
            )
        ).first()
        if has_results is None:
            raise rule("No published results to put on a transcript", "NO_RESULTS", 422)
        t = Transcript(
            institution_id=self.inst,
            student_program_enrollment_id=e.id,
            transcript_type=body.transcript_type,
            copies=body.copies,
            status="fee_pending",
        )
        self.db.add(t)
        await self.db.flush()
        fee = (await self._fees()).get(body.transcript_type, 0) * body.copies
        meta = {
            "type": t.transcript_type,
            "copies": t.copies,
            "delivery": body.delivery,
            "purpose": body.purpose,
            "fee": fee,
        }
        await self._audit("transcript_request", ENTITY, t.id, None, meta)
        if fee > 0:
            inv = await InvoiceService(self.db, None, self.request, self.inst).link(
                "transcript", t.id, fee, e.id, f"Transcript ({t.transcript_type}) × {t.copies}", head_type="certificate"
            )
            t.fee_invoice_id = inv.id
        else:
            await self._paid(t, meta)
        await self.db.flush()
        await self._emit("transcript.requested", {"transcript_id": str(t.id), "type": t.transcript_type}, ENTITY, t.id)
        return (await self.outs([t]))[0]

    async def _meta(self, t: Transcript) -> dict[str, Any]:
        from sqlalchemy import text

        row = (
            await self.db.execute(
                text(
                    "SELECT new_values FROM audit_logs WHERE record_type = 'transcript' AND record_id = CAST(:r AS uuid) "
                    "AND action = 'transcript_request' ORDER BY occurred_at LIMIT 1"
                ),
                {"r": str(t.id)},
            )
        ).first()
        return dict(row[0] or {}) if row else {}

    async def _paid(self, t: Transcript, meta: dict[str, Any] | None = None) -> None:
        t.status = "requested"
        e = (
            await self.db.execute(
                select(StudentProgramEnrollment).where(StudentProgramEnrollment.id == t.student_program_enrollment_id)
            )
        ).scalar_one()
        meta = meta or await self._meta(t)
        try:
            wf = await workflow_engine.start(
                self.db,
                institution_id=self.inst,
                key=WF_TRANSCRIPT,
                entity_type=ENTITY,
                entity_id=t.id,
                started_by=self.actor_id,
                context={
                    "college_id": str(e.college_id),
                    "transcript_type": t.transcript_type,
                    "copies": t.copies,
                    "delivery": meta.get("delivery"),
                    "purpose": meta.get("purpose"),
                },
                title=f"Transcript ({t.transcript_type}) × {t.copies}",
            )
            t.workflow_instance_id = wf.id
        except APIError:
            pass  # approved from the transcripts queue either way

    async def on_paid(self, tid: uuid.UUID) -> None:
        t = (
            await self.db.execute(select(Transcript).where(Transcript.id == tid).with_for_update())
        ).scalar_one_or_none()
        if t is None or t.status != "fee_pending":
            return
        await self._paid(t)
        await self.db.flush()

    async def mine_list(self) -> list[TranscriptResponse]:
        rows = (
            await self.db.execute(
                select(Transcript)
                .where(
                    Transcript.institution_id == self.inst,
                    Transcript.student_program_enrollment_id.in_(own_enrollment_ids(self.principal, advisees=False)),
                )
                .order_by(Transcript.requested_at.desc())
            )
        ).scalars()
        return await self.outs(list(rows))

    async def queue(self, status: str | None) -> list[TranscriptResponse]:
        self.require_office()
        q = select(Transcript).where(Transcript.institution_id == self.inst)
        if status:
            q = q.where(Transcript.status == status)
        colleges = self._college_ids()
        if colleges and not any(st == "institution" for st, _ in getattr(self.principal, "scopes", [])):
            q = q.where(
                Transcript.student_program_enrollment_id.in_(
                    select(StudentProgramEnrollment.id).where(StudentProgramEnrollment.college_id.in_(colleges))
                )
            )
        return await self.outs(
            list((await self.db.execute(q.order_by(Transcript.requested_at.desc()).limit(500))).scalars())
        )

    # ---- approve / generate / issue ----------------------------------------------------------------------------------------
    async def checks(self, t: Transcript) -> dict[str, Any]:
        self.require_office()
        holds = [
            h.hold_type
            for h in (
                await self.db.execute(
                    select(StudentHold).where(
                        StudentHold.student_program_enrollment_id == t.student_program_enrollment_id,
                        StudentHold.released_at.is_(None),
                        StudentHold.hold_type.in_(("transcript", "all")),
                    )
                )
            ).scalars()
        ]
        no_dues = (
            await self.db.execute(
                select(NoDuesRequest.id).where(
                    NoDuesRequest.student_program_enrollment_id == t.student_program_enrollment_id,
                    NoDuesRequest.status == "cleared",
                )
            )
        ).first() is not None
        return {"holds": holds, "no_dues_cleared": no_dues, "requires_no_dues": t.transcript_type == "final"}

    async def _assert_clear(self, t: Transcript) -> None:
        c = await self.checks(t)
        if c["holds"]:
            raise rule("An open transcript hold blocks the issue", "HOLD_BLOCKED", holds=c["holds"])
        if c["requires_no_dues"] and not c["no_dues_cleared"]:
            raise rule("A final transcript needs cleared no-dues", "NO_DUES_PENDING")

    async def approve(self, tid: uuid.UUID, comment: str | None) -> TranscriptResponse:
        self.require_office()
        t = await self.tr(tid, for_update=True)
        if t.status != "requested":
            raise rule(f"A {t.status} transcript cannot be approved", "INVALID_TRANSITION")
        await self._assert_clear(t)
        if t.workflow_instance_id:
            wf = (
                await self.db.execute(select(WorkflowInstance).where(WorkflowInstance.id == t.workflow_instance_id))
            ).scalar_one_or_none()
            if wf is not None and wf.status in ("pending", "escalated"):
                await workflow_engine.act(
                    self.db, instance_id=wf.id, actor=self.principal, decision="approve", comment=comment
                )
                await self.db.refresh(t)
                if t.status == "approved":
                    return (await self.outs([t]))[0]
        await self.mark_approved(t)
        return (await self.outs([t]))[0]

    async def mark_approved(self, t: Transcript) -> None:
        if t.status == "requested":
            t.status = "approved"
            await self.db.flush()
            await self._audit("transcript_approve", ENTITY, t.id, {"status": "requested"}, {"status": "approved"})

    async def _number(self, college_id: uuid.UUID | None) -> str:
        from app.services.sequence_service import SequenceService

        try:
            return (
                await SequenceService(self.db, self.principal, self.request, self.inst).next("transcript", college_id)
            ).rendered[:40]
        except APIError:
            n = (
                await self.db.execute(
                    select(func.count()).select_from(Transcript).where(Transcript.institution_id == self.inst)
                )
            ).scalar_one()
            return f"TR/{now_utc():%Y}/{int(n) + 1:06d}"

    async def _summary(self, enrol_id: uuid.UUID) -> dict[str, Any]:
        rows = (
            await self.db.execute(
                select(StudentCourseResult, Course, StudentTermRecord.term_number)
                .join(Course, Course.id == StudentCourseResult.course_id)
                .outerjoin(
                    StudentTermRecord,
                    (
                        StudentTermRecord.student_program_enrollment_id
                        == StudentCourseResult.student_program_enrollment_id
                    )
                    & (StudentTermRecord.term_id == StudentCourseResult.term_id),
                )
                .where(
                    StudentCourseResult.student_program_enrollment_id == enrol_id,
                    StudentCourseResult.status == "published",
                    StudentCourseResult.is_current.is_(True),
                )
                .order_by(StudentTermRecord.term_number, Course.code)
            )
        ).all()
        terms = (
            await self.db.execute(
                select(StudentTermResult, StudentTermRecord.term_number)
                .join(StudentTermRecord, StudentTermRecord.id == StudentTermResult.student_term_record_id)
                .where(
                    StudentTermRecord.student_program_enrollment_id == enrol_id,
                    StudentTermResult.is_current.is_(True),
                    StudentTermResult.status == "published",
                )
                .order_by(StudentTermRecord.term_number)
            )
        ).all()
        by_term: dict[int, list[Any]] = defaultdict(list)
        for r, c, tn in rows:
            by_term[int(tn or 0)].append((r, c))
        last = terms[-1][0] if terms else None
        return {
            "by_term": by_term,
            "terms": {int(tn): t for t, tn in terms},
            "cgpa": last.cgpa if last else None,
            "credits": last.cumulative_credits
            if last
            else sum((r.credits for r, _, _ in rows if r.result_status in ("pass", "credit_transfer")), Decimal(0)),
            "class": last.result_class if last else None,
            "hashes": sorted(r.hash for r, _, _ in rows if r.hash),
        }

    async def generate(self, tid: uuid.UUID) -> TranscriptResponse:
        self.require_office()
        from app.core.files import build_key, storage
        from app.utils.pdf import simple_pdf

        t = await self.tr(tid, for_update=True)
        if t.status not in ("approved", "generated"):
            raise rule(f"A {t.status} transcript cannot be generated (approve it first)", "INVALID_TRANSITION")
        await self._assert_clear(t)
        e = (
            await self.db.execute(
                select(StudentProgramEnrollment).where(StudentProgramEnrollment.id == t.student_program_enrollment_id)
            )
        ).scalar_one()
        st = (await self.db.execute(select(Student).where(Student.id == e.student_id))).scalar_one()
        s = await self._summary(e.id)
        inst = await self.institution()
        t.document_number = t.document_number or await self._number(e.college_id)
        t.verification_token = f"tr{secrets.token_hex(24)}"
        label = {
            "provisional": "PROVISIONAL TRANSCRIPT",
            "consolidated": "CONSOLIDATED TRANSCRIPT",
            "final": "TRANSCRIPT OF RECORDS",
            "duplicate": "TRANSCRIPT (DUPLICATE)",
            "migration": "TRANSCRIPT (MIGRATION)",
        }[t.transcript_type]
        lines = [
            inst.name,
            label,
            f"No. {t.document_number}",
            f"Name: {' '.join(x for x in (st.first_name, st.last_name) if x)}    Reg. no: {st.registration_number}",
            f"Status: {e.status}{' — provisional, degree not yet awarded' if e.status != 'graduated' and t.transcript_type != 'final' else ''}",
            "",
        ]
        for tn in sorted(s["by_term"]):
            tres = s["terms"].get(tn)
            lines.append(f"Term {tn}" + (f"   SGPA {tres.sgpa}   credits {tres.credits_earned}" if tres else ""))
            for r, c in s["by_term"][tn]:
                lines.append(
                    f"   {c.code:<12} {c.title[:48]:<48} {r.credits!s:>5}  {r.letter_grade or '—':<3} {r.grade_point if r.grade_point is not None else ''}"
                )
            lines.append("")
        lines.append(
            f"CGPA {s['cgpa'] if s['cgpa'] is not None else '—'}   Credits earned {s['credits']}   Class {s['class'] or '—'}"
        )
        if t.transcript_type == "migration":
            mc = (
                await self.db.execute(
                    select(StudentTransfer.migration_certificate_no).where(
                        StudentTransfer.student_id == st.id, StudentTransfer.migration_certificate_no.is_not(None)
                    )
                )
            ).scalar_one_or_none()
            lines.append(f"Migration certificate: {mc or 'to be issued'}")
        lines += ["", f"Verify: /verify/{t.verification_token}", f"Copies: {t.copies}"]
        key = build_key(self.inst, "transcripts", f"{t.document_number.replace('/', '-')}-{t.id.hex[:8]}.pdf")
        await storage.put(key, simple_pdf(lines, title=label.title()), "application/pdf")
        t.pdf_url, t.status = key, "generated"
        await self.db.flush()
        await self._audit(
            "transcript_generate",
            ENTITY,
            t.id,
            None,
            {"document_number": t.document_number, "terms": len(s["by_term"])},
        )
        return (await self.outs([t]))[0]

    async def issue(self, tid: uuid.UUID, body: TranscriptIssueRequest) -> TranscriptResponse:
        self.require_office()
        t = await self.tr(tid, for_update=True)
        if t.status != "generated":
            raise rule("Generate the transcript before issuing it", "INVALID_TRANSITION")
        t.status, t.issued_at, t.issued_by = "issued", now_utc(), self.actor_id
        await self.db.flush()
        await self._audit("transcript_issue", ENTITY, t.id, None, {"delivery": body.delivery, "remarks": body.remarks})
        await self._emit(
            "transcript.issued",
            {"transcript_id": str(t.id), "enrollment_id": str(t.student_program_enrollment_id)},
            ENTITY,
            t.id,
        )
        st = (
            await self.db.execute(
                select(Student)
                .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
                .where(StudentProgramEnrollment.id == t.student_program_enrollment_id)
            )
        ).scalar_one()
        if st.user_id:
            await self._notify(
                "results.transcript_ready", [st.user_id], {"type": t.transcript_type, "number": t.document_number or ""}
            )
        return (await self.outs([t]))[0]

    async def reissue(self, tid: uuid.UUID) -> TranscriptResponse:
        self.require_office()
        old = await self.tr(tid, for_update=True)
        if old.status not in ("issued", "generated"):
            raise rule("Only a generated / issued transcript is reissued", "INVALID_TRANSITION")
        new = Transcript(
            institution_id=self.inst,
            student_program_enrollment_id=old.student_program_enrollment_id,
            transcript_type=old.transcript_type,
            copies=old.copies,
            fee_invoice_id=old.fee_invoice_id,
            workflow_instance_id=old.workflow_instance_id,
            status="approved",
        )
        self.db.add(new)
        old.status = "superseded"
        await self.db.flush()
        await self._audit("transcript_reissue", ENTITY, new.id, None, {"supersedes": str(old.id)})
        await self.generate(new.id)
        return await self.issue(new.id, TranscriptIssueRequest(remarks=f"reissue of {old.document_number}"))

    async def cancel(self, tid: uuid.UUID) -> TranscriptResponse:
        t = await self.tr(tid, for_update=True)
        if t.status in ("issued", "superseded", "cancelled"):
            raise rule(f"A {t.status} transcript cannot be cancelled", "INVALID_TRANSITION")
        t.status = "cancelled"
        if t.workflow_instance_id:
            with contextlib.suppress(APIError, TypeError):
                await workflow_engine.cancel(self.db, instance_id=t.workflow_instance_id, actor=self.principal)
        await self.db.flush()
        await self._audit("transcript_cancel", ENTITY, t.id, None, {})
        return (await self.outs([t]))[0]

    async def download(self, tid: uuid.UUID) -> tuple[bytes, str]:
        from app.core.files import storage

        t = await self.tr(tid)
        if not t.pdf_url or t.status not in ("generated", "issued", "superseded"):
            raise APIError(404, ErrorCode.NOT_FOUND, "The transcript is not generated yet")
        if not self._office() and t.status != "issued":
            raise APIError(404, ErrorCode.NOT_FOUND, "The transcript is not issued yet")
        data = await storage.get(t.pdf_url)
        if not data:
            raise APIError(404, ErrorCode.NOT_FOUND, "The transcript file is missing")
        return data, (t.document_number or "transcript").replace("/", "-")

    async def reminders(self) -> int:
        """Beat (daily): remind the registrar's queue of paid requests waiting more than three days."""
        from datetime import timedelta

        n = (
            await self.db.execute(
                select(func.count())
                .select_from(Transcript)
                .where(
                    Transcript.institution_id == self.inst,
                    or_(Transcript.status == "requested", Transcript.status == "approved"),
                    Transcript.requested_at < now_utc() - timedelta(days=3),
                )
            )
        ).scalar_one()
        if n:
            await self._notify(
                "results.transcript_ready",
                [],
                {"type": f"{n} pending request(s)", "number": "queue"},
                audience={"roles": ["registrar"]},
            )
        return int(n)


async def verify_transcript(token: str) -> TranscriptVerifyResponse | None:
    """``/verify/{token}`` for transcript tokens (``tr`` + 48 hex; platform session — the token names the tenant)."""
    from app.db.session import PlatformSessionLocal
    from app.models.platform import Institution
    from app.services.results.compute import checksum

    if not (token.startswith("tr") and len(token) == 50):
        return None
    async with PlatformSessionLocal() as db:
        row = (
            await db.execute(
                select(Transcript, Student, Institution.name)
                .join(StudentProgramEnrollment, StudentProgramEnrollment.id == Transcript.student_program_enrollment_id)
                .join(Student, Student.id == StudentProgramEnrollment.student_id)
                .join(Institution, Institution.id == Transcript.institution_id)
                .where(Transcript.verification_token == token)
            )
        ).first()
        if row is None:
            return TranscriptVerifyResponse(valid=False, message="Unknown transcript")
        t, st, inst = row
        last = (
            await db.execute(
                select(StudentTermResult)
                .join(StudentTermRecord, StudentTermRecord.id == StudentTermResult.student_term_record_id)
                .where(
                    StudentTermRecord.student_program_enrollment_id == t.student_program_enrollment_id,
                    StudentTermResult.is_current.is_(True),
                    StudentTermResult.status == "published",
                )
                .order_by(StudentTermRecord.term_number.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        hashes = (
            (
                await db.execute(
                    select(StudentCourseResult.hash).where(
                        StudentCourseResult.student_program_enrollment_id == t.student_program_enrollment_id,
                        StudentCourseResult.status.in_(("published", "superseded")),
                        StudentCourseResult.published_at <= (t.issued_at or now_utc()),
                    )
                )
            )
            .scalars()
            .all()
        )
        newer = (
            t.issued_at is not None
            and (
                await db.execute(
                    select(StudentCourseResult.id).where(
                        StudentCourseResult.student_program_enrollment_id == t.student_program_enrollment_id,
                        StudentCourseResult.status == "published",
                        StudentCourseResult.published_at > t.issued_at,
                    )
                )
            ).first()
            is not None
        )
    superseded = t.status == "superseded" or newer
    return TranscriptVerifyResponse(
        valid=t.status in ("issued", "superseded"),
        document_number=t.document_number,
        transcript_type=t.transcript_type,
        holder_name=" ".join(x for x in (st.first_name, st.last_name) if x),
        registration_number=st.registration_number,
        cgpa=last.cgpa if last else None,
        credits_earned=last.cumulative_credits if last else None,
        hash=checksum(sorted(h for h in hashes if h)),
        superseded=superseded,
        issued_at=t.issued_at,
        institution=inst,
        message="Superseded by a later result version — ask the holder for the reissued transcript"
        if superseded
        else None,
    )


def _actor(instance: WorkflowInstance, actor: Any) -> Any:
    from app.services.fees.payment_service import _Actor

    return _Actor(instance.institution_id, getattr(actor, "id", None))


@workflow_engine.on(WF_TRANSCRIPT, "approved")
async def _transcript_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type != ENTITY:
        return
    t = (
        await db.execute(select(Transcript).where(Transcript.id == instance.entity_id).with_for_update())
    ).scalar_one_or_none()
    if t is not None:
        await TranscriptService(db, _actor(instance, actor), None, instance.institution_id).mark_approved(t)


@workflow_engine.on(WF_TRANSCRIPT, "rejected")
async def _transcript_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type != ENTITY:
        return
    t = (
        await db.execute(select(Transcript).where(Transcript.id == instance.entity_id).with_for_update())
    ).scalar_one_or_none()
    if t is not None and t.status == "requested":
        t.status = "cancelled"
        await db.flush()


@workflow_engine.summariser(ENTITY)
async def _summarise(db: Any, entity_id: uuid.UUID) -> tuple[str | None, str | None]:
    t = (await db.execute(select(Transcript).where(Transcript.id == entity_id))).scalar_one_or_none()
    return (f"Transcript ({t.transcript_type}) × {t.copies}", "/admin/results/transcripts") if t else (None, None)
