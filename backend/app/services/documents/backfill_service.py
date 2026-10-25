"""``documents.backfill_register`` — registers the PDFs earlier phases stored on their own rows as
``issued_documents`` (Prompts/26 §26.2), keeping their original numbers and verification tokens:

* grade cards (``grade_cards.pdf_url`` / ``document_number`` / ``qr_token``),
* transcripts (``transcripts.pdf_url`` / ``document_number`` / ``verification_token``),
* degrees and provisional certificates (``degrees_awarded.pdf_url`` / ``certificate_number`` / ``serial_no``; the token
  from the internal ``digital_credentials`` row),
* hall tickets (``exam_registrations.hall_ticket_pdf_url`` / ``hall_ticket_qr_token``),
* admission offer letters (``admission_offers.letter_url``),
* Phase 25 event certificates — tracked in ``event_registrations.external.certificate_id / certificate_no`` because
  ``certificate_document_id`` references this register: rendered now through the event-certificate template with the
  original certificate number, and ``certificate_document_id`` is set.

``content_hash`` is the SHA-256 of the stored file (a missing file hashes the key and is flagged in the report).
Re-running is idempotent (one live register row per ``(entity_type, entity_id, template_type)``); a number already
used by another document gets a type suffix.
"""

import hashlib
import secrets
import uuid
from typing import Any

from sqlalchemy import select

from app.models.documents import IssuedDocument
from app.services.documents.common import DocumentsBase


class BackfillService(DocumentsBase):
    async def _exists(self, entity_type: str, entity_id: uuid.UUID, template_type: str) -> bool:
        return (
            await self.db.execute(
                select(IssuedDocument.id).where(
                    IssuedDocument.institution_id == self.inst,
                    IssuedDocument.entity_type == entity_type,
                    IssuedDocument.entity_id == entity_id,
                    IssuedDocument.template_type == template_type,
                )
            )
        ).first() is not None

    async def _hash(self, key: str) -> tuple[str, bool]:
        from app.core.files import get_storage

        try:
            return hashlib.sha256(await get_storage().get(key)).hexdigest(), True
        except Exception:  # noqa: BLE001 - legacy rows whose file is gone still enter the register
            return hashlib.sha256(key.encode()).hexdigest(), False

    async def _number(self, number: str, template_type: str) -> str:
        n = number[:40]
        taken = (
            await self.db.execute(
                select(IssuedDocument.id).where(
                    IssuedDocument.institution_id == self.inst, IssuedDocument.document_number == n
                )
            )
        ).first()
        return f"{number[:30]}-{template_type[:8].upper()}"[:40] if taken else n

    async def _token(self, token: str | None) -> str:
        if token:
            used = (
                await self.db.execute(select(IssuedDocument.id).where(IssuedDocument.verification_token == token))
            ).first()
            if used is None:
                return token[:64]
        return secrets.token_hex(32)

    async def register(
        self,
        *,
        template_type: str,
        entity_type: str,
        entity_id: uuid.UUID,
        key: str,
        number: str,
        token: str | None,
        person_type: str | None,
        person_id: uuid.UUID | None,
        issued_at: Any = None,
        serial_no: str | None = None,
        report: dict[str, Any],
    ) -> IssuedDocument | None:
        if await self._exists(entity_type, entity_id, template_type):
            report["skipped"] = report.get("skipped", 0) + 1
            return None
        digest, found = await self._hash(key)
        d = IssuedDocument(
            institution_id=self.inst,
            template_type=template_type,
            person_type=person_type,
            person_id=person_id,
            entity_type=entity_type,
            entity_id=entity_id,
            document_number=await self._number(number, template_type),
            serial_no=serial_no,
            pdf_url=key,
            verification_token=await self._token(token),
            content_hash=digest,
        )
        if issued_at is not None:
            d.issued_at = issued_at
        self.db.add(d)
        await self.db.flush()
        await self.put_meta("doc", d.id, {"backfilled": True, "file_missing": not found, "template_version": 0})
        report[template_type] = report.get(template_type, 0) + 1
        if not found:
            report.setdefault("missing_files", []).append(d.document_number)
        return d

    async def _student_of_enrolment(self, enrol_id: uuid.UUID) -> uuid.UUID | None:
        from app.models.students import StudentProgramEnrollment

        return (
            await self.db.execute(
                select(StudentProgramEnrollment.student_id).where(StudentProgramEnrollment.id == enrol_id)
            )
        ).scalar_one_or_none()

    async def run(self) -> dict[str, Any]:
        report: dict[str, Any] = {}
        await self.grade_cards(report)
        await self.transcripts(report)
        await self.degrees(report)
        await self.hall_tickets(report)
        await self.offers(report)
        await self.event_certificates(report)
        if isinstance(report.get("missing_files"), list):
            report["missing_files"] = report["missing_files"][:100]
        return report

    async def grade_cards(self, report: dict[str, Any]) -> None:
        from app.models.results import GradeCard, StudentTermResult
        from app.models.students import StudentTermRecord

        rows = (
            await self.db.execute(
                select(GradeCard, StudentTermRecord.student_program_enrollment_id)
                .join(StudentTermResult, StudentTermResult.id == GradeCard.student_term_result_id)
                .join(StudentTermRecord, StudentTermRecord.id == StudentTermResult.student_term_record_id)
                .where(GradeCard.institution_id == self.inst, GradeCard.pdf_url.is_not(None))
            )
        ).all()
        for g, enrol_id in rows:
            await self.register(
                template_type="grade_card",
                entity_type="grade_card",
                entity_id=g.id,
                key=str(g.pdf_url),
                number=g.document_number,
                token=g.qr_token,
                person_type="student",
                person_id=await self._student_of_enrolment(enrol_id),
                issued_at=g.generated_at,
                report=report,
            )

    async def transcripts(self, report: dict[str, Any]) -> None:
        from app.models.post_result import Transcript

        for t in (
            await self.db.execute(
                select(Transcript).where(Transcript.institution_id == self.inst, Transcript.pdf_url.is_not(None))
            )
        ).scalars():
            await self.register(
                template_type="transcript",
                entity_type="transcript",
                entity_id=t.id,
                key=str(t.pdf_url),
                number=t.document_number or f"TR/{t.id.hex[:10].upper()}",
                token=t.verification_token,
                person_type="student",
                person_id=await self._student_of_enrolment(t.student_program_enrollment_id),
                issued_at=t.issued_at,
                report=report,
            )

    async def degrees(self, report: dict[str, Any]) -> None:
        from app.models.degrees import DegreeAwarded, DigitalCredential

        for a in (
            await self.db.execute(
                select(DegreeAwarded).where(
                    DegreeAwarded.institution_id == self.inst, DegreeAwarded.pdf_url.is_not(None)
                )
            )
        ).scalars():
            cred = (
                (
                    await self.db.execute(
                        select(DigitalCredential).where(
                            DigitalCredential.entity_id == a.id, DigitalCredential.channel == "internal"
                        )
                    )
                )
                .scalars()
                .first()
            )
            tok = (cred.payload or {}).get("token") if cred is not None else None
            kind = "provisional" if a.award_type in ("provisional", "provisional_certificate") else "degree"
            d = await self.register(
                template_type=kind,
                entity_type="degree_awarded",
                entity_id=a.id,
                key=str(a.pdf_url),
                number=a.certificate_number or f"DEG/{a.id.hex[:10].upper()}",
                token=tok,
                person_type="student",
                person_id=await self._student_of_enrolment(a.student_program_enrollment_id),
                serial_no=a.serial_no,
                report=report,
            )
            if d is not None and a.status in ("cancelled", "revoked"):
                from app.services.documents.common import now_utc

                d.revoked_at, d.revoke_reason = now_utc(), "Award cancelled (back-filled)"

    async def hall_tickets(self, report: dict[str, Any]) -> None:
        from app.models.exams import ExamRegistration

        for r in (
            await self.db.execute(
                select(ExamRegistration).where(
                    ExamRegistration.institution_id == self.inst, ExamRegistration.hall_ticket_pdf_url.is_not(None)
                )
            )
        ).scalars():
            await self.register(
                template_type="hall_ticket",
                entity_type="exam_registration",
                entity_id=r.id,
                key=str(r.hall_ticket_pdf_url),
                number=f"HT/{r.id.hex[:12].upper()}",
                token=r.hall_ticket_qr_token,
                person_type="student",
                person_id=await self._student_of_enrolment(r.student_program_enrollment_id),
                report=report,
            )

    async def offers(self, report: dict[str, Any]) -> None:
        from app.models.admissions import AdmissionOffer

        for o in (
            await self.db.execute(
                select(AdmissionOffer).where(
                    AdmissionOffer.institution_id == self.inst, AdmissionOffer.letter_url.is_not(None)
                )
            )
        ).scalars():
            key = str(o.letter_url)
            if key.startswith(("http://", "https://", "/")):
                continue  # a public URL, not a storage key
            await self.register(
                template_type="offer_letter",
                entity_type="admission_offer",
                entity_id=o.id,
                key=key,
                number=f"OFR/{o.id.hex[:12].upper()}",
                token=None,
                person_type=None,
                person_id=None,
                report=report,
            )

    async def event_certificates(self, report: dict[str, Any]) -> None:
        """Phase 25 certificates → rendered once through the register with the original certificate number."""
        from app.models.events import EventRegistration
        from app.services.documents.render_service import RenderService

        r_svc = RenderService(self.db, self.principal, self.request, self.inst)
        rows = (
            await self.db.execute(
                select(EventRegistration).where(
                    EventRegistration.institution_id == self.inst,
                    EventRegistration.certificate_document_id.is_(None),
                    EventRegistration.external["certificate_id"].astext.is_not(None),
                )
            )
        ).scalars()
        for reg in rows:
            ext = dict(reg.external or {})
            no = str(ext.get("certificate_no") or "")
            try:
                async with self.db.begin_nested():
                    res = await r_svc.render(
                        "event_certificate",
                        "event_registration",
                        reg.id,
                        document_number=(await self._number(no, "event_certificate")) if no else None,
                    )
                reg.certificate_document_id = res.issued_document_id
                ext["certificate_token"] = res.verification_token
                reg.external = ext
                report["event_certificate"] = report.get("event_certificate", 0) + 1
            except Exception as exc:  # noqa: BLE001 - one bad registration must not stop the back-fill
                report.setdefault("event_failures", []).append(
                    {"registration_id": str(reg.id), "error": str(exc)[:200]}
                )
        await self.db.flush()
