"""Alumni stats — Prompts/29 §29.6 ``stats_service`` and ``requests_bridge_service``.

Stats: verified / claimed %, employed % (a current employment row), higher-studies % (side-store
``higher_studies``), consent, mentors / recruiters, geographic spread, donations by campaign / financial year, alumni
event participation and job posts — for ``alumni:view_all`` holders (IQAC, registrar, coordinator, placement officer)
and published as ``alumni.*`` metrics for NAAC 5.4.x (Phase 32 reads ``alumni.stats_published``).

Requests bridge: alumni transcript / certificate requests run on the Phase 16 / 26 endpoints under the ``alumni``
role; this guard (called by those services through ``require_verified_alumni``) refuses unverified alumni with 403
``VERIFICATION_REQUIRED`` and resolves the alumni fee rule.
"""

import uuid
from collections import Counter
from typing import Any

from sqlalchemy import func, select

from app.models.alumni import (
    AlumniEmploymentHistory,
    AlumniEvent,
    AlumniJob,
    AlumniProfile,
    Donation,
    FundraisingCampaign,
)
from app.models.students import Student
from app.schemas.alumni import AlumniStats
from app.services.alumni.common import AlumniBase, financial_year, forbidden, rule


def _pct(n: int, d: int) -> float:
    return round(100 * n / d, 1) if d else 0.0


class AlumniStatsService(AlumniBase):
    async def stats(
        self, batch: int | None = None, program_id: uuid.UUID | None = None, college_id: uuid.UUID | None = None
    ) -> AlumniStats:
        if not (self.can("alumni", "view_all") or self.can("alumni", "manage")):
            raise forbidden("alumni:view_all required")
        stmt = select(AlumniProfile).where(AlumniProfile.institution_id == self.inst, await self.profile_predicate())
        if batch:
            stmt = stmt.where(AlumniProfile.graduation_year == batch)
        if program_id:
            stmt = stmt.where(AlumniProfile.program_id == program_id)
        if college_id:
            stmt = stmt.where(AlumniProfile.student_id.in_(select(Student.id).where(Student.college_id == college_id)))
        rows = list((await self.db.execute(stmt)).scalars())
        ids = [a.id for a in rows]
        metas = await self.metas("profile", [str(i) for i in ids]) if ids else {}
        employed: set[uuid.UUID] = set()
        if ids:
            employed = {
                r[0]
                for r in (
                    await self.db.execute(
                        select(AlumniEmploymentHistory.alumni_id)
                        .where(AlumniEmploymentHistory.alumni_id.in_(ids), AlumniEmploymentHistory.is_current.is_(True))
                        .distinct()
                    )
                ).all()
            }
        employed |= {a.id for a in rows if a.current_company}
        claimed = sum(1 for a in rows if (metas.get(str(a.id)) or {}).get("claim_status") in ("claimed", "verified"))
        higher = sum(1 for a in rows if (metas.get(str(a.id)) or {}).get("higher_studies"))
        total = len(rows)
        out = AlumniStats(
            total=total,
            by_batch=dict(sorted(Counter(str(a.graduation_year or "—") for a in rows).items())),
            verified_pct=_pct(sum(1 for a in rows if a.is_verified), total),
            claimed_pct=_pct(claimed, total),
            employed_pct=_pct(len(employed), total),
            higher_studies_pct=_pct(higher, total),
            consent_contact_pct=_pct(sum(1 for a in rows if a.consent_contact), total),
            mentors=sum(1 for a in rows if a.willing_to_mentor),
            recruiters=sum(1 for a in rows if a.willing_to_recruit),
            by_city=dict(Counter(a.city for a in rows if a.city).most_common(15)),
            by_country=dict(Counter(a.country for a in rows if a.country).most_common(10)),
        )
        if self.can("fundraising", "view_all") or self.can("fundraising", "manage") or self.can("alumni", "manage"):
            drows = (
                await self.db.execute(
                    select(Donation.amount_paise, Donation.on_date, FundraisingCampaign.title)
                    .outerjoin(FundraisingCampaign, FundraisingCampaign.id == Donation.campaign_id)
                    .where(Donation.institution_id == self.inst)
                )
            ).all()
            by_c: Counter[str] = Counter()
            by_y: Counter[str] = Counter()
            for amt, on, title in drows:
                by_c[title or "General fund"] += int(amt)
                by_y[financial_year(on)] += int(amt)
            out.donations_total_paise = sum(by_c.values())
            out.donations_by_campaign = dict(by_c)
            out.donations_by_year = dict(sorted(by_y.items()))
        out.events = int(
            (
                await self.db.execute(
                    select(func.count()).select_from(AlumniEvent).where(AlumniEvent.institution_id == self.inst)
                )
            ).scalar_one()
        )
        out.event_participation = int(
            (
                await self.db.execute(
                    select(func.coalesce(func.sum(AlumniEvent.registrations_count), 0)).where(
                        AlumniEvent.institution_id == self.inst
                    )
                )
            ).scalar_one()
        )
        out.jobs_posted = int(
            (
                await self.db.execute(
                    select(func.count()).select_from(AlumniJob).where(AlumniJob.institution_id == self.inst)
                )
            ).scalar_one()
        )
        return out

    async def publish_metrics(self) -> dict[str, Any]:
        s = await self.stats()
        payload = {
            "alumni.total": s.total,
            "alumni.verified_pct": s.verified_pct,
            "alumni.employed_pct": s.employed_pct,
            "alumni.higher_studies_pct": s.higher_studies_pct,
            "alumni.mentors": s.mentors,
            "alumni.events": s.events,
            "alumni.event_participation": s.event_participation,
            "alumni.donations_total_paise": s.donations_total_paise,
        }
        await self._emit("alumni.stats_published", {"metrics": payload}, "alumni_profile", None)
        return payload


class RequestsBridge(AlumniBase):
    """Phase 16 / 26 hook: alumni requests need a verified profile; the alumni fee rule applies."""

    async def require_verified_alumni(self) -> AlumniProfile | None:
        a = await self.my_profile()
        if a is None:
            return None  # not an alumnus — the caller's own rules apply
        if not a.is_verified:
            raise rule("Your alumni profile is not verified yet", "VERIFICATION_REQUIRED", 403)
        return a

    async def fee_paise(self, template_type: str, default: int) -> int:
        rules = await self.setting("documents", "request_rules")
        r = (rules or {}).get(template_type) if isinstance(rules, dict) else None
        return int((r or {}).get("alumni_fee_paise", default)) if isinstance(r, dict) else default
