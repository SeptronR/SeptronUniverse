"""Shared plumbing of the Phase 08 admissions services — tenant, repositories, audit / outbox / notifications (from the
Phase 07 base), the applicant status machine with its timeline, response builders with PII masking and the mock
payment stub that stands in for Phase 12 invoices.

Applicant timeline: every status change is an audit row ``(module='admissions', record_type='applicant',
action='status')`` with ``old_values.status`` / ``new_values.status`` / ``new_values.reason``; document decisions,
payments and allotment decisions are audit rows on the same record, so ``GET .../timeline`` reads the audit log.

Payments (Phase 12 owns ``fee_invoices``): the application / admission fee is a mock-adapter order kept in
``applicants.documents["_payments"][purpose] = {ref, amount_paise, status, provider, created_at, paid_at}``;
``mark_paid`` is what the Phase 12 ``fees.invoice_paid`` consumer will call.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.masking import mask_value
from app.core.errors import APIError, ErrorCode
from app.enums.admissions import APPLICANT_TRANSITIONS
from app.models.admissions import AdmissionCycle, Applicant, ApplicantDocumentVerification, SeatAllotment
from app.models.platform import AuditLog, User
from app.repositories.admission_repository import AdmissionRepository
from app.repositories.applicant_repository import ApplicantRepository
from app.repositories.applicant_scope import may_view_pii
from app.repositories.counselling_repository import CounsellingRepository
from app.repositories.merit_repository import MeritRepository
from app.schemas.admissions import (
    AllotmentResponse,
    ApplicantDocumentOut,
    ApplicantListItem,
    ApplicantResponse,
    ApplicantSelfResponse,
    PreferenceOut,
    TimelineEntry,
)
from app.services.students.common import StudentServiceBase

# statuses whose change emits a dedicated ``applicant.<status>`` event (Prompts/08 §08.7)
STATUS_EVENTS = {
    "submitted",
    "fee_paid",
    "verified",
    "doc_rejected",
    "merit_listed",
    "allotted",
    "accepted",
    "declined",
    "lapsed",
    "withdrawn",
    "admitted",
}
STATUS_LABELS = {
    "draft": "Draft",
    "submitted": "Submitted",
    "fee_paid": "Fee paid",
    "under_verification": "Under verification",
    "verified": "Verified",
    "doc_rejected": "Document rejected — please resubmit",
    "waitlisted": "Waitlisted",
    "merit_listed": "On the merit list",
    "allotted": "Seat allotted",
    "accepted": "Seat accepted",
    "provisionally_admitted": "Provisionally admitted",
    "admitted": "Admitted",
    "declined": "Seat declined",
    "lapsed": "Allotment lapsed",
    "withdrawn": "Withdrawn",
    "rejected": "Rejected",
}
CONTACT_PII = {"phone": "phone", "email": "email", "guardian_phone": "phone", "guardian_email": "email"}
DEFAULT_DOCUMENTS: dict[str, list[dict[str, Any]]] = {
    "ug": [
        {"doc_type": "photo", "label": "Photograph", "required": True},
        {"doc_type": "marksheet_12", "label": "Class XII marksheet", "required": True},
        {"doc_type": "marksheet_10", "label": "Class X marksheet", "required": True},
        {"doc_type": "category_certificate", "label": "Category certificate", "required": False},
    ],
    "pg": [
        {"doc_type": "photo", "label": "Photograph", "required": True},
        {"doc_type": "degree_certificate", "label": "Degree certificate", "required": True},
        {"doc_type": "marksheet_ug", "label": "UG marksheets", "required": True},
    ],
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def mask_contact(contact: dict[str, Any] | None) -> dict[str, Any] | None:
    """PII inside the ``contact`` JSON column, masked key by key (``mask_value``); the address is hidden."""
    if not contact:
        return contact
    out = dict(contact)
    for key, kind in CONTACT_PII.items():
        if out.get(key):
            out[key] = mask_value(out[key], kind)
    if out.get("address"):
        out["address"] = mask_value(out["address"], "secret")
    return out


class AdmissionsBase(StudentServiceBase):
    audit_module = "admissions"

    def __init__(
        self, db: AsyncSession, principal: Any, request: Request | None = None, institution_id: uuid.UUID | None = None
    ):
        super().__init__(db, principal, request, institution_id)
        self.cycles = AdmissionRepository(db, self.inst)
        self.applicants = ApplicantRepository(db, principal, self.inst)
        self.merit = MeritRepository(db, self.inst)
        self.counselling = CounsellingRepository(db, self.inst)

    # pack codes (same normalisation as StudentService so admitted applicants pass the student checks unchanged)
    def _category(self, raw: str | None, pack: Any) -> str | None:
        if not raw:
            return None
        codes: dict[str, str] = {c.code.upper(): c.code for c in pack.categories}
        key = raw.strip().upper().replace("_", "-")
        if key not in codes:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"Unknown category {raw!r} for the {pack.code} pack",
                {"field": "category", "allowed": sorted(codes.values())},
            )
        return codes[key]

    def _quota(self, raw: str | None, pack: Any) -> str | None:
        if not raw:
            return None
        codes: dict[str, str] = {q.code.upper(): q.code for q in pack.quotas}
        key = raw.strip().upper()
        if key not in codes:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"Unknown quota {raw!r} for the {pack.code} pack",
                {"field": "quota_claimed", "allowed": sorted(codes.values())},
            )
        return codes[key]

    async def adm_setting(self, key: str, default: Any = None) -> Any:
        value = await self.setting("admissions", key)
        return default if value is None else value

    def form_value(self, cycle: AdmissionCycle, key: str, default: Any = None) -> Any:
        cfg = cycle.form_config or {}
        return cfg.get(key, default)

    # ---- documents -----------------------------------------------------------------------------------------------
    def required_documents(self, cycle: AdmissionCycle, entry_type: str = "regular") -> list[dict[str, Any]]:
        docs = cycle.required_documents or DEFAULT_DOCUMENTS.get(cycle.level, DEFAULT_DOCUMENTS["ug"])
        out = []
        for d in docs:
            types = d.get("entry_types")
            if types and entry_type not in types:
                continue
            out.append(d)
        return out

    def missing_documents(
        self, cycle: AdmissionCycle, applicant: Applicant, docs: Sequence[ApplicantDocumentVerification]
    ) -> list[str]:
        have = {d.doc_type for d in docs if d.file_url and d.status != "rejected"}
        return [
            d["doc_type"]
            for d in self.required_documents(cycle, applicant.entry_type)
            if d.get("required", True) and d["doc_type"] not in have
        ]

    # ---- status machine ------------------------------------------------------------------------------------------
    async def transition(
        self,
        applicant: Applicant,
        to: str,
        *,
        reason: str | None = None,
        force: bool = False,
        notify: bool = True,
        extra: dict[str, Any] | None = None,
    ) -> None:
        old = applicant.status
        if old == to and not force:
            return
        if not force and to not in APPLICANT_TRANSITIONS.get(old, set()):
            raise APIError(
                409,
                ErrorCode.CONFLICT,
                f"An application in status '{old}' cannot move to '{to}'",
                {"from": old, "to": to, "allowed": sorted(APPLICANT_TRANSITIONS.get(old, set()))},
            )
        applicant.status = to
        await self.db.flush()
        await self._audit(
            "status",
            "applicant",
            applicant.id,
            {"status": old},
            {"status": to, "reason": reason, **(extra or {})},
        )
        event = f"applicant.{to}" if to in STATUS_EVENTS else "applicant.status_changed"
        await self._emit(
            event,
            {
                "applicant_id": str(applicant.id),
                "application_number": applicant.application_number,
                "cycle_id": str(applicant.cycle_id),
                "from": old,
                "to": to,
            },
            "applicant",
            applicant.id,
        )
        if notify and applicant.user_id:
            await self._notify(
                "admissions.status_changed",
                [applicant.user_id],
                {"application_no": applicant.application_number, "status": STATUS_LABELS.get(to, to)},
            )

    async def timeline(self, applicant: Applicant) -> list[TimelineEntry]:
        rows = (
            (
                await self.db.execute(
                    select(AuditLog)
                    .where(AuditLog.record_type == "applicant", AuditLog.record_id == applicant.id)
                    .order_by(AuditLog.occurred_at)
                )
            )
            .scalars()
            .all()
        )
        users = {
            u.id: u
            for u in (await self.db.execute(select(User).where(User.id.in_([r.user_id for r in rows if r.user_id]))))
            .scalars()
            .all()
        }
        out: list[TimelineEntry] = []
        for r in rows:
            new, old = r.new_values or {}, r.old_values or {}
            by = users.get(r.user_id) if r.user_id else None
            out.append(
                TimelineEntry(
                    at=r.occurred_at,
                    action=r.action,
                    status_from=old.get("status"),
                    status_to=new.get("status"),
                    by=(by.display_name or by.username) if by else None,
                    remarks=new.get("reason") or new.get("remarks") or new.get("note"),
                )
            )
        return out

    # ---- payments (mock adapter until Phase 12) ----------------------------------------------------------------------
    @staticmethod
    def payments(applicant: Applicant) -> dict[str, Any]:
        return dict((applicant.documents or {}).get("_payments") or {})

    def set_payment(self, applicant: Applicant, purpose: str, data: dict[str, Any]) -> None:
        docs = dict(applicant.documents or {})
        pays = dict(docs.get("_payments") or {})
        pays[purpose] = data
        docs["_payments"] = pays
        applicant.documents = docs

    async def create_payment(self, applicant: Applicant, purpose: str, amount_paise: int) -> dict[str, Any]:
        from app.integrations.registry import get_adapter

        existing = self.payments(applicant).get(purpose)
        if existing and existing.get("status") in ("pending", "paid"):
            return dict(existing)
        order = await get_adapter("payment", "mock").create_order(
            amount_paise=amount_paise, purpose=purpose, payer_type="applicant", payer_ref=applicant.application_number
        )
        data = {
            "ref": f"MOCK-{purpose[:3].upper()}-{uuid.uuid4().hex[:10].upper()}",
            "provider_ref": order.get("reference"),
            "amount_paise": int(amount_paise),
            "status": "paid" if amount_paise == 0 else "pending",
            "provider": "mock",
            "payer_type": "applicant",
            "source_type": f"{purpose}_fee",
            "created_at": utcnow().isoformat(),
            "paid_at": utcnow().isoformat() if amount_paise == 0 else None,
        }
        self.set_payment(applicant, purpose, data)
        await self.db.flush()
        await self._audit("payment_created", "applicant", applicant.id, None, {"purpose": purpose, **data})
        return data

    # ---- response builders -----------------------------------------------------------------------------------------
    def _masked(self, self_view: bool) -> bool:
        return not self_view and not may_view_pii(self.principal) if self.principal is not None else False

    async def respond(self, applicant: Applicant, *, self_view: bool = False) -> ApplicantResponse:
        cycle = await self.cycles.cycle(applicant.cycle_id)
        prefs = (await self.applicants.preferences([applicant.id]))[applicant.id]
        docs = (await self.applicants.documents([applicant.id]))[applicant.id]
        programs = await self.cycles.program_rows([p.program_id for p in prefs])
        holding = (await self.counselling.holding([applicant.id])).get(applicant.id)
        latest = holding or await self.counselling.latest_for(applicant.id)
        contact = applicant.contact or {}
        cls = ApplicantSelfResponse if self_view else ApplicantResponse
        out = cls(
            id=applicant.id,
            cycle_id=applicant.cycle_id,
            cycle_name=cycle.name,
            cycle_slug=cycle.slug,
            application_number=applicant.application_number,
            user_id=applicant.user_id,
            first_name=applicant.first_name,
            middle_name=applicant.middle_name,
            last_name=applicant.last_name,
            name=applicant.full_name,
            dob=applicant.dob,
            gender=applicant.gender,
            category=applicant.category,
            is_pwd=applicant.is_pwd,
            quota_claimed=applicant.quota_claimed,
            nationality=applicant.nationality,
            domicile_state=applicant.domicile_state,
            phone=contact.get("phone"),
            email=contact.get("email"),
            contact=contact or None,
            entrance=applicant.entrance,
            qualifying_exams=applicant.qualifying_exams,
            merit_score=applicant.merit_score,
            status=applicant.status,
            entry_type=applicant.entry_type,
            source=applicant.source,
            remarks=applicant.remarks,
            submitted_at=applicant.submitted_at,
            admitted_student_id=applicant.admitted_student_id,
            preferences=[
                PreferenceOut(
                    priority=p.priority,
                    program_id=p.program_id,
                    college_id=p.college_id,
                    program_code=programs[p.program_id].code if p.program_id in programs else None,
                    program_name=programs[p.program_id].name if p.program_id in programs else None,
                )
                for p in prefs
            ],
            documents=[ApplicantDocumentOut.model_validate(d) for d in docs],
            missing_documents=self.missing_documents(cycle, applicant, docs),
            payments=self.payments(applicant),
            allotment=await self.allotment_out(latest) if latest else None,
            allowed_transitions=sorted(APPLICANT_TRANSITIONS.get(applicant.status, set())),
            version=applicant.version,
            created_at=applicant.created_at,
        )
        if self._masked(self_view):
            out = out.model_copy(
                update={
                    "phone": mask_value(out.phone, "phone"),
                    "email": mask_value(out.email, "email"),
                    "contact": mask_contact(out.contact),
                }
            )
        return out

    async def list_items(self, rows: Sequence[Applicant]) -> list[ApplicantListItem]:  # type: ignore[override]
        rows = list(rows)
        ids = [a.id for a in rows]
        prefs = await self.applicants.preferences(ids)
        docs = await self.applicants.documents(ids)
        programs = await self.cycles.program_rows([p.program_id for ps in prefs.values() for p in ps])
        masked = self._masked(False)
        out = []
        for a in rows:
            contact = a.contact or {}
            first = prefs.get(a.id) or []
            item = ApplicantListItem(
                id=a.id,
                cycle_id=a.cycle_id,
                application_number=a.application_number,
                name=a.full_name,
                category=a.category,
                is_pwd=a.is_pwd,
                quota_claimed=a.quota_claimed,
                entry_type=a.entry_type,
                source=a.source,
                status=a.status,
                merit_score=a.merit_score,
                phone=mask_value(contact.get("phone"), "phone") if masked else contact.get("phone"),
                email=mask_value(contact.get("email"), "email") if masked else contact.get("email"),
                first_preference=(
                    programs[first[0].program_id].code if first and first[0].program_id in programs else None
                ),
                submitted_at=a.submitted_at,
                docs_pending=sum(1 for d in docs.get(a.id, []) if d.status in ("pending", "resubmit")),
            )
            out.append(item)
        return out

    async def allotment_out(self, row: SeatAllotment, applicant: Applicant | None = None) -> AllotmentResponse:
        rnd = await self.counselling.round(row.round_id)
        programs = await self.cycles.program_rows([row.program_id])
        applicant = applicant or await self.applicants.get_any(row.applicant_id)
        prefs = (await self.applicants.preferences([row.applicant_id]))[row.applicant_id]
        priority = next(
            (p.priority for p in prefs if p.program_id == row.program_id and p.college_id == row.college_id), None
        )
        prog = programs.get(row.program_id)
        return AllotmentResponse(
            id=row.id,
            round_id=row.round_id,
            round_number=rnd.round_number,
            applicant_id=row.applicant_id,
            application_number=applicant.application_number if applicant else None,
            applicant_name=applicant.full_name if applicant else None,
            program_id=row.program_id,
            program_code=prog.code if prog else None,
            program_name=prog.name if prog else None,
            college_id=row.college_id,
            quota=row.quota,
            category=row.category,
            priority=priority,
            status=row.status,
            admission_fee_paise=row.admission_fee_paise,
            accepted_at=row.accepted_at,
            reporting_deadline=rnd.reporting_deadline,
            payment=self.payments(applicant).get("admission") if applicant else None,
            created_at=row.created_at,
        )
