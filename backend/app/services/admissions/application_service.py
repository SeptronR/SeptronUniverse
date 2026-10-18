"""Applications — Prompts/08 §08.6 ``application_service.py``.

Rules
1. **Public start** (captcha + rate limit): ``POST /public/admissions/{slug}/start`` without ``otp_code`` sends a
   6-digit code to the phone (mock SMS; the code is echoed as ``dev_otp`` in development); with the code it creates the
   ``applicant`` user (username = application number from the ``application_no`` sequence, phone / e-mail, the chosen
   password, role ``applicant`` @self, **time-boxed** ``valid_to`` = cycle close + ``admissions.applicant_validity_days``
   and expired when the cycle is archived) and the draft application. Preferences ≤ ``max_preferences``.
2. **Submit**: required fields, preferences, the required documents of the level / entry type (422 listing
   ``missing``) and the eligibility rules per preferred programme (min qualifying % with category relaxation,
   subjects, age, entrance required); with ``strict_eligibility`` an ineligible preference → 422 ``RULE_VIOLATION``
   ``NOT_ELIGIBLE`` naming it (the others are allowed). Then ``submitted`` + the application-fee payment (mock adapter;
   Phase 12 swaps in ``fee_service.create_invoice(payer_type='applicant', source_type='application_fee')``); payment →
   ``fee_paid`` → ``under_verification`` (a zero fee skips straight to verification).
3. **Verification queue**: per-document verify / reject / resubmit (the applicant is notified); any rejected →
   ``doc_rejected``; a re-upload clears it back to ``under_verification``; all required documents verified →
   ``verified``.
4. Status machine (``enums.admissions.APPLICANT_TRANSITIONS``); every change is audited (= timeline) and notified
   (``admissions.status_changed``).
5. **Withdrawal** → refund rule (``admissions.refunds``): before acceptance the application fee minus the processing
   fee, after acceptance ``refund_policy.after_acceptance_pct`` of the admission fee; a positive amount starts the
   ``admissions.refund`` workflow (admissions office → accounts; Phase 12 pays it out). A held seat is released.
6. **Import** from a counselling CSV (job ``admissions.import``): mapping JSON, dry-run report, ``source =
   counselling_import`` (rows with a phone get an applicant account with a temporary password — the office hands it
   over / the applicant resets it — so they can decide on their seat in the portal), ``status = allotted`` (+ a seat allotment in the cycle's latest round) when the row carries an
   allotment. **Export** (job ``admissions.export``): XLSX, PII masked without ``admissions:view_pii``.
"""

import csv
import io
import json
import secrets
import uuid
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from fastapi import UploadFile
from sqlalchemy import false, func, or_, select

from app.core import jobs
from app.core.config import settings
from app.core.errors import APIError, ErrorCode
from app.core.features import is_enabled
from app.core.security import generate_temp_password, hash_password
from app.core.workflow import engine as workflow_engine
from app.db.session import redis_client
from app.models.admissions import (
    AdmissionCycle,
    Applicant,
    ApplicantDocumentVerification,
    CounsellingRound,
    SeatAllotment,
    SeatMatrix,
)
from app.models.platform import User, UserRole, WorkflowInstance
from app.repositories.role_repository import RoleRepository
from app.schemas.admissions import (
    ApplicantResponse,
    ApplicantStatusChange,
    ApplicantUpdate,
    DocumentVerifyRequest,
    ImportFailure,
    ImportResult,
    PaymentResult,
    PreferencesReplace,
    PublicStartRequest,
    PublicStartResult,
    RefundOut,
    WithdrawalRequest,
    WithdrawalResult,
)
from app.services.admissions.common import AdmissionsBase, utcnow
from app.services.file_service import DOCUMENT_TYPES, IMAGE_TYPES, FileService
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta

REFUND_WORKFLOW = "admissions.refund"
ENTITY = "applicant"
EDITABLE = {"draft", "doc_rejected"}
OTP_TTL = 600
IMPORT_FIELDS = (
    "application_number",
    "first_name",
    "last_name",
    "dob",
    "gender",
    "category",
    "quota",
    "is_pwd",
    "phone",
    "email",
    "entrance_score",
    "entrance_rank",
    "qualifying_pct",
    "program_code",
    "entry_type",
    "allotted",
    "allotted_category",
)


def _phone(value: str | None) -> str | None:
    if not value:
        return None
    return "".join(ch for ch in value if ch.isdigit() or ch == "+")[:20] or None


def _age(dob: date, on: date) -> int:
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


class ApplicationService(AdmissionsBase):
    # ---- rule 1: public start --------------------------------------------------------------------------------------
    async def _open_cycle(self, slug: str) -> AdmissionCycle:
        cycle = await self.cycles.by_slug(slug)
        if cycle is None or cycle.status == "draft":
            raise APIError(404, ErrorCode.NOT_FOUND, "Admission cycle not found")
        now = utcnow()
        if (
            cycle.status != "open"
            or (cycle.opens_at and cycle.opens_at > now)
            or (cycle.closes_at and cycle.closes_at <= now)
        ):
            raise APIError(
                409, ErrorCode.RULE_VIOLATION, "Applications are not open for this cycle", {"reason": "closed"}
            )
        return cycle

    async def public_start(self, slug: str, body: PublicStartRequest) -> PublicStartResult:
        cycle = await self._open_cycle(slug)
        phone = _phone(body.phone) or ""
        key = f"admotp:{self.inst}:{cycle.id}:{phone}"
        if body.otp_code is None:
            rate = f"{key}:rate"
            if await redis_client.exists(rate):
                raise APIError(
                    429,
                    ErrorCode.RATE_LIMITED,
                    "Code already sent; wait before requesting another",
                    {"retry_after": 30},
                )
            code = f"{secrets.randbelow(10**6):06d}"
            await redis_client.set(key, code, ex=OTP_TTL)
            await redis_client.set(rate, "1", ex=30)
            from app.integrations.registry import get_adapter

            await get_adapter("sms", "mock").send(to=phone, template="admissions.otp", ttl=OTP_TTL)
            return PublicStartResult(
                otp_sent=True, ttl_seconds=OTP_TTL, dev_otp=code if settings.APP_ENV == "development" else None
            )
        stored = await redis_client.get(key)
        if not stored or stored != body.otp_code:
            raise APIError(422, ErrorCode.VALIDATION, "Invalid or expired code", {"field": "otp_code"})
        await redis_client.delete(key)
        if await self.applicants.by_phone(cycle.id, phone) is not None:
            raise APIError(
                409, ErrorCode.CONFLICT, "An application with this phone already exists — sign in", {"field": "phone"}
            )
        if body.entry_type.value == "lateral" and not await is_enabled(self.inst, "admissions.lateral_entry"):
            raise APIError(
                403, ErrorCode.FEATURE_DISABLED, "Lateral entry is not enabled", {"feature": "admissions.lateral_entry"}
            )
        applicant, user = await self.create_applicant(
            cycle,
            first_name=body.first_name,
            last_name=body.last_name,
            phone=phone,
            email=str(body.email) if body.email else None,
            password=body.password,
            entry_type=body.entry_type.value,
            source="online",
        )
        return PublicStartResult(
            otp_sent=False,
            applicant_id=applicant.id,
            application_number=applicant.application_number,
            username=user.username if user else None,
        )

    async def next_application_number(self) -> str:
        from app.services.sequence_service import SequenceService

        seq = SequenceService(self.db, self.principal, institution_id=self.inst)
        for _ in range(50):
            number = (await seq.next("application_no")).rendered.upper()[:30]
            if await self.applicants.by_number(number) is None:
                return number
        raise APIError(409, ErrorCode.CONFLICT, "The application_no sequence keeps producing taken numbers")

    async def create_applicant(
        self,
        cycle: AdmissionCycle,
        *,
        first_name: str,
        last_name: str | None,
        phone: str | None,
        email: str | None,
        password: str | None,
        entry_type: str = "regular",
        source: str = "online",
        number: str | None = None,
        create_user: bool = True,
        **fields: Any,
    ) -> tuple[Applicant, User | None]:
        number = number or await self.next_application_number()
        user: User | None = None
        if create_user and (phone or email):
            clash = (
                await self.db.execute(
                    select(User.id).where(
                        User.institution_id == self.inst,
                        User.deleted_at.is_(None),
                        or_(
                            User.phone == phone if phone else false(),
                            func.lower(User.email) == email.lower() if email else false(),
                        ),
                    )
                )
            ).first()
            if clash is not None:
                raise APIError(
                    409,
                    ErrorCode.CONFLICT,
                    "This mobile number / e-mail already has an account — sign in instead",
                    {"field": "phone"},
                )
        if create_user:
            role = await RoleRepository(self.db).get_by_slug("applicant", self.inst)
            if role is None:
                raise APIError(422, ErrorCode.VALIDATION, "The institution has no 'applicant' role")
            days = int(await self.adm_setting("applicant_validity_days", 365))
            valid_to = (cycle.closes_at or utcnow()) + timedelta(days=days)
            user = User(
                institution_id=self.inst,
                username=number,
                email=email,
                phone=phone,
                display_name=" ".join(p for p in (first_name, last_name) if p),
                user_type="applicant",
                password_hash=hash_password(password or generate_temp_password()),
                must_change_password=password is None,
                is_verified=True,
                locale="en-IN",
                valid_to=valid_to,
            )
            self.db.add(user)
            await self.db.flush()
            self.db.add(
                UserRole(institution_id=self.inst, user_id=user.id, role_id=role.id, scope_type="self", scope_id=None)
            )
        applicant = Applicant(
            institution_id=self.inst,
            cycle_id=cycle.id,
            application_number=number,
            user_id=user.id if user else None,
            first_name=first_name.strip(),
            last_name=last_name,
            contact={k: v for k, v in (("phone", phone), ("email", email)) if v},
            entry_type=entry_type,
            source=source,
            status="draft",
            created_by=self.actor_id,
            **fields,
        )
        self.db.add(applicant)
        await self.db.flush()
        await self._audit(
            "create",
            "applicant",
            applicant.id,
            None,
            {"status": "draft", "source": source, "application_number": number},
        )
        return applicant, user

    # ---- self service ----------------------------------------------------------------------------------------------
    async def mine(self, *, for_update: bool = False) -> Applicant:
        row = await self.applicants.of_user(self.principal.id)
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "No application for this account")
        if for_update:
            row = await self.applicants.get_any(row.id, for_update=True) or row
        return row

    async def me(self) -> ApplicantResponse:
        return await self.respond(await self.mine(), self_view=True)

    async def update_me(self, body: ApplicantUpdate) -> ApplicantResponse:
        a = await self.mine(for_update=True)
        if a.status not in EDITABLE:
            raise APIError(409, ErrorCode.RECORD_LOCKED, "The application was submitted — it can no longer be edited")
        await self._apply(a, body, self_view=True)
        return await self.respond(a, self_view=True)

    async def _apply(self, a: Applicant, body: ApplicantUpdate, *, self_view: bool) -> None:
        if body.version is not None and body.version != a.version:
            raise APIError(409, ErrorCode.STALE_VERSION, "The application was changed elsewhere — reload")
        data = body.model_dump(exclude_unset=True, exclude={"version"}, mode="json")
        if self_view:
            data.pop("remarks", None)
        pack = await self.pack()
        if data.get("category"):
            data["category"] = self._category(data["category"], pack)
        if data.get("quota_claimed"):
            data["quota_claimed"] = self._quota(data["quota_claimed"], pack)
        if "dob" in data and data["dob"]:
            data["dob"] = date.fromisoformat(data["dob"])
        if "contact" in data and data["contact"] is not None:
            merged = dict(a.contact or {})
            merged.update(data["contact"])
            if merged.get("phone"):
                merged["phone"] = _phone(merged["phone"])
            data["contact"] = merged
        old = {k: getattr(a, k) for k in data if k != "contact"}
        for k, v in data.items():
            setattr(a, k, v)
        await self.db.flush()
        await self._audit("update", "applicant", a.id, _jsonable(old), {"fields": sorted(data)})

    async def max_preferences(self, cycle: AdmissionCycle) -> int:
        return int(self.form_value(cycle, "max_preferences") or await self.adm_setting("max_preferences", 5))

    async def set_preferences(self, a: Applicant, body: PreferencesReplace, *, choice_filling: bool = False) -> None:
        cycle = await self.cycles.cycle(a.cycle_id)
        if not choice_filling and a.status not in EDITABLE:
            raise APIError(409, ErrorCode.RECORD_LOCKED, "Preferences are locked after submission (use choice filling)")
        limit = await self.max_preferences(cycle)
        if len(body.preferences) > limit:
            raise APIError(
                422, ErrorCode.VALIDATION, f"At most {limit} preferences", {"field": "preferences", "max": limit}
            )
        offered = {p.program_id: p for p in await self.cycles.programs(cycle.id)}
        out: list[tuple[uuid.UUID, uuid.UUID]] = []
        for i, p in enumerate(body.preferences):
            cp = offered.get(p.program_id)
            if cp is None or (p.college_id and p.college_id != cp.college_id):
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    f"Preference {i + 1} is not offered in this cycle",
                    {"field": f"preferences.{i}"},
                )
            if a.entry_type == "lateral" and cp.lateral_intake <= 0:
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    f"Preference {i + 1} has no lateral-entry seats",
                    {"field": f"preferences.{i}"},
                )
            if (cp.program_id, cp.college_id) in out:
                raise APIError(422, ErrorCode.VALIDATION, "Duplicate preference", {"field": f"preferences.{i}"})
            out.append((cp.program_id, cp.college_id))
        await self.applicants.replace_preferences(a, out)
        await self._audit(
            "choice_filling" if choice_filling else "preferences",
            "applicant",
            a.id,
            None,
            {"preferences": [str(p) for p, _ in out]},
        )

    async def preferences_me(self, body: PreferencesReplace) -> ApplicantResponse:
        a = await self.mine(for_update=True)
        await self.set_preferences(a, body)
        return await self.respond(a, self_view=True)

    async def upload_document(self, a: Applicant, doc_type: str, upload: UploadFile) -> ApplicantResponse:
        from app.core.files import storage

        cycle = await self.cycles.cycle(a.cycle_id)
        allowed = {d["doc_type"] for d in self.required_documents(cycle, a.entry_type)}
        if doc_type not in allowed:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"Unknown document type {doc_type!r}",
                {"field": "doc_type", "allowed": sorted(allowed)},
            )
        row = await self.applicants.document(a.id, doc_type, for_update=True)
        if row is not None and row.status == "verified":
            raise APIError(409, ErrorCode.RECORD_LOCKED, "This document is already verified")
        if a.status not in EDITABLE | {"submitted", "fee_paid", "under_verification"}:
            raise APIError(409, ErrorCode.RECORD_LOCKED, "Documents can no longer be changed")
        saved = await FileService(self.db).save(
            upload, "applicant-documents", IMAGE_TYPES + DOCUMENT_TYPES, max_mb=10, institution_id=self.inst
        )
        url = storage.signed_url(saved.key, 365 * 24 * 3600)
        if row is None:
            row = ApplicantDocumentVerification(institution_id=self.inst, applicant_id=a.id, doc_type=doc_type)
            self.db.add(row)
        resubmitted = row.status in ("rejected", "resubmit")
        row.file_url, row.status, row.verified_by, row.verified_at = url, "pending", None, None
        await self.db.flush()
        await self._audit("document", "applicant", a.id, None, {"doc_type": doc_type, "resubmitted": resubmitted})
        if a.status == "doc_rejected":
            docs = (await self.applicants.documents([a.id]))[a.id]
            if not any(d.status in ("rejected", "resubmit") for d in docs):
                await self.transition(a, "under_verification", reason="documents resubmitted")
        return await self.respond(a, self_view=True)

    # ---- rule 2: submit ------------------------------------------------------------------------------------------
    def evaluate(self, a: Applicant, rules: dict[str, Any] | None, on: date) -> list[str]:
        """Reasons the applicant fails a programme's ``eligibility_rules`` (empty = eligible)."""
        if not rules:
            return []
        reasons: list[str] = []
        exams = list(a.qualifying_exams or [])
        level = rules.get("qualifying_level")
        exam = next((e for e in exams if level and str(e.get("level")) == str(level)), exams[-1] if exams else None)
        min_pct = rules.get("min_qualifying_pct")
        if min_pct is not None:
            relax = (rules.get("category_relaxation_pct") or {}).get(a.category or "", 0)
            if a.is_pwd:
                relax = max(relax, (rules.get("category_relaxation_pct") or {}).get("PWD", 0))
            need = float(min_pct) - float(relax)
            got = float(exam.get("pct") or 0) if exam else 0.0
            if got < need:
                reasons.append(f"qualifying % {got:g} below {need:g}")
        subjects = rules.get("subjects") or []
        if subjects:
            have = {str(s).upper() for s in (exam or {}).get("subjects") or []}
            missing = [s for s in subjects if str(s).upper() not in have]
            if missing:
                reasons.append(f"missing subjects {', '.join(missing)}")
        if a.dob and rules.get("max_age") and _age(a.dob, on) > int(rules["max_age"]):
            reasons.append(f"age above {rules['max_age']}")
        if a.dob and rules.get("min_age") and _age(a.dob, on) < int(rules["min_age"]):
            reasons.append(f"age below {rules['min_age']}")
        if rules.get("entrance_required") and not (a.entrance or {}).get("score"):
            reasons.append("entrance score required")
        return reasons

    async def eligibility(self, a: Applicant) -> list[dict[str, Any]]:
        cycle = await self.cycles.cycle(a.cycle_id)
        offered = {p.program_id: p for p in await self.cycles.programs(cycle.id)}
        progs = await self.cycles.program_rows(list(offered))
        on = cycle.opens_at.date() if cycle.opens_at else await self.today()
        out = []
        for p in (await self.applicants.preferences([a.id]))[a.id]:
            cp = offered.get(p.program_id)
            reasons = self.evaluate(a, cp.eligibility_rules if cp else None, on)
            out.append(
                {
                    "priority": p.priority,
                    "program_id": str(p.program_id),
                    "program_code": progs[p.program_id].code if p.program_id in progs else None,
                    "eligible": not reasons,
                    "reasons": reasons,
                }
            )
        return out

    async def submit(self, a: Applicant) -> ApplicantResponse:
        if a.status != "draft":
            raise APIError(409, ErrorCode.CONFLICT, f"The application is already {a.status}")
        cycle = await self._open_cycle((await self.cycles.cycle(a.cycle_id)).slug)
        contact = a.contact or {}
        missing_fields = [
            f
            for f, ok in (
                ("first_name", bool(a.first_name)),
                ("dob", a.dob is not None),
                ("gender", bool(a.gender)),
                ("category", bool(a.category)),
                ("contact.phone", bool(contact.get("phone"))),
                ("qualifying_exams", bool(a.qualifying_exams)),
            )
            if not ok
        ]
        prefs = (await self.applicants.preferences([a.id]))[a.id]
        if not prefs:
            missing_fields.append("preferences")
        docs = (await self.applicants.documents([a.id]))[a.id]
        missing_docs = self.missing_documents(cycle, a, docs)
        if missing_fields or missing_docs:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "The application is incomplete",
                {"missing_fields": missing_fields, "missing": missing_docs},
            )
        elig = await self.eligibility(a)
        strict = self.form_value(cycle, "strict_eligibility")
        if strict is None:
            strict = await self.adm_setting("strict_eligibility", False)
        bad = [e for e in elig if not e["eligible"]]
        if strict and bad:
            raise APIError(
                422,
                ErrorCode.RULE_VIOLATION,
                "Not eligible for " + ", ".join(str(e["program_code"]) for e in bad),
                {"reason": "NOT_ELIGIBLE", "preferences": bad},
            )
        a.submitted_at = utcnow()
        await self.transition(a, "submitted", extra={"eligibility": elig})
        pay = await self.create_payment(a, "application", cycle.application_fee_paise)
        if pay["status"] == "paid":
            await self.transition(a, "fee_paid", notify=False)
            await self.transition(a, "under_verification")
        return await self.respond(a, self_view=True)

    # ---- payments --------------------------------------------------------------------------------------------------
    async def pay_me(self, purpose: str) -> PaymentResult:
        a = await self.mine(for_update=True)
        pay = self.payments(a).get(purpose)
        if not pay:
            raise APIError(409, ErrorCode.CONFLICT, f"No {purpose} fee is due")
        if pay["status"] != "paid":
            await self.mark_paid(a, purpose)
        return PaymentResult(**{**self.payments(a)[purpose], "purpose": purpose})

    async def find_payment(self, ref: str) -> tuple[Applicant, str]:
        for purpose in ("application", "admission"):
            row = (
                await self.db.execute(
                    select(Applicant)
                    .where(
                        Applicant.institution_id == self.inst,
                        Applicant.documents["_payments"][purpose]["ref"].astext == ref,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if row is not None:
                return row, purpose
        raise APIError(404, ErrorCode.NOT_FOUND, "Payment reference not found")

    async def mark_paid(self, a: Applicant, purpose: str, status: str = "paid") -> None:
        """The Phase 12 ``fees.invoice_paid`` consumer calls this; until then the mock gateway / ``_dev`` route."""
        pay = dict(self.payments(a).get(purpose) or {})
        if not pay:
            raise APIError(409, ErrorCode.CONFLICT, f"No {purpose} fee is due")
        if pay.get("status") == "paid":
            return
        pay["status"], pay["paid_at"] = status, utcnow().isoformat() if status == "paid" else None
        self.set_payment(a, purpose, pay)
        await self.db.flush()
        if status == "paid" and pay.get("invoice_id"):
            # Phase 12: settle the backing invoice when the payment arrived outside the fees module (mock / _dev);
            # a fees.payment_received replay finds it paid and does nothing
            await self._settle_invoice(uuid.UUID(str(pay["invoice_id"])))
        await self._audit("payment", "applicant", a.id, None, {"purpose": purpose, "ref": pay["ref"], "status": status})
        if status != "paid":
            return
        if purpose == "application" and a.status == "submitted":
            await self.transition(a, "fee_paid")
            await self.transition(a, "under_verification", notify=False)
        elif purpose == "admission":
            from app.services.admissions.counselling_service import CounsellingService

            await CounsellingService(self.db, self.principal, self.request, self.inst).on_admission_fee_paid(a)

    async def _settle_invoice(self, invoice_id: uuid.UUID) -> None:
        from app.models.fees import FeeInvoice
        from app.services.fees.payment_service import PaymentService

        ps = PaymentService(self.db, self.principal, self.request, self.inst)
        inv = (
            await self.db.execute(select(FeeInvoice).where(FeeInvoice.id == invoice_id).with_for_update())
        ).scalar_one_or_none()
        if inv is None:
            return
        await ps.recompute(inv)
        if inv.balance_paise > 0:
            await ps.record(inv, inv.balance_paise, "gateway", gateway_name="mock", reference="admissions", emit=False)

    # ---- rule 3: verification --------------------------------------------------------------------------------------
    async def verify_document(
        self, applicant_id: uuid.UUID, doc_type: str, body: DocumentVerifyRequest
    ) -> ApplicantResponse:
        a = await self.applicants.get_visible(applicant_id, for_update=True)
        row = await self.applicants.document(a.id, doc_type, for_update=True)
        if row is None or not row.file_url:
            raise APIError(404, ErrorCode.NOT_FOUND, f"No {doc_type} uploaded")
        if a.status not in ("under_verification", "doc_rejected", "verified", "fee_paid"):
            raise APIError(409, ErrorCode.CONFLICT, f"Documents of a {a.status} application cannot be verified")
        row.status, row.remarks = body.status, body.remarks
        row.verified_by, row.verified_at = self.actor_id, utcnow()
        await self.db.flush()
        await self._audit(
            "verify_document",
            "applicant",
            a.id,
            None,
            {"doc_type": doc_type, "status": body.status, "remarks": body.remarks},
        )
        cycle = await self.cycles.cycle(a.cycle_id)
        docs = (await self.applicants.documents([a.id]))[a.id]
        if body.status in ("rejected", "resubmit"):
            if a.status in ("under_verification", "verified", "fee_paid"):
                if a.status == "fee_paid":
                    await self.transition(a, "under_verification", notify=False)
                await self.transition(
                    a, "doc_rejected", reason=f"{doc_type}: {body.remarks or body.status}", force=a.status == "verified"
                )
        else:
            required = {d["doc_type"] for d in self.required_documents(cycle, a.entry_type) if d.get("required", True)}
            by_type = {d.doc_type: d for d in docs}
            if (
                a.status == "under_verification"
                and all(by_type.get(t) is not None and by_type[t].status == "verified" for t in required)
                and not any(d.status in ("rejected", "resubmit") for d in docs)
            ):
                await self.transition(a, "verified")
        return await self.respond(a)

    async def verification_queue(
        self, cycle_id: uuid.UUID | None, params: PageParams
    ) -> tuple[list[Any], PaginationMeta]:
        stmt = self.applicants.filtered(cycle_id=cycle_id, statuses=["under_verification", "doc_rejected"]).order_by(
            Applicant.submitted_at
        )
        rows, pagination = await self.applicants.paginate(stmt, params)
        return [await self.respond(a) for a in rows], pagination

    # ---- staff reads / edits ---------------------------------------------------------------------------------------
    async def list_page(self, params: PageParams, **filters: Any) -> tuple[list[Any], PaginationMeta, VisibilityMeta]:
        from app.repositories.applicant_scope import applicant_visibility

        stmt = self.applicants.filtered(**filters)
        if not params.sort:
            stmt = stmt.order_by(Applicant.merit_score.desc().nulls_last(), Applicant.application_number)
        rows, pagination = await self.applicants.paginate(stmt, params)
        return await self.list_items(rows), pagination, applicant_visibility(self.principal)

    async def get(self, applicant_id: uuid.UUID) -> ApplicantResponse:
        return await self.respond(await self.applicants.get_visible(applicant_id))

    async def update(self, applicant_id: uuid.UUID, body: ApplicantUpdate) -> ApplicantResponse:
        a = await self.applicants.get_visible(applicant_id, for_update=True)
        if a.status in ("admitted", "withdrawn", "rejected"):
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"A {a.status} application is read-only")
        await self._apply(a, body, self_view=False)
        return await self.respond(a)

    async def manual_status(self, applicant_id: uuid.UUID, body: ApplicantStatusChange) -> ApplicantResponse:
        a = await self.applicants.get_visible(applicant_id, for_update=True)
        if body.status.value == "admitted":
            raise APIError(409, ErrorCode.CONFLICT, "Use the admit action to admit an applicant")
        if body.status.value in ("withdrawn",):
            return (await self.withdraw(a, WithdrawalRequest(reason=body.reason))).applicant
        await self.transition(a, body.status.value, reason=body.reason)
        return await self.respond(a)

    # ---- rule 5: withdrawal ----------------------------------------------------------------------------------------
    async def withdraw(self, a: Applicant, body: WithdrawalRequest, *, self_view: bool = False) -> WithdrawalResult:
        if a.status in ("admitted", "withdrawn", "rejected"):
            raise APIError(409, ErrorCode.CONFLICT, f"A {a.status} application cannot be withdrawn")
        cycle = await self.cycles.cycle(a.cycle_id)
        pays = self.payments(a)
        app_paid = (
            int(pays.get("application", {}).get("amount_paise") or 0)
            if pays.get("application", {}).get("status") == "paid"
            else 0
        )
        adm_paid = (
            int(pays.get("admission", {}).get("amount_paise") or 0)
            if pays.get("admission", {}).get("status") == "paid"
            else 0
        )
        policy = {
            **(await self.adm_setting("refund_policy", {}) or {}),
            **(self.form_value(cycle, "refund_policy") or {}),
        }
        processing = int(policy.get("processing_fee_paise", 50000))
        if adm_paid:
            pct = int(policy.get("after_acceptance_pct", 50))
            amount, rule = adm_paid * pct // 100, f"after acceptance: {pct}% of the admission fee"
        else:
            amount, rule = max(app_paid - processing, 0), "before allotment: application fee minus processing fee"
        holding = (await self.counselling.holding([a.id])).get(a.id)
        if holding is not None:
            from app.services.admissions.counselling_service import CounsellingService

            await CounsellingService(self.db, self.principal, self.request, self.inst).release(holding, "declined")
        await self.transition(a, "withdrawn", reason=body.reason, force=True)
        refund: RefundOut | None = None
        if (app_paid or adm_paid) and await is_enabled(self.inst, "admissions.refunds"):
            instance_id = None
            if amount > 0:
                instance = await workflow_engine.start(
                    self.db,
                    institution_id=self.inst,
                    key=REFUND_WORKFLOW,
                    entity_type=ENTITY,
                    entity_id=a.id,
                    started_by=self.actor_id,
                    context={"cycle_id": str(a.cycle_id), "amount_paise": amount, "applicant_id": str(a.id)},
                    title=f"Admission refund ₹{amount / 100:,.2f} — {a.full_name} ({a.application_number})",
                )
                instance_id = instance.id
            data = {
                "amount_paise": amount,
                "paid_paise": app_paid + adm_paid,
                "policy": rule,
                "status": "requested" if amount > 0 else "none",
                "workflow_instance_id": str(instance_id) if instance_id else None,
                "requested_at": utcnow().isoformat(),
            }
            self.set_payment(a, "refund", data)
            await self.db.flush()
            await self._audit("refund_request", "applicant", a.id, None, data)
            refund = RefundOut(**{**data, "workflow_instance_id": instance_id})
        return WithdrawalResult(applicant=await self.respond(a, self_view=self_view), refund=refund)

    async def refund_decided(self, instance: WorkflowInstance, status: str) -> None:
        a = await self.applicants.get_any(instance.entity_id, for_update=True)
        if a is None:
            return
        data = dict(self.payments(a).get("refund") or {})
        if not data:
            return
        data["status"], data["decided_at"] = status, utcnow().isoformat()
        self.set_payment(a, "refund", data)
        await self.db.flush()
        await self._audit("refund_" + status, "applicant", a.id, None, {"amount_paise": data.get("amount_paise")})
        if a.user_id:
            await self._notify(
                "admissions.status_changed",
                [a.user_id],
                {"application_no": a.application_number, "status": f"Refund {status}"},
            )

    # ---- rule 6: import / export -----------------------------------------------------------------------------------
    @staticmethod
    def parse_csv(content: bytes) -> list[dict[str, str]]:
        text = content.decode("utf-8-sig", errors="replace")
        return [
            {(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(io.StringIO(text))
        ]

    async def _import_rows(
        self, cycle: AdmissionCycle, rows: list[dict[str, str]], mapping: dict[str, str] | None
    ) -> tuple[list[dict[str, Any]], list[ImportFailure]]:
        mapping = mapping or {}
        pack = await self.pack()
        programs = {}
        for cp in await self.cycles.programs(cycle.id):
            p = (await self.cycles.program_rows([cp.program_id]))[cp.program_id]
            programs[p.code.upper()] = cp
        good: list[dict[str, Any]] = []
        failed: list[ImportFailure] = []
        seen: set[str] = set()
        for i, raw in enumerate(rows, start=2):
            row = {f: raw.get(mapping.get(f, f), "") for f in IMPORT_FIELDS}
            try:
                if not row["first_name"]:
                    raise ValueError("first_name is required")
                cp_row = programs.get(row["program_code"].upper())
                if cp_row is None:
                    raise ValueError(f"unknown programme {row['program_code']!r}")
                category = self._category(row["category"], pack) if row["category"] else "GEN"
                quota = self._quota(row["quota"], pack) if row["quota"] else "STATE"
                dob = date.fromisoformat(row["dob"]) if row["dob"] else None
                number = row["application_number"].upper() or None
                if number:
                    if number in seen or await self.applicants.by_number(number) is not None:
                        raise ValueError(f"application number {number} already exists")
                    seen.add(number)
                score = Decimal(row["entrance_score"]) if row["entrance_score"] else None
                good.append(
                    {
                        "row": i,
                        "number": number,
                        "first_name": row["first_name"],
                        "last_name": row["last_name"] or None,
                        "dob": dob,
                        "gender": (row["gender"] or "")[:1].upper() or None,
                        "category": category,
                        "quota": quota,
                        "is_pwd": row["is_pwd"].lower() in ("y", "yes", "true", "1"),
                        "phone": _phone(row["phone"]),
                        "email": row["email"] or None,
                        "score": score,
                        "rank": int(row["entrance_rank"]) if row["entrance_rank"] else None,
                        "qualifying_pct": float(row["qualifying_pct"]) if row["qualifying_pct"] else None,
                        "program": cp_row,
                        "entry_type": row["entry_type"].lower() or "regular",
                        "allotted": row["allotted"].lower() in ("y", "yes", "true", "1"),
                        "allotted_category": self._category(row["allotted_category"], pack)
                        if row["allotted_category"]
                        else None,
                    }
                )
            except APIError as exc:
                failed.append(ImportFailure(row=i, error=exc.message))
            except (ValueError, ArithmeticError) as exc:
                failed.append(ImportFailure(row=i, error=str(exc)[:200]))
        return good, failed

    async def import_dry_run(self, cycle_id: uuid.UUID, content: bytes, mapping: dict[str, str] | None) -> ImportResult:
        cycle = await self.cycles.cycle(cycle_id)
        rows = self.parse_csv(content)
        good, failed = await self._import_rows(cycle, rows, mapping)
        return ImportResult(
            dry_run=True,
            total=len(rows),
            succeeded=len(good),
            allotted=sum(1 for g in good if g["allotted"]),
            failed=failed,
        )

    async def enqueue_import(self, cycle_id: uuid.UUID, content: bytes, mapping: dict[str, str] | None) -> ImportResult:
        from app.core.files import build_key, storage

        cycle = await self.cycles.cycle(cycle_id)
        rows = self.parse_csv(content)
        if not rows:
            raise APIError(422, ErrorCode.VALIDATION, "The file has no data rows", {"field": "file"})
        key = build_key(self.inst, "admission-imports", "counselling.csv")
        await storage.put(key, content, "text/csv")
        job = await jobs.enqueue(
            self.db,
            self.principal,
            "admissions.import",
            {"cycle_id": str(cycle.id), "key": key, "mapping": mapping or {}},
            queue="reports",
        )
        return ImportResult(dry_run=False, total=len(rows), succeeded=0, job_id=job.id)

    async def run_import(
        self,
        cycle_id: uuid.UUID,
        content: bytes,
        mapping: dict[str, str] | None,
        progress: Callable[[int, str], Awaitable[None]],
    ) -> dict[str, Any]:
        cycle = await self.cycles.cycle(cycle_id)
        rows = self.parse_csv(content)
        good, failed = await self._import_rows(cycle, rows, mapping)
        rnd = None
        if any(g["allotted"] for g in good):
            rounds = await self.counselling.rounds(cycle.id)
            rnd = rounds[-1] if rounds else None
            if rnd is None:
                rnd = CounsellingRound(
                    institution_id=self.inst,
                    cycle_id=cycle.id,
                    round_number=1,
                    name="State counselling",
                    status="allotted",
                )
                self.db.add(rnd)
                await self.db.flush()
        created = allotted = 0
        for n, g in enumerate(good, start=1):
            try:
                async with self.db.begin_nested():
                    a, _ = await self.create_applicant(
                        cycle,
                        first_name=g["first_name"],
                        last_name=g["last_name"],
                        phone=g["phone"],
                        email=g["email"],
                        password=None,
                        entry_type=g["entry_type"]
                        if g["entry_type"] in ("regular", "lateral", "migration")
                        else "regular",
                        source="counselling_import",
                        number=g["number"],
                        create_user=bool(g["phone"]),
                        dob=g["dob"],
                        gender=g["gender"],
                        category=g["category"],
                        quota_claimed=g["quota"],
                        is_pwd=g["is_pwd"],
                        entrance={
                            "exam": "state_cet",
                            "score": float(g["score"]) if g["score"] is not None else None,
                            "rank": g["rank"],
                        },
                        qualifying_exams=[{"level": "12", "pct": g["qualifying_pct"]}]
                        if g["qualifying_pct"] is not None
                        else None,
                        merit_score=g["score"],
                    )
                    cp = g["program"]
                    await self.applicants.replace_preferences(a, [(cp.program_id, cp.college_id)])
                    a.submitted_at = utcnow()
                    status = "verified"
                    if g["allotted"] and rnd is not None:
                        seat = await self._import_seat(cycle, cp, g["quota"], g["allotted_category"] or g["category"])
                        if seat is not None:
                            self.db.add(
                                SeatAllotment(
                                    institution_id=self.inst,
                                    round_id=rnd.id,
                                    applicant_id=a.id,
                                    program_id=cp.program_id,
                                    college_id=cp.college_id,
                                    seat_matrix_id=seat.id,
                                    quota=seat.quota,
                                    category=seat.category,
                                    status="allotted",
                                    admission_fee_paise=int(await self.adm_setting("admission_fee_paise", 0)),
                                )
                            )
                            seat.filled += 1
                            status = "allotted"
                            allotted += 1
                    await self.transition(a, status, reason="counselling import", force=True, notify=False)
                    created += 1
            except Exception as exc:  # noqa: BLE001 - one row's failure must not stop the import
                failed.append(ImportFailure(row=g["row"], error=str(exc)[:200]))
            if n % 20 == 0:
                await progress(int(n * 100 / max(len(good), 1)), f"{n}/{len(good)} rows")
        await self._audit(
            "import",
            "admission_cycle",
            cycle.id,
            None,
            {"created": created, "allotted": allotted, "failed": len(failed)},
        )
        return {
            "total": len(rows),
            "succeeded": created,
            "allotted": allotted,
            "failed": [f.model_dump() for f in failed],
        }

    async def _import_seat(self, cycle: AdmissionCycle, cp: Any, quota: str, category: str) -> SeatMatrix | None:
        rows = [
            r
            for r in await self.cycles.seat_rows(cycle.id, for_update=True)
            if r.program_id == cp.program_id and r.college_id == cp.college_id and r.filled < r.seats
        ]
        for want in ((quota, category), (quota, "GEN"), (None, category), (None, "GEN")):
            for r in rows:
                if (want[0] is None or r.quota == want[0]) and r.category == want[1]:
                    return r
        return None

    async def enqueue_export(self, filters: dict[str, Any]) -> uuid.UUID:
        clean = {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in filters.items() if v is not None}
        job = await jobs.enqueue(self.db, self.principal, "admissions.export", {"filters": clean}, queue="reports")
        return job.id

    async def export_xlsx(self, **filters: Any) -> bytes:
        from openpyxl import Workbook

        stmt = self.applicants.filtered(**filters).order_by(Applicant.application_number)
        rows = list((await self.db.execute(stmt.limit(20000))).scalars().all())
        items = []
        for i in range(0, len(rows), 500):
            items += await self.list_items(rows[i : i + 500])
        wb = Workbook()
        ws = wb.active
        assert ws is not None
        ws.title = "Applicants"
        ws.append(
            [
                "Application no.",
                "Name",
                "Status",
                "Category",
                "PwD",
                "Quota",
                "Entry",
                "Source",
                "Merit score",
                "First preference",
                "Phone",
                "E-mail",
            ]
        )
        for r in items:
            ws.append(
                [
                    r.application_number,
                    r.name,
                    r.status,
                    r.category,
                    "Y" if r.is_pwd else "",
                    r.quota_claimed,
                    r.entry_type,
                    r.source,
                    float(r.merit_score) if r.merit_score is not None else None,
                    r.first_preference,
                    r.phone,
                    r.email,
                ]
            )
        buf = io.BytesIO()
        wb.save(buf)
        await self._audit("export", "applicant", None, None, {"rows": len(rows)})
        return buf.getvalue()


def _jsonable(d: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(json.dumps(d, default=str))
    return out


# ---- workflow hooks + inbox summaries ------------------------------------------------------------------------------------
@workflow_engine.on(REFUND_WORKFLOW, "approved")
async def _refund_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type == ENTITY:
        await ApplicationService(db, actor, institution_id=instance.institution_id).refund_decided(instance, "approved")


@workflow_engine.on(REFUND_WORKFLOW, "rejected")
async def _refund_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type == ENTITY:
        await ApplicationService(db, actor, institution_id=instance.institution_id).refund_decided(instance, "rejected")


@workflow_engine.summariser(ENTITY)
async def _summarise(db: Any, entity_id: uuid.UUID) -> tuple[str | None, str | None]:
    a = (await db.execute(select(Applicant).where(Applicant.id == entity_id))).scalar_one_or_none()
    if a is None:
        return None, None
    return f"{a.full_name} ({a.application_number})", f"/admin/admissions/applicants/{entity_id}"


__all__ = ["ApplicationService"]
