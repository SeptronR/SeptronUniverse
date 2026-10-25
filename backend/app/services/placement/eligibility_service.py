"""Placement policies and the eligibility engine — Prompts/28 §28.6 ``policy_service`` / ``eligibility_service``.

Policies: per batch / programme rows (``batch + programme`` → ``batch`` → ``programme`` → ``placement.policy_defaults``)
with ``max_offers`` (1 = one-offer policy), ``dream_ctc_threshold_paise`` + ``allow_upgrade_if_dream`` (a placed
student may only apply to drives with ``ctc_min ≥ threshold`` or a ``dream`` / ``super_dream`` company), ``opt_out_allowed``
and free ``rules`` (``internship_ppo_counts_as_offer``, ``mass_recruiter_cap`` …).

Eligibility (``evaluate``) is computed live and in bulk: CGPA from the latest published current
``student_term_results`` (enrolment ``cgpa`` as fallback), active backlogs = open ``student_arrears``, history backlogs
= every arrear row ever, 10th / 12th % and the 12th year from ``applicants.qualifying_exams`` (profile-entered values when
no applicant record exists — flagged ``pct_verified = false``), gap years = admission year − 12th year, programme /
batch / college filters, attendance % (optional), skills (optional), placed status against the policy, open holds of
type ``all`` / ``placement``, blacklist (manual, rule-based or discipline ``debar_placement``) and opt-out. The result
is snapshotted on the application; later changes do not affect it unless the drive is re-evaluated.
"""

import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.enums.placement import DREAM_TIERS, ELIGIBILITY_DEFAULTS, HOLDING_OFFER, POLICY_DEFAULTS
from app.models.admissions import Applicant
from app.models.attendance import AttendanceSummary
from app.models.placement import (
    Company,
    DriveApplication,
    PlacementDrive,
    PlacementOffer,
    PlacementPolicy,
    StudentPlacementProfile,
)
from app.models.registration import StudentArrear
from app.models.results import StudentTermResult
from app.models.students import Student, StudentHold, StudentProgramEnrollment, StudentTermRecord
from app.schemas.placement import PlcEligibilityPreview, PlcEligibilitySnapshot, PlcPolicyIn, PlcPolicyOut
from app.services.placement.common import PlacementBase, not_found, now_utc


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class PolicyService(PlacementBase):
    async def defaults(self) -> dict[str, Any]:
        d = await self.setting("placement", "policy_defaults")
        return {**POLICY_DEFAULTS, **(d if isinstance(d, dict) else {})}

    @staticmethod
    def out(p: PlacementPolicy, source: str = "policy") -> PlcPolicyOut:
        return PlcPolicyOut(
            id=p.id,
            batch_id=p.batch_id,
            program_id=p.program_id,
            max_offers=p.max_offers,
            dream_ctc_threshold_paise=p.dream_ctc_threshold_paise,
            allow_upgrade_if_dream=p.allow_upgrade_if_dream,
            opt_out_allowed=p.opt_out_allowed,
            rules=p.rules,
            source=source,
        )

    async def list_policies(self) -> list[PlcPolicyOut]:
        rows = (
            await self.db.execute(
                select(PlacementPolicy)
                .where(PlacementPolicy.institution_id == self.inst)
                .order_by(PlacementPolicy.created_at)
            )
        ).scalars()
        return [self.out(p) for p in rows]

    async def create(self, body: PlcPolicyIn) -> PlcPolicyOut:
        self.require_officer("manage")
        dup = (
            await self.db.execute(
                select(PlacementPolicy.id).where(
                    PlacementPolicy.institution_id == self.inst,
                    (
                        PlacementPolicy.batch_id.is_(None)
                        if body.batch_id is None
                        else PlacementPolicy.batch_id == body.batch_id
                    ),
                    (
                        PlacementPolicy.program_id.is_(None)
                        if body.program_id is None
                        else PlacementPolicy.program_id == body.program_id
                    ),
                )
            )
        ).first()
        if dup is not None:
            from app.services.placement.common import rule

            raise rule("A policy for this batch / programme exists — edit it", "DUPLICATE_POLICY")
        p = PlacementPolicy(institution_id=self.inst, **body.model_dump())
        self.db.add(p)
        await self.db.flush()
        await self._audit("create", "placement_policy", p.id, None, body.model_dump(mode="json"))
        return self.out(p)

    async def update(self, pid: uuid.UUID, body: PlcPolicyIn) -> PlcPolicyOut:
        self.require_officer("manage")
        p = (
            await self.db.execute(
                select(PlacementPolicy).where(PlacementPolicy.id == pid, PlacementPolicy.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if p is None:
            raise not_found("Policy")
        old = self.out(p).model_dump(mode="json")
        for k, v in body.model_dump().items():
            setattr(p, k, v)
        await self.db.flush()
        await self._audit("update", "placement_policy", p.id, old, body.model_dump(mode="json"))
        return self.out(p)

    async def effective(self, batch_id: uuid.UUID | None, program_id: uuid.UUID | None) -> PlcPolicyOut:
        rows = list(
            (
                await self.db.execute(select(PlacementPolicy).where(PlacementPolicy.institution_id == self.inst))
            ).scalars()
        )
        for match, source in (
            (
                lambda p: p.batch_id == batch_id and p.program_id == program_id and batch_id and program_id,
                "batch_program",
            ),
            (lambda p: p.batch_id == batch_id and p.program_id is None and batch_id, "batch"),
            (lambda p: p.program_id == program_id and p.batch_id is None and program_id, "program"),
            (lambda p: p.batch_id is None and p.program_id is None, "institution"),
        ):
            hit = next((p for p in rows if match(p)), None)
            if hit is not None:
                return self.out(hit, source)
        d = await self.defaults()
        return PlcPolicyOut(
            batch_id=batch_id,
            program_id=program_id,
            max_offers=int(d.get("max_offers") or 1),
            dream_ctc_threshold_paise=d.get("dream_ctc_threshold_paise"),
            allow_upgrade_if_dream=bool(d.get("allow_upgrade_if_dream", True)),
            opt_out_allowed=bool(d.get("opt_out_allowed", True)),
            rules=None,
            source="defaults",
        )


class EligibilityService(PlacementBase):
    # ---- academic facts (bulk) -----------------------------------------------------------------------------------------
    async def facts(self, enrolments: list[StudentProgramEnrollment]) -> dict[uuid.UUID, dict[str, Any]]:
        ids = [e.id for e in enrolments]
        if not ids:
            return {}
        out: dict[uuid.UUID, dict[str, Any]] = {
            e.id: {
                "cgpa": _f(e.cgpa),
                "active_backlogs": 0,
                "history_backlogs": 0,
                "pct_10": None,
                "pct_12": None,
                "year_12": None,
                "pct_verified": True,
                "gap_years": None,
                "attendance_pct": None,
                "holds": 0,
                "admission_year": e.admission_date.year if e.admission_date else None,
                "program_id": e.program_id,
                "batch_id": e.batch_id,
                "college_id": e.college_id,
                "status": e.status,
                "student_id": e.student_id,
            }
            for e in enrolments
        }
        # latest published current term result → CGPA
        res = await self.db.execute(
            select(
                StudentTermRecord.student_program_enrollment_id,
                StudentTermResult.cgpa,
                StudentTermRecord.term_number,
            )
            .join(StudentTermResult, StudentTermResult.student_term_record_id == StudentTermRecord.id)
            .where(
                StudentTermRecord.student_program_enrollment_id.in_(ids),
                StudentTermResult.is_current.is_(True),
                StudentTermResult.published_at.is_not(None),
                StudentTermResult.cgpa.is_not(None),
            )
            .order_by(StudentTermRecord.term_number)
        )
        for eid, cgpa, _ in res.all():
            out[eid]["cgpa"] = _f(cgpa)
        arrears = await self.db.execute(
            select(StudentArrear.student_program_enrollment_id, StudentArrear.status, func.count())
            .where(StudentArrear.student_program_enrollment_id.in_(ids))
            .group_by(StudentArrear.student_program_enrollment_id, StudentArrear.status)
        )
        for eid, status, n in arrears.all():
            out[eid]["history_backlogs"] += int(n)
            if status == "open":
                out[eid]["active_backlogs"] += int(n)
        att = await self.db.execute(
            select(AttendanceSummary.student_program_enrollment_id, func.avg(AttendanceSummary.pct))
            .where(AttendanceSummary.student_program_enrollment_id.in_(ids))
            .group_by(AttendanceSummary.student_program_enrollment_id)
        )
        for eid, pct in att.all():
            out[eid]["attendance_pct"] = round(float(pct), 2) if pct is not None else None
        holds = await self.db.execute(
            select(StudentHold.student_program_enrollment_id, func.count())
            .where(
                StudentHold.student_program_enrollment_id.in_(ids),
                StudentHold.released_at.is_(None),
                StudentHold.hold_type.in_(("all", "placement")),
            )
            .group_by(StudentHold.student_program_enrollment_id)
        )
        for eid, n in holds.all():
            out[eid]["holds"] = int(n)
        # 10th / 12th from the admitted applicant record
        by_student = {e.student_id: e.id for e in enrolments}
        apps = await self.db.execute(
            select(Applicant.admitted_student_id, Applicant.qualifying_exams).where(
                Applicant.admitted_student_id.in_(list(by_student))
            )
        )
        found: set[uuid.UUID] = set()
        for sid, exams in apps.all():
            eid = by_student.get(sid)
            if eid is None:
                continue
            for x in exams if isinstance(exams, list) else []:
                if not isinstance(x, dict):
                    continue
                level = str(x.get("level") or "").lower()
                if level in ("10", "x", "ssc", "10th"):
                    out[eid]["pct_10"] = _f(x.get("pct"))
                    found.add(eid)
                elif level in ("12", "xii", "hsc", "12th", "diploma"):
                    out[eid]["pct_12"] = _f(x.get("pct"))
                    out[eid]["year_12"] = x.get("year")
                    found.add(eid)
        # profile-entered fallback (unverified)
        missing = [i for i in ids if i not in found]
        if missing:
            profs = await self.db.execute(
                select(
                    StudentPlacementProfile.student_program_enrollment_id, StudentPlacementProfile.resume_json
                ).where(StudentPlacementProfile.student_program_enrollment_id.in_(missing))
            )
            for eid, rj in profs.all():
                entered = (rj or {}).get("academics_entered") if isinstance(rj, dict) else None
                if isinstance(entered, dict):
                    out[eid]["pct_10"] = _f(entered.get("pct_10"))
                    out[eid]["pct_12"] = _f(entered.get("pct_12"))
                    out[eid]["year_12"] = entered.get("year_12")
                    out[eid]["pct_verified"] = False
        for f in out.values():
            if f["year_12"] and f["admission_year"]:
                try:
                    f["gap_years"] = max(0, int(f["admission_year"]) - int(f["year_12"]))
                except (TypeError, ValueError):
                    f["gap_years"] = None
        return out

    async def placement_state(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
        """Profile flags + accepted offers per enrolment."""
        state: dict[uuid.UUID, dict[str, Any]] = {
            i: {
                "status": "unplaced",
                "opted_out": False,
                "blacklisted": False,
                "debarred": False,
                "holding": 0,
                "skills": [],
            }
            for i in ids
        }
        if not ids:
            return state
        profs = (
            await self.db.execute(
                select(StudentPlacementProfile).where(StudentPlacementProfile.student_program_enrollment_id.in_(ids))
            )
        ).scalars()
        bl = await self.metas("blacklist", [str(i) for i in ids])
        for p in profs:
            s = state[p.student_program_enrollment_id]
            s.update(
                status=p.placement_status,
                opted_out=p.is_opted_out,
                blacklisted=p.is_blacklisted,
                skills=[str(x).lower() for x in (p.skills or [])],
                consent=p.consent_share_profile,
            )
            m = bl.get(str(p.student_program_enrollment_id)) or {}
            s["debarred"] = p.is_blacklisted and m.get("source") == "discipline"
        offers = await self.db.execute(
            select(DriveApplication.student_program_enrollment_id, func.count())
            .join(PlacementOffer, PlacementOffer.application_id == DriveApplication.id)
            .where(DriveApplication.student_program_enrollment_id.in_(ids), PlacementOffer.status.in_(HOLDING_OFFER))
            .group_by(DriveApplication.student_program_enrollment_id)
        )
        for eid, n in offers.all():
            state[eid]["holding"] = int(n)
        return state

    async def rules_of(self, d: PlacementDrive) -> dict[str, Any]:
        base = await self.setting("placement", "eligibility_defaults")
        merged = {**ELIGIBILITY_DEFAULTS, **(base if isinstance(base, dict) else {})}
        for k, v in (d.eligibility_rules or {}).items():
            if v is not None and v != [] or k not in merged:
                merged[k] = v
        return merged

    async def is_dream(self, d: PlacementDrive, threshold: int | None, company: Company | None = None) -> bool:
        if company is None:
            company = (await self.db.execute(select(Company).where(Company.id == d.company_id))).scalar_one_or_none()
        if company is not None and company.tier in DREAM_TIERS:
            return True
        return bool(threshold and (d.ctc_min_paise or 0) >= threshold)

    async def evaluate_many(
        self, d: PlacementDrive, enrolments: list[StudentProgramEnrollment]
    ) -> dict[uuid.UUID, PlcEligibilitySnapshot]:
        rules = await self.rules_of(d)
        facts = await self.facts(enrolments)
        state = await self.placement_state([e.id for e in enrolments])
        company = (await self.db.execute(select(Company).where(Company.id == d.company_id))).scalar_one_or_none()
        policies = PolicyService(self.db, self.principal, self.request, self.inst)
        pol_cache: dict[tuple[Any, Any], PlcPolicyOut] = {}
        programs = {str(x) for x in rules.get("programs") or []}
        batches = {str(x) for x in rules.get("batches") or []}
        colleges = {str(x) for x in rules.get("colleges") or []}
        skills_any = {str(x).lower() for x in rules.get("skills_any") or []}
        now = now_utc()
        out: dict[uuid.UUID, PlcEligibilitySnapshot] = {}
        for e in enrolments:
            f, s = facts[e.id], state[e.id]
            key = (e.batch_id, e.program_id)
            if key not in pol_cache:
                pol_cache[key] = await policies.effective(e.batch_id, e.program_id)
            pol = pol_cache[key]
            reasons: list[str] = []
            if e.status not in ("active",):
                reasons.append("INACTIVE")
            mc = _f(rules.get("min_cgpa"))
            if mc is not None and (f["cgpa"] is None or f["cgpa"] < mc):
                reasons.append("CGPA")
            ma = rules.get("max_active_backlogs")
            if ma is not None and f["active_backlogs"] > int(ma):
                reasons.append("ACTIVE_BACKLOGS")
            mh = rules.get("max_history_backlogs")
            if mh is not None and f["history_backlogs"] > int(mh):
                reasons.append("HISTORY_BACKLOGS")
            p10, p12 = _f(rules.get("min_10th_pct")), _f(rules.get("min_12th_pct"))
            if p10 is not None and f["pct_10"] is not None and f["pct_10"] < p10:
                reasons.append("PCT_10")
            if p12 is not None and f["pct_12"] is not None and f["pct_12"] < p12:
                reasons.append("PCT_12")
            mg = rules.get("max_gap_years")
            if mg is not None and f["gap_years"] is not None and f["gap_years"] > int(mg):
                reasons.append("GAP_YEARS")
            if programs and str(e.program_id) not in programs:
                reasons.append("PROGRAM")
            if batches and str(e.batch_id) not in batches:
                reasons.append("BATCH")
            if (
                d.mode == "pooled"
                and colleges
                and str(e.college_id) not in colleges
                or d.mode != "pooled"
                and d.college_id is not None
                and e.college_id != d.college_id
            ):
                reasons.append("PROGRAM")
            matt = _f(rules.get("min_attendance_pct"))
            if matt is not None and (f["attendance_pct"] or 0) < matt:
                reasons.append("ATTENDANCE")
            if skills_any and not (skills_any & set(s["skills"])):
                reasons.append("SKILLS")
            if s["opted_out"]:
                reasons.append("OPTED_OUT")
            if s["debarred"]:
                reasons.append("DEBARRED")
            elif s["blacklisted"]:
                reasons.append("BLACKLISTED")
            if f["holds"]:
                reasons.append("HOLD")
            if s["holding"] >= (pol.max_offers or 1):
                dream = pol.allow_upgrade_if_dream and await self.is_dream(d, pol.dream_ctc_threshold_paise, company)
                if not (rules.get("allowed_if_already_placed") or dream):
                    reasons.append("ALREADY_PLACED")
            seen: list[str] = []
            for r in reasons:
                if r not in seen:
                    seen.append(r)
            out[e.id] = PlcEligibilitySnapshot(
                is_eligible=not seen,
                cgpa=f["cgpa"],
                active_backlogs=f["active_backlogs"],
                history_backlogs=f["history_backlogs"],
                pct_10=f["pct_10"],
                pct_12=f["pct_12"],
                pct_verified=f["pct_verified"],
                gap_years=f["gap_years"],
                placed_status=s["status"],
                attendance_pct=f["attendance_pct"],
                reasons=seen,
                evaluated_at=now,
            )
        return out

    async def evaluate(self, d: PlacementDrive, e: StudentProgramEnrollment) -> PlcEligibilitySnapshot:
        return (await self.evaluate_many(d, [e]))[e.id]

    async def candidates(self, d: PlacementDrive, *, limit: int | None = None) -> list[StudentProgramEnrollment]:
        """Active enrolments the drive could target (programme / batch / college filters applied in SQL)."""
        rules = d.eligibility_rules or {}
        stmt = select(StudentProgramEnrollment).where(
            StudentProgramEnrollment.institution_id == self.inst, StudentProgramEnrollment.status == "active"
        )
        if rules.get("programs"):
            stmt = stmt.where(StudentProgramEnrollment.program_id.in_([uuid.UUID(str(x)) for x in rules["programs"]]))
        if rules.get("batches"):
            stmt = stmt.where(StudentProgramEnrollment.batch_id.in_([uuid.UUID(str(x)) for x in rules["batches"]]))
        if d.mode == "pooled" and rules.get("colleges"):
            stmt = stmt.where(StudentProgramEnrollment.college_id.in_([uuid.UUID(str(x)) for x in rules["colleges"]]))
        elif d.mode != "pooled" and d.college_id is not None:
            stmt = stmt.where(StudentProgramEnrollment.college_id == d.college_id)
        if limit:
            stmt = stmt.limit(limit)
        return list((await self.db.execute(stmt)).scalars())

    async def preview(self, d: PlacementDrive) -> PlcEligibilityPreview:
        enrols = await self.candidates(d)
        snaps = await self.evaluate_many(d, enrols)
        by_reason: dict[str, int] = defaultdict(int)
        eligible = 0
        for snap in snaps.values():
            if snap.is_eligible:
                eligible += 1
            for r in snap.reasons:
                by_reason[r] += 1
        cards = await self.enrollment_cards([e.id for e in enrols[:20]])
        sample = [
            {
                "enrollment_id": str(e.id),
                "name": cards.get(e.id, {}).get("name"),
                "registration_number": cards.get(e.id, {}).get("registration_number"),
                "is_eligible": snaps[e.id].is_eligible,
                "reasons": snaps[e.id].reasons,
                "cgpa": snaps[e.id].cgpa,
            }
            for e in enrols[:20]
        ]
        return PlcEligibilityPreview(
            total=len(enrols), eligible_count=eligible, ineligible_by_reason=dict(by_reason), sample=sample
        )

    async def eligible_list(self, d: PlacementDrive) -> list[dict[str, Any]]:
        enrols = await self.candidates(d)
        snaps = await self.evaluate_many(d, enrols)
        ok_ids = [e.id for e in enrols if snaps[e.id].is_eligible]
        cards = await self.enrollment_cards(ok_ids)
        return [
            {
                "enrollment_id": str(i),
                "name": cards.get(i, {}).get("name"),
                "registration_number": cards.get(i, {}).get("registration_number"),
                "user_id": str(cards.get(i, {}).get("user_id") or ""),
                "cgpa": snaps[i].cgpa,
            }
            for i in ok_ids
        ]


def ctc_lpa(paise: int | None) -> str:
    if not paise:
        return "—"
    return f"₹{Decimal(paise) / Decimal(10_000_000):.2f} LPA"


async def student_names(db: Any, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = await db.execute(
        select(StudentProgramEnrollment.id, Student.first_name, Student.last_name)
        .join(Student, Student.id == StudentProgramEnrollment.student_id)
        .where(StudentProgramEnrollment.id.in_(ids))
    )
    return {r[0]: " ".join(x for x in (r[1], r[2]) if x) for r in rows.all()}
