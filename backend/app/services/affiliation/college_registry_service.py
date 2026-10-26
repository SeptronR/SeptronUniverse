"""College registry — Prompts/34 §34.6 ``college_registry_service`` {affiliation.core}.

Enriches the Phase 03 ``colleges`` rows with the affiliation fields (number, since, AISHE / AICTE ids, principal,
exam-centre flag), handles type transitions (``affiliated → autonomous`` flips ``programs.exam_authority`` to
``autonomous_college`` for the college's programmes — the university keeps awarding the degree; ``→ constituent`` /
``→ affiliated`` flips it back to ``university``), keeps the statutory documents vault with expiries and computes the
compliance score (approvals valid, dues clear, submissions on time, deficiencies closed, documents in date).

A college admin edits only ``principal_staff_id`` / ``aishe_code`` / ``aicte_pid`` of their own college; every other
field is the affiliation office's.
"""

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select

from app.models.academic import Program
from app.models.affiliation import AffiliationApplication, AffiliationProgramApproval, CollegeDataSubmission
from app.models.platform import College
from app.schemas.affiliation import (
    ApprovalsSummary,
    CollegeAffiliationProfile,
    CollegeProfileUpdate,
    CollegeRow,
    ComplianceFlags,
    VaultDocument,
)
from app.services.affiliation.common import AffiliationBase, forbidden, not_found, now_utc, pairs, rule

COLLEGE_EDITABLE = {"principal_staff_id", "aishe_code", "aicte_pid"}
EXAM_AUTHORITY = {
    "autonomous": "autonomous_college",
    "affiliated": "university",
    "constituent": "university",
    "campus": "university",
    "study_centre": "university",
}


class CollegeRegistryService(AffiliationBase):
    # ---- compliance -------------------------------------------------------------------------------------------------
    async def approvals_summary(self, college_id: uuid.UUID) -> ApprovalsSummary:
        today = await self.today()
        rows = list(
            (
                await self.db.execute(
                    select(AffiliationProgramApproval).where(
                        AffiliationProgramApproval.institution_id == self.inst,
                        AffiliationProgramApproval.college_id == college_id,
                    )
                )
            ).scalars()
        )
        latest: dict[uuid.UUID, AffiliationProgramApproval] = {}
        for a in rows:
            if a.program_id not in latest or (a.valid_to or date.min) > (latest[a.program_id].valid_to or date.min):
                latest[a.program_id] = a
        days = await self.aff_int("expiry_reminder_days")
        live = [a for a in latest.values() if a.approval_status != "withdrawn"]
        return ApprovalsSummary(
            programmes=len(live),
            sanctioned_intake=sum(int(a.sanctioned_intake) for a in live),
            lateral_intake=sum(int(a.lateral_intake or 0) for a in live),
            expiring=sum(1 for a in live if a.valid_to and today <= a.valid_to <= today + timedelta(days=days)),
            withdrawn=len(latest) - len(live),
        )

    async def outstanding_paise(self, college_id: uuid.UUID) -> tuple[int, int]:
        from app.models.fees import FeeInvoice

        today = await self.today()
        rows = (
            await self.db.execute(
                select(FeeInvoice).where(
                    FeeInvoice.institution_id == self.inst,
                    FeeInvoice.payer_type == "college",
                    FeeInvoice.payer_id == college_id,
                    FeeInvoice.status.notin_(("cancelled", "paid", "waived", "refunded")),
                )
            )
        ).scalars()
        out = overdue = 0
        for inv in rows:
            bal = int(getattr(inv, "balance_paise", None) or 0)
            out += bal
            due = getattr(inv, "due_date", None)
            if due is not None and due < today:
                overdue += bal
        return out, overdue

    async def compliance(self, c: College, meta: dict[str, Any] | None = None) -> ComplianceFlags:
        meta = meta if meta is not None else await self.meta("college", c.id)
        today = await self.today()
        approvals = await self.approvals_summary(c.id)
        outstanding, overdue = await self.outstanding_paise(c.id)
        subs = list(
            (
                await self.db.execute(
                    select(CollegeDataSubmission).where(
                        CollegeDataSubmission.institution_id == self.inst, CollegeDataSubmission.college_id == c.id
                    )
                )
            ).scalars()
        )
        sub_meta = await self.metas("sub", [s.id for s in subs]) if subs else {}
        done = [s for s in subs if s.submitted_at is not None]
        on_time = [s for s in done if not (sub_meta.get(str(s.id)) or {}).get("late")]
        pct = round(100 * len(on_time) / len(done), 1) if done else None
        apps = list(
            (
                await self.db.execute(
                    select(AffiliationApplication.deficiencies).where(
                        AffiliationApplication.institution_id == self.inst, AffiliationApplication.college_id == c.id
                    )
                )
            ).scalars()
        )
        open_def = sum(1 for defs in apps for d in (defs or []) if d.get("status") != "closed")
        expired = sum(
            1
            for d in meta.get("documents") or []
            if d.get("valid_to") and date.fromisoformat(str(d["valid_to"])[:10]) < today
        )
        score = 100
        if c.college_type in ("affiliated", "autonomous") and approvals.programmes == 0:
            score -= 30
        score -= 10 * min(approvals.expiring, 2)
        if overdue:
            score -= 20
        elif outstanding:
            score -= 5
        if pct is not None:
            score -= int((100 - pct) / 5)
        score -= 5 * min(open_def, 4)
        score -= 5 * min(expired, 2)
        return ComplianceFlags(
            approvals_valid=approvals.programmes > 0 or c.college_type not in ("affiliated", "autonomous"),
            dues_clear=outstanding == 0,
            submissions_on_time_pct=pct,
            deficiencies_open=open_def,
            documents_expired=expired,
            score=max(0, min(100, score)),
        )

    # ---- profile ----------------------------------------------------------------------------------------------------
    async def profile_out(self, c: College) -> CollegeAffiliationProfile:
        meta = await self.meta("college", c.id)
        today = await self.today()
        names = await self.staff_names([c.principal_staff_id])
        docs = [
            VaultDocument(
                **{k: v for k, v in d.items() if k in VaultDocument.model_fields and k != "expired"},
                expired=bool(d.get("valid_to") and date.fromisoformat(str(d["valid_to"])[:10]) < today),
            )
            for d in meta.get("documents") or []
        ]
        last = meta.get("last_inspection_on")
        return CollegeAffiliationProfile(
            college_id=c.id,
            code=c.code,
            name=c.name,
            college_type=c.college_type,
            affiliation_number=c.affiliation_number,
            affiliated_since=c.affiliated_since,
            principal_staff_id=c.principal_staff_id,
            principal_name=names.get(c.principal_staff_id) if c.principal_staff_id else None,
            aishe_code=c.aishe_code,
            aicte_pid=c.aicte_pid,
            is_exam_centre=c.is_exam_centre,
            exam_centre_code=c.exam_centre_code,
            is_active=c.is_active,
            last_inspection_on=date.fromisoformat(last) if last else None,
            documents=docs,
            approvals=await self.approvals_summary(c.id),
            compliance=await self.compliance(c, meta),
        )

    async def profile(self, college_id: uuid.UUID) -> CollegeAffiliationProfile:
        return await self.profile_out(await self.visible_college(college_id))

    async def list_colleges(
        self, college_type: str | None, status: str | None, faculty_id: uuid.UUID | None
    ) -> list[CollegeRow]:
        stmt = select(College).where(
            College.institution_id == self.inst,
            College.deleted_at.is_(None),
            await self.college_predicate(College.id),
        )
        if college_type:
            stmt = stmt.where(College.college_type == college_type)
        if status == "active":
            stmt = stmt.where(College.is_active.is_(True))
        elif status == "inactive":
            stmt = stmt.where(College.is_active.is_(False))
        if faculty_id is not None:
            stmt = stmt.where(
                College.id.in_(select(Program.college_id).where(Program.faculty_id == faculty_id).distinct())
            )
        colleges = list((await self.db.execute(stmt.order_by(College.code))).scalars())
        ids = [c.id for c in colleges]
        if not ids:
            return []
        cur = await self.current_year_row()
        year_ids = [cur.id] if cur is not None else [uuid.uuid4()]
        appr: dict[uuid.UUID, tuple[int, int]] = {}
        for cid, n, s in (
            await self.db.execute(
                select(
                    AffiliationProgramApproval.college_id,
                    func.count(func.distinct(AffiliationProgramApproval.program_id)),
                    func.coalesce(func.sum(AffiliationProgramApproval.sanctioned_intake), 0),
                )
                .where(
                    AffiliationProgramApproval.college_id.in_(ids),
                    AffiliationProgramApproval.approval_status != "withdrawn",
                    AffiliationProgramApproval.academic_year_id.in_(year_ids),
                )
                .group_by(AffiliationProgramApproval.college_id)
            )
        ).all():
            appr[cid] = (int(n), int(s))
        open_apps = pairs(
            (
                await self.db.execute(
                    select(AffiliationApplication.college_id, func.count())
                    .where(
                        AffiliationApplication.college_id.in_(ids),
                        AffiliationApplication.status.notin_(("approved", "conditional", "rejected", "withdrawn")),
                    )
                    .group_by(AffiliationApplication.college_id)
                )
            ).all()
        )
        metas = await self.metas("college", ids)
        out = []
        for c in colleges:
            dues, _ = await self.outstanding_paise(c.id)
            score = int((metas.get(str(c.id)) or {}).get("compliance_score") or 100)
            n, s = appr.get(c.id, (0, 0))
            out.append(
                CollegeRow(
                    college_id=c.id,
                    code=c.code,
                    name=c.name,
                    college_type=c.college_type,
                    affiliation_number=c.affiliation_number,
                    affiliated_since=c.affiliated_since,
                    is_exam_centre=c.is_exam_centre,
                    programmes=n,
                    sanctioned_intake=s,
                    open_applications=int(open_apps.get(c.id, 0)),
                    dues_paise=dues,
                    compliance_score=score,
                )
            )
        return out

    async def update_profile(self, college_id: uuid.UUID, body: CollegeProfileUpdate) -> CollegeAffiliationProfile:
        self.require_writer()
        c = await self.college(college_id, lock=True)
        fields = body.model_dump(exclude_unset=True, exclude={"effective_year_id", "reason"})
        if not self.office():
            if not self.college_writer(c.id, "apply"):
                raise forbidden("Only the affiliation office or the college's administrators may edit the profile")
            extra = set(fields) - COLLEGE_EDITABLE
            if extra:
                raise forbidden(f"Colleges may edit only {', '.join(sorted(COLLEGE_EDITABLE))}")
        old = {k: str(getattr(c, k)) if getattr(c, k) is not None else None for k in fields}
        new_type = fields.pop("college_type", None)
        for k, v in fields.items():
            setattr(c, k, v)
        if new_type and new_type != c.college_type:
            await self.transition_type(c, new_type, body.effective_year_id, body.reason or "profile update")
        await self.db.flush()
        await self._audit("college_profile", "college", c.id, old, body.model_dump(mode="json", exclude_unset=True))
        await self._emit("affiliation.college_updated", {"college_id": str(c.id)}, "college", c.id)
        return await self.profile_out(c)

    async def transition_type(self, c: College, new_type: str, effective_year_id: uuid.UUID | None, reason: str) -> int:
        """Type change with the programme exam-authority flip; returns the programmes updated."""
        if new_type not in EXAM_AUTHORITY:
            raise rule(f"Unknown college type {new_type}", "INVALID_TYPE", 422)
        old_type = c.college_type
        c.college_type = new_type
        authority = EXAM_AUTHORITY[new_type]
        progs = list(
            (
                await self.db.execute(
                    select(Program).where(Program.institution_id == self.inst, Program.college_id == c.id)
                )
            ).scalars()
        )
        n = 0
        for p in progs:
            if p.exam_authority != authority:
                p.exam_authority = authority
                n += 1
        meta = await self.meta("college", c.id)
        history = list(meta.get("type_history") or [])
        history.append(
            {
                "from": old_type,
                "to": new_type,
                "at": now_utc().isoformat(),
                "by": str(self.actor_id) if self.actor_id else None,
                "effective_year_id": str(effective_year_id) if effective_year_id else None,
                "reason": reason,
                "programs_updated": n,
            }
        )
        meta["type_history"] = history
        await self.put_meta("college", c.id, meta)
        await self.db.flush()
        await self._emit(
            "affiliation.type_changed",
            {"college_id": str(c.id), "from": old_type, "to": new_type, "programs_updated": n},
            "college",
            c.id,
        )
        return n

    # ---- documents vault ----------------------------------------------------------------------------------------------
    async def documents(self, college_id: uuid.UUID) -> list[VaultDocument]:
        return (await self.profile(college_id)).documents

    async def add_document(self, college_id: uuid.UUID, body: VaultDocument) -> list[VaultDocument]:
        self.require_writer()
        c = await self.college(college_id)
        if not (self.office() or self.college_writer(c.id, "apply")):
            raise forbidden("Only the affiliation office or the college's administrators may upload documents")
        meta = await self.meta("college", c.id)
        docs = [d for d in meta.get("documents") or [] if d.get("key") != body.key]
        docs.append({**body.model_dump(mode="json", exclude={"expired"}), "uploaded_at": now_utc().isoformat()})
        meta["documents"] = docs
        await self.put_meta("college", c.id, meta)
        await self._audit("college_document", "college", c.id, None, {"key": body.key, "title": body.title})
        return (await self.profile_out(c)).documents

    async def refresh_scores(self) -> int:
        """Recompute and store compliance scores (portfolio refresh job)."""
        n = 0
        for c in (await self.colleges_map()).values():
            if c.college_type not in ("affiliated", "autonomous"):
                continue
            meta = await self.meta("college", c.id)
            meta["compliance_score"] = (await self.compliance(c, meta)).score
            await self.put_meta("college", c.id, meta)
            n += 1
        return n

    async def require_college(self, college_id: uuid.UUID) -> College:
        c = await self.college(college_id)
        if c is None:
            raise not_found("College")
        return c
