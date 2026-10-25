"""Offers, blacklist, company feedback — Prompts/28 §28.6 ``drive_service`` 3–5 ({placement.core}).

3. Offers are created from ``selected`` applications (or as PPO) → ``offered`` + ``placement.offer_received``. The
   student accepts / declines; **acceptance enforces the policy** with ``FOR UPDATE`` on the application and the
   student's placement profile: holding offers (``accepted | joined``) ≥ ``max_offers`` → 409 ``MAX_OFFERS`` unless
   the new offer is a dream upgrade (``allow_upgrade_if_dream`` and the drive is dream by tier / threshold), in which
   case the previously accepted offer is auto-``declined`` with reason ``dream_upgrade``; the profile becomes
   ``placed`` (or ``multiple`` when the policy allows more than one). ``joined | not_joined`` after the joining date
   (weekly follow-up), revocation by the company / officer, daily reminders for undecided offers. Every offer is
   archived through Phase 26 ``documents.render('custom', 'placement_offer', id)`` (the company's letter stays as the
   ``offer_letter_url`` attachment). Recruiter-submitted offers wait in the drive's side store until an officer
   confirms them.
4. Blacklist on ``student_placement_profiles.is_blacklisted`` — manual (reason / until), automatic by
   ``placement.blacklist_rules`` (absent after shortlist ≥ N, decline after accept ≥ N) or from a discipline
   ``debar_placement`` sanction; each emits ``placement.blacklisted`` (+ ``placement.policy_violation`` for rule /
   manual cases so Phase 27 may open a disciplinary case) and notifies the student; unblacklisting is audited; a daily
   Beat lifts expired entries.
5. Company feedback per drive (ratings on candidates / process).
"""

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError
from app.enums.placement import BLACKLIST_RULES, HOLDING_OFFER
from app.models.placement import (
    Company,
    CompanyFeedback,
    DriveApplication,
    DriveRoundResult,
    PlacementDrive,
    PlacementOffer,
    StudentPlacementProfile,
)
from app.models.students import StudentProgramEnrollment
from app.schemas.placement import (
    PlcBlacklistOut,
    PlcBlacklistRequest,
    PlcFeedbackIn,
    PlcFeedbackOut,
    PlcOfferCreate,
    PlcOfferDecision,
    PlcOfferOut,
    PlcOfferStatusUpdate,
    PlcPendingOffer,
)
from app.services.documents.render_service import RenderService, register_resolver
from app.services.placement.common import PlacementBase, forbidden, not_found, now_utc, rule
from app.services.placement.eligibility_service import EligibilityService, PolicyService, ctc_lpa


class OfferService(PlacementBase):
    # ---- read ---------------------------------------------------------------------------------------------------------
    async def outs(self, rows: list[PlacementOffer]) -> list[PlcOfferOut]:
        apps = {
            a.id: a
            for a in (
                await self.db.execute(
                    select(DriveApplication).where(
                        DriveApplication.id.in_([o.application_id for o in rows] or [uuid.uuid4()])
                    )
                )
            ).scalars()
        }
        drives = await self.drives_map([a.drive_id for a in apps.values()])
        companies = await self.companies_map([o.company_id for o in rows])
        cards = await self.enrollment_cards([a.student_program_enrollment_id for a in apps.values()])
        docs = await self.metas("offer", [str(o.id) for o in rows])
        elig = EligibilityService(self.db, self.principal, self.request, self.inst)
        out = []
        for o in rows:
            a = apps.get(o.application_id)
            d = drives.get(a.drive_id) if a else None
            c = companies.get(o.company_id)
            card = cards.get(a.student_program_enrollment_id, {}) if a else {}
            doc = docs.get(str(o.id), {}).get("document_id")
            pol = await PolicyService(self.db, self.principal, self.request, self.inst).effective(
                card.get("batch_id"), card.get("program_id")
            )
            dream = bool(d and await elig.is_dream(d, pol.dream_ctc_threshold_paise, c))
            out.append(
                PlcOfferOut(
                    id=o.id,
                    application_id=o.application_id,
                    drive_id=a.drive_id if a else None,
                    company_id=o.company_id,
                    company_name=c.name if c else None,
                    company_tier=c.tier if c else None,
                    student_program_enrollment_id=a.student_program_enrollment_id if a else None,
                    student_name=card.get("name"),
                    registration_number=card.get("registration_number"),
                    role=o.role,
                    ctc_paise=o.ctc_paise,
                    ctc_breakup=o.ctc_breakup,
                    location=o.location,
                    offer_letter_url=o.offer_letter_url,
                    offered_on=o.offered_on,
                    joining_on=o.joining_on,
                    status=o.status,
                    is_ppo=o.is_ppo,
                    is_dream=dream,
                    document_id=uuid.UUID(doc) if doc else None,
                    created_at=o.created_at,
                )
            )
        return out

    async def _visible_stmt(self, scope: str | None = None) -> Any:
        stmt = select(PlacementOffer).join(DriveApplication, DriveApplication.id == PlacementOffer.application_id)
        stmt = stmt.where(PlacementOffer.institution_id == self.inst)
        if self.officer():
            return stmt
        if self.is_recruiter():
            return stmt.where(PlacementOffer.company_id.in_(await self.my_company_ids() or [uuid.uuid4()]))
        return stmt.where(await self.enrolment_predicate(DriveApplication.student_program_enrollment_id, scope))

    async def list_offers(self, status: str | None, drive_id: uuid.UUID | None, scope: str | None) -> list[PlcOfferOut]:
        stmt = await self._visible_stmt(scope)
        if status:
            stmt = stmt.where(PlacementOffer.status == status)
        if drive_id:
            stmt = stmt.where(DriveApplication.drive_id == drive_id)
        rows = list((await self.db.execute(stmt.order_by(PlacementOffer.created_at.desc()).limit(2000))).scalars())
        return await self.outs(rows)

    async def get(self, oid: uuid.UUID) -> PlcOfferOut:
        stmt = (await self._visible_stmt()).where(PlacementOffer.id == oid)
        o = (await self.db.execute(stmt)).scalar_one_or_none()
        if o is None:
            raise not_found("Offer")
        return (await self.outs([o]))[0]

    async def mine(self) -> list[PlcOfferOut]:
        ids = await self.my_enrollment_ids()
        return await self._for_enrolments(ids)

    async def wards(self) -> list[PlcOfferOut]:
        return await self._for_enrolments(await self.ward_enrollment_ids())

    async def _for_enrolments(self, ids: list[uuid.UUID]) -> list[PlcOfferOut]:
        rows = list(
            (
                await self.db.execute(
                    select(PlacementOffer)
                    .join(DriveApplication, DriveApplication.id == PlacementOffer.application_id)
                    .where(DriveApplication.student_program_enrollment_id.in_(ids or [uuid.uuid4()]))
                    .order_by(PlacementOffer.created_at.desc())
                )
            ).scalars()
        )
        out = await self.outs(rows)
        holding = sum(1 for o in out if o.status in HOLDING_OFFER)
        for o in out:
            if o.status == "offered" and holding:
                o.policy_warning = "You already hold an accepted offer — accepting this one needs a dream upgrade or a multi-offer policy"
        return out

    # ---- create -------------------------------------------------------------------------------------------------------
    async def create(self, body: PlcOfferCreate) -> PlcOfferOut:
        self.require_officer("offer_manage")
        a = (
            await self.db.execute(
                select(DriveApplication)
                .where(DriveApplication.id == body.application_id, DriveApplication.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if a is None:
            raise not_found("Application")
        d = (await self.db.execute(select(PlacementDrive).where(PlacementDrive.id == a.drive_id))).scalar_one()
        self.college_guard(d.college_id)
        if a.status != "selected" and not body.is_ppo:
            raise rule("Offers are made to selected candidates (or as PPO)", "NOT_SELECTED")
        if (await self.db.execute(select(PlacementOffer.id).where(PlacementOffer.application_id == a.id))).first():
            raise rule("This application already has an offer", "OFFER_EXISTS")
        o = PlacementOffer(
            institution_id=self.inst,
            application_id=a.id,
            company_id=d.company_id,
            role=body.role or d.job_role,
            ctc_paise=body.ctc_paise,
            ctc_breakup=body.ctc_breakup,
            location=body.location,
            offer_letter_url=body.offer_letter_url,
            offered_on=body.offered_on or await self.today(),
            joining_on=body.joining_on,
            status="offered",
            is_ppo=body.is_ppo,
        )
        self.db.add(o)
        if a.status != "selected":
            a.status = "selected"
        await self.db.flush()
        await self._audit("create", "placement_offer", o.id, None, body.model_dump(mode="json"))
        await self._emit(
            "placement.offer_created",
            {"offer_id": str(o.id), "application_id": str(a.id), "enrollment_id": str(a.student_program_enrollment_id)},
            "placement_offer",
            o.id,
        )
        await self._archive(o)
        company = (await self.db.execute(select(Company.name).where(Company.id == o.company_id))).scalar_one()
        card = (await self.enrollment_cards([a.student_program_enrollment_id])).get(a.student_program_enrollment_id, {})
        await self._notify("placement.offer_received", [card.get("user_id")], {"company": company}, guardians=True)
        return (await self.outs([o]))[0]

    async def _archive(self, o: PlacementOffer) -> None:
        if not await self.feature("documents.templates"):
            return
        try:
            res = await RenderService(self.db, self.principal, self.request, self.inst).render(
                "custom",
                "placement_offer",
                o.id,
                allow_multiple=True,
                variables_override={"title": "Placement offer"},
            )
        except APIError:
            return
        await self.put_meta("offer", o.id, {"document_id": str(res.issued_document_id)})

    # ---- decisions ----------------------------------------------------------------------------------------------------
    async def _lock(self, oid: uuid.UUID) -> tuple[PlacementOffer, DriveApplication]:
        o = (
            await self.db.execute(
                select(PlacementOffer)
                .where(PlacementOffer.id == oid, PlacementOffer.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if o is None:
            raise not_found("Offer")
        a = (
            await self.db.execute(
                select(DriveApplication).where(DriveApplication.id == o.application_id).with_for_update()
            )
        ).scalar_one()
        return o, a

    async def decide(self, oid: uuid.UUID, body: PlcOfferDecision) -> PlcOfferOut:
        o, a = await self._lock(oid)
        if a.student_program_enrollment_id not in await self.my_enrollment_ids():
            raise not_found("Offer")
        if o.status != "offered":
            raise rule(f"Offer is {o.status}", "OFFER_STATE")
        prof = await self.profile_of(a.student_program_enrollment_id, lock=True)
        e = await self.enrollment(a.student_program_enrollment_id)
        if body.action == "decline":
            o.status = "declined"
            a.status = "offer_declined"
            await self.db.flush()
            await self._audit("decline", "placement_offer", o.id, {"status": "offered"}, {"reason": body.reason})
            await self._emit(
                "placement.offer_declined", {"offer_id": str(o.id), "reason": body.reason}, "placement_offer", o.id
            )
            return (await self.outs([o]))[0]
        pol = await PolicyService(self.db, self.principal, self.request, self.inst).effective(e.batch_id, e.program_id)
        held = list(
            (
                await self.db.execute(
                    select(PlacementOffer)
                    .join(DriveApplication, DriveApplication.id == PlacementOffer.application_id)
                    .where(
                        DriveApplication.student_program_enrollment_id == e.id,
                        PlacementOffer.status.in_(HOLDING_OFFER),
                        PlacementOffer.id != o.id,
                    )
                    .with_for_update()
                )
            ).scalars()
        )
        rules = pol.rules or {}
        if not rules.get("internship_ppo_counts_as_offer", True):
            held = [h for h in held if not h.is_ppo]
        upgraded: PlacementOffer | None = None
        if len(held) >= (pol.max_offers or 1):
            d = (
                await self.db.execute(
                    select(PlacementDrive)
                    .join(DriveApplication, DriveApplication.drive_id == PlacementDrive.id)
                    .where(DriveApplication.id == a.id)
                )
            ).scalar_one()
            elig = EligibilityService(self.db, self.principal, self.request, self.inst)
            dream = await elig.is_dream(d, pol.dream_ctc_threshold_paise) or (
                pol.dream_ctc_threshold_paise is not None and o.ctc_paise >= pol.dream_ctc_threshold_paise
            )
            prev = max(held, key=lambda h: h.ctc_paise)
            if not (pol.allow_upgrade_if_dream and dream and o.ctc_paise > prev.ctc_paise):
                raise rule(f"Policy allows {pol.max_offers} accepted offer(s)", "MAX_OFFERS", max_offers=pol.max_offers)
            upgraded = min(held, key=lambda h: h.ctc_paise)
            upgraded.status = "declined"
            prev_app = (
                await self.db.execute(select(DriveApplication).where(DriveApplication.id == upgraded.application_id))
            ).scalar_one()
            prev_app.status = "offer_declined"
            await self.put_meta(
                "offer", upgraded.id, {**await self.meta("offer", upgraded.id), "declined_reason": "dream_upgrade"}
            )
            await self._emit(
                "placement.offer_declined",
                {"offer_id": str(upgraded.id), "reason": "dream_upgrade", "upgraded_to": str(o.id)},
                "placement_offer",
                upgraded.id,
            )
        o.status = "accepted"
        a.status = "offer_accepted"
        holding_after = len(held) - (1 if upgraded else 0) + 1
        prof.placement_status = "multiple" if holding_after > 1 else "placed"
        await self.db.flush()
        await self._audit(
            "accept",
            "placement_offer",
            o.id,
            {"status": "offered"},
            {"upgraded_from": str(upgraded.id) if upgraded else None, "placement_status": prof.placement_status},
        )
        await self._emit(
            "placement.offer_accepted",
            {"offer_id": str(o.id), "enrollment_id": str(e.id), "ctc_paise": o.ctc_paise},
            "placement_offer",
            o.id,
        )
        return (await self.outs([o]))[0]

    async def set_status(self, oid: uuid.UUID, body: PlcOfferStatusUpdate) -> PlcOfferOut:
        self.require_officer("offer_manage")
        o, a = await self._lock(oid)
        old = o.status
        if body.status == "revoked":
            if o.status in ("revoked", "declined"):
                raise rule(f"Offer is {o.status}", "OFFER_STATE")
        elif o.status not in ("accepted", "joined", "not_joined"):
            raise rule("Joining status applies to accepted offers", "OFFER_STATE")
        elif body.status == "joined" and o.joining_on and o.joining_on > await self.today():
            raise rule("Joining date has not been reached", "BEFORE_JOINING")
        o.status = body.status
        if body.status in ("revoked", "not_joined") and old in HOLDING_OFFER:
            await self._recompute_status(a.student_program_enrollment_id)
        await self.db.flush()
        await self._audit(body.status, "placement_offer", o.id, {"status": old}, {"reason": body.reason})
        await self._emit(
            f"placement.offer_{body.status}", {"offer_id": str(o.id), "reason": body.reason}, "placement_offer", o.id
        )
        if body.status == "not_joined":
            # an accepted offer the student walked away from counts toward ``offer_decline_after_accept``
            limit = int((await self._rules()).get("offer_decline_after_accept") or 0)
            n = (
                await self.db.execute(
                    select(func.count())
                    .select_from(PlacementOffer)
                    .join(DriveApplication, DriveApplication.id == PlacementOffer.application_id)
                    .where(
                        DriveApplication.student_program_enrollment_id == a.student_program_enrollment_id,
                        PlacementOffer.status == "not_joined",
                    )
                )
            ).scalar_one()
            if limit and n >= limit:
                await self._blacklist(
                    a.student_program_enrollment_id,
                    f"Declined {n} accepted offer(s)",
                    None,
                    "offer_decline_after_accept",
                )
        return (await self.outs([o]))[0]

    async def _recompute_status(self, enrollment_id: uuid.UUID) -> None:
        prof = await self.profile_of(enrollment_id, lock=True)
        n = (
            await self.db.execute(
                select(func.count())
                .select_from(PlacementOffer)
                .join(DriveApplication, DriveApplication.id == PlacementOffer.application_id)
                .where(
                    DriveApplication.student_program_enrollment_id == enrollment_id,
                    PlacementOffer.status.in_(HOLDING_OFFER),
                )
            )
        ).scalar_one()
        if prof.is_opted_out:
            prof.placement_status = "opted_out"
        else:
            prof.placement_status = "multiple" if n > 1 else ("placed" if n == 1 else "unplaced")

    # ---- recruiter-submitted offers -----------------------------------------------------------------------------------
    async def submit_pending(self, drive_id: uuid.UUID, body: Any) -> PlcPendingOffer:
        a = (
            await self.db.execute(
                select(DriveApplication).where(
                    DriveApplication.id == body.application_id, DriveApplication.drive_id == drive_id
                )
            )
        ).scalar_one_or_none()
        if a is None:
            raise not_found("Application")
        if a.status != "selected":
            raise rule("Offers are made to selected candidates", "NOT_SELECTED")
        meta = await self.meta("drive", drive_id)
        pending = dict(meta.get("pending_offers") or {})
        pending[str(a.id)] = {
            "offer": body.model_dump(mode="json"),
            "submitted_by": str(self.actor_id),
            "submitted_at": now_utc().isoformat(),
        }
        meta["pending_offers"] = pending
        await self.put_meta("drive", drive_id, meta)
        await self._audit("submit_offer", "drive_application", a.id, None, body.model_dump(mode="json"))
        card = (await self.enrollment_cards([a.student_program_enrollment_id])).get(a.student_program_enrollment_id, {})
        return PlcPendingOffer(
            application_id=a.id,
            drive_id=drive_id,
            student_name=None,
            registration_number=card.get("registration_number"),
            submitted_by=self.actor_id,
            submitted_at=pending[str(a.id)]["submitted_at"],
            offer=pending[str(a.id)]["offer"],
        )

    async def pending(self) -> list[PlcPendingOffer]:
        self.require_officer("offer_manage", "view_all")
        out: list[PlcPendingOffer] = []
        metas = await self.metas("drive")
        app_ids = [uuid.UUID(k) for m in metas.values() for k in (m.get("pending_offers") or {})]
        cards: dict[uuid.UUID, dict[str, Any]] = {}
        if app_ids:
            apps = {
                a.id: a
                for a in (
                    await self.db.execute(select(DriveApplication).where(DriveApplication.id.in_(app_ids)))
                ).scalars()
            }
            cards = await self.enrollment_cards([a.student_program_enrollment_id for a in apps.values()])
        else:
            apps = {}
        for did, m in metas.items():
            for aid, p in (m.get("pending_offers") or {}).items():
                a = apps.get(uuid.UUID(aid))
                card = cards.get(a.student_program_enrollment_id, {}) if a else {}
                out.append(
                    PlcPendingOffer(
                        application_id=uuid.UUID(aid),
                        drive_id=uuid.UUID(did),
                        student_name=card.get("name"),
                        registration_number=card.get("registration_number"),
                        submitted_by=(
                            uuid.UUID(p["submitted_by"]) if p.get("submitted_by") not in (None, "None") else None
                        ),
                        submitted_at=p.get("submitted_at"),
                        offer=p.get("offer") or {},
                    )
                )
        return out

    async def confirm_pending(self, application_id: uuid.UUID) -> PlcOfferOut:
        self.require_officer("offer_manage")
        a = (
            await self.db.execute(select(DriveApplication).where(DriveApplication.id == application_id))
        ).scalar_one_or_none()
        if a is None:
            raise not_found("Application")
        meta = await self.meta("drive", a.drive_id)
        pending = dict(meta.get("pending_offers") or {})
        p = pending.pop(str(a.id), None)
        if p is None:
            raise not_found("Pending offer")
        out = await self.create(PlcOfferCreate.model_validate({**p["offer"], "application_id": str(a.id)}))
        meta["pending_offers"] = pending
        await self.put_meta("drive", a.drive_id, meta)
        return out

    # ---- blacklist ----------------------------------------------------------------------------------------------------
    async def blacklist(self, body: PlcBlacklistRequest) -> PlcBlacklistOut:
        self.require_officer("manage")
        e = await self.enrollment(body.enrollment_id)
        await self._blacklist(e.id, body.reason, body.until, "manual", violation=body.open_discipline_case)
        return (await self.blacklisted([e.id]))[0]

    async def _blacklist(
        self, enrollment_id: uuid.UUID, reason: str, until: date | None, source: str, *, violation: bool = True
    ) -> None:
        prof = await self.profile_of(enrollment_id, lock=True)
        if prof.is_blacklisted and source != "discipline":
            return
        prof.is_blacklisted, prof.blacklist_reason = True, reason[:2000]
        m = await self.meta("blacklist", enrollment_id)
        hist = list(m.get("history") or [])
        hist.append({"at": now_utc().isoformat(), "action": "blacklisted", "reason": reason, "source": source})
        await self.put_meta(
            "blacklist",
            enrollment_id,
            {
                "reason": reason,
                "until": until.isoformat() if until else None,
                "source": source,
                "at": now_utc().isoformat(),
                "by": str(self.actor_id) if self.actor_id else None,
                "history": hist,
            },
        )
        await self.db.flush()
        await self._audit("blacklist", "student_placement_profile", prof.id, None, {"reason": reason, "source": source})
        await self._emit(
            "placement.blacklisted",
            {"enrollment_id": str(enrollment_id), "reason": reason, "source": source},
            "student_placement_profile",
            prof.id,
        )
        if violation and source != "discipline":
            await self._emit(
                "placement.policy_violation",
                {"id": str(prof.id), "enrollment_id": str(enrollment_id), "reason": reason, "rule": source},
                "student_placement_profile",
                prof.id,
            )
        card = (await self.enrollment_cards([enrollment_id])).get(enrollment_id, {})
        await self._notify("placement.blacklisted", [card.get("user_id")], {"reason": reason})

    async def unblacklist(self, enrollment_id: uuid.UUID, reason: str | None = None) -> PlcBlacklistOut:
        self.require_officer("manage")
        prof = await self.profile_of(enrollment_id, lock=True, create=False)
        if prof is None or not prof.is_blacklisted:
            raise not_found("Blacklist entry")
        await self._lift(prof, reason or "lifted by officer")
        return (await self.blacklisted([enrollment_id], include_lifted=True))[0]

    async def _lift(self, prof: StudentPlacementProfile, reason: str) -> None:
        old = prof.blacklist_reason
        prof.is_blacklisted, prof.blacklist_reason = False, None
        m = await self.meta("blacklist", prof.student_program_enrollment_id)
        hist = list(m.get("history") or [])
        hist.append({"at": now_utc().isoformat(), "action": "unblacklisted", "reason": reason})
        m.update(history=hist, lifted_at=now_utc().isoformat(), until=None)
        await self.put_meta("blacklist", prof.student_program_enrollment_id, m)
        await self.db.flush()
        await self._audit("unblacklist", "student_placement_profile", prof.id, {"reason": old}, {"reason": reason})
        await self._emit(
            "placement.unblacklisted",
            {"enrollment_id": str(prof.student_program_enrollment_id), "reason": reason},
            "student_placement_profile",
            prof.id,
        )

    async def blacklisted(
        self, ids: list[uuid.UUID] | None = None, *, include_lifted: bool = False
    ) -> list[PlcBlacklistOut]:
        stmt = select(StudentPlacementProfile).where(StudentPlacementProfile.institution_id == self.inst)
        if ids is not None:
            stmt = stmt.where(StudentPlacementProfile.student_program_enrollment_id.in_(ids))
        if not include_lifted:
            stmt = stmt.where(StudentPlacementProfile.is_blacklisted.is_(True))
        rows = list((await self.db.execute(stmt)).scalars())
        cards = await self.enrollment_cards([p.student_program_enrollment_id for p in rows])
        metas = await self.metas("blacklist", [str(p.student_program_enrollment_id) for p in rows])
        out = []
        for p in rows:
            m = metas.get(str(p.student_program_enrollment_id), {})
            card = cards.get(p.student_program_enrollment_id, {})
            out.append(
                PlcBlacklistOut(
                    student_program_enrollment_id=p.student_program_enrollment_id,
                    student_name=card.get("name"),
                    registration_number=card.get("registration_number"),
                    reason=p.blacklist_reason or m.get("reason"),
                    until=m.get("until"),
                    source=m.get("source"),
                    at=m.get("at"),
                )
            )
        return out

    async def list_blacklist(self) -> list[PlcBlacklistOut]:
        self.require_officer("manage", "view_all")
        return await self.blacklisted()

    async def _rules(self) -> dict[str, int]:
        r = await self.setting("placement", "blacklist_rules")
        return {**BLACKLIST_RULES, **(r if isinstance(r, dict) else {})}

    async def apply_no_show_rule(self, enrollment_ids: list[uuid.UUID]) -> list[str]:
        """Absent after shortlist N times (across drives) → automatic blacklist."""
        limit = int((await self._rules()).get("no_show_after_shortlist") or 0)
        if limit <= 0:
            return []
        out: list[str] = []
        for eid in set(enrollment_ids):
            n = (
                await self.db.execute(
                    select(func.count())
                    .select_from(DriveRoundResult)
                    .join(DriveApplication, DriveApplication.id == DriveRoundResult.application_id)
                    .where(DriveApplication.student_program_enrollment_id == eid, DriveRoundResult.status == "absent")
                )
            ).scalar_one()
            if n >= limit:
                await self._blacklist(eid, f"Absent after shortlist {n} time(s)", None, "no_show_after_shortlist")
                out.append(str(eid))
        return out

    async def blacklist_expiry(self) -> int:
        """Beat (daily): lift blacklists whose ``until`` has passed."""
        today = await self.today()
        n = 0
        metas = await self.metas("blacklist")
        for eid, m in metas.items():
            until = m.get("until")
            if not until or date.fromisoformat(until) >= today:
                continue
            prof = await self.profile_of(uuid.UUID(eid), lock=True, create=False)
            if prof is not None and prof.is_blacklisted:
                await self._lift(prof, "blacklist period ended")
                n += 1
        return n

    async def debar_from_discipline(self, enrollment_id: uuid.UUID, case_id: str | None, until: Any) -> None:
        """Consumer of ``discipline.sanction_applied`` (``type = debar_placement``)."""
        until_d = None
        if until:
            try:
                until_d = date.fromisoformat(str(until)[:10])
            except ValueError:
                until_d = None
        await self._blacklist(
            enrollment_id,
            f"Debarred from placements (disciplinary case {case_id or ''})".strip(),
            until_d,
            "discipline",
            violation=False,
        )

    # ---- Beat ---------------------------------------------------------------------------------------------------------
    async def offer_reminders(self) -> int:
        """Daily: undecided offers older than 3 days → reminder to the student."""
        cutoff = await self.today() - timedelta(days=3)
        rows = (
            await self.db.execute(
                select(PlacementOffer, DriveApplication.student_program_enrollment_id, Company.name)
                .join(DriveApplication, DriveApplication.id == PlacementOffer.application_id)
                .join(Company, Company.id == PlacementOffer.company_id)
                .where(
                    PlacementOffer.institution_id == self.inst,
                    PlacementOffer.status == "offered",
                    PlacementOffer.offered_on <= cutoff,
                )
            )
        ).all()
        cards = await self.enrollment_cards([r[1] for r in rows])
        for _, eid, company in rows:
            await self._notify("placement.offer_reminder", [cards.get(eid, {}).get("user_id")], {"company": company})
        return len(rows)

    async def joining_followup(self) -> int:
        """Weekly: accepted offers past the joining date without a joined / not-joined update → officers."""
        today = await self.today()
        n = (
            await self.db.execute(
                select(func.count())
                .select_from(PlacementOffer)
                .where(
                    PlacementOffer.institution_id == self.inst,
                    PlacementOffer.status == "accepted",
                    PlacementOffer.joining_on.is_not(None),
                    PlacementOffer.joining_on < today,
                )
            )
        ).scalar_one()
        if n:
            await self._notify(
                "placement.offer_reminder",
                [],
                {"company": f"{n} offer(s) awaiting joining confirmation"},
                audience={"roles": ["placement_officer"]},
            )
        return int(n)

    # ---- feedback -----------------------------------------------------------------------------------------------------
    async def feedback(self, drive_id: uuid.UUID, body: PlcFeedbackIn) -> PlcFeedbackOut:
        if not (self.officer() or self.can("placement", "recruiter")):
            raise forbidden()
        d = (
            await self.db.execute(
                select(PlacementDrive).where(PlacementDrive.id == drive_id, PlacementDrive.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if d is None or (self.is_recruiter() and d.company_id not in await self.my_company_ids()):
            raise not_found("Drive")
        f = CompanyFeedback(
            institution_id=self.inst,
            drive_id=d.id,
            ratings=body.ratings,
            remarks=body.remarks,
            submitted_by=self.actor_id,
        )
        self.db.add(f)
        await self.db.flush()
        await self._audit("feedback", "placement_drive", d.id, None, body.model_dump(mode="json"))
        return PlcFeedbackOut(
            id=f.id,
            drive_id=d.id,
            drive_title=d.title,
            ratings=f.ratings or {},
            remarks=f.remarks,
            submitted_by=f.submitted_by,
            submitted_at=f.submitted_at,
        )


@register_resolver("placement_offer")
async def _offer_ctx(svc: RenderService, oid: uuid.UUID) -> tuple[dict[str, Any], str | None, uuid.UUID | None]:
    o = (await svc.db.execute(select(PlacementOffer).where(PlacementOffer.id == oid))).scalar_one()
    a = (await svc.db.execute(select(DriveApplication).where(DriveApplication.id == o.application_id))).scalar_one()
    company = (await svc.db.execute(select(Company.name).where(Company.id == o.company_id))).scalar_one()
    ctx, ptype, pid = await svc.enrolment_ctx(a.student_program_enrollment_id)
    name = (ctx.get("student") or {}).get("name", "")
    ctx["offer"] = {
        "company": company,
        "role": o.role,
        "ctc": ctc_lpa(o.ctc_paise),
        "joining_on": str(o.joining_on or ""),
    }
    ctx["title"] = "Placement offer"
    ctx["body"] = (
        f"This records that {name} has received an offer from {company} for the role of {o.role or '—'} with a CTC of "
        f"{ctc_lpa(o.ctc_paise)}{' (pre-placement offer)' if o.is_ppo else ''}"
        f"{f', joining on {o.joining_on:%d-%m-%Y}' if o.joining_on else ''}. The company's offer letter is kept on file."
    )
    return ctx, ptype, pid


async def enrolment_of_offer(db: Any, oid: uuid.UUID) -> uuid.UUID | None:
    eid: uuid.UUID | None = (
        await db.execute(
            select(StudentProgramEnrollment.id)
            .join(DriveApplication, DriveApplication.student_program_enrollment_id == StudentProgramEnrollment.id)
            .join(PlacementOffer, PlacementOffer.application_id == DriveApplication.id)
            .where(PlacementOffer.id == oid)
        )
    ).scalar_one_or_none()
    return eid
