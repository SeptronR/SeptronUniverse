"""Guardians, documents, undertakings, ID cards and verification — Prompts/07 §07.6 ``student_service`` rules 4–6.

Rules
1. **Guardians**: unique per (student, relation, name) (409); one primary. With ``students.guardians_portal`` on, a
   guardian with ``portal_access`` gets a parent-portal user (role ``parent``) — **reused** when a guardian user with
   the same phone or e-mail exists (siblings share one login) — otherwise a new one with a temporary password
   (``guardian.welcome``). ``guardian_portal_consent`` is toggled by the registrar (``students:update``) or by the
   student themself once adult (setting ``students.adult_age``, pack default 18); parents only ever see consented
   wards.
2. **Documents** (``students.documents``): office uploads are verified on upload, a student's own uploads wait for
   ``POST /documents/{id}/verify``; deletion by the office (or the student for an unverified own upload). Beat
   ``students.document_expiry`` reminds before ``expires_on`` (setting ``students.document_expiry_days``).
3. **Undertakings** (``students.undertakings``): texts are the platform ``document_templates`` of type ``undertaking``
   (revision 0007, IN pack texts; an institution copy wins); accepting records ip / user agent / optional drawn
   signature and counts for the **current academic year** (a re-acceptance next year updates the row — every
   acceptance is audited). **Gates**: registration (Phase 09) and hostel (Phase 20) call
   ``assert_undertakings(student, gate)`` → ``409 RULE_VIOLATION`` ``UNDERTAKING_PENDING`` while a required one
   (setting ``students.undertakings_required``, pack default ``anti_ragging`` + ``conduct``; hostel adds
   ``hostel_rules``) is pending.
4. **ID cards** (``students.id_cards``): a signed token (``core.security.sign_payload``) valid until the end of the
   expected graduation year (or ``students.id_card_validity_years``) is the QR payload → public ``GET /verify/{token}``
   (name, registration number, programme, status); single PDF or a ZIP job (``students.id_cards``). The renderer is
   WeasyPrint over the ``id_card`` template when its native libraries load, else the vector card writer
   (``utils/pdf.id_card_pdf``) — Phase 26 takes over rendering and the unified verification endpoint.
"""

import base64
import io
import uuid
import zipfile
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, time
from typing import Any

from fastapi import UploadFile
from jinja2.sandbox import SandboxedEnvironment
from sqlalchemy import func, select

from app.core.config import settings
from app.core.errors import APIError, ErrorCode
from app.core.features import is_enabled
from app.core.security import generate_temp_password, hash_password, sign_payload, verify_signed
from app.core.tenancy import institution_tz
from app.models.platform import College, Role, User, UserRole
from app.models.students import Student, StudentDocument, StudentGuardian, StudentUndertaking
from app.repositories.student_repository import StudentDocumentRepository, UndertakingRepository
from app.schemas.students import (
    DocumentOut,
    GuardianIn,
    GuardianOut,
    GuardianUpdate,
    IdCardResponse,
    UndertakingAccept,
    UndertakingOut,
    UndertakingStatus,
    VerifyResponse,
)
from app.services.students.common import StudentServiceBase, snap

TEN_YEARS = 10 * 365 * 24 * 3600
GUARDIAN_KEYS = ("relation", "name", "phone", "email", "is_primary", "portal_access", "user_id")
UNDERTAKING_GATES = {"registration": (), "hostel": ("hostel_rules",)}
_jinja = SandboxedEnvironment(autoescape=False)


class StudentRecordsService(StudentServiceBase):
    # ---- rule 1: guardians ------------------------------------------------------------------------------------------
    async def guardian_responses(self, student: Student) -> list[GuardianOut]:
        from app.core.authz.masking import mask_pii

        rows = await self.guardians.for_student(student.id)
        users = await self.students.users([g.user_id for g in rows])
        own = student.user_id is not None and student.user_id == self.actor_id
        out = []
        for g in rows:
            r = GuardianOut.model_validate(g)
            user = users.get(g.user_id) if g.user_id else None
            r.username = user.username if user else None
            out.append(r if own or g.user_id == self.actor_id else mask_pii(r, self.principal, "students"))
        return out

    async def list_guardians(self, student_id: uuid.UUID) -> list[GuardianOut]:
        return await self.guardian_responses(await self.students.get_visible(student_id))

    async def add_guardian(self, student_id: uuid.UUID, body: GuardianIn) -> dict[str, Any]:
        student = await self.students.get_visible(student_id, for_update=True)
        account = await self.add_guardian_row(student, body)
        return {"guardians": await self.guardian_responses(student), "account": account}

    async def add_guardian_row(self, student: Student, g: GuardianIn, *, notify: bool = True) -> dict[str, Any] | None:
        if await self.guardians.duplicate(student.id, g.relation.value, g.name.strip()):
            raise APIError(
                409, ErrorCode.CONFLICT, f"{g.relation.value} {g.name} is already a guardian", {"field": "guardians"}
            )
        if g.is_primary:
            await self.guardians.clear_primary(student.id)
        phone = "".join(ch for ch in (g.phone or "") if ch.isdigit() or ch == "+")[:20] or None
        row = await self.guardians.add(
            StudentGuardian(
                institution_id=self.inst,
                student_id=student.id,
                relation=g.relation.value,
                name=g.name.strip(),
                phone=phone,
                email=str(g.email) if g.email else None,
                occupation=g.occupation,
                annual_income_paise=g.annual_income_paise,
                address=g.address,
                is_primary=g.is_primary,
                portal_access=g.portal_access,
            )
        )
        account: dict[str, Any] | None = None
        if (
            g.create_portal_user
            and g.portal_access
            and (phone or g.email)
            and await is_enabled(self.inst, "students.guardians_portal")
        ):
            user, temp, reused = await self._guardian_user(row, phone, str(g.email) if g.email else None)
            row.user_id = user.id
            await self.db.flush()
            account = {"guardian_id": str(row.id), "username": user.username, "temp_password": temp, "reused": reused}
            await self._emit(
                "guardian.linked",
                {"student_id": str(student.id), "guardian_id": str(row.id), "user_id": str(user.id), "reused": reused},
                "student",
                student.id,
            )
            if not reused and notify:
                await self._notify(
                    "guardian.welcome",
                    [user.id],
                    {
                        "name": row.name,
                        "student_name": student.full_name,
                        "username": user.username,
                        "institution_name": (await self.institution()).name,
                    },
                )
        await self._audit("guardian_add", "student", student.id, None, snap(row, GUARDIAN_KEYS))
        return account

    async def _guardian_user(
        self, guardian: StudentGuardian, phone: str | None, email: str | None
    ) -> tuple[User, str | None, bool]:
        role = (
            await self.db.execute(
                select(Role).where(Role.institution_id == self.inst, Role.slug == "parent", Role.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if role is None:
            raise APIError(422, ErrorCode.VALIDATION, "The institution has no 'parent' role")
        existing = await self.guardians.guardian_user(phone, email)
        if existing is not None:
            await self._ensure_parent_role(existing.id, role.id)
            return existing, None, True
        base = f"p{phone.lstrip('+')[-10:]}" if phone else (email or "parent").split("@")[0].lower()
        username = base[:70]
        n = 1
        while (
            await self.db.execute(
                select(User.id).where(User.institution_id == self.inst, func.lower(User.username) == username.lower())
            )
        ).first() is not None:
            n += 1
            username = f"{base[:66]}.{n}"
        temp = generate_temp_password()
        user = User(
            institution_id=self.inst,
            username=username,
            email=email,
            phone=phone,
            display_name=guardian.name,
            user_type="guardian",
            password_hash=hash_password(temp),
            must_change_password=True,
            is_verified=False,
            locale="en-IN",
            created_by=self.actor_id,
        )
        self.db.add(user)
        await self.db.flush()
        await self._ensure_parent_role(user.id, role.id)
        return user, temp, False

    async def _ensure_parent_role(self, user_id: uuid.UUID, role_id: uuid.UUID) -> None:
        exists = (
            await self.db.execute(select(UserRole.id).where(UserRole.user_id == user_id, UserRole.role_id == role_id))
        ).first()
        if exists is None:
            self.db.add(
                UserRole(
                    institution_id=self.inst,
                    user_id=user_id,
                    role_id=role_id,
                    scope_type="self",
                    scope_id=None,
                    assigned_by=self.actor_id,
                )
            )
            await self.db.flush()

    async def update_guardian(
        self, student_id: uuid.UUID, guardian_id: uuid.UUID, body: GuardianUpdate
    ) -> list[GuardianOut]:
        student = await self.students.get_visible(student_id, for_update=True)
        row = await self.guardians.get(student.id, guardian_id)
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Guardian not found")
        values = body.model_dump(exclude_unset=True)
        old = snap(row, GUARDIAN_KEYS)
        if values.get("is_primary"):
            await self.guardians.clear_primary(student.id, keep=row.id)
        for k, v in values.items():
            if k == "phone" and v:
                v = "".join(ch for ch in v if ch.isdigit() or ch == "+")[:20]
            if k == "email" and v is not None:
                v = str(v)
            setattr(row, k, v)
        await self.db.flush()
        await self._audit("guardian_update", "student", student.id, old, snap(row, GUARDIAN_KEYS))
        return await self.guardian_responses(student)

    async def delete_guardian(self, student_id: uuid.UUID, guardian_id: uuid.UUID) -> list[GuardianOut]:
        student = await self.students.get_visible(student_id, for_update=True)
        row = await self.guardians.get(student.id, guardian_id)
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Guardian not found")
        old = snap(row, GUARDIAN_KEYS)
        await self.guardians.delete(row)
        await self._audit("guardian_delete", "student", student.id, old, None)
        return await self.guardian_responses(student)

    async def set_consent(self, student_id: uuid.UUID, consent: bool) -> dict[str, Any]:
        student = await self.students.get_visible(student_id, for_update=True)
        own = student.user_id is not None and student.user_id == self.actor_id
        if own:
            if not await self.is_adult(student.dob):
                raise APIError(
                    403,
                    ErrorCode.PERMISSION_DENIED,
                    "Students under the age of majority cannot change the guardian consent — ask the office",
                    {"reason": "minor"},
                )
        elif not self.can("students", "update"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Requires students:update")
        previous = student.guardian_portal_consent
        student.guardian_portal_consent = consent
        await self.db.flush()
        await self._audit(
            "guardian_consent",
            "student",
            student.id,
            {"guardian_portal_consent": previous},
            {"guardian_portal_consent": consent, "by_student": own},
        )
        await self._emit(
            "student.updated",
            {"student_id": str(student.id), "fields": ["guardian_portal_consent"], "consent": consent},
            "student",
            student.id,
        )
        return {"student_id": str(student.id), "guardian_portal_consent": consent}

    # ---- rule 2: documents ------------------------------------------------------------------------------------------
    async def document_responses(self, student: Student) -> list[DocumentOut]:
        today = await self.today()
        out = []
        for d in await StudentDocumentRepository(self.db).for_student(student.id):
            r = DocumentOut.model_validate(d)
            r.is_verified = d.verified_at is not None
            r.is_expired = bool(d.expires_on and d.expires_on < today)
            out.append(r)
        return out

    async def list_documents(self, student_id: uuid.UUID) -> list[DocumentOut]:
        return await self.document_responses(await self.students.get_visible(student_id))

    async def add_document(
        self, student_id: uuid.UUID, upload: UploadFile, doc_type: str, expires_on: date | None, remarks: str | None
    ) -> DocumentOut:
        from app.services.file_service import DOCUMENT_TYPES, IMAGE_TYPES, FileService, storage

        student = await self.students.get_visible(student_id)
        own = student.user_id is not None and student.user_id == self.actor_id
        if not own and not self.can("students", "update"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Requires students:update")
        allowed = set((await self.pack()).students.document_types)
        if allowed and doc_type not in allowed:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"Unknown document type {doc_type!r}",
                {"field": "doc_type", "allowed": sorted(allowed)},
            )
        saved = await FileService(self.db).save(
            upload, "student-documents", IMAGE_TYPES + DOCUMENT_TYPES, max_mb=10, institution_id=self.inst
        )
        repo = StudentDocumentRepository(self.db)
        doc = await repo.add(
            StudentDocument(
                institution_id=self.inst,
                student_id=student.id,
                doc_type=doc_type,
                file_url=storage.signed_url(saved.key, TEN_YEARS),
                expires_on=expires_on,
                remarks=remarks,
                verified_by=None if own else self.actor_id,
                verified_at=None if own else datetime.now(UTC),
            )
        )
        await self._audit(
            "document_add", "student", student.id, None, {"doc_type": doc_type, "self": own, "key": saved.key}
        )
        return (await self._doc_out([doc]))[0]

    async def _doc_out(self, docs: list[StudentDocument]) -> list[DocumentOut]:
        today = await self.today()
        out = []
        for d in docs:
            r = DocumentOut.model_validate(d)
            r.is_verified = d.verified_at is not None
            r.is_expired = bool(d.expires_on and d.expires_on < today)
            out.append(r)
        return out

    async def _visible_document(self, doc_id: uuid.UUID) -> tuple[StudentDocument, Student]:
        doc = await StudentDocumentRepository(self.db).get(doc_id, for_update=True)
        if doc is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Document not found")
        student = await self.students.get_visible(doc.student_id)
        return doc, student

    async def verify_document(self, doc_id: uuid.UUID, remarks: str | None) -> DocumentOut:
        doc, student = await self._visible_document(doc_id)
        if not self.can("students", "update"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Requires students:update")
        doc.verified_by, doc.verified_at = self.actor_id, datetime.now(UTC)
        if remarks is not None:
            doc.remarks = remarks
        await self.db.flush()
        await self._audit(
            "document_verify", "student", student.id, None, {"document_id": str(doc.id), "doc_type": doc.doc_type}
        )
        return (await self._doc_out([doc]))[0]

    async def delete_document(self, doc_id: uuid.UUID) -> None:
        doc, student = await self._visible_document(doc_id)
        own = student.user_id is not None and student.user_id == self.actor_id
        if not (self.can("students", "update") or (own and doc.verified_at is None)):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only the office deletes a verified document")
        await StudentDocumentRepository(self.db).delete(doc)
        await self._audit(
            "document_delete", "student", student.id, {"document_id": str(doc_id), "doc_type": doc.doc_type}, None
        )

    async def remind_expiring_documents(self) -> int:
        today = await self.today()
        days = int(await self.setting("students", "document_expiry_days") or 30)
        from datetime import timedelta

        n = 0
        for doc, student in await StudentDocumentRepository(self.db).expiring(
            self.inst, today, today + timedelta(days=days)
        ):
            await self._notify(
                "student.document_expiring",
                [student.user_id],
                {
                    "doc_type": doc.doc_type.replace("_", " "),
                    "student_name": student.full_name,
                    "registration_number": student.registration_number,
                    "expires_on": doc.expires_on.isoformat() if doc.expires_on else "",
                },
                audience={"user_ids": [str(student.user_id)] if student.user_id else [], "roles": ["registrar"]},
            )
            n += 1
        return n

    # ---- rule 3: undertakings ---------------------------------------------------------------------------------------
    async def templates(self) -> dict[str, dict[str, Any]]:
        """undertaking_type → {id, name, body, version}: institution rows win over platform rows; pack text as the
        fallback when revision 0007 has not seeded the table."""
        out: dict[str, dict[str, Any]] = {}
        pack_code = (await self.pack()).code
        for row in await UndertakingRepository(self.db).templates(self.inst):
            layout = row.get("layout") or {}
            if not isinstance(layout, dict):
                continue
            kind = layout.get("undertaking_type")
            if row.get("institution_id") is None and layout.get("pack") not in (None, pack_code):
                continue  # a platform row of another pack
            if kind and kind not in out:
                out[kind] = {
                    "id": row["id"],
                    "name": row["name"],
                    "body": row.get("html_template") or "",
                    "version": layout.get("text_version") or str(row.get("version") or 1),
                }
        for kind, spec in (await self.pack()).students.undertakings.items():
            out.setdefault(kind, {"id": None, "name": spec["name"], "body": spec["body"], "version": spec["version"]})
        return out

    async def _year_start(self, student: Student) -> datetime | None:
        year = await self.current_year(student.college_id)
        if year is None:
            return None
        tz = institution_tz(await self.institution())
        return datetime.combine(year.start_date, time.min, tzinfo=tz).astimezone(UTC)

    async def _context(self, student: Student) -> dict[str, Any]:
        enrolment = await self.enrollments.current(student.id)
        program = (
            (await self.students.program_rows([enrolment.program_id])).get(enrolment.program_id) if enrolment else None
        )
        year = await self.current_year(student.college_id)
        return {
            "student_name": student.full_name,
            "registration_number": student.registration_number,
            "institution_name": (await self.institution()).name,
            "program_name": program.name if program else "",
            "academic_year": year.name if year else "",
        }

    async def undertaking_status(self, student: Student, *, with_body: bool = False) -> list[UndertakingStatus]:
        templates = await self.templates()
        required = set(await self.required_undertakings(student.college_id))
        since = await self._year_start(student)
        accepted = {u.undertaking_type: u for u in await UndertakingRepository(self.db).for_student(student.id)}
        ctx = await self._context(student) if with_body else {}
        out = []
        for kind, tmpl in templates.items():
            row = accepted.get(kind)
            ok = row is not None and (since is None or row.accepted_at >= since)
            item = UndertakingStatus(
                undertaking_type=kind,
                name=tmpl["name"],
                template_id=tmpl["id"],
                version=tmpl["version"],
                required=kind in required,
                accepted=ok,
                accepted_at=row.accepted_at if ok and row else None,
            )
            if with_body and not ok:
                item.body = _jinja.from_string(tmpl["body"]).render(**ctx)
            out.append(item)
        out.sort(key=lambda u: (not u.required, u.accepted, u.undertaking_type))
        return out

    async def pending(self, student: Student) -> list[UndertakingStatus]:
        return [u for u in await self.undertaking_status(student, with_body=True) if u.required and not u.accepted]

    async def my_pending(self) -> list[UndertakingStatus]:
        student = await self._me()
        return await self.pending(student)

    async def _me(self) -> Student:
        row = await self.students.by_user(self.principal.id)
        if row is None:
            raise APIError(
                404, ErrorCode.NOT_FOUND, "Your account is not linked to a student record", {"reason": "no_student"}
            )
        return row

    async def accept(self, body: UndertakingAccept, ip: str | None, user_agent: str | None) -> UndertakingOut:
        student = await self._me()
        templates = await self.templates()
        kind = body.undertaking_type.value
        tmpl = templates.get(kind)
        if tmpl is None and kind != "custom":
            raise APIError(
                422, ErrorCode.VALIDATION, f"No {kind} undertaking is configured", {"field": "undertaking_type"}
            )
        template_id = body.template_id or (tmpl["id"] if tmpl else None)
        if kind == "custom" and template_id is None:
            raise APIError(
                422, ErrorCode.VALIDATION, "A custom undertaking needs template_id", {"field": "template_id"}
            )
        signature_url = await self._signature(body.signature_data_url) if body.signature_data_url else None
        repo = UndertakingRepository(self.db)
        row = await repo.find(student.id, kind, template_id)
        now = datetime.now(UTC)
        if row is None:
            row = await repo.add(
                StudentUndertaking(
                    institution_id=self.inst,
                    student_id=student.id,
                    undertaking_type=kind,
                    template_id=template_id,
                    accepted_at=now,
                    ip=ip,
                    user_agent=(user_agent or "")[:500] or None,
                    signature_url=signature_url,
                )
            )
        else:
            row.accepted_at, row.ip, row.user_agent = now, ip, (user_agent or "")[:500] or None
            if signature_url:
                row.signature_url = signature_url
            await self.db.flush()
        await self._audit(
            "undertaking_accept",
            "student",
            student.id,
            None,
            {
                "undertaking_type": kind,
                "template_id": str(template_id) if template_id else None,
                "version": tmpl["version"] if tmpl else None,
                "ip": ip,
            },
        )
        await self._emit(
            "undertaking.accepted",
            {
                "student_id": str(student.id),
                "undertaking_type": kind,
                "template_id": str(template_id) if template_id else None,
            },
            "student",
            student.id,
        )
        out = UndertakingOut.model_validate(row)
        out.ip = None if row.ip is None else str(row.ip)
        return out

    async def _signature(self, data_url: str) -> str:
        from app.services.file_service import IMAGE_TYPES, FileService, storage

        try:
            raw = base64.b64decode(data_url.split(",", 1)[1], validate=True)
        except (IndexError, ValueError):
            raise APIError(
                422, ErrorCode.VALIDATION, "Unreadable signature image", {"field": "signature_data_url"}
            ) from None
        saved = await FileService(self.db).save(
            raw, "student-signatures", IMAGE_TYPES, max_mb=1, institution_id=self.inst, filename="signature.png"
        )
        return storage.signed_url(saved.key, TEN_YEARS)

    async def assert_undertakings(self, student: Student, gate: str) -> None:
        """Rule 3 gate: ``409 RULE_VIOLATION`` (``UNDERTAKING_PENDING``) while a required undertaking is pending."""
        if gate not in UNDERTAKING_GATES or not await is_enabled(self.inst, "students.undertakings"):
            return
        status = {u.undertaking_type: u for u in await self.undertaking_status(student)}
        needed = list(await self.required_undertakings(student.college_id)) + list(UNDERTAKING_GATES[gate])
        pending = [k for k in dict.fromkeys(needed) if k in status and not status[k].accepted]
        if pending:
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                f"Accept the pending undertakings first: {', '.join(pending)}",
                {"code": "UNDERTAKING_PENDING", "gate": gate, "pending": pending},
            )

    async def remind_pending_undertakings(self, today: date) -> int:
        """Beat ``students.undertaking_reminders``: on the academic year's first day and weekly for four weeks."""
        from app.models.students import Student as S

        year = await self.current_year(None)
        if year is None or (today - year.start_date).days not in (0, 7, 14, 21, 28):
            return 0
        students = (
            (
                await self.db.execute(
                    select(S).where(
                        S.institution_id == self.inst,
                        S.deleted_at.is_(None),
                        S.status.in_(("admitted", "active")),
                        S.user_id.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        n = 0
        for student in students:
            pending = await self.pending(student)
            if pending:
                await self._notify(
                    "undertaking.reminder",
                    [student.user_id],
                    {"academic_year": year.name, "pending": ", ".join(p.name for p in pending)},
                )
                n += 1
        return n

    # ---- rule 4: ID cards / verification ----------------------------------------------------------------------------
    async def id_card(self, student_id: uuid.UUID | None = None) -> IdCardResponse:
        student = await self._me() if student_id is None else await self.students.get_visible(student_id)
        own = student.user_id is not None and student.user_id == self.actor_id
        if not own and not self.can("students", "id_card"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Requires students:id_card")
        return (await self._cards([student]))[0]

    async def _cards(self, students: list[Student]) -> list[IdCardResponse]:
        enrolments = await self.enrollments.current_for([s.id for s in students])
        programs = await self.students.program_rows([e.program_id for e in enrolments.values()])
        batches = await self.students.batch_rows([e.batch_id for e in enrolments.values()])
        colleges = {
            c.id: c
            for c in (
                await self.db.execute(select(College).where(College.id.in_([s.college_id for s in students])))
            ).scalars()
        }
        institution = await self.institution()
        years = int(await self.setting("students", "id_card_validity_years") or 5)
        today = await self.today()
        out = []
        for s in students:
            e = enrolments.get(s.id)
            batch = batches.get(e.batch_id) if e else None
            program = programs.get(e.program_id) if e else None
            last_year = (batch.expected_graduation_year if batch and batch.expected_graduation_year else None) or (
                today.year + years
            )
            valid_until = min(date(last_year, 12, 31), date(today.year + years, 12, 31))
            ttl = max(
                86400, int((datetime.combine(valid_until, time.max, tzinfo=UTC) - datetime.now(UTC)).total_seconds())
            )
            token = sign_payload({"t": "id_card", "i": str(self.inst), "s": str(s.id)}, ttl)
            emergency = (s.current_address or {}).get("emergency_contact") or {}
            out.append(
                IdCardResponse(
                    student_id=s.id,
                    registration_number=s.registration_number,
                    name=s.full_name,
                    program=program.name if program else None,
                    batch=batch.code if batch else None,
                    college=colleges[s.college_id].name if s.college_id in colleges else None,
                    institution=institution.name,
                    blood_group=s.blood_group,
                    photo_url=s.photo_url,
                    emergency_phone=emergency.get("phone") if isinstance(emergency, dict) else None,
                    valid_until=valid_until,
                    token=token,
                    verify_url=f"{settings.frontend_url}/verify/{token}",
                )
            )
        return out

    async def id_card_pdf(self, student_id: uuid.UUID | None = None) -> tuple[bytes, str]:
        card = await self.id_card(student_id)
        return _render_cards([card]), f"{card.registration_number}.pdf"

    async def enqueue_id_cards(self, student_ids: list[uuid.UUID]) -> uuid.UUID:
        from app.core import jobs

        visible = (
            (await self.db.execute(self.students.filtered(scope="all", ids=student_ids).with_only_columns(Student.id)))
            .scalars()
            .all()
        )
        if not visible:
            raise APIError(404, ErrorCode.NOT_FOUND, "No visible students in the selection")
        job = await jobs.enqueue(
            self.db, self.principal, "students.id_cards", {"student_ids": [str(i) for i in visible]}, queue="documents"
        )
        return job.id

    async def run_id_cards(
        self, student_ids: list[uuid.UUID], progress: Callable[[int, str], Awaitable[None]]
    ) -> dict[str, Any]:
        from app.core.files import build_key, storage

        rows = list((await self.db.execute(self.students.filtered(scope="all", ids=student_ids))).scalars().all())
        buf = io.BytesIO()
        tokens: dict[str, str] = {}
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for i in range(0, len(rows), 50):
                cards = await self._cards(rows[i : i + 50])
                for card in cards:
                    zf.writestr(f"{card.registration_number}.pdf", _render_cards([card]))
                    tokens[str(card.student_id)] = card.token
                await progress(
                    int(min(len(rows), i + 50) * 95 / max(len(rows), 1)), f"{min(len(rows), i + 50)}/{len(rows)} cards"
                )
        key = build_key(self.inst, "id-cards", "id-cards.zip")
        await storage.put(key, buf.getvalue(), "application/zip")
        await self._audit("id_cards", "student", None, None, {"count": len(rows)})
        return {"result_url": storage.signed_url(key, 7 * 24 * 3600), "count": len(rows), "tokens": tokens}


def _render_cards(cards: list[IdCardResponse]) -> bytes:
    from app.utils.pdf import id_card_pdf

    return id_card_pdf(
        [
            {
                "institution": c.institution or "",
                "college": c.college or "",
                "name": c.name,
                "registration_number": c.registration_number,
                "program": c.program or "",
                "batch": c.batch or "",
                "blood_group": c.blood_group or "",
                "valid_until": c.valid_until.strftime("%d %b %Y") if c.valid_until else "",
                "emergency": c.emergency_phone or "",
                "verify_url": c.verify_url,
            }
            for c in cards
        ]
    )


async def verify_token(token: str) -> VerifyResponse:
    """Public ``GET /verify/{token}`` — runs on the platform session (no tenant context; the token names it)."""
    from app.db.session import PlatformSessionLocal
    from app.models.academic import Program
    from app.models.platform import Institution
    from app.models.students import StudentProgramEnrollment

    try:
        claims = verify_signed(token)
    except APIError as exc:
        return VerifyResponse(valid=False, document_type="unknown", message=exc.message)
    if claims.get("t") != "id_card":
        return VerifyResponse(
            valid=False, document_type=str(claims.get("t") or "unknown"), message="Unknown document type"
        )
    async with PlatformSessionLocal() as db:
        try:
            sid, iid = uuid.UUID(claims["s"]), uuid.UUID(claims["i"])
        except (KeyError, ValueError):
            return VerifyResponse(valid=False, document_type="id_card", message="Malformed token")
        student = (
            await db.execute(select(Student).where(Student.id == sid, Student.institution_id == iid))
        ).scalar_one_or_none()
        if student is None or student.deleted_at is not None:
            return VerifyResponse(valid=False, document_type="id_card", message="No such student")
        institution = (await db.execute(select(Institution).where(Institution.id == iid))).scalar_one()
        college = (await db.execute(select(College).where(College.id == student.college_id))).scalar_one_or_none()
        program = (
            await db.execute(
                select(Program.name)
                .join(StudentProgramEnrollment, StudentProgramEnrollment.program_id == Program.id)
                .where(StudentProgramEnrollment.student_id == sid, StudentProgramEnrollment.deleted_at.is_(None))
                .order_by(StudentProgramEnrollment.admission_date.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    expires = datetime.fromtimestamp(int(claims.get("exp", 0)), UTC).date()
    current = student.status in ("provisional", "admitted", "active", "on_break", "detained", "graduated", "alumni")
    return VerifyResponse(
        valid=current,
        document_type="id_card",
        holder_name=student.full_name,
        registration_number=student.registration_number,
        program=program,
        status=student.status,
        institution=institution.name,
        college=college.name if college else None,
        valid_until=expires,
        message=None if current else f"The student is {student.status.replace('_', ' ')}",
    )
