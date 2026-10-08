"""Subscription entitlements — Prompts/02 §02.6 ``entitlement_service`` (plan, status, seat/storage/SMS limits).

Business rules
1. ``current`` — the tenant's latest ``institution_subscriptions`` row joined with its plan; no row → status ``none``
   (treated like an active starter plan without limits so a fresh tenant is never locked out before billing exists).
2. ``require_active_subscription`` — ``active`` / ``trial`` pass; ``grace`` refuses writes with
   ``403 RULE_VIOLATION`` (``code: SUBSCRIPTION_GRACE`` — the "402-style" answer of the prompt) but allows reads;
   ``expired`` / ``cancelled`` refuse everything with ``403 RULE_VIOLATION`` (``code: SUBSCRIPTION_EXPIRED``).
   ``subscription_required()`` wraps it as a route dependency for later phases.
3. ``enforce_seat_limit(kind)`` — before creating a student/staff account: the seats in use + ``adding`` must not
   exceed the plan limit → ``403 RULE_VIOLATION`` (``code: SEAT_LIMIT``, details ``{kind, limit, current}``). Students
   count the student master (Phase 07: non-deleted students in a seated status — provisional, admitted, active, on
   break, detained); staff still count active ``users.user_type = staff`` accounts.
4. ``entitlements`` — plan, status, limits and current usage (latest ``usage_meters`` row or a live count).
5. ``meter(institution_id, month)`` — Beat ``usage.meter`` (monthly) upserts ``usage_meters``; ``reminders`` — Beat
   ``subscriptions.reminders`` (daily) emits ``subscription.expiring`` 30/7/1 days before ``ends_on``.
"""

import uuid
from datetime import date, timedelta
from typing import Any

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.authz.dependencies import Principal, get_current_user
from app.core.errors import APIError, ErrorCode
from app.db.session import get_db
from app.models.saas import InstitutionSubscription, SubscriptionPlan, plan_limits
from app.repositories.subscription_repository import SubscriptionRepository
from app.repositories.user_repository import UserRepository
from app.schemas.saas import EntitlementLimits, EntitlementsResponse, EntitlementUsage

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
SEAT_TYPES = {"student": ("student", "learner"), "staff": ("staff",)}


class EntitlementService:
    def __init__(self, db: AsyncSession, principal: Principal | None = None):
        self.db, self.principal = db, principal
        self.repo = SubscriptionRepository(db)

    def _institution(self, institution_id: uuid.UUID | None) -> uuid.UUID:
        inst = institution_id or (self.principal.institution_id if self.principal else None)
        if inst is None:
            raise APIError(422, ErrorCode.VALIDATION, "An institution context is required")
        return inst

    # ---- rule 1 -----------------------------------------------------------------------------------------------
    async def current(
        self, institution_id: uuid.UUID | None = None
    ) -> tuple[InstitutionSubscription | None, SubscriptionPlan | None]:
        inst = self._institution(institution_id)
        sub = await self.repo.current(inst)
        plan = await self.repo.plan(sub.plan_id) if sub else None
        return sub, plan

    # ---- rule 2 -----------------------------------------------------------------------------------------------
    async def require_active_subscription(self, *, write: bool, institution_id: uuid.UUID | None = None) -> None:
        sub, _ = await self.current(institution_id)
        status = sub.status if sub else "none"
        if status in {"active", "trial", "none"}:
            return
        if status == "grace":
            if write:
                raise APIError(
                    403,
                    ErrorCode.RULE_VIOLATION,
                    "The subscription is in its grace period; the workspace is read-only until it is renewed",
                    {
                        "code": "SUBSCRIPTION_GRACE",
                        "grace_until": sub.grace_until.isoformat() if sub and sub.grace_until else None,
                    },
                )
            return
        raise APIError(
            403,
            ErrorCode.RULE_VIOLATION,
            "The subscription has expired; contact SeptronUniverse to renew",
            {"code": "SUBSCRIPTION_EXPIRED", "status": status},
        )

    # ---- rule 3 -----------------------------------------------------------------------------------------------
    async def enforce_seat_limit(self, kind: str, *, institution_id: uuid.UUID | None = None, adding: int = 1) -> None:
        inst = self._institution(institution_id)
        _, plan = await self.current(inst)
        limit = None if plan is None else (plan.student_limit if kind == "student" else plan.staff_limit)
        if limit is None:
            return
        current = await self.seats_in_use(inst, kind)
        if current + adding > limit:
            raise APIError(
                403,
                ErrorCode.RULE_VIOLATION,
                f"The {kind} seat limit of the plan ({limit}) is reached",
                {"code": "SEAT_LIMIT", "kind": kind, "limit": limit, "current": current},
            )

    async def seats_in_use(self, institution_id: uuid.UUID, kind: str) -> int:
        if kind == "student":
            from app.repositories.student_repository import StudentRepository

            return await StudentRepository(self.db, None, institution_id).count_seated(institution_id)
        return await UserRepository(self.db).count_active(institution_id, SEAT_TYPES.get(kind, (kind,)))

    # ---- rule 4 -----------------------------------------------------------------------------------------------
    async def entitlements(self, institution_id: uuid.UUID | None = None) -> EntitlementsResponse:
        inst = self._institution(institution_id)
        sub, plan = await self.current(inst)
        meter = await self.repo.latest_meter(inst)
        users = UserRepository(self.db)
        usage = EntitlementUsage(
            students=meter.active_students if meter else await self.seats_in_use(inst, "student"),
            staff=meter.active_staff if meter else await users.count_active(inst, SEAT_TYPES["staff"]),
            storage_bytes=meter.storage_bytes if meter else 0,
            sms_sent=meter.sms_sent if meter else 0,
            period_month=meter.period_month if meter else None,
        )
        status = sub.status if sub else "none"
        return EntitlementsResponse(
            institution_id=inst,
            plan=plan.code if plan else None,
            plan_name=plan.name if plan else None,
            tier=plan.tier if plan else None,
            status=status,
            starts_on=sub.starts_on if sub else None,
            ends_on=sub.ends_on if sub else None,
            grace_until=sub.grace_until if sub else None,
            limits=EntitlementLimits(**plan_limits(plan)),
            usage=usage,
            writable=status in {"active", "trial", "none"},
        )

    # ---- rule 5 -----------------------------------------------------------------------------------------------
    async def meter(self, institution_id: uuid.UUID, period_month: date) -> dict[str, Any]:
        users = UserRepository(self.db)
        values = {
            "active_students": await self.seats_in_use(institution_id, "student"),
            "active_staff": await users.count_active(institution_id, SEAT_TYPES["staff"]),
        }
        await self.repo.upsert_meter(institution_id, period_month, **values)
        return values

    async def reminders(self, today: date) -> int:
        emitted = 0
        for sub in await self.repo.expiring(today + timedelta(days=30)):
            assert sub.ends_on is not None
            days = (sub.ends_on - today).days
            if days in (30, 7, 1, 0):
                await events.emit(
                    self.db,
                    institution_id=sub.institution_id,
                    event_type="subscription.expiring",
                    payload={"subscription_id": str(sub.id), "ends_on": sub.ends_on.isoformat(), "days_left": days},
                    aggregate_type="institution_subscription",
                    aggregate_id=sub.id,
                )
                emitted += 1
        return emitted


def subscription_required() -> Any:
    """Route dependency for later phases: writes need an active/trial subscription (grace → read-only)."""

    async def _dep(
        request: Request, principal: Principal = Depends(get_current_user), db: AsyncSession = Depends(get_db)
    ) -> None:
        if principal.is_super_admin or principal.institution_id is None:
            return
        await EntitlementService(db, principal).require_active_subscription(write=request.method in WRITE_METHODS)

    return Depends(_dep)
