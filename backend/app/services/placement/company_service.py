"""Companies — Prompts/28 §28.6 ``company_service`` ({placement.core}; invitations {placement.recruiter_portal}).

Company master with tier, contacts, MoU link (kept in ``contacts`` meta until Phase 30 ``mous``), blacklisting (no new
drives for a blacklisted company), recruiter invitations — an email invite creates (or reuses) an ``external`` user
with the ``recruiter`` role at ``self`` scope and binds it through ``companies.recruiter_user_ids`` — and the company
page with history (drives, hires, feedback average).
"""

import secrets
import uuid
from typing import Any

from sqlalchemy import func, select

from app.models.placement import Company, CompanyFeedback, DriveApplication, PlacementDrive, PlacementOffer
from app.models.platform import Role, User, UserRole
from app.schemas.placement import (
    PlcCompanyBlacklist,
    PlcCompanyIn,
    PlcCompanyOut,
    PlcFeedbackOut,
    PlcRecruiterInvite,
    PlcRecruiterInviteOut,
)
from app.services.placement.common import PlacementBase, forbidden, not_found, rule


class CompanyService(PlacementBase):
    async def _get(self, cid: uuid.UUID) -> Company:
        c = (
            await self.db.execute(
                select(Company).where(
                    Company.id == cid, Company.institution_id == self.inst, Company.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()
        if c is None:
            raise not_found("Company")
        if self.is_recruiter() and cid not in await self.my_company_ids():
            raise not_found("Company")
        return c

    async def _stats(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
        out: dict[uuid.UUID, dict[str, Any]] = {i: {"drives": 0, "hires": 0, "feedback_avg": None} for i in ids}
        if not ids:
            return out
        for cid, n in (
            await self.db.execute(
                select(PlacementDrive.company_id, func.count())
                .where(PlacementDrive.company_id.in_(ids))
                .group_by(PlacementDrive.company_id)
            )
        ).all():
            out[cid]["drives"] = int(n)
        for cid, n in (
            await self.db.execute(
                select(PlacementOffer.company_id, func.count())
                .where(PlacementOffer.company_id.in_(ids), PlacementOffer.status.in_(("accepted", "joined")))
                .group_by(PlacementOffer.company_id)
            )
        ).all():
            out[cid]["hires"] = int(n)
        fb = await self.db.execute(
            select(PlacementDrive.company_id, CompanyFeedback.ratings)
            .join(CompanyFeedback, CompanyFeedback.drive_id == PlacementDrive.id)
            .where(PlacementDrive.company_id.in_(ids))
        )
        sums: dict[uuid.UUID, list[float]] = {}
        for cid, ratings in fb.all():
            vals = [float(v) for v in (ratings or {}).values() if isinstance(v, int | float)]
            if vals:
                sums.setdefault(cid, []).append(sum(vals) / len(vals))
        for cid, vals in sums.items():
            out[cid]["feedback_avg"] = round(sum(vals) / len(vals), 2)
        return out

    def _out(self, c: Company, st: dict[str, Any]) -> PlcCompanyOut:
        return PlcCompanyOut(
            id=c.id,
            name=c.name,
            sector=c.sector,
            website=c.website,
            hq_city=c.hq_city,
            tier=c.tier,
            contacts=list(c.contacts or []),
            recruiter_user_ids=list(c.recruiter_user_ids or []) if self.officer() else [],
            is_blacklisted=c.is_blacklisted,
            notes=c.notes if self.officer() else None,
            logo_url=c.logo_url,
            is_active=c.is_active,
            **st,
        )

    async def list_companies(self, q: str | None, tier: str | None, blacklisted: bool | None) -> list[PlcCompanyOut]:
        stmt = select(Company).where(Company.institution_id == self.inst, Company.deleted_at.is_(None))
        if self.is_recruiter():
            stmt = stmt.where(Company.id.in_(await self.my_company_ids() or [uuid.uuid4()]))
        if q:
            stmt = stmt.where(Company.name.ilike(f"%{q}%"))
        if tier:
            stmt = stmt.where(Company.tier == tier)
        if blacklisted is not None:
            stmt = stmt.where(Company.is_blacklisted.is_(blacklisted))
        rows = list((await self.db.execute(stmt.order_by(Company.name).limit(1000))).scalars())
        st = await self._stats([c.id for c in rows])
        return [self._out(c, st[c.id]) for c in rows]

    async def get(self, cid: uuid.UUID) -> PlcCompanyOut:
        c = await self._get(cid)
        out = self._out(c, (await self._stats([c.id]))[c.id])
        drives = (
            await self.db.execute(
                select(PlacementDrive)
                .where(PlacementDrive.company_id == c.id)
                .order_by(PlacementDrive.created_at.desc())
            )
        ).scalars()
        hist = []
        for d in drives:
            apps = (
                await self.db.execute(
                    select(func.count()).select_from(DriveApplication).where(DriveApplication.drive_id == d.id)
                )
            ).scalar_one()
            hires = (
                await self.db.execute(
                    select(func.count())
                    .select_from(PlacementOffer)
                    .join(DriveApplication, DriveApplication.id == PlacementOffer.application_id)
                    .where(DriveApplication.drive_id == d.id, PlacementOffer.status.in_(("accepted", "joined")))
                )
            ).scalar_one()
            hist.append(
                {
                    "drive_id": str(d.id),
                    "title": d.title,
                    "status": d.status,
                    "drive_on": d.drive_on.isoformat() if d.drive_on else None,
                    "applications": int(apps),
                    "hires": int(hires),
                    "ctc_min_paise": d.ctc_min_paise,
                }
            )
        out.history = hist
        return out

    async def create(self, body: PlcCompanyIn) -> PlcCompanyOut:
        self.require_officer("manage")
        dup = (
            await self.db.execute(
                select(Company.id).where(
                    Company.institution_id == self.inst, func.lower(Company.name) == body.name.lower()
                )
            )
        ).first()
        if dup is not None:
            raise rule("A company with this name exists", "DUPLICATE_COMPANY")
        data = body.model_dump(mode="json", exclude={"mou_id"})
        c = Company(institution_id=self.inst, recruiter_user_ids=[], **data)
        if body.mou_id:
            c.notes = ((c.notes or "") + f"\nMoU: {body.mou_id}").strip()
        self.db.add(c)
        await self.db.flush()
        await self._audit("create", "company", c.id, None, data)
        await self._emit("placement.company_created", {"company_id": str(c.id), "name": c.name}, "company", c.id)
        return self._out(c, {"drives": 0, "hires": 0, "feedback_avg": None})

    async def update(self, cid: uuid.UUID, body: PlcCompanyIn) -> PlcCompanyOut:
        self.require_officer("manage")
        c = await self._get(cid)
        old = {"name": c.name, "tier": c.tier, "contacts": c.contacts}
        data = body.model_dump(mode="json", exclude={"mou_id"})
        for k, v in data.items():
            setattr(c, k, v)
        await self.db.flush()
        await self._audit("update", "company", c.id, old, data)
        return self._out(c, (await self._stats([c.id]))[c.id])

    async def blacklist(self, cid: uuid.UUID, body: PlcCompanyBlacklist) -> PlcCompanyOut:
        self.require_officer("manage")
        c = await self._get(cid)
        old = c.is_blacklisted
        c.is_blacklisted = body.blacklisted
        c.notes = ((c.notes or "") + f"\n[{'blacklisted' if body.blacklisted else 'restored'}] {body.reason}").strip()
        await self.db.flush()
        await self._audit("blacklist", "company", c.id, {"is_blacklisted": old}, body.model_dump())
        if body.blacklisted:
            await self._emit(
                "placement.company_blacklisted", {"company_id": str(c.id), "reason": body.reason}, "company", c.id
            )
        return self._out(c, (await self._stats([c.id]))[c.id])

    async def invite(self, cid: uuid.UUID, body: PlcRecruiterInvite) -> PlcRecruiterInviteOut:
        """Account with the ``recruiter`` role bound to the company (idempotent per email)."""
        from app.core.security import hash_password

        self.require_officer("manage")
        await self.require_feature("placement.recruiter_portal")
        c = await self._get(cid)
        if c.is_blacklisted:
            raise rule("Company is blacklisted", "COMPANY_BLACKLISTED")
        email = body.email.strip().lower()
        user = (
            await self.db.execute(select(User).where(User.institution_id == self.inst, func.lower(User.email) == email))
        ).scalar_one_or_none()
        created = False
        if user is None:
            user = User(
                institution_id=self.inst,
                username=email[:100],
                email=email,
                phone=body.phone,
                display_name=body.name[:200],
                user_type="external",
                password_hash=hash_password(secrets.token_urlsafe(24)),
                is_verified=True,
                must_change_password=True,
            )
            self.db.add(user)
            await self.db.flush()
            created = True
        elif getattr(user, "user_type", None) not in ("external", None):
            raise forbidden("An institution user cannot be bound as a recruiter")
        role = (
            await self.db.execute(
                select(Role).where(
                    Role.institution_id == self.inst, Role.slug == "recruiter", Role.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()
        if (
            role is not None
            and (
                await self.db.execute(
                    select(UserRole.id).where(UserRole.user_id == user.id, UserRole.role_id == role.id)
                )
            ).first()
            is None
        ):
            self.db.add(
                UserRole(institution_id=self.inst, user_id=user.id, role_id=role.id, scope_type="self", scope_id=None)
            )
        ids = [str(x) for x in (c.recruiter_user_ids or [])]
        if str(user.id) not in ids:
            c.recruiter_user_ids = [*ids, str(user.id)]
        await self.db.flush()
        await self._audit("invite_recruiter", "company", c.id, None, {"user_id": str(user.id), "email": email})
        await self._emit(
            "placement.recruiter_invited", {"company_id": str(c.id), "user_id": str(user.id)}, "company", c.id
        )
        inst = await self.institution()
        await self._notify(
            "recruiter.invited",
            [user.id],
            {"company": c.name, "institution": inst.name, "username": user.username},
            audience={
                "user_ids": [str(user.id)],
                "direct_contacts": [{"to": email, "channel": "email", "name": body.name}],
            },
        )
        return PlcRecruiterInviteOut(user_id=user.id, username=user.username, company_id=c.id, created=created)

    async def feedback(self, cid: uuid.UUID) -> list[PlcFeedbackOut]:
        c = await self._get(cid)
        rows = (
            await self.db.execute(
                select(CompanyFeedback, PlacementDrive.title)
                .join(PlacementDrive, PlacementDrive.id == CompanyFeedback.drive_id)
                .where(PlacementDrive.company_id == c.id)
                .order_by(CompanyFeedback.submitted_at.desc())
            )
        ).all()
        return [
            PlcFeedbackOut(
                id=f.id,
                drive_id=f.drive_id,
                drive_title=t,
                ratings=f.ratings or {},
                remarks=f.remarks,
                submitted_by=f.submitted_by,
                submitted_at=f.submitted_at,
            )
            for f, t in rows
        ]
