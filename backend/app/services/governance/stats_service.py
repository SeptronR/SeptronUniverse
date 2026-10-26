"""Governance statistics — Prompts/33 §33.6 ``stats_service``: meetings per committee per year, quorum compliance,
resolutions implemented %, ATR pendency, legal cases by status, RTI disposal within time %, audit paras settled %, e-file
pendency and policy acknowledgement % — for Phase 32 (6.5.x / 7.1.x evidence), Phase 35 dashboards and Phase 36 returns.
Readers: ``governance:view_all`` / ``manage`` (IQAC, registrar, principal, auditor). Counts only — no PII."""

from sqlalchemy import func, select

from app.models.governance import ActionTakenReport, AuditPara, Committee, Efile, Meeting, Resolution, RtiRequest
from app.schemas.governance import GovernanceStats
from app.services.governance.common import GovernanceBase, forbidden


def _pct(n: int, d: int) -> float | None:
    return round(100 * n / d, 1) if d else None


class StatsService(GovernanceBase):
    async def stats(self, year: int | None = None) -> GovernanceStats:
        if not (self.reader_all() or self.has_any("governance", "view_all", "manage")):
            raise forbidden("governance:view_all required")
        y = year or (await self.today()).year
        yr = func.extract("year", Meeting.held_on) == y
        per = (
            await self.db.execute(
                select(Committee.id, Committee.name, Committee.committee_type, func.count(Meeting.id))
                .join(Meeting, Meeting.committee_id == Committee.id)
                .where(Committee.institution_id == self.inst, yr, Meeting.status != "cancelled")
                .group_by(Committee.id, Committee.name, Committee.committee_type)
                .order_by(func.count(Meeting.id).desc())
            )
        ).all()
        held = (
            await self.db.execute(
                select(Meeting.quorum_met, func.count())
                .where(Meeting.institution_id == self.inst, yr, Meeting.quorum_met.is_not(None))
                .group_by(Meeting.quorum_met)
            )
        ).all()
        q = {bool(k): int(v) for k, v in held}
        res = {
            k: int(v)
            for k, v in (
                await self.db.execute(
                    select(Resolution.status, func.count())
                    .join(Meeting, Meeting.id == Resolution.meeting_id)
                    .where(Resolution.institution_id == self.inst, yr)
                    .group_by(Resolution.status)
                )
            ).all()
        }
        owned = (
            await self.db.execute(
                select(func.count())
                .select_from(Resolution)
                .join(Meeting, Meeting.id == Resolution.meeting_id)
                .where(Resolution.institution_id == self.inst, yr, Resolution.action_owner_staff_id.is_not(None))
            )
        ).scalar_one()
        atr_pending = (
            await self.db.execute(
                select(func.count()).where(
                    ActionTakenReport.institution_id == self.inst, ActionTakenReport.status == "submitted"
                )
            )
        ).scalar_one()
        from app.services.governance.legal_service import LegalService

        legal = await LegalService(self.db, None, institution_id=self.inst).summary()
        rti = list(
            (
                await self.db.execute(
                    select(RtiRequest).where(
                        RtiRequest.institution_id == self.inst, func.extract("year", RtiRequest.received_on) == y
                    )
                )
            ).scalars()
        )
        disposed = [r for r in rti if r.responded_on]
        within = [r for r in disposed if r.responded_on and r.responded_on <= r.due_on]
        paras = {
            k: int(v)
            for k, v in (
                await self.db.execute(
                    select(AuditPara.status, func.count())
                    .where(AuditPara.institution_id == self.inst)
                    .group_by(AuditPara.status)
                )
            ).all()
        }
        from app.services.governance.efile_service import EfileService
        from app.services.governance.policy_service import PolicyService

        es = EfileService(self.db, None, institution_id=self.inst)
        open_files = list(
            (
                await self.db.execute(select(Efile).where(Efile.institution_id == self.inst, Efile.status != "closed"))
            ).scalars()
        )
        over = sum(1 for o in await es.outs(open_files) if o.over_sla)
        ps = PolicyService(self.db, None, institution_id=self.inst)
        acked = [
            p for p in await ps.outs(await ps.published_rows(), stats=True) if p.requires_ack and p.ack_pct is not None
        ]
        return GovernanceStats(
            year=y,
            meetings_per_committee=[
                {"committee_id": str(i), "name": n, "committee_type": t, "meetings": int(c)} for i, n, t, c in per
            ],
            meetings=sum(int(c) for *_, c in per),
            quorum_compliance_pct=_pct(q.get(True, 0), sum(q.values())),
            resolutions=sum(res.values()),
            resolutions_implemented_pct=_pct(res.get("implemented", 0), int(owned)),
            atr_pending=int(atr_pending),
            legal_by_status=legal,
            rti_received=len(rti),
            rti_within_time_pct=_pct(len(within), len(disposed)),
            audit_paras_settled_pct=_pct(paras.get("settled", 0) + paras.get("dropped", 0), sum(paras.values())),
            efile_open=len(open_files),
            efile_over_sla=over,
            policy_ack_pct=round(sum(p.ack_pct or 0 for p in acked) / len(acked), 1) if acked else None,
        )
