"""Approval-workflow engine — Prompts/00 §3.17, completed by Prompts/04 §04.6 (Technical_Architecture §6).

Tables: ``workflow_definitions`` (versioned ``steps`` JSONB), ``workflow_instances``, ``workflow_steps``,
``workflow_delegations``. Modules register hooks with ``@engine.on("leave.approval", "approved")``; the engine
routes, records, notifies and fires the hooks **in the same transaction** as the status change.

Rules
1. ``start`` loads the latest active definition of the key for the institution, creates the instance and
   materialises step 1: one ``workflow_steps`` row per resolved approver. Approver specs:
   * ``{"type":"user","value":<uuid>}``;
   * ``{"type":"role","value":<slug>}`` — holders of the role whose assignment scope matches the ``context``
     (``department_id`` / ``faculty_id`` / ``college_id`` / ``offering_id`` / ``committee_id`` / ``hostel_id``; the
     department's faculty/college are derived), else the institution-scoped holders, else a **role pool** row
     (``approver_role_slug`` without a user — any holder of the role may act);
   * ``{"type":"scope_rule","value":…}`` — ``entity.department.hod``, ``entity.college.principal``,
     ``requester.manager`` (``staff.reports_to_staff_id``) or ``context.<key>`` (a user id carried in the context);
     an unresolvable rule → 422.
   ``sla_due_at = now + sla_hours``; approvers are notified (``workflow.step_pending``); ``workflow.started`` emitted.
2. Delegation is resolved **at read/act time**: ``approver_user_id`` keeps the original approver and an active
   ``workflow_delegations`` row (today within ``from_on..to_on``, ``module`` NULL or the definition's module) lets the
   delegate see and act on the step — ``acted_by`` ≠ ``approver_user_id`` records who acted for whom.
3. ``act``: the actor must be a resolved approver of a pending/escalated step of the current order (directly, by
   role pool, as delegate or as ``escalated_to``) — else 403. ``approve`` in sequential mode closes the step (other
   pool rows of the order → ``skipped``) and moves on; parallel mode waits for every approver; any ``reject`` rejects
   the instance; ``delegate`` hands the step to ``delegate_to``. Final approval → ``approved`` + hook ``approved``;
   rejection → hook ``rejected``; every action emits ``workflow.acted`` (+ ``workflow.approved|rejected``) and the
   requester is notified.
4. ``cancel`` — the requester (or the super admin) while pending; open steps → ``skipped``.
5. ``inbox(principal)`` — steps addressed to the user directly, via a role pool, as delegate or after escalation.
6. ``escalate_due(now)`` (Beat ``workflow.escalate``): pending steps past ``sla_due_at`` → ``escalated`` with
   ``escalated_to`` from the spec's ``escalate_to`` (role resolved like rule 1, first holder), ``sla_due_at`` renewed
   for another SLA window (re-escalation), notification ``workflow.escalated``; hook ``escalated``.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.errors import APIError, ErrorCode
from app.models.platform import (
    Role,
    UserRole,
    WorkflowDefinition,
    WorkflowDelegation,
    WorkflowInstance,
    WorkflowStep,
)

Hook = Callable[[AsyncSession, WorkflowInstance, Any], Awaitable[None]]
# (db, entity_id) -> (summary, client route) for the approvals inbox; modules register one per entity type
Summariser = Callable[[AsyncSession, uuid.UUID], Awaitable[tuple[str | None, str | None]]]
DECISIONS = {"approve", "reject", "delegate"}
OPEN_STEP = ("pending", "escalated")
CONTEXT_SCOPES = {
    "department": "department_id",
    "faculty": "faculty_id",
    "college": "college_id",
    "offering": "offering_id",
    "committee": "committee_id",
    "hostel": "hostel_id",
    "program": "program_id",
}


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except (TypeError, ValueError):
        return None


class WorkflowEngine:
    def __init__(self) -> None:
        self._hooks: dict[tuple[str, str], list[Hook]] = {}
        self._summarisers: dict[str, Summariser] = {}

    def summariser(self, entity_type: str) -> Callable[[Summariser], Summariser]:
        """``@engine.summariser("leave_request")`` — entity summary + route shown in the approvals inbox."""

        def deco(fn: Summariser) -> Summariser:
            self._summarisers[entity_type] = fn
            return fn

        return deco

    async def summarise(
        self, db: AsyncSession, entity_type: str, entity_id: uuid.UUID
    ) -> tuple[str | None, str | None]:
        fn = self._summarisers.get(entity_type)
        return await fn(db, entity_id) if fn else (None, None)

    # ---- registration -------------------------------------------------------------------------------------
    def on(self, key: str, event: str) -> Callable[[Hook], Hook]:
        """``@engine.on("leave.approval", "approved")`` — events: approved | rejected | step_approved | escalated |
        cancelled. Hooks run inside the transaction of the status change."""

        def deco(fn: Hook) -> Hook:
            self._hooks.setdefault((key, event), []).append(fn)
            return fn

        return deco

    async def _fire(self, db: AsyncSession, key: str, event: str, instance: WorkflowInstance, actor: Any) -> None:
        for hook in self._hooks.get((key, event), []) + self._hooks.get(("*", event), []):
            await hook(db, instance, actor)

    # ---- definitions ------------------------------------------------------------------------------------------
    async def definition_for(self, db: AsyncSession, institution_id: uuid.UUID, key: str) -> WorkflowDefinition:
        definition = (
            await db.execute(
                select(WorkflowDefinition)
                .where(
                    WorkflowDefinition.institution_id == institution_id,
                    WorkflowDefinition.key == key,
                    WorkflowDefinition.is_active.is_(True),
                )
                .order_by(WorkflowDefinition.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if definition is None:
            raise APIError(404, ErrorCode.NOT_FOUND, f"Workflow definition {key!r} not found")
        return definition

    # ---- rule 1 -----------------------------------------------------------------------------------------------
    async def start(
        self,
        db: AsyncSession,
        *,
        institution_id: uuid.UUID,
        key: str,
        entity_type: str,
        entity_id: uuid.UUID,
        started_by: uuid.UUID | None,
        context: dict[str, Any],
        title: str | None = None,
    ) -> WorkflowInstance:
        definition = await self.definition_for(db, institution_id, key)
        existing = (
            await db.execute(
                select(WorkflowInstance).where(
                    WorkflowInstance.entity_type == entity_type,
                    WorkflowInstance.entity_id == entity_id,
                    WorkflowInstance.definition_id == definition.id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise APIError(
                409,
                ErrorCode.CONFLICT,
                "A workflow is already running for this record",
                {"instance_id": str(existing.id)},
            )
        ctx = await self._enrich_context(db, dict(context or {}))
        instance = WorkflowInstance(
            institution_id=institution_id,
            definition_id=definition.id,
            entity_type=entity_type,
            entity_id=entity_id,
            title=(title or definition.name)[:200],
            status="pending",
            current_step=1,
            started_by=started_by,
            context=ctx,
        )
        db.add(instance)
        await db.flush()
        await self._materialise_step(db, definition, instance, 1)
        await self._emit(db, instance, "workflow.started", {"key": key}, started_by)
        return instance

    async def _enrich_context(self, db: AsyncSession, ctx: dict[str, Any]) -> dict[str, Any]:
        """A department implies its college and faculty (role resolution needs every level)."""
        dept = _uuid(ctx.get("department_id"))
        if dept and not (ctx.get("college_id") and ctx.get("faculty_id")):
            row = (
                await db.execute(text("SELECT college_id, faculty_id FROM departments WHERE id = :d"), {"d": dept})
            ).first()
            if row is not None:
                ctx.setdefault("college_id", str(row.college_id) if row.college_id else None)
                ctx.setdefault("faculty_id", str(row.faculty_id) if row.faculty_id else None)
        return ctx

    def _specs(self, definition: WorkflowDefinition, order: int) -> list[dict[str, Any]]:
        return [s for s in definition.steps if int(s.get("order", 0)) == order]

    def _max_order(self, definition: WorkflowDefinition) -> int:
        return max((int(s.get("order", 0)) for s in definition.steps), default=1)

    async def _materialise_step(
        self, db: AsyncSession, definition: WorkflowDefinition, instance: WorkflowInstance, order: int
    ) -> list[WorkflowStep]:
        created: list[WorkflowStep] = []
        now = datetime.now(UTC)
        for spec in self._specs(definition, order):
            sla_hours = spec.get("sla_hours")
            due = now + timedelta(hours=float(sla_hours)) if sla_hours else None
            approver = spec.get("approver") or {}
            resolved = await self.resolve_approvers(db, instance, approver)
            if not resolved:
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    f"No approver could be resolved for step {order} ({approver.get('type')}: {approver.get('value')})",
                    {"step": order},
                )
            for user_id, role_slug in resolved:
                step = WorkflowStep(
                    institution_id=instance.institution_id,
                    instance_id=instance.id,
                    step_order=order,
                    approver_user_id=user_id,
                    approver_role_slug=role_slug,
                    status="pending",
                    sla_due_at=due,
                )
                db.add(step)
                created.append(step)
        await db.flush()
        for step in created:
            await self._notify_step(db, instance, step, "workflow.step_pending")
        return created

    async def resolve_approvers(
        self, db: AsyncSession, instance: WorkflowInstance, approver: dict[str, Any]
    ) -> list[tuple[uuid.UUID | None, str | None]]:
        kind, value = approver.get("type"), approver.get("value")
        ctx = instance.context or {}
        if kind == "user":
            uid = _uuid(value)
            return [(uid, None)] if uid else []
        if kind == "role" and value:
            users = await self._role_holders(db, instance.institution_id, str(value), ctx)
            return [(u, str(value)) for u in users] if users else [(None, str(value))]
        if kind == "scope_rule" and value:
            uid = await self._scope_rule(db, instance, str(value), ctx)
            return [(uid, None)] if uid else []
        return []

    async def _role_holders(
        self, db: AsyncSession, institution_id: uuid.UUID, slug: str, ctx: dict[str, Any]
    ) -> list[uuid.UUID]:
        today = datetime.now(UTC)
        rows = (
            await db.execute(
                select(UserRole.user_id, UserRole.scope_type, UserRole.scope_id)
                .join(Role, Role.id == UserRole.role_id)
                .where(
                    Role.institution_id == institution_id,
                    Role.slug == slug,
                    Role.deleted_at.is_(None),
                    or_(UserRole.valid_from.is_(None), UserRole.valid_from <= today),
                    or_(UserRole.valid_to.is_(None), UserRole.valid_to >= today),
                )
            )
        ).all()
        # most specific context match first: department → faculty → program → offering → college → institution
        for scope in ("department", "faculty", "program", "offering", "committee", "hostel", "college"):
            wanted = _uuid(ctx.get(CONTEXT_SCOPES[scope]))
            if wanted is None:
                continue
            hits = [r.user_id for r in rows if r.scope_type == scope and r.scope_id == wanted]
            if hits:
                return sorted(set(hits), key=str)
        inst_wide = [r.user_id for r in rows if r.scope_type in ("institution", "self")]
        if inst_wide:
            return sorted(set(inst_wide), key=str)
        return []

    async def _scope_rule(
        self, db: AsyncSession, instance: WorkflowInstance, rule: str, ctx: dict[str, Any]
    ) -> uuid.UUID | None:
        if rule.startswith("context."):
            return _uuid(ctx.get(rule.split(".", 1)[1]))
        if rule == "entity.department.hod":
            users = await self._role_holders(
                db, instance.institution_id, "hod", {"department_id": ctx.get("department_id")}
            )
            return users[0] if users else None
        if rule == "entity.college.principal":
            college = _uuid(ctx.get("college_id"))
            if college:
                row = (
                    await db.execute(
                        text(
                            "SELECT s.user_id FROM colleges c JOIN staff s ON s.id = c.principal_staff_id WHERE c.id = :c"
                        ),
                        {"c": college},
                    )
                ).first()
                if row and row.user_id:
                    return uuid.UUID(str(row.user_id))
            users = await self._role_holders(db, instance.institution_id, "vice_chancellor", ctx)
            return users[0] if users else None
        if rule == "requester.manager" and instance.started_by:
            row = (
                await db.execute(
                    text(
                        "SELECT m.user_id FROM staff s JOIN staff m ON m.id = s.reports_to_staff_id "
                        "WHERE s.user_id = :u AND s.deleted_at IS NULL"
                    ),
                    {"u": instance.started_by},
                )
            ).first()
            return uuid.UUID(str(row.user_id)) if row and row.user_id else None
        return None

    # ---- rule 2 -----------------------------------------------------------------------------------------------
    async def _local_today(self, db: AsyncSession, institution_id: uuid.UUID) -> date:
        """Delegation ``from_on`` / ``to_on`` are institution-local calendar dates (found by the Phase 06 regression
        run between 18:30 and 24:00 UTC, when the UTC date still trails IST)."""
        from types import SimpleNamespace

        from app.core.tenancy import today_for

        tz = (await db.execute(text("SELECT timezone FROM institutions WHERE id = :i"), {"i": institution_id})).scalar()
        return today_for(SimpleNamespace(timezone=tz))

    async def delegators_of(
        self,
        db: AsyncSession,
        institution_id: uuid.UUID,
        user_id: uuid.UUID,
        module: str | None = None,
        on: date | None = None,
    ) -> list[tuple[uuid.UUID, str | None]]:
        """(from_user_id, module) of the delegations active today that hand approvals to ``user_id``."""
        today = on or await self._local_today(db, institution_id)
        q = select(WorkflowDelegation.from_user_id, WorkflowDelegation.module).where(
            and_(
                WorkflowDelegation.institution_id == institution_id,
                WorkflowDelegation.to_user_id == user_id,
                WorkflowDelegation.is_active.is_(True),
                WorkflowDelegation.from_on <= today,
                WorkflowDelegation.to_on >= today,
            )
        )
        if module:
            q = q.where(or_(WorkflowDelegation.module.is_(None), WorkflowDelegation.module == module))
        return [(r[0], r[1]) for r in (await db.execute(q)).all()]

    async def _delegate_of(
        self, db: AsyncSession, institution_id: uuid.UUID, approver: uuid.UUID, module: str
    ) -> uuid.UUID | None:
        today = await self._local_today(db, institution_id)
        return (
            await db.execute(
                select(WorkflowDelegation.to_user_id)
                .where(
                    WorkflowDelegation.institution_id == institution_id,
                    WorkflowDelegation.from_user_id == approver,
                    WorkflowDelegation.is_active.is_(True),
                    WorkflowDelegation.from_on <= today,
                    WorkflowDelegation.to_on >= today,
                    or_(WorkflowDelegation.module.is_(None), WorkflowDelegation.module == module),
                )
                .limit(1)
            )
        ).scalar_one_or_none()

    # ---- rule 3 -----------------------------------------------------------------------------------------------
    async def act(
        self,
        db: AsyncSession,
        *,
        instance_id: uuid.UUID,
        actor: Any,
        decision: str,
        comment: str | None,
        delegate_to: uuid.UUID | None = None,
    ) -> WorkflowInstance:
        if decision not in DECISIONS:
            raise APIError(422, ErrorCode.VALIDATION, f"decision must be one of {sorted(DECISIONS)}")
        instance = await self._locked_instance(db, instance_id)
        if instance.status not in ("pending", "escalated"):
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"Workflow already {instance.status}")
        definition = (
            await db.execute(select(WorkflowDefinition).where(WorkflowDefinition.id == instance.definition_id))
        ).scalar_one()
        step = await self._actionable_step(db, instance, definition, actor)
        now = datetime.now(UTC)
        key = definition.key
        if decision == "delegate":
            if not delegate_to:
                raise APIError(422, ErrorCode.VALIDATION, "delegate_to is required", {"field": "delegate_to"})
            step.status, step.acted_by, step.acted_at, step.comment = "delegated", actor.id, now, comment
            new = WorkflowStep(
                institution_id=instance.institution_id,
                instance_id=instance.id,
                step_order=step.step_order,
                approver_user_id=delegate_to,
                status="pending",
                sla_due_at=step.sla_due_at,
            )
            db.add(new)
            await db.flush()
            await self._emit(
                db,
                instance,
                "workflow.acted",
                {"decision": "delegate", "step_id": str(step.id), "to": str(delegate_to)},
                actor.id,
            )
            await self._notify_step(db, instance, new, "workflow.step_pending")
            return instance
        step.status = "approved" if decision == "approve" else "rejected"
        step.acted_by, step.acted_at, step.comment = actor.id, now, comment
        order_specs = self._specs(definition, step.step_order)
        parallel = any(s.get("mode") == "parallel" for s in order_specs)
        siblings = list(
            (
                await db.execute(
                    select(WorkflowStep).where(
                        WorkflowStep.instance_id == instance.id,
                        WorkflowStep.step_order == step.step_order,
                        WorkflowStep.id != step.id,
                        WorkflowStep.status.in_(OPEN_STEP),
                    )
                )
            ).scalars()
        )
        payload = {"decision": decision, "step_id": str(step.id), "step_order": step.step_order, "comment": comment}
        if decision == "reject":
            for s in siblings:
                s.status = "skipped"
            instance.status, instance.closed_at = "rejected", now
            await db.flush()
            await self._emit(db, instance, "workflow.acted", payload, actor.id)
            await self._emit(db, instance, "workflow.rejected", {"comment": comment}, actor.id)
            await self._notify_requester(db, instance, "workflow.rejected", comment)
            await self._fire(db, key, "rejected", instance, actor)
            return instance
        if parallel and siblings:
            await db.flush()
            await self._emit(db, instance, "workflow.acted", payload, actor.id)
            return instance
        for s in siblings:  # sequential pool: the first approver decides for the order
            s.status = "skipped"
        await self._emit(db, instance, "workflow.acted", payload, actor.id)
        await self._fire(db, key, "step_approved", instance, actor)
        if step.step_order >= self._max_order(definition):
            instance.status, instance.closed_at = "approved", now
            await db.flush()
            await self._emit(db, instance, "workflow.approved", {}, actor.id)
            await self._notify_requester(db, instance, "workflow.approved", None)
            await self._fire(db, key, "approved", instance, actor)
        else:
            instance.current_step = step.step_order + 1
            instance.status = "pending"
            await db.flush()
            await self._materialise_step(db, definition, instance, instance.current_step)
        return instance

    async def _locked_instance(self, db: AsyncSession, instance_id: uuid.UUID) -> WorkflowInstance:
        instance = (
            await db.execute(select(WorkflowInstance).where(WorkflowInstance.id == instance_id).with_for_update())
        ).scalar_one_or_none()
        if instance is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Workflow instance not found")
        return instance

    async def _actionable_step(
        self, db: AsyncSession, instance: WorkflowInstance, definition: WorkflowDefinition, actor: Any
    ) -> WorkflowStep:
        steps = list(
            (
                await db.execute(
                    select(WorkflowStep)
                    .where(
                        WorkflowStep.instance_id == instance.id,
                        WorkflowStep.step_order == instance.current_step,
                        WorkflowStep.status.in_(OPEN_STEP),
                    )
                    .with_for_update()
                )
            ).scalars()
        )
        role_slugs = set(getattr(actor, "roles", []) or [])
        delegators = {f for f, _ in await self.delegators_of(db, instance.institution_id, actor.id, definition.module)}
        for predicate in (
            lambda s: s.approver_user_id == actor.id,
            lambda s: s.escalated_to == actor.id,
            lambda s: s.approver_user_id is None and s.approver_role_slug in role_slugs,
            lambda s: s.approver_user_id in delegators,
        ):
            for s in steps:
                if predicate(s):
                    return s
        if getattr(actor, "is_super_admin", False) and steps:
            return steps[0]
        raise APIError(403, ErrorCode.PERMISSION_DENIED, "You are not an approver for the current step")

    # ---- rule 4 -----------------------------------------------------------------------------------------------
    async def cancel(
        self, db: AsyncSession, *, instance_id: uuid.UUID, actor: Any, reason: str | None = None
    ) -> WorkflowInstance:
        instance = await self._locked_instance(db, instance_id)
        if instance.status not in ("pending", "escalated"):
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"Workflow already {instance.status}")
        if instance.started_by != actor.id and not getattr(actor, "is_super_admin", False):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only the requester can cancel this request")
        now = datetime.now(UTC)
        for s in (
            await db.execute(
                select(WorkflowStep).where(WorkflowStep.instance_id == instance.id, WorkflowStep.status.in_(OPEN_STEP))
            )
        ).scalars():
            s.status = "skipped"
        instance.status, instance.closed_at = "cancelled", now
        await db.flush()
        definition = (
            await db.execute(select(WorkflowDefinition).where(WorkflowDefinition.id == instance.definition_id))
        ).scalar_one()
        await self._emit(db, instance, "workflow.acted", {"decision": "cancel", "reason": reason}, actor.id)
        await self._fire(db, definition.key, "cancelled", instance, actor)
        return instance

    # ---- rule 5 -----------------------------------------------------------------------------------------------
    async def inbox(
        self, db: AsyncSession, principal: Any
    ) -> list[tuple[WorkflowStep, WorkflowInstance, WorkflowDefinition]]:
        """Open steps of the current order addressed to the user (direct, role pool, delegation, escalation)."""
        inst_id = principal.institution_id
        role_slugs = list(getattr(principal, "roles", []) or [])
        delegations = await self.delegators_of(db, inst_id, principal.id)
        conds = [WorkflowStep.approver_user_id == principal.id, WorkflowStep.escalated_to == principal.id]
        if role_slugs:
            conds.append(and_(WorkflowStep.approver_user_id.is_(None), WorkflowStep.approver_role_slug.in_(role_slugs)))
        for from_user, module in delegations:
            cond = WorkflowStep.approver_user_id == from_user
            conds.append(and_(cond, WorkflowDefinition.module == module) if module else cond)
        q = (
            select(WorkflowStep, WorkflowInstance, WorkflowDefinition)
            .join(WorkflowInstance, WorkflowInstance.id == WorkflowStep.instance_id)
            .join(WorkflowDefinition, WorkflowDefinition.id == WorkflowInstance.definition_id)
            .where(
                WorkflowStep.institution_id == inst_id,
                WorkflowStep.status.in_(OPEN_STEP),
                WorkflowInstance.status.in_(("pending", "escalated")),
                WorkflowInstance.current_step == WorkflowStep.step_order,
                or_(*conds),
            )
            .order_by(WorkflowStep.sla_due_at.nulls_last(), WorkflowStep.created_at)
        )
        seen: set[uuid.UUID] = set()
        out = []
        for step, instance, definition in (await db.execute(q)).all():
            if instance.id in seen:
                continue
            seen.add(instance.id)
            out.append((step, instance, definition))
        return out

    # ---- rule 6 -----------------------------------------------------------------------------------------------
    async def escalate_due(self, db: AsyncSession, now: datetime | None = None) -> int:
        """Platform session (all tenants): escalate open steps past their SLA."""
        now = now or datetime.now(UTC)
        rows = (
            await db.execute(
                select(WorkflowStep, WorkflowInstance, WorkflowDefinition)
                .join(WorkflowInstance, WorkflowInstance.id == WorkflowStep.instance_id)
                .join(WorkflowDefinition, WorkflowDefinition.id == WorkflowInstance.definition_id)
                .where(
                    WorkflowStep.status.in_(OPEN_STEP),
                    WorkflowStep.sla_due_at.is_not(None),
                    WorkflowStep.sla_due_at < now,
                    WorkflowInstance.status.in_(("pending", "escalated")),
                    WorkflowInstance.current_step == WorkflowStep.step_order,
                )
                .with_for_update(of=WorkflowStep, skip_locked=True)
            )
        ).all()
        count = 0
        for step, instance, definition in rows:
            spec = next(
                (
                    s
                    for s in self._specs(definition, step.step_order)
                    if (s.get("approver") or {}).get("value") in (step.approver_role_slug, str(step.approver_user_id))
                ),
                (self._specs(definition, step.step_order) or [{}])[0],
            )
            target = None
            esc = spec.get("escalate_to") or {}
            if esc:
                resolved = await self.resolve_approvers(db, instance, esc)
                target = next((u for u, _ in resolved if u is not None), None)
            sla = float(spec.get("sla_hours") or 24)
            step.status = "escalated"
            step.escalated_to = target or step.escalated_to
            step.sla_due_at = now + timedelta(hours=sla)
            instance.status = "escalated"
            await db.flush()
            await self._emit(
                db,
                instance,
                "workflow.escalated",
                {"step_id": str(step.id), "escalated_to": str(target) if target else None},
                None,
            )
            if target:
                await self._notify(db, instance, "workflow.escalated", {"user_ids": [str(target)]}, {})
            await self._fire(db, definition.key, "escalated", instance, None)
            count += 1
        return count

    # ---- events / notifications -------------------------------------------------------------------------------
    async def _emit(
        self, db: AsyncSession, instance: WorkflowInstance, event_type: str, payload: dict[str, Any], actor_id: Any
    ) -> None:
        await events.emit(
            db,
            institution_id=instance.institution_id,
            event_type=event_type,
            payload={
                "instance_id": str(instance.id),
                "entity_type": instance.entity_type,
                "entity_id": str(instance.entity_id),
                "status": instance.status,
                "title": instance.title,
                **payload,
            },
            aggregate_type="workflow_instance",
            aggregate_id=instance.id,
            actor_user_id=actor_id,
        )

    async def _notify(
        self,
        db: AsyncSession,
        instance: WorkflowInstance,
        event_type: str,
        audience: dict[str, Any],
        extra: dict[str, Any],
    ) -> None:
        from app.core.notifications.notify import notify_event

        await notify_event(
            db,
            instance.institution_id,
            event_type,
            audience=audience,
            context={"title": instance.title or "", "instance_id": str(instance.id), **extra},
        )

    async def _notify_step(
        self, db: AsyncSession, instance: WorkflowInstance, step: WorkflowStep, event_type: str
    ) -> None:
        if step.approver_user_id:
            audience: dict[str, Any] = {"user_ids": [str(step.approver_user_id)]}
            delegate = await self._delegate_of(db, instance.institution_id, step.approver_user_id, "")
            if delegate:
                audience["user_ids"].append(str(delegate))
        elif step.approver_role_slug:
            audience = {"roles": [step.approver_role_slug]}
        else:
            return
        requester = ""
        if instance.started_by:
            row = (
                await db.execute(
                    text("SELECT display_name, username FROM users WHERE id = :u"), {"u": instance.started_by}
                )
            ).first()
            requester = (row.display_name or row.username) if row else ""
        await self._notify(db, instance, event_type, audience, {"requester": requester})

    async def _notify_requester(
        self, db: AsyncSession, instance: WorkflowInstance, event_type: str, comment: str | None
    ) -> None:
        if instance.started_by:
            await self._notify(
                db, instance, event_type, {"user_ids": [str(instance.started_by)]}, {"comment": comment or ""}
            )


engine = WorkflowEngine()
