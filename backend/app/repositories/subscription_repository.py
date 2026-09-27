"""``subscription_plans`` / ``institution_subscriptions`` / ``usage_meters`` / ``impersonation_logs`` — Prompts/02 §02.5."""

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.saas import ImpersonationLog, InstitutionSubscription, SubscriptionPlan, UsageMeter


class SubscriptionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def plan_by_code(self, code: str) -> SubscriptionPlan | None:
        return (
            await self.db.execute(select(SubscriptionPlan).where(SubscriptionPlan.code == code))
        ).scalar_one_or_none()

    async def plan(self, plan_id: uuid.UUID) -> SubscriptionPlan | None:
        return (
            await self.db.execute(select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id))
        ).scalar_one_or_none()

    async def plans(self) -> Sequence[SubscriptionPlan]:
        return (await self.db.execute(select(SubscriptionPlan).order_by(SubscriptionPlan.created_at))).scalars().all()

    async def current(self, institution_id: uuid.UUID) -> InstitutionSubscription | None:
        q = (
            select(InstitutionSubscription)
            .where(InstitutionSubscription.institution_id == institution_id)
            .order_by(InstitutionSubscription.starts_on.desc(), InstitutionSubscription.created_at.desc())
            .limit(1)
        )
        return (await self.db.execute(q)).scalar_one_or_none()

    async def create(
        self,
        *,
        institution_id: uuid.UUID,
        plan_id: uuid.UUID,
        starts_on: date,
        ends_on: date | None,
        status: str,
        billing_cycle: str = "yearly",
    ) -> InstitutionSubscription:
        row = InstitutionSubscription(
            institution_id=institution_id,
            plan_id=plan_id,
            starts_on=starts_on,
            ends_on=ends_on,
            status=status,
            billing_cycle=billing_cycle,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def expiring(self, on_or_before: date) -> Sequence[InstitutionSubscription]:
        q = select(InstitutionSubscription).where(
            InstitutionSubscription.status.in_(["trial", "active"]),
            InstitutionSubscription.ends_on.is_not(None),
            InstitutionSubscription.ends_on <= on_or_before,
        )
        return (await self.db.execute(q)).scalars().all()

    async def latest_meter(self, institution_id: uuid.UUID) -> UsageMeter | None:
        q = (
            select(UsageMeter)
            .where(UsageMeter.institution_id == institution_id)
            .order_by(UsageMeter.period_month.desc())
            .limit(1)
        )
        return (await self.db.execute(q)).scalar_one_or_none()

    async def upsert_meter(self, institution_id: uuid.UUID, period_month: date, **values: int) -> UsageMeter:
        row = (
            await self.db.execute(
                select(UsageMeter).where(
                    UsageMeter.institution_id == institution_id, UsageMeter.period_month == period_month
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = UsageMeter(institution_id=institution_id, period_month=period_month, **values)
            self.db.add(row)
        else:
            for k, v in values.items():
                setattr(row, k, v)
            row.computed_at = datetime.now(UTC)
        await self.db.flush()
        return row


class ImpersonationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def start(
        self,
        *,
        institution_id: uuid.UUID | None,
        impersonator_id: uuid.UUID,
        target_user_id: uuid.UUID,
        reason: str | None,
        ip: str | None,
    ) -> ImpersonationLog:
        row = ImpersonationLog(
            institution_id=institution_id,
            impersonator_id=impersonator_id,
            target_user_id=target_user_id,
            reason=reason,
            ip=ip,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def get(self, log_id: uuid.UUID) -> ImpersonationLog | None:
        return (
            await self.db.execute(select(ImpersonationLog).where(ImpersonationLog.id == log_id))
        ).scalar_one_or_none()

    async def end(self, row: ImpersonationLog) -> None:
        if row.ended_at is None:
            row.ended_at = datetime.now(UTC)
            await self.db.flush()
