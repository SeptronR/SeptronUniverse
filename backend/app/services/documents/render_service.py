"""The document renderer — Prompts/26 §26.6 ``render_service`` (**the API every phase calls**).

``await render(db, principal, template_type, entity_type, entity_id, *, template_id=None, register=None,
variables_override=None, watermark=None, language=None, allow_multiple=False, document_number=None, job_id=None)``

1. Template: institution override (latest published ``version``, ``is_default`` first) → platform default of the
   type (``institution_id`` NULL; the IN-pack bilingual variant when ``language`` asks for one) → the built-in
   default of ``defaults.py``. The issued row keeps the exact ``template_id`` (one row per version), so re-rendering
   an old document uses its original version.
2. Variables from the resolver registry (``register_resolver(entity_type)``; the built-ins cover enrolments,
   students, staff, event registrations, hostel allocations, grade cards, transcripts, degrees, exam registrations,
   admission offers and certificate requests), the institution, the ``documents.signatories`` setting, then
   ``variables_override``. Rendering uses Jinja's ``SandboxedEnvironment`` over plain dicts only (no ORM objects).
3. HTML → PDF through ``app.utils.pdf.render_pdf`` (WeasyPrint with the bundled Noto fonts; the plain fallback writer
   on workstations without Pango), with the signed QR (``/verify/{token}``), signatures / seal and watermark.
4. Register entry: ``document_number`` from ``number_sequences('doc:{type}')`` (yearly reset; or the caller's number),
   ``serial_no`` from the register (``documents.serial_registers``: lowest reserved serial, else the next one),
   ``content_hash`` = SHA-256 of the stored PDF, ``verification_token`` = 32 random bytes (hex), storage key in
   ``pdf_url``; event ``documents.issued``.
5. Idempotent per ``(entity_type, entity_id, template_type)`` unless ``allow_multiple``; ``reissue`` revokes the old
   document and issues a new one (``superseded_by`` / ``supersedes`` in ``documents_meta``).
"""

import hashlib
import html as _html
import io
import json
import re
import secrets
import uuid
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.enums.documents import DEFAULT_SIGNATORIES, MULTI_TYPES, REGISTERS, TEMPLATE_TYPES
from app.models.academic import Batch, Program
from app.models.documents import DocumentTemplate, IssuedDocument
from app.models.hr import Designation, Staff
from app.models.platform import Department
from app.models.students import Student, StudentGuardian, StudentProgramEnrollment
from app.schemas.documents import DocRenderResult
from app.services.documents.common import DocumentsBase, forbidden, not_found, now_utc, rule
from app.services.documents.defaults import compile_layout, default_template

Resolver = Callable[["RenderService", uuid.UUID], Awaitable[tuple[dict[str, Any], str | None, uuid.UUID | None]]]
RESOLVERS: dict[str, Resolver] = {}
PREFIX: dict[str, str] = {
    "bonafide": "BON",
    "character": "CHR",
    "conduct": "CON",
    "tc": "TC",
    "migration": "MIG",
    "course_completion": "CC",
    "provisional": "PC",
    "degree": "DEG",
    "grade_card": "GC",
    "transcript": "TR",
    "hall_ticket": "HT",
    "experience": "EXP",
    "service": "SRV",
    "noc": "NOC",
    "internship_noc": "INOC",
    "id_card": "ID",
    "event_certificate": "EVC",
    "hostel_allotment": "HAL",
    "donation_receipt_80g": "80G",
    "alumni_membership_card": "ALM",
    "phd_registration_letter": "PHDR",
    "phd_synopsis_ack": "PHDS",
    "phd_provisional_certificate": "PHDP",
    "examiner_invitation": "PHDX",
}


def register_resolver(entity_type: str) -> Callable[[Resolver], Resolver]:
    """``documents.register_resolver(entity_type, fn)`` — phases register the variables of their entities."""

    def deco(fn: Resolver) -> Resolver:
        RESOLVERS[entity_type] = fn
        return fn

    return deco


def _d(v: Any) -> str:
    if isinstance(v, datetime):
        return v.strftime("%d-%m-%Y")
    if isinstance(v, date):
        return v.strftime("%d-%m-%Y")
    return "" if v is None else str(v)


def _merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge; ``a.b`` keys in ``extra`` address nested values."""
    out = json.loads(json.dumps(base, default=str))
    for k, v in (extra or {}).items():
        target = out
        parts = str(k).split(".")
        for p in parts[:-1]:
            nxt = target.get(p)
            if not isinstance(nxt, dict):
                nxt = target[p] = {}
            target = nxt
        target[parts[-1]] = v
    return dict(out)


def _sandbox() -> Any:
    from jinja2.sandbox import SandboxedEnvironment

    return SandboxedEnvironment(autoescape=True)


def html_to_lines(markup: str) -> list[str]:
    text = re.sub(r"<style.*?</style>", "", markup, flags=re.S)
    text = re.sub(r"<br\s*/?>|</p>|</div>|</tr>|</h1>", "\n", text)
    text = _html.unescape(re.sub(r"<[^>]+>", " ", text))
    return [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines() if ln.strip()]


def qr_data_url(text: str) -> str | None:
    try:
        import base64

        import qrcode

        buf = io.BytesIO()
        qrcode.make(text).save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001 - a QR-less certificate still verifies by token / number
        return None


def pdf_bytes(markup: str, title: str, watermark: str | None = None) -> bytes:
    from app.utils.pdf import render_pdf

    lines = html_to_lines(markup)
    if watermark:
        lines.append(f"[{watermark}]")
    return render_pdf(markup, lines, title=title)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RenderService(DocumentsBase):
    # ---- templates -----------------------------------------------------------------------------------------------------
    @staticmethod
    def published(t: DocumentTemplate) -> bool:
        return bool(((t.layout or {}).get("_meta") or {}).get("status", "published") == "published")

    async def resolve_template(
        self,
        template_type: str,
        template_id: uuid.UUID | None = None,
        language: str | None = None,
        college_id: uuid.UUID | None = None,
    ) -> DocumentTemplate | None:
        if template_id is not None:
            t = (
                await self.db.execute(
                    select(DocumentTemplate).where(
                        DocumentTemplate.id == template_id,
                        DocumentTemplate.deleted_at.is_(None),
                        (DocumentTemplate.institution_id == self.inst) | DocumentTemplate.institution_id.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if t is None or t.template_type != template_type:
                raise not_found("Template")
            return t
        want_bi = bool(language and language != "en")
        rows = (
            (
                await self.db.execute(
                    select(DocumentTemplate)
                    .where(
                        DocumentTemplate.template_type == template_type,
                        DocumentTemplate.is_active.is_(True),
                        DocumentTemplate.deleted_at.is_(None),
                        (DocumentTemplate.institution_id == self.inst) | DocumentTemplate.institution_id.is_(None),
                    )
                    .order_by(DocumentTemplate.version.desc())
                )
            )
            .scalars()
            .all()
        )
        rows = [t for t in rows if self.published(t)]

        def rank(t: DocumentTemplate) -> tuple[int, int, int, int, int]:
            college = ((t.layout or {}).get("_meta") or {}).get("college_id")
            return (
                1 if t.institution_id is not None else 0,
                1 if college_id is not None and college == str(college_id) else (0 if college else 1),
                1 if t.is_bilingual == want_bi else 0,
                1 if t.is_default else 0,
                t.version,
            )

        return max(rows, key=rank) if rows else None

    # ---- variables ------------------------------------------------------------------------------------------------------
    async def base_context(self) -> dict[str, Any]:
        from app.models.platform import InstitutionProfile

        inst = await self.institution()
        prof = (
            await self.db.execute(select(InstitutionProfile).where(InstitutionProfile.institution_id == self.inst))
        ).scalar_one_or_none()
        addr = inst.address if isinstance(inst.address, dict) else {}
        signatories = dict(DEFAULT_SIGNATORIES)
        configured = await self.setting("documents", "signatories")
        if isinstance(configured, dict):
            signatories.update(
                {k: {**signatories.get(k, {}), **v} for k, v in configured.items() if isinstance(v, dict)}
            )
        if prof is not None and prof.head_name and signatories.get("principal", {}).get("name") == "Principal":
            signatories["principal"] = {**signatories["principal"], "name": prof.head_name}
        return {
            "institution": {
                "name": inst.name,
                "short_name": inst.short_name,
                "address": ", ".join(str(v) for v in addr.values() if v) if addr else "",
                "logo_url": inst.logo_url,
                "seal_url": prof.seal_url if prof else None,
                "letterhead_url": prof.letterhead_url if prof else None,
            },
            "signatories": signatories,
            "today": _d(await self.today()),
        }

    async def context(
        self, template_type: str, entity_type: str, entity_id: uuid.UUID, overrides: dict[str, Any] | None
    ) -> tuple[dict[str, Any], str | None, uuid.UUID | None]:
        resolver = RESOLVERS.get(entity_type)
        if resolver is None:
            raise APIError(422, ErrorCode.VALIDATION, f"No variables resolver for entity type {entity_type}")
        own, ptype, pid = await resolver(self, entity_id)
        ctx = _merge({**await self.base_context(), **own}, overrides or {})
        ctx.setdefault("purpose", (overrides or {}).get("purpose") or "")
        return ctx, ptype, pid

    async def student_ctx(self, st: Student, e: StudentProgramEnrollment | None) -> dict[str, Any]:
        g = (
            await self.db.execute(
                select(StudentGuardian.name)
                .where(StudentGuardian.student_id == st.id)
                .order_by(StudentGuardian.relation)
                .limit(1)
            )
        ).scalar_one_or_none()
        out: dict[str, Any] = {
            "student": {
                "id": str(st.id),
                "name": st.full_name,
                "name_secondary": (getattr(st, "name_secondary", None) or st.full_name),
                "registration_number": st.registration_number,
                "dob": _d(st.dob),
                "gender": st.gender or "",
                "guardian_name": g or "",
                "photo_url": st.photo_url,
                "blood_group": st.blood_group or "",
            },
            "photo": st.photo_url,
        }
        if e is not None:
            prog = (await self.db.execute(select(Program).where(Program.id == e.program_id))).scalar_one_or_none()
            batch = (await self.db.execute(select(Batch).where(Batch.id == e.batch_id))).scalar_one_or_none()
            dep = (
                (
                    await self.db.execute(select(Department.name).where(Department.id == e.department_id))
                ).scalar_one_or_none()
                if e.department_id
                else None
            )
            year = await self.current_year(e.college_id)
            out["enrolment"] = {
                "id": str(e.id),
                "program": prog.name if prog else "",
                "program_code": prog.code if prog else "",
                "batch": (batch.name or batch.code) if batch else "",
                "department": dep or "",
                "admission_date": _d(e.admission_date),
                "status": e.status,
                "cgpa": str(e.cgpa) if e.cgpa is not None else "",
                "credits_earned": str(e.credits_earned),
                "academic_year": getattr(year, "name", "") if year else "",
                "college_id": str(e.college_id),
            }
        return out

    async def enrolment_of(self, student_id: uuid.UUID) -> StudentProgramEnrollment | None:
        return (
            await self.db.execute(
                select(StudentProgramEnrollment)
                .where(StudentProgramEnrollment.student_id == student_id, StudentProgramEnrollment.deleted_at.is_(None))
                .order_by(StudentProgramEnrollment.admission_date.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def enrolment_ctx(self, enrol_id: uuid.UUID) -> tuple[dict[str, Any], str, uuid.UUID]:
        e = (
            await self.db.execute(select(StudentProgramEnrollment).where(StudentProgramEnrollment.id == enrol_id))
        ).scalar_one_or_none()
        if e is None:
            raise not_found("Enrolment")
        st = (await self.db.execute(select(Student).where(Student.id == e.student_id))).scalar_one()
        return await self.student_ctx(st, e), "student", st.id

    async def staff_ctx(self, staff_id: uuid.UUID) -> tuple[dict[str, Any], str, uuid.UUID]:
        s = (await self.db.execute(select(Staff).where(Staff.id == staff_id))).scalar_one_or_none()
        if s is None:
            raise not_found("Staff")
        desig = (
            (
                await self.db.execute(select(Designation.name).where(Designation.id == s.designation_id))
            ).scalar_one_or_none()
            if s.designation_id
            else None
        )
        dep = (
            (
                await self.db.execute(select(Department.name).where(Department.id == s.department_id))
            ).scalar_one_or_none()
            if s.department_id
            else None
        )
        return (
            {
                "staff": {
                    "id": str(s.id),
                    "name": " ".join(x for x in (s.first_name, s.middle_name, s.last_name) if x),
                    "employee_id": s.employee_id,
                    "designation": desig or "",
                    "department": dep or "",
                    "joining_date": _d(s.joining_date),
                    "exit_date": _d(s.exit_date) or "date",
                    "blood_group": s.blood_group or "",
                },
                "photo": s.photo_url,
            },
            "staff",
            s.id,
        )

    # ---- rendering ------------------------------------------------------------------------------------------------------
    def render_html(self, tpl: DocumentTemplate | dict[str, Any], ctx: dict[str, Any]) -> str:
        get = (lambda k: tpl.get(k)) if isinstance(tpl, dict) else (lambda k: getattr(tpl, k))
        layout = get("layout") or {}
        source = get("html_template") if (layout.get("mode") == "html" or not layout.get("blocks")) else None
        source = source or compile_layout(layout)
        css = get("css") or ""
        try:
            return str(_sandbox().from_string(source).render(**{**ctx, "css": css}))
        except Exception as exc:  # noqa: BLE001 - template syntax errors surface as 422 to the builder
            raise APIError(422, ErrorCode.VALIDATION, f"Template error: {exc}"[:300]) from None

    async def render(
        self,
        template_type: str,
        entity_type: str,
        entity_id: uuid.UUID,
        *,
        template_id: uuid.UUID | None = None,
        register: str | None = None,
        variables_override: dict[str, Any] | None = None,
        watermark: str | None = None,
        language: str | None = None,
        allow_multiple: bool = False,
        document_number: str | None = None,
        job_id: uuid.UUID | None = None,
        issued_by: uuid.UUID | None = None,
        token: str | None = None,
        supersedes: IssuedDocument | None = None,
    ) -> DocRenderResult:
        if template_type not in TEMPLATE_TYPES:
            raise APIError(422, ErrorCode.VALIDATION, f"Unknown template type {template_type}")
        await self.require_feature("documents.templates")
        if language and language != "en" and not await self.feature("documents.bilingual_templates"):
            language = None
        if supersedes is None and not allow_multiple:
            existing = (
                await self.db.execute(
                    select(IssuedDocument)
                    .where(
                        IssuedDocument.institution_id == self.inst,
                        IssuedDocument.entity_type == entity_type,
                        IssuedDocument.entity_id == entity_id,
                        IssuedDocument.template_type == template_type,
                        IssuedDocument.revoked_at.is_(None),
                    )
                    .order_by(IssuedDocument.issued_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if existing is not None:
                return self.result(existing, reused=True)
        elif allow_multiple and template_type not in MULTI_TYPES and supersedes is None:
            # copies of statutory documents are reissues, not parallel originals
            raise rule(f"{template_type} allows a single live document — reissue instead", "SINGLE_DOCUMENT")
        ctx, ptype, pid = await self.context(template_type, entity_type, entity_id, variables_override)
        college = (ctx.get("enrolment") or {}).get("college_id")
        tpl = await self.resolve_template(template_type, template_id, language, uuid.UUID(college) if college else None)
        number = document_number or await self.next_number(template_type)
        serial = None
        if register:
            if register not in REGISTERS:
                raise APIError(422, ErrorCode.VALIDATION, f"Unknown register {register}")
            if await self.feature("documents.serial_registers"):
                from app.services.documents.registers_service import RegistersService

                serial = await RegistersService(self.db, self.principal, self.request, self.inst).take(register)
        token = token or secrets.token_hex(32)
        ctx["document"] = {
            "number": number,
            "serial_no": serial.serial_no if serial else "",
            "issued_on": _d(await self.today()),
            "verify_url": f"/verify/{token}",
            "qr": qr_data_url(f"/verify/{token}"),
        }
        ctx["watermark"] = watermark or ""
        source = tpl if tpl is not None else default_template(template_type)
        markup = self.render_html(source, ctx)
        title = source.name if isinstance(source, DocumentTemplate) else str(source["name"])
        pdf = pdf_bytes(markup, title, watermark)
        key = await self.store(template_type, number, pdf)
        doc = IssuedDocument(
            institution_id=self.inst,
            template_id=tpl.id if tpl is not None else None,
            template_type=template_type,
            person_type=ptype,
            person_id=pid,
            entity_type=entity_type,
            entity_id=entity_id,
            document_number=number[:40],
            serial_no=serial.serial_no if serial else None,
            pdf_url=key,
            verification_token=token,
            content_hash=sha256(pdf),
            watermark_text=(watermark or None) and watermark[:120],
            issued_by=issued_by or self.actor_id,
            job_id=job_id,
        )
        self.db.add(doc)
        await self.db.flush()
        if serial is not None:
            serial.issued_document_id, serial.status = doc.id, "used"
        meta: dict[str, Any] = {
            "template_version": tpl.version if tpl is not None else 0,
            "variables_override": variables_override or None,
            "language": language,
        }
        if supersedes is not None:
            meta["supersedes"] = str(supersedes.id)
        await self.put_meta("doc", doc.id, meta)
        await self._emit(
            "documents.issued",
            {
                "document_id": str(doc.id),
                "template_type": template_type,
                "entity_type": entity_type,
                "entity_id": str(entity_id),
                "document_number": doc.document_number,
                "person_type": ptype,
                "person_id": str(pid) if pid else None,
            },
            "issued_document",
            doc.id,
        )
        return self.result(doc)

    def result(self, d: IssuedDocument, reused: bool = False) -> DocRenderResult:
        return DocRenderResult(
            issued_document_id=d.id,
            document_number=d.document_number,
            serial_no=d.serial_no,
            pdf_url=None,
            verification_token=d.verification_token,
            content_hash=d.content_hash,
            reused=reused,
        )

    async def next_number(self, template_type: str) -> str:
        n = await self.sequence(f"doc:{template_type}", PREFIX.get(template_type, "DOC"))
        while (
            await self.db.execute(
                select(func.count())
                .select_from(IssuedDocument)
                .where(IssuedDocument.institution_id == self.inst, IssuedDocument.document_number == n)
            )
        ).scalar_one():
            n = await self.sequence(f"doc:{template_type}", PREFIX.get(template_type, "DOC"))
        return n

    async def store(self, template_type: str, number: str, pdf: bytes) -> str:
        from app.core.files import build_key, get_storage

        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", number)[:60] or uuid.uuid4().hex
        key = build_key(self.inst, f"documents/{template_type}", f"{safe}-{uuid.uuid4().hex[:6]}.pdf")
        await get_storage().put(key, pdf, "application/pdf")
        return key

    async def original_pdf(self, d: IssuedDocument) -> bytes:
        from app.core.files import get_storage

        return await get_storage().get(d.pdf_url)

    # ---- revoke / reissue -----------------------------------------------------------------------------------------------
    async def revoke(self, did: uuid.UUID, reason: str) -> IssuedDocument:
        if not self.registrar_like():
            raise forbidden("Only the registrar revokes documents")
        self.require_writer()
        d = await self.visible_document(did, for_update=True)
        if d.revoked_at is not None:
            raise rule("The document is already revoked", "ALREADY_REVOKED")
        d.revoked_at, d.revoke_reason = now_utc(), reason
        await self.db.flush()
        await self._audit("revoke", "issued_document", d.id, None, {"reason": reason})
        await self._emit(
            "documents.revoked",
            {"document_id": str(d.id), "template_type": d.template_type, "reason": reason},
            "issued_document",
            d.id,
        )
        uid = await self.person_user_id(d.person_type or "student", d.person_id) if d.person_id else None
        await self._notify("documents.revoked", [uid], {"document_number": d.document_number, "reason": reason})
        return d

    async def reissue(self, did: uuid.UUID, reason: str, overrides: dict[str, Any] | None) -> DocRenderResult:
        if not self.registrar_like():
            raise forbidden("Only the registrar reissues documents")
        self.require_writer()
        old = await self.visible_document(did, for_update=True)
        if old.revoked_at is None:
            old.revoked_at, old.revoke_reason = now_utc(), reason
        m = await self.meta("doc", old.id)
        res = await self.render(
            old.template_type,
            old.entity_type or "student",
            old.entity_id or old.person_id or uuid.uuid4(),
            template_id=None,
            variables_override={**(m.get("variables_override") or {}), **(overrides or {})},
            supersedes=old,
        )
        m["superseded_by"] = str(res.issued_document_id)
        await self.put_meta("doc", old.id, m)
        await self._audit("reissue", "issued_document", old.id, None, {"new": str(res.issued_document_id)})
        await self._emit(
            "documents.reissued",
            {"document_id": str(old.id), "new_document_id": str(res.issued_document_id), "reason": reason},
            "issued_document",
            old.id,
        )
        return res


# ---- resolvers ------------------------------------------------------------------------------------------------------------
@register_resolver("student_program_enrollment")
async def _enrolment(svc: RenderService, eid: uuid.UUID) -> tuple[dict[str, Any], str | None, uuid.UUID | None]:
    return await svc.enrolment_ctx(eid)


@register_resolver("student")
async def _student(svc: RenderService, sid: uuid.UUID) -> tuple[dict[str, Any], str | None, uuid.UUID | None]:
    st = (await svc.db.execute(select(Student).where(Student.id == sid))).scalar_one_or_none()
    if st is None:
        raise not_found("Student")
    return await svc.student_ctx(st, await svc.enrolment_of(st.id)), "student", st.id


@register_resolver("staff")
async def _staff(svc: RenderService, sid: uuid.UUID) -> tuple[dict[str, Any], str | None, uuid.UUID | None]:
    return await svc.staff_ctx(sid)


@register_resolver("event_registration")
async def _event_reg(svc: RenderService, rid: uuid.UUID) -> tuple[dict[str, Any], str | None, uuid.UUID | None]:
    from app.models.events import Event, EventRegistration

    r = (await svc.db.execute(select(EventRegistration).where(EventRegistration.id == rid))).scalar_one_or_none()
    if r is None:
        raise not_found("Registration")
    e = (await svc.db.execute(select(Event).where(Event.id == r.event_id))).scalar_one()
    ctx: dict[str, Any] = {}
    name = (r.external or {}).get("name")
    ptype: str | None = None
    if r.person_type == "student" and r.person_id:
        ctx, ptype, _ = await _student(svc, r.person_id)
        name = ctx["student"]["name"]
    elif r.person_type == "staff" and r.person_id:
        ctx, ptype, _ = await svc.staff_ctx(r.person_id)
        name = ctx["staff"]["name"]
    ctx["event"] = {
        "title": e.title,
        "type": e.event_type.replace("_", " "),
        "from_on": _d(e.from_on),
        "to_on": _d(e.to_on),
    }
    ctx["participant"] = {"name": name or "Participant", "certificate_no": (r.external or {}).get("certificate_no")}
    return ctx, ptype, r.person_id


@register_resolver("hostel_allocation")
async def _hostel(svc: RenderService, aid: uuid.UUID) -> tuple[dict[str, Any], str | None, uuid.UUID | None]:
    from app.models.hostel import Hostel, HostelAllocation, HostelBed, HostelRoom

    a = (await svc.db.execute(select(HostelAllocation).where(HostelAllocation.id == aid))).scalar_one_or_none()
    if a is None:
        raise not_found("Allocation")
    ctx, ptype, pid = await svc.enrolment_ctx(a.student_program_enrollment_id)
    h = (await svc.db.execute(select(Hostel.name).where(Hostel.id == a.hostel_id))).scalar_one_or_none()
    bed = (
        await svc.db.execute(
            select(HostelBed.bed_label, HostelRoom.room_number)
            .join(HostelRoom, HostelRoom.id == HostelBed.room_id)
            .where(HostelBed.id == a.bed_id)
        )
    ).first()
    ctx["hostel"] = {"name": h or "", "room": f"{bed[1]} / {bed[0]}" if bed else "", "from_on": _d(a.from_on)}
    return ctx, ptype, pid


@register_resolver("grade_card")
async def _grade_card(svc: RenderService, gid: uuid.UUID) -> tuple[dict[str, Any], str | None, uuid.UUID | None]:
    from app.models.results import GradeCard, StudentTermResult
    from app.models.students import StudentTermRecord

    row = (
        await svc.db.execute(
            select(GradeCard, StudentTermResult, StudentTermRecord)
            .join(StudentTermResult, StudentTermResult.id == GradeCard.student_term_result_id)
            .join(StudentTermRecord, StudentTermRecord.id == StudentTermResult.student_term_record_id)
            .where(GradeCard.id == gid)
        )
    ).first()
    if row is None:
        raise not_found("Grade card")
    ctx, ptype, pid = await svc.enrolment_ctx(row[2].student_program_enrollment_id)
    ctx["term"] = {"sgpa": str(row[1].sgpa or ""), "number": row[2].term_number}
    return ctx, ptype, pid


@register_resolver("transcript")
async def _transcript(svc: RenderService, tid: uuid.UUID) -> tuple[dict[str, Any], str | None, uuid.UUID | None]:
    from app.models.post_result import Transcript

    t = (await svc.db.execute(select(Transcript).where(Transcript.id == tid))).scalar_one_or_none()
    if t is None:
        raise not_found("Transcript")
    return await svc.enrolment_ctx(t.student_program_enrollment_id)


@register_resolver("degree_awarded")
async def _degree(svc: RenderService, aid: uuid.UUID) -> tuple[dict[str, Any], str | None, uuid.UUID | None]:
    from app.models.degrees import DegreeAwarded

    a = (await svc.db.execute(select(DegreeAwarded).where(DegreeAwarded.id == aid))).scalar_one_or_none()
    if a is None:
        raise not_found("Award")
    ctx, ptype, pid = await svc.enrolment_ctx(a.student_program_enrollment_id)
    ctx["award"] = {
        "degree": a.degree_name,
        "specialization": a.specialization or "",
        "class": a.result_class or "",
        "cgpa": str(a.cgpa or ""),
        "date": _d(a.date_of_award),
    }
    return ctx, ptype, pid


@register_resolver("exam_registration")
async def _exam_reg(svc: RenderService, rid: uuid.UUID) -> tuple[dict[str, Any], str | None, uuid.UUID | None]:
    from app.models.exams import ExamRegistration

    r = (await svc.db.execute(select(ExamRegistration).where(ExamRegistration.id == rid))).scalar_one_or_none()
    if r is None:
        raise not_found("Exam registration")
    return await svc.enrolment_ctx(r.student_program_enrollment_id)


@register_resolver("admission_offer")
async def _offer(svc: RenderService, oid: uuid.UUID) -> tuple[dict[str, Any], str | None, uuid.UUID | None]:
    from app.models.admissions import AdmissionOffer, Applicant

    row = (
        await svc.db.execute(
            select(AdmissionOffer, Applicant)
            .join(Applicant, Applicant.id == AdmissionOffer.applicant_id)
            .where(AdmissionOffer.id == oid)
        )
    ).first()
    if row is None:
        raise not_found("Offer")
    o, a = row
    prog = (await svc.db.execute(select(Program.name).where(Program.id == o.program_id))).scalar_one_or_none()
    name = " ".join(x for x in (a.first_name, a.middle_name, a.last_name) if x)
    return (
        {
            "student": {"name": name, "registration_number": a.application_number, "dob": _d(a.dob)},
            "enrolment": {"program": prog or ""},
            "offer": {"type": o.offer_type, "valid_until": _d(o.valid_until)},
        },
        None,
        None,
    )


@register_resolver("certificate_request")
async def _request(svc: RenderService, rid: uuid.UUID) -> tuple[dict[str, Any], str | None, uuid.UUID | None]:
    from app.models.documents import CertificateRequest

    r = (await svc.db.execute(select(CertificateRequest).where(CertificateRequest.id == rid))).scalar_one_or_none()
    if r is None:
        raise not_found("Request")
    ctx: dict[str, Any]
    if r.person_type == "staff":
        ctx, _, _ = await svc.staff_ctx(r.person_id)
    else:
        ctx, _, _ = await _student(svc, r.person_id)
    ptype: str | None = r.person_type
    pid: uuid.UUID | None = r.person_id
    ctx["purpose"] = r.purpose or ""
    ctx["request"] = {"copies": r.copies, "delivery": r.delivery}
    return ctx, ptype, pid


async def render(
    db: Any,
    principal: Any,
    template_type: str,
    entity_type: str,
    entity_id: uuid.UUID,
    *,
    institution_id: uuid.UUID | None = None,
    **kw: Any,
) -> DocRenderResult:
    """``documents.render(template_type, entity, variables)`` — the hook every phase calls."""
    return await RenderService(db, principal, institution_id=institution_id).render(
        template_type, entity_type, entity_id, **kw
    )
