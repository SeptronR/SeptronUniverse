"""Drives, applications, rounds — Prompts/28 §28.6 ``drive_service`` 1–2 ({placement.core}).

1. Lifecycle ``draft → open (publish) → closed (deadline) → in_progress (rounds) → completed | cancelled``. Publishing
   computes the eligible list, notifies eligible students (``placement.drive_published``) and mirrors ``drive_on`` /
   rounds into the Phase 25 calendar; a blacklisted company cannot get new drives; ``pooled`` drives span the colleges
   listed in ``eligibility_rules.colleges``.
2. Applications: the student applies (live eligibility check → 409 ``NOT_ELIGIBLE`` with reasons; one per drive;
   ``Idempotency-Key`` on the route), with the eligibility snapshot and resume URL frozen; withdraw before shortlist;
   officer / recruiter shortlist import by application id or registration number (partial-success report); override of
   eligibility with reason (``placement:override_eligibility``, audited); re-evaluation of non-overridden applications
   after results are republished (snapshots of eligible applicants are kept). Rounds with per-round bulk results
   (``cleared | not_cleared | absent``); ``absent`` after shortlist counts toward the automatic blacklist rule; the
   final round (or ``final=true``) marks cleared candidates ``selected``. Funnel per round.
"""

import uuid
from datetime import datetime, time
from typing import Any

from sqlalchemy import func, select

from app.enums.placement import DRIVE_TRANSITIONS, REASONS
from app.models.placement import (
    Company,
    DriveApplication,
    DriveRound,
    DriveRoundResult,
    PlacementDrive,
    PlacementOffer,
)
from app.models.students import StudentProgramEnrollment
from app.schemas.placement import (
    PlcApplicationOut,
    PlcApplyRequest,
    PlcBulkReport,
    PlcDriveAction,
    PlcDriveCreate,
    PlcDriveOut,
    PlcDriveUpdate,
    PlcFunnel,
    PlcOverrideEligibility,
    PlcRoundIn,
    PlcRoundOut,
    PlcRoundResultsBulk,
    PlcRoundUpdate,
    PlcShortlistBulk,
)
from app.services.placement.common import PlacementBase, forbidden, not_found, now_utc, rule
from app.services.placement.eligibility_service import EligibilityService, ctc_lpa

SHORTLISTED_OR_LATER = ("shortlisted", "in_process", "selected", "offer_accepted", "offer_declined")


class DriveService(PlacementBase):
    @property
    def elig(self) -> EligibilityService:
        return EligibilityService(self.db, self.principal, self.request, self.inst)

    # ---- drives -----------------------------------------------------------------------------------------------------
    async def outs(self, rows: list[PlacementDrive], *, mine: bool = False, funnel: bool = False) -> list[PlcDriveOut]:
        companies = await self.companies_map([d.company_id for d in rows])
        counts: dict[uuid.UUID, int] = {}
        if rows:
            for did, n in (
                await self.db.execute(
                    select(DriveApplication.drive_id, func.count())
                    .where(DriveApplication.drive_id.in_([d.id for d in rows]))
                    .group_by(DriveApplication.drive_id)
                )
            ).all():
                counts[did] = int(n)
        my_apps: dict[uuid.UUID, DriveApplication] = {}
        snaps: dict[uuid.UUID, Any] = {}
        if mine:
            e = await self.my_enrollment()
            if e is not None:
                for a in (
                    await self.db.execute(
                        select(DriveApplication).where(
                            DriveApplication.student_program_enrollment_id == e.id,
                            DriveApplication.drive_id.in_([d.id for d in rows] or [uuid.uuid4()]),
                        )
                    )
                ).scalars():
                    my_apps[a.drive_id] = a
                for d in rows:
                    snaps[d.id] = await self.elig.evaluate(d, e)
        out = []
        for d in rows:
            c = companies.get(d.company_id)
            o = PlcDriveOut(
                id=d.id,
                company_id=d.company_id,
                company_name=c.name if c else None,
                company_tier=c.tier if c else None,
                college_id=d.college_id,
                title=d.title,
                job_role=d.job_role,
                job_type=d.job_type,
                ctc_min_paise=d.ctc_min_paise,
                ctc_max_paise=d.ctc_max_paise,
                stipend_paise=d.stipend_paise,
                locations=list(d.locations or []),
                bond=d.bond,
                eligibility_rules=d.eligibility_rules or {},
                registration_deadline=d.registration_deadline,
                drive_on=d.drive_on,
                mode=d.mode,
                status=d.status,
                jd_url=d.jd_url,
                owner_staff_id=d.owner_staff_id,
                applications=counts.get(d.id, 0),
                created_at=d.created_at,
            )
            if mine:
                o.my_eligibility = snaps.get(d.id)
                mine_app = my_apps.get(d.id)
                if mine_app is not None:
                    o.my_application_id, o.my_application_status = mine_app.id, mine_app.status
            if funnel:
                o.funnel = (await self.funnel(d.id)).rounds
            out.append(o)
        return out

    async def list_drives(self, status: str | None, company_id: uuid.UUID | None) -> list[PlcDriveOut]:
        stmt = select(PlacementDrive).where(PlacementDrive.institution_id == self.inst, await self.drive_predicate())
        if status:
            stmt = stmt.where(PlacementDrive.status == status)
        if company_id:
            stmt = stmt.where(PlacementDrive.company_id == company_id)
        rows = list((await self.db.execute(stmt.order_by(PlacementDrive.created_at.desc()).limit(500))).scalars())
        return await self.outs(rows)

    async def open_drives(self) -> list[PlcDriveOut]:
        """Student view: published drives with my eligibility + reasons."""
        rows = list(
            (
                await self.db.execute(
                    select(PlacementDrive)
                    .where(
                        PlacementDrive.institution_id == self.inst, PlacementDrive.status.in_(("open", "in_progress"))
                    )
                    .order_by(PlacementDrive.registration_deadline.nullslast())
                )
            ).scalars()
        )
        e = await self.my_enrollment()
        if e is not None:
            rows = [d for d in rows if d.mode == "pooled" or d.college_id is None or d.college_id == e.college_id]
        return await self.outs(rows, mine=True)

    async def get(self, did: uuid.UUID) -> PlcDriveOut:
        d = await self.drive(did)
        mine = self.can("placement", "self") and not self.officer()
        return (await self.outs([d], mine=mine, funnel=not mine))[0]

    async def _company_ok(self, company_id: uuid.UUID) -> Company:
        c = (
            await self.db.execute(
                select(Company).where(
                    Company.id == company_id, Company.institution_id == self.inst, Company.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()
        if c is None:
            raise not_found("Company")
        if c.is_blacklisted:
            raise rule("Company is blacklisted — no new drives", "COMPANY_BLACKLISTED")
        return c

    async def create(self, body: PlcDriveCreate, *, recruiter: bool = False) -> PlcDriveOut:
        if not recruiter:
            self.require_officer("drive_manage")
            self.college_guard(body.college_id)
        await self._company_ok(body.company_id)
        data = body.model_dump(mode="json")
        d = PlacementDrive(
            institution_id=self.inst,
            company_id=body.company_id,
            college_id=body.college_id,
            title=body.title,
            job_role=body.job_role,
            job_type=body.job_type,
            ctc_min_paise=body.ctc_min_paise,
            ctc_max_paise=body.ctc_max_paise,
            stipend_paise=body.stipend_paise,
            locations=body.locations,
            bond=body.bond,
            eligibility_rules=body.eligibility_rules.model_dump(mode="json"),
            registration_deadline=body.registration_deadline,
            drive_on=body.drive_on,
            mode=body.mode,
            jd_url=body.jd_url,
            owner_staff_id=body.owner_staff_id or (None if recruiter else await self.my_staff_id()),
            status="draft",
            created_by=self.actor_id,
        )
        self.db.add(d)
        await self.db.flush()
        if recruiter:
            await self.put_meta("drive", d.id, {"recruiter_created": True, "created_by": str(self.actor_id)})
        await self._audit("create", "placement_drive", d.id, None, {**data, "recruiter": recruiter})
        return (await self.outs([d]))[0]

    async def update(self, did: uuid.UUID, body: PlcDriveUpdate, *, recruiter: bool = False) -> PlcDriveOut:
        if not recruiter:
            self.require_officer("drive_manage")
        d = await self.drive(did, lock=True)
        self.college_guard(d.college_id)
        if d.status in ("completed", "cancelled"):
            raise rule(f"Drive is {d.status}", "DRIVE_CLOSED")
        if recruiter and d.status != "draft":
            raise rule("Recruiters edit draft drives only", "NOT_DRAFT")
        old = {"title": d.title, "eligibility_rules": d.eligibility_rules, "ctc_min_paise": d.ctc_min_paise}
        data = body.model_dump(exclude_unset=True)
        for k, v in data.items():
            if k == "eligibility_rules" and v is not None:
                v = body.eligibility_rules.model_dump(mode="json") if body.eligibility_rules else {}
            setattr(d, k, v)
        await self.db.flush()
        await self._audit("update", "placement_drive", d.id, old, body.model_dump(mode="json", exclude_unset=True))
        if d.status != "draft":
            await self._calendar(d)
        return (await self.outs([d]))[0]

    async def action(self, did: uuid.UUID, body: PlcDriveAction) -> PlcDriveOut:
        self.require_officer("drive_manage")
        d = await self.drive(did, lock=True)
        self.college_guard(d.college_id)
        nxt = DRIVE_TRANSITIONS[body.action].get(d.status)
        if nxt is None:
            raise rule(f"Cannot {body.action} a {d.status} drive", "INVALID_TRANSITION")
        if body.action == "publish":
            await self._company_ok(d.company_id)
        old = d.status
        d.status = nxt
        await self.db.flush()
        await self._audit(body.action, "placement_drive", d.id, {"status": old}, {"status": nxt, "reason": body.reason})
        event = {
            "publish": "placement.drive_published",
            "close": "placement.drive_closed",
            "start": "placement.drive_started",
            "complete": "placement.drive_completed",
            "cancel": "placement.drive_cancelled",
        }[body.action]
        await self._emit(event, {"drive_id": str(d.id), "company_id": str(d.company_id)}, "placement_drive", d.id)
        if body.action == "publish":
            await self.publish_effects(d)
        elif body.action == "cancel":
            from app.services.facilities.calendar_service import CalendarService

            await CalendarService(self.db, self.principal, self.request, self.inst).unmirror("placement_drive", d.id)
        return (await self.outs([d]))[0]

    async def publish_effects(self, d: PlacementDrive) -> int:
        """Eligible list → notifications + calendar (inline; the ``placement.publish_drive`` job re-runs it)."""
        eligible = await self.elig.eligible_list(d)
        company = (await self.db.execute(select(Company).where(Company.id == d.company_id))).scalar_one()
        users = [uuid.UUID(r["user_id"]) for r in eligible if r.get("user_id")]
        deadline = d.registration_deadline.strftime("%d %b %Y %H:%M") if d.registration_deadline else "—"
        await self._notify("placement.drive_published", users, {"company": company.name, "deadline": deadline})
        meta = await self.meta("drive", d.id)
        meta.update(published_at=now_utc().isoformat(), notified=len(users), eligible=len(eligible))
        await self.put_meta("drive", d.id, meta)
        await self._calendar(d)
        return len(users)

    async def _calendar(self, d: PlacementDrive) -> None:
        from app.services.facilities.calendar_service import CalendarService

        cal = CalendarService(self.db, self.principal, self.request, self.inst)
        company = (await self.db.execute(select(Company.name).where(Company.id == d.company_id))).scalar_one()
        if d.drive_on:
            start = datetime.combine(d.drive_on, time(9, 0)).astimezone()
            await cal.mirror(
                "placement_drive",
                d.id,
                title=f"Placement drive: {company} — {d.title}",
                starts=start,
                ends=None,
                event_type="placement",
                college_id=d.college_id,
            )
        for r in (await self.db.execute(select(DriveRound).where(DriveRound.drive_id == d.id))).scalars():
            if r.scheduled_at:
                await cal.mirror(
                    "placement_round",
                    r.id,
                    title=f"{company}: {r.name}",
                    starts=r.scheduled_at,
                    ends=None,
                    event_type="placement",
                    college_id=d.college_id,
                    location=r.venue,
                )

    async def eligibility_preview(self, did: uuid.UUID) -> Any:
        self.require_officer("drive_manage", "view_all")
        d = await self.drive(did)
        return await self.elig.preview(d)

    async def eligible_list(self, did: uuid.UUID) -> list[dict[str, Any]]:
        if not (self.officer() or self.can("placement", "view_all")):
            raise forbidden()
        d = await self.drive(did)
        rows = await self.elig.eligible_list(d)
        await self._audit("export_eligible", "placement_drive", d.id, None, {"rows": len(rows)})
        return [{k: v for k, v in r.items() if k != "user_id"} for r in rows]

    async def deadline_close(self) -> int:
        """Beat (hourly): open drives past their registration deadline → ``closed``."""
        n = 0
        for d in (
            await self.db.execute(
                select(PlacementDrive).where(
                    PlacementDrive.institution_id == self.inst,
                    PlacementDrive.status == "open",
                    PlacementDrive.registration_deadline.is_not(None),
                    PlacementDrive.registration_deadline < now_utc(),
                )
            )
        ).scalars():
            d.status = "closed"
            await self._emit("placement.drive_closed", {"drive_id": str(d.id), "auto": True}, "placement_drive", d.id)
            n += 1
        await self.db.flush()
        return n

    # ---- applications -------------------------------------------------------------------------------------------------
    async def app_outs(self, rows: list[DriveApplication], *, rounds: bool = False) -> list[PlcApplicationOut]:
        drives = await self.drives_map([a.drive_id for a in rows])
        companies = await self.companies_map([d.company_id for d in drives.values()])
        cards = await self.enrollment_cards([a.student_program_enrollment_id for a in rows])
        depts = await self.department_codes([c.get("department_id") for c in cards.values()])
        offers: dict[uuid.UUID, PlacementOffer] = {}
        results: dict[uuid.UUID, list[dict[str, Any]]] = {}
        if rows:
            ids = [a.id for a in rows]
            for o in (
                await self.db.execute(select(PlacementOffer).where(PlacementOffer.application_id.in_(ids)))
            ).scalars():
                offers[o.application_id] = o
            if rounds:
                for rr, r in (
                    await self.db.execute(
                        select(DriveRoundResult, DriveRound)
                        .join(DriveRound, DriveRound.id == DriveRoundResult.round_id)
                        .where(DriveRoundResult.application_id.in_(ids))
                        .order_by(DriveRound.round_no)
                    )
                ).all():
                    results.setdefault(rr.application_id, []).append(
                        {
                            "round_id": str(r.id),
                            "round_no": r.round_no,
                            "name": r.name,
                            "scheduled_at": r.scheduled_at.isoformat() if r.scheduled_at else None,
                            "venue": r.venue,
                            "status": rr.status,
                            "score": float(rr.score) if rr.score is not None else None,
                        }
                    )
        out = []
        for a in rows:
            d = drives.get(a.drive_id)
            c = companies.get(d.company_id) if d else None
            card = cards.get(a.student_program_enrollment_id, {})
            off = offers.get(a.id)
            out.append(
                PlcApplicationOut(
                    id=a.id,
                    drive_id=a.drive_id,
                    drive_title=d.title if d else None,
                    company_name=c.name if c else None,
                    student_program_enrollment_id=a.student_program_enrollment_id,
                    student_name=card.get("name"),
                    registration_number=card.get("registration_number"),
                    department_code=depts.get(card["department_id"]) if card.get("department_id") else None,
                    eligibility_snapshot=a.eligibility_snapshot,
                    is_eligible=a.is_eligible,
                    override_reason=a.override_reason,
                    resume_url=a.resume_url,
                    status=a.status,
                    applied_at=a.applied_at,
                    rounds=results.get(a.id, []),
                    offer={"id": str(off.id), "status": off.status, "ctc_paise": off.ctc_paise} if off else None,
                )
            )
        return out

    async def apply(self, did: uuid.UUID, body: PlcApplyRequest) -> PlcApplicationOut:
        e = await self.require_my_enrollment()
        d = await self.drive(did, lock=True)
        if d.status != "open":
            raise rule("Drive is not open for registration", "DRIVE_NOT_OPEN")
        if d.registration_deadline and d.registration_deadline < now_utc():
            raise rule("Registration deadline has passed", "DEADLINE_PASSED")
        existing = (
            await self.db.execute(
                select(DriveApplication).where(
                    DriveApplication.drive_id == d.id, DriveApplication.student_program_enrollment_id == e.id
                )
            )
        ).scalar_one_or_none()
        if existing is not None and existing.status != "withdrawn":
            return (await self.app_outs([existing]))[0]
        await self.profile_of(e.id, lock=True)
        snap = await self.elig.evaluate(d, e)
        if not snap.is_eligible and not (existing is not None and existing.override_by):
            raise rule(
                "Not eligible for this drive",
                "NOT_ELIGIBLE",
                reasons=snap.reasons,
                messages=[REASONS.get(r, r) for r in snap.reasons],
            )
        prof = await self.profile_of(e.id)
        resume = body.resume_url or prof.resume_url
        if existing is not None:
            existing.status, existing.eligibility_snapshot, existing.resume_url = (
                "applied",
                snap.model_dump(mode="json"),
                resume,
            )
            existing.is_eligible = snap.is_eligible or bool(existing.override_by)
            a = existing
        else:
            a = DriveApplication(
                institution_id=self.inst,
                drive_id=d.id,
                student_program_enrollment_id=e.id,
                eligibility_snapshot=snap.model_dump(mode="json"),
                is_eligible=True,
                resume_url=resume,
                status="applied",
            )
            self.db.add(a)
        await self.db.flush()
        await self._emit(
            "placement.applied",
            {"application_id": str(a.id), "drive_id": str(d.id), "enrollment_id": str(e.id)},
            "drive_application",
            a.id,
        )
        return (await self.app_outs([a]))[0]

    async def _app(self, aid: uuid.UUID, *, lock: bool = False) -> DriveApplication:
        stmt = select(DriveApplication).where(DriveApplication.id == aid, DriveApplication.institution_id == self.inst)
        if lock:
            stmt = stmt.with_for_update()
        a = (await self.db.execute(stmt)).scalar_one_or_none()
        if a is None:
            raise not_found("Application")
        return a

    async def withdraw(self, aid: uuid.UUID) -> PlcApplicationOut:
        a = await self._app(aid, lock=True)
        if a.student_program_enrollment_id not in await self.my_enrollment_ids():
            raise not_found("Application")
        if a.status != "applied":
            raise rule("Withdrawal is allowed only before shortlisting", "WITHDRAW_LOCKED")
        a.status = "withdrawn"
        await self.db.flush()
        await self._emit("placement.withdrawn", {"application_id": str(a.id)}, "drive_application", a.id)
        return (await self.app_outs([a]))[0]

    async def my_applications(self) -> list[PlcApplicationOut]:
        ids = await self.my_enrollment_ids()
        rows = list(
            (
                await self.db.execute(
                    select(DriveApplication)
                    .where(DriveApplication.student_program_enrollment_id.in_(ids or [uuid.uuid4()]))
                    .order_by(DriveApplication.applied_at.desc())
                )
            ).scalars()
        )
        return await self.app_outs(rows, rounds=True)

    async def ward_applications(self) -> list[PlcApplicationOut]:
        ids = await self.ward_enrollment_ids()
        rows = list(
            (
                await self.db.execute(
                    select(DriveApplication)
                    .where(DriveApplication.student_program_enrollment_id.in_(ids or [uuid.uuid4()]))
                    .order_by(DriveApplication.applied_at.desc())
                )
            ).scalars()
        )
        return await self.app_outs(rows, rounds=True)

    async def drive_applications(
        self,
        did: uuid.UUID,
        status: str | None,
        round_id: uuid.UUID | None,
        department_id: uuid.UUID | None,
        scope: str | None,
    ) -> list[PlcApplicationOut]:
        d = await self.drive(did)
        stmt = select(DriveApplication).where(DriveApplication.drive_id == d.id)
        if not self.officer():
            stmt = stmt.where(await self.enrolment_predicate(DriveApplication.student_program_enrollment_id, scope))
        if status:
            stmt = stmt.where(DriveApplication.status == status)
        if department_id:
            stmt = stmt.where(
                DriveApplication.student_program_enrollment_id.in_(
                    select(StudentProgramEnrollment.id).where(StudentProgramEnrollment.department_id == department_id)
                )
            )
        if round_id:
            stmt = stmt.where(
                DriveApplication.id.in_(
                    select(DriveRoundResult.application_id).where(DriveRoundResult.round_id == round_id)
                )
            )
        rows = list((await self.db.execute(stmt.order_by(DriveApplication.applied_at))).scalars())
        return await self.app_outs(rows, rounds=True)

    async def resolve_rows(
        self, drive_id: uuid.UUID, rows: list[Any]
    ) -> tuple[dict[int, DriveApplication], list[dict[str, Any]]]:
        """Map bulk rows (application id | registration number) to applications of the drive."""
        regs = await self.enrollment_by_reg([r.registration_number for r in rows if r.registration_number])
        apps = {
            a.id: a
            for a in (
                await self.db.execute(select(DriveApplication).where(DriveApplication.drive_id == drive_id))
            ).scalars()
        }
        by_enrol = {a.student_program_enrollment_id: a for a in apps.values()}
        found: dict[int, DriveApplication] = {}
        failed: list[dict[str, Any]] = []
        for i, r in enumerate(rows):
            a = None
            if r.application_id:
                a = apps.get(r.application_id)
            elif r.registration_number:
                eid = regs.get(r.registration_number.strip())
                a = by_enrol.get(eid) if eid else None
            if a is None:
                failed.append({"row": i, "key": str(r.application_id or r.registration_number), "error": "NOT_FOUND"})
            else:
                found[i] = a
        return found, failed

    async def shortlist(self, did: uuid.UUID, body: PlcShortlistBulk, *, recruiter: bool = False) -> PlcBulkReport:
        if not recruiter:
            self.require_officer("drive_manage")
        d = await self.drive(did, lock=True)
        if d.status in ("draft", "cancelled", "completed"):
            raise rule(f"Drive is {d.status}", "DRIVE_STATE")
        found, failed = await self.resolve_rows(d.id, body.rows)
        company = (await self.db.execute(select(Company.name).where(Company.id == d.company_id))).scalar_one()
        users: list[uuid.UUID] = []
        ok = 0
        for i, a in found.items():
            if a.status not in ("applied", "shortlisted"):
                failed.append({"row": i, "key": str(a.id), "error": f"STATUS_{a.status.upper()}"})
                continue
            a.status = "shortlisted"
            ok += 1
            card = (await self.enrollment_cards([a.student_program_enrollment_id])).get(
                a.student_program_enrollment_id, {}
            )
            if card.get("user_id"):
                users.append(card["user_id"])
            await self._emit(
                "placement.shortlisted", {"application_id": str(a.id), "drive_id": str(d.id)}, "drive_application", a.id
            )
        await self.db.flush()
        await self._notify("placement.shortlisted", users, {"company": company, "drive": d.title})
        await self._audit(
            "shortlist", "placement_drive", d.id, None, {"ok": ok, "failed": len(failed), "recruiter": recruiter}
        )
        return PlcBulkReport(processed=len(body.rows), succeeded=ok, failed=failed)

    async def override(self, body: PlcOverrideEligibility) -> PlcApplicationOut:
        self.require_writer()
        if not self.can("placement", "override_eligibility"):
            raise forbidden("placement:override_eligibility required")
        if body.application_id:
            a = await self._app(body.application_id, lock=True)
        else:
            if not (body.drive_id and body.enrollment_id):
                raise rule("application_id or drive_id + enrollment_id required", "MISSING_TARGET", status=422)
            d = await self.drive(body.drive_id, lock=True)
            e = await self.enrollment(body.enrollment_id)
            existing = (
                await self.db.execute(
                    select(DriveApplication).where(
                        DriveApplication.drive_id == d.id, DriveApplication.student_program_enrollment_id == e.id
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                a = existing
            else:
                snap = await self.elig.evaluate(d, e)
                a = DriveApplication(
                    institution_id=self.inst,
                    drive_id=d.id,
                    student_program_enrollment_id=e.id,
                    eligibility_snapshot=snap.model_dump(mode="json"),
                    status="ineligible",
                    is_eligible=False,
                )
                self.db.add(a)
                await self.db.flush()
        old = {"is_eligible": a.is_eligible, "status": a.status}
        a.is_eligible, a.override_by, a.override_reason = True, self.actor_id, body.reason
        if a.status == "ineligible":
            a.status = "applied"
        await self.db.flush()
        await self._audit("override_eligibility", "drive_application", a.id, old, {"reason": body.reason})
        await self._emit(
            "placement.eligibility_overridden",
            {"application_id": str(a.id), "reason": body.reason},
            "drive_application",
            a.id,
        )
        return (await self.app_outs([a]))[0]

    async def re_evaluate(self, did: uuid.UUID) -> PlcBulkReport:
        """Re-run eligibility for non-overridden applications; eligible snapshots stay untouched."""
        self.require_officer("drive_manage", "override_eligibility")
        d = await self.drive(did)
        apps = list(
            (
                await self.db.execute(
                    select(DriveApplication).where(
                        DriveApplication.drive_id == d.id, DriveApplication.override_by.is_(None)
                    )
                )
            ).scalars()
        )
        enrols = {
            e.id: e
            for e in (
                await self.db.execute(
                    select(StudentProgramEnrollment).where(
                        StudentProgramEnrollment.id.in_(
                            [a.student_program_enrollment_id for a in apps] or [uuid.uuid4()]
                        )
                    )
                )
            ).scalars()
        }
        snaps = await self.elig.evaluate_many(d, list(enrols.values()))
        changed = 0
        for a in apps:
            s = snaps.get(a.student_program_enrollment_id)
            if s is None:
                continue
            if not a.is_eligible and s.is_eligible:
                a.is_eligible, a.eligibility_snapshot = True, s.model_dump(mode="json")
                if a.status == "ineligible":
                    a.status = "applied"
                changed += 1
            elif a.is_eligible and not s.is_eligible and a.status == "applied":
                a.is_eligible, a.status = False, "ineligible"
                a.eligibility_snapshot = {**(a.eligibility_snapshot or {}), "reevaluated": s.model_dump(mode="json")}
                changed += 1
        await self.db.flush()
        await self._audit("re_evaluate", "placement_drive", d.id, None, {"changed": changed})
        return PlcBulkReport(processed=len(apps), succeeded=changed)

    # ---- rounds -----------------------------------------------------------------------------------------------------
    async def round_outs(self, rows: list[DriveRound]) -> list[PlcRoundOut]:
        counts: dict[uuid.UUID, dict[str, int]] = {r.id: {} for r in rows}
        if rows:
            for rid, st, n in (
                await self.db.execute(
                    select(DriveRoundResult.round_id, DriveRoundResult.status, func.count())
                    .where(DriveRoundResult.round_id.in_([r.id for r in rows]))
                    .group_by(DriveRoundResult.round_id, DriveRoundResult.status)
                )
            ).all():
                counts[rid][st] = int(n)
        return [
            PlcRoundOut(
                id=r.id,
                drive_id=r.drive_id,
                round_no=r.round_no,
                name=r.name,
                round_type=r.round_type,
                scheduled_at=r.scheduled_at,
                venue=r.venue,
                results=counts[r.id],
            )
            for r in rows
        ]

    async def rounds(self, did: uuid.UUID) -> list[PlcRoundOut]:
        d = await self.drive(did)
        rows = list(
            (
                await self.db.execute(
                    select(DriveRound).where(DriveRound.drive_id == d.id).order_by(DriveRound.round_no)
                )
            ).scalars()
        )
        return await self.round_outs(rows)

    async def add_round(self, did: uuid.UUID, body: PlcRoundIn, *, recruiter: bool = False) -> PlcRoundOut:
        if not recruiter:
            self.require_officer("drive_manage")
        d = await self.drive(did, lock=True)
        if d.status in ("completed", "cancelled"):
            raise rule(f"Drive is {d.status}", "DRIVE_STATE")
        dup = (
            await self.db.execute(
                select(DriveRound.id).where(DriveRound.drive_id == d.id, DriveRound.round_no == body.round_no)
            )
        ).first()
        if dup is not None:
            raise rule(f"Round {body.round_no} exists", "DUPLICATE_ROUND")
        r = DriveRound(institution_id=self.inst, drive_id=d.id, **body.model_dump())
        self.db.add(r)
        await self.db.flush()
        await self._audit("add_round", "placement_drive", d.id, None, body.model_dump(mode="json"))
        await self._round_notice(d, r)
        return (await self.round_outs([r]))[0]

    async def _round_notice(self, d: PlacementDrive, r: DriveRound) -> None:
        if r.scheduled_at is None or d.status == "draft":
            return
        await self._calendar(d)
        apps = (
            await self.db.execute(
                select(DriveApplication.student_program_enrollment_id).where(
                    DriveApplication.drive_id == d.id, DriveApplication.status.in_(("shortlisted", "in_process"))
                )
            )
        ).all()
        cards = await self.enrollment_cards([x[0] for x in apps])
        company = (await self.db.execute(select(Company.name).where(Company.id == d.company_id))).scalar_one()
        await self._notify(
            "placement.round_scheduled",
            [c.get("user_id") for c in cards.values()],
            {
                "company": company,
                "round": r.name,
                "at": r.scheduled_at.strftime("%d %b %H:%M"),
                "venue": r.venue or "—",
            },
        )

    async def _round(self, rid: uuid.UUID, *, lock: bool = False) -> tuple[DriveRound, PlacementDrive]:
        r = (
            await self.db.execute(
                select(DriveRound).where(DriveRound.id == rid, DriveRound.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if r is None:
            raise not_found("Round")
        d = await self.drive(r.drive_id, lock=lock)
        return r, d

    async def update_round(self, rid: uuid.UUID, body: PlcRoundUpdate) -> PlcRoundOut:
        self.require_officer("drive_manage")
        r, d = await self._round(rid)
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(r, k, v)
        await self.db.flush()
        await self._audit("update_round", "drive_round", r.id, None, body.model_dump(mode="json", exclude_unset=True))
        if "scheduled_at" in body.model_fields_set:
            await self._round_notice(d, r)
        return (await self.round_outs([r]))[0]

    async def round_results(
        self, rid: uuid.UUID, body: PlcRoundResultsBulk, *, recruiter: bool = False
    ) -> PlcBulkReport:
        if not recruiter:
            self.require_officer("drive_manage")
        r, d = await self._round(rid, lock=True)
        if d.status in ("draft", "cancelled", "completed"):
            raise rule(f"Drive is {d.status}", "DRIVE_STATE")
        last_no = (
            await self.db.execute(select(func.max(DriveRound.round_no)).where(DriveRound.drive_id == d.id))
        ).scalar_one()
        final = body.final or r.round_type == "final" or r.round_no == last_no
        found, failed = await self.resolve_rows(d.id, body.rows)
        existing = {
            x.application_id: x
            for x in (
                await self.db.execute(select(DriveRoundResult).where(DriveRoundResult.round_id == r.id))
            ).scalars()
        }
        company = (await self.db.execute(select(Company.name).where(Company.id == d.company_id))).scalar_one()
        ok = 0
        absent_enrols: list[uuid.UUID] = []
        notify: list[tuple[uuid.UUID, str]] = []
        for i, a in found.items():
            row = body.rows[i]
            if a.status not in ("shortlisted", "in_process", "selected", "absent"):
                failed.append({"row": i, "key": str(a.id), "error": f"STATUS_{a.status.upper()}"})
                continue
            res = existing.get(a.id)
            if res is None:
                res = DriveRoundResult(institution_id=self.inst, application_id=a.id, round_id=r.id)
                self.db.add(res)
            res.status, res.score, res.remarks = row.status, row.score, row.remarks
            res.recorded_by, res.recorded_at = self.actor_id, now_utc()
            if row.status == "cleared":
                a.status = "selected" if final else "in_process"
                if final:
                    await self._emit("placement.selected", {"application_id": str(a.id)}, "drive_application", a.id)
            elif row.status == "not_cleared":
                a.status = "rejected"
            elif row.status == "absent":
                a.status = "absent"
                absent_enrols.append(a.student_program_enrollment_id)
            notify.append((a.student_program_enrollment_id, row.status))
            ok += 1
        if d.status in ("open", "closed"):
            d.status = "in_progress"
        await self.db.flush()
        await self._emit(
            "placement.round_result", {"round_id": str(r.id), "drive_id": str(d.id), "rows": ok}, "drive_round", r.id
        )
        cards = await self.enrollment_cards([e for e, _ in notify])
        for e, st in notify:
            uid = cards.get(e, {}).get("user_id")
            if uid:
                await self._notify("placement.round_result", [uid], {"company": company, "round": r.name, "status": st})
        await self._audit(
            "round_results", "drive_round", r.id, None, {"ok": ok, "failed": len(failed), "recruiter": recruiter}
        )
        blacklisted: list[str] = []
        if absent_enrols:
            from app.services.placement.offer_service import OfferService

            blacklisted = await OfferService(self.db, self.principal, self.request, self.inst).apply_no_show_rule(
                absent_enrols
            )
        return PlcBulkReport(processed=len(body.rows), succeeded=ok, failed=failed, blacklisted=blacklisted)

    async def funnel(self, did: uuid.UUID) -> PlcFunnel:
        apps: dict[str, int] = {
            str(k): int(n)
            for k, n in (
                await self.db.execute(
                    select(DriveApplication.status, func.count())
                    .where(DriveApplication.drive_id == did)
                    .group_by(DriveApplication.status)
                )
            ).all()
        }
        applied = sum(int(v) for k, v in apps.items() if k not in ("withdrawn", "ineligible"))
        shortlisted = sum(int(v) for k, v in apps.items() if k in (*SHORTLISTED_OR_LATER, "rejected", "absent"))
        rounds = []
        for r in (
            await self.db.execute(select(DriveRound).where(DriveRound.drive_id == did).order_by(DriveRound.round_no))
        ).scalars():
            st: dict[str, int] = {
                str(k): int(n)
                for k, n in (
                    await self.db.execute(
                        select(DriveRoundResult.status, func.count())
                        .where(DriveRoundResult.round_id == r.id)
                        .group_by(DriveRoundResult.status)
                    )
                ).all()
            }
            rounds.append(
                {
                    "round_id": str(r.id),
                    "round_no": r.round_no,
                    "name": r.name,
                    "appeared": int(sum(v for k, v in st.items() if k in ("cleared", "not_cleared"))),
                    "cleared": int(st.get("cleared", 0)),
                    "absent": int(st.get("absent", 0)),
                }
            )
        offers: dict[str, int] = {
            str(k): int(n)
            for k, n in (
                await self.db.execute(
                    select(PlacementOffer.status, func.count())
                    .join(DriveApplication, DriveApplication.id == PlacementOffer.application_id)
                    .where(DriveApplication.drive_id == did)
                    .group_by(PlacementOffer.status)
                )
            ).all()
        }
        return PlcFunnel(
            drive_id=did,
            applied=applied,
            shortlisted=shortlisted,
            rounds=rounds,
            selected=int(sum(v for k, v in apps.items() if k in ("selected", "offer_accepted", "offer_declined"))),
            offers=int(sum(offers.values())),
            accepted=int(sum(v for k, v in offers.items() if k in ("accepted", "joined"))),
        )

    async def funnel_for(self, did: uuid.UUID) -> PlcFunnel:
        d = await self.drive(did)
        return await self.funnel(d.id)

    def ctc_label(self, d: PlacementDrive) -> str:
        return ctc_lpa(d.ctc_min_paise)
