"""Health centre — Prompts/25 §25.6 ``health_service`` ({facilities.health_centre}).

Confidential visits are recorded and read only by ``health:record`` holders (medical officer / nurse); a person sees
their own visits (with diagnosis); everyone else — including the auditor and HODs — gets 403 on visit detail. Counts
only (``GET /health/stats``) for ``health:view_all`` / ``manage`` holders other than the auditor. Every read of a
confidential record by a medical officer is audited (``health.read``). Medical certificates are rendered as a PDF with
a verification link (Phase 26 custom ``medical_certificate`` template later) and recorded in ``facilities_meta``
(``health:<visit id>``) so Phase 11 condonation can cite the ``document_id``. Insurance policies per person with expiry
reminders (weekly Beat).
"""

import uuid
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from sqlalchemy import func, literal_column, select

from app.core.errors import APIError
from app.models.facilities import CounsellingAppointment, HealthVisit, InsurancePolicy
from app.schemas.facilities import (
    HealthCertificateRequest,
    HealthStats,
    HealthVisitIn,
    HealthVisitOut,
    InsurancePolicyIn,
    InsurancePolicyOut,
)
from app.services.facilities.common import FacilitiesBase, forbidden, is_auditor, not_found, now_utc


class HealthService(FacilitiesBase):
    audit_module = "health"
    module = "health"

    def recorder(self) -> bool:
        return self.can("health", "record")

    def _counts_reader(self) -> bool:
        if is_auditor(self.principal):
            return False
        return self.recorder() or self.can("health", "view_all") or self.can("health", "manage")

    async def outs(self, rows: Sequence[HealthVisit]) -> list[HealthVisitOut]:
        names = await self.person_names([(r.person_type, r.person_id) for r in rows])
        metas = await self.metas("health", [r.id for r in rows])
        out = []
        for r in rows:
            o = HealthVisitOut.model_validate(r)
            o.person_name = names.get(r.person_id)
            o.certificate_issued = bool(metas.get(str(r.id), {}).get("certificate"))
            out.append(o)
        return out

    async def record(self, body: HealthVisitIn) -> HealthVisitOut:
        if not self.recorder():
            raise forbidden("health:record required")
        r = HealthVisit(
            institution_id=self.inst,
            person_type=body.person_type,
            person_id=body.person_id,
            visited_at=body.visited_at or now_utc(),
            complaint=body.complaint,
            diagnosis=body.diagnosis,
            treatment=body.treatment,
            referred_to=body.referred_to,
            attended_by=self.actor_id,
            is_confidential=body.is_confidential,
        )
        self.db.add(r)
        await self.db.flush()
        await self._audit("create", "health_visit", r.id, None, {"person_type": r.person_type})
        await self._emit("health.visit_recorded", {"visit_id": str(r.id)}, "health_visit", r.id)
        return (await self.outs([r]))[0]

    async def list_visits(self, person_id: uuid.UUID | None = None) -> list[HealthVisitOut]:
        if not self.recorder():
            raise forbidden("Health records are confidential")
        stmt = select(HealthVisit).where(HealthVisit.institution_id == self.inst)
        if person_id:
            stmt = stmt.where(HealthVisit.person_id == person_id)
        rows = (await self.db.execute(stmt.order_by(HealthVisit.visited_at.desc()).limit(500))).scalars().all()
        await self._audit(
            "read", "health_visit", None, None, {"count": len(rows), "person_id": str(person_id) if person_id else None}
        )
        return await self.outs(rows)

    async def get(self, vid: uuid.UUID) -> HealthVisitOut:
        r = (
            await self.db.execute(
                select(HealthVisit).where(HealthVisit.id == vid, HealthVisit.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if r is None:
            raise not_found("Visit")
        if not self.recorder():
            try:
                ptype, pid = await self.me_person()
            except APIError:
                raise not_found("Visit") from None
            if (r.person_type, r.person_id) != (ptype, pid):
                raise not_found("Visit")
        else:
            await self._audit("read", "health_visit", r.id, None, {"person_id": str(r.person_id)})
        return (await self.outs([r]))[0]

    async def mine(self) -> list[HealthVisitOut]:
        ptype, pid = await self.me_person()
        rows = (
            (
                await self.db.execute(
                    select(HealthVisit)
                    .where(
                        HealthVisit.institution_id == self.inst,
                        HealthVisit.person_type == ptype,
                        HealthVisit.person_id == pid,
                    )
                    .order_by(HealthVisit.visited_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return await self.outs(rows)

    async def certificate(self, vid: uuid.UUID, body: HealthCertificateRequest) -> dict[str, Any]:
        from app.core.files import build_key, get_storage
        from app.core.security import sign_payload
        from app.utils.pdf import simple_pdf

        if not self.recorder():
            raise forbidden("health:record required")
        r = (
            await self.db.execute(
                select(HealthVisit).where(HealthVisit.id == vid, HealthVisit.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if r is None:
            raise not_found("Visit")
        name = (await self.person_names([(r.person_type, r.person_id)])).get(r.person_id, "")
        doc_id = uuid.uuid4()
        token = sign_payload({"t": "medical_cert", "d": str(doc_id), "i": str(self.inst)}, 3650 * 86400)
        inst = await self.institution()
        pdf = simple_pdf(
            [
                "Medical certificate",
                "",
                f"This is to certify that {name} was examined at the {inst.name} health centre",
                f"on {r.visited_at.date().isoformat()} and was advised rest from {body.from_on.isoformat()} to {body.to_on.isoformat()}.",
                "",
                body.remarks or "",
                f"Document: {doc_id}",
                f"Verify: /api/v1/verify/medical-certificate?token={token}",
            ],
            title="Medical certificate",
        )
        key = build_key(self.inst, "health", f"medical-certificate-{doc_id}.pdf")
        storage = get_storage()
        await storage.put(key, pdf, "application/pdf")
        meta = await self.meta("health", r.id)
        meta["certificate"] = {
            "document_id": str(doc_id),
            "from_on": body.from_on.isoformat(),
            "to_on": body.to_on.isoformat(),
            "key": key,
        }
        await self.put_meta("health", r.id, meta)
        await self._audit("certificate", "health_visit", r.id, None, {"document_id": str(doc_id)})
        await self._emit(
            "health.certificate_issued",
            {
                "visit_id": str(r.id),
                "document_id": str(doc_id),
                "person_type": r.person_type,
                "person_id": str(r.person_id),
            },
            "health_visit",
            r.id,
        )
        return {"document_id": str(doc_id), "result_url": storage.signed_url(key)}

    # ---- insurance ---------------------------------------------------------------------------------------------------------
    async def policy_outs(self, rows: Sequence[InsurancePolicy]) -> list[InsurancePolicyOut]:
        names = await self.person_names([(r.person_type, r.person_id) for r in rows])
        out = []
        for r in rows:
            o = InsurancePolicyOut.model_validate(r)
            o.person_name = names.get(r.person_id)
            out.append(o)
        return out

    async def policies(self) -> list[InsurancePolicyOut]:
        if not (self.recorder() or self.can("health", "manage")):
            raise forbidden("health:record required")
        rows = (
            (
                await self.db.execute(
                    select(InsurancePolicy)
                    .where(InsurancePolicy.institution_id == self.inst)
                    .order_by(InsurancePolicy.valid_to)
                    .limit(1000)
                )
            )
            .scalars()
            .all()
        )
        return await self.policy_outs(rows)

    async def add_policy(self, body: InsurancePolicyIn) -> InsurancePolicyOut:
        if not (self.recorder() or self.can("health", "manage")):
            raise forbidden("health:record required")
        r = InsurancePolicy(institution_id=self.inst, **body.model_dump())
        self.db.add(r)
        await self.db.flush()
        await self._audit("create", "insurance_policy", r.id, None, {"policy_no": r.policy_no})
        return (await self.policy_outs([r]))[0]

    async def my_policies(self) -> list[InsurancePolicyOut]:
        ptype, pid = await self.me_person()
        rows = (
            (
                await self.db.execute(
                    select(InsurancePolicy).where(
                        InsurancePolicy.person_type == ptype,
                        InsurancePolicy.person_id == pid,
                        InsurancePolicy.institution_id == self.inst,
                    )
                )
            )
            .scalars()
            .all()
        )
        return await self.policy_outs(rows)

    async def insurance_expiry_scan(self) -> int:
        today = await self.today()
        rows = (
            (
                await self.db.execute(
                    select(InsurancePolicy).where(
                        InsurancePolicy.institution_id == self.inst,
                        InsurancePolicy.valid_to >= today,
                        InsurancePolicy.valid_to <= today + timedelta(days=30),
                    )
                )
            )
            .scalars()
            .all()
        )
        for r in rows:
            uid = await self.person_user_id(r.person_type, r.person_id)
            assert r.valid_to is not None
            await self._notify(
                "health.appointment_reminder",
                [uid],
                {"what": f"Insurance {r.policy_no} expires", "on": r.valid_to.isoformat()},
            )
        return len(rows)

    # ---- stats (counts only) -------------------------------------------------------------------------------------------
    async def stats(self) -> HealthStats:
        if not self._counts_reader():
            raise forbidden("Health statistics are restricted")
        visits = (
            await self.db.execute(
                select(func.count()).select_from(HealthVisit).where(HealthVisit.institution_id == self.inst)
            )
        ).scalar_one()
        by_month = {
            m: int(n)
            for m, n in (
                await self.db.execute(
                    select(func.to_char(HealthVisit.visited_at, literal_column("'YYYY-MM'")), func.count())
                    .where(HealthVisit.institution_id == self.inst)
                    .group_by(func.to_char(HealthVisit.visited_at, literal_column("'YYYY-MM'")))
                    .order_by(func.to_char(HealthVisit.visited_at, literal_column("'YYYY-MM'")))
                )
            ).all()
        }
        referrals = (
            await self.db.execute(
                select(func.count())
                .select_from(HealthVisit)
                .where(HealthVisit.institution_id == self.inst, HealthVisit.referred_to.is_not(None))
            )
        ).scalar_one()
        certs = sum(1 for m in (await self.metas("health")).values() if m.get("certificate"))
        insured = (
            await self.db.execute(
                select(func.count()).select_from(InsurancePolicy).where(InsurancePolicy.institution_id == self.inst)
            )
        ).scalar_one()
        counselling = {
            s: int(n)
            for s, n in (
                await self.db.execute(
                    select(CounsellingAppointment.status, func.count())
                    .where(CounsellingAppointment.institution_id == self.inst)
                    .group_by(CounsellingAppointment.status)
                )
            ).all()
        }
        return HealthStats(
            visits=int(visits),
            by_month=by_month,
            referrals=int(referrals),
            certificates=certs,
            insured=int(insured),
            counselling=counselling,
        )
