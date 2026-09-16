"""Approval-workflow engine (API surface) — Prompts/00_PREREQUISITE_Project_Setup.md §3.17; Technical_Architecture §6.

Tables: ``workflow_definitions`` (steps JSONB), ``workflow_instances``, ``workflow_steps``, ``workflow_delegations``.
Modules register hooks with ``@engine.on("leave.approval", "approved")`` so side effects stay in module code; the
engine only routes and records. Phase 04 completes approver resolution (``role`` / ``scope_rule`` / ``user``),
delegation, SLA escalation (Beat ``workflow.escalate``) and the inbox endpoint; the contract is fixed here.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.models.platform import WorkflowDefinition, WorkflowDelegation, WorkflowInstance, WorkflowStep

Hook = Callable[[AsyncSession, WorkflowInstance, Any], Awaitable[None]]
DECISIONS = {"approve", "reject", "delegate"}


class WorkflowEngine:
    def __init__(self) -> None:
        self._hooks: dict[tuple[str, str], list[Hook]] = {}

    # ---- registration -------------------------------------------------------------------------------------
    def on(self, key: str, event: str) -> Callable[[Hook], Hook]:
        """Decorator: ``@engine.on("leave.approval", "approved")`` (events: approved | rejected | step_approved | escalated)."""

        def deco(fn: Hook) -> Hook:
            self._hooks.setdefault((key, event), []).append(fn)
            return fn

        return deco

    async def _fire(self, db: AsyncSession, key: str, event: str, instance: WorkflowInstance, actor: Any) -> None:
        for hook in self._hooks.get((key, event), []):
            await hook(db, instance, actor)

    # ---- lifecycle ----------------------------------------------------------------------------------------
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
        instance = WorkflowInstance(
            institution_id=institution_id,
            definition_id=definition.id,
            entity_type=entity_type,
            entity_id=entity_id,
            title=title,
            status="pending",
            current_step=1,
            started_by=started_by,
            context=context,
        )
        db.add(instance)
        await db.flush()
        await self._materialise_step(db, definition, instance, 1)
        return instance

    async def _materialise_step(
        self, db: AsyncSession, definition: WorkflowDefinition, instance: WorkflowInstance, order: int
    ) -> None:
        steps = sorted(definition.steps, key=lambda s: s.get("order", 0))
        spec = next((s for s in steps if s.get("order") == order), None)
        if spec is None:
            return
        sla_hours = spec.get("sla_hours")
        approvers = await self.resolve_approvers(db, instance, spec.get("approver") or {})
        for approver_id, role_slug in approvers or [(None, (spec.get("approver") or {}).get("value"))]:
            db.add(
                WorkflowStep(
                    institution_id=instance.institution_id,
                    instance_id=instance.id,
                    step_order=order,
                    approver_user_id=await self._apply_delegation(db, instance, approver_id),
                    approver_role_slug=role_slug if isinstance(role_slug, str) else None,
                    status="pending",
                    sla_due_at=datetime.now(UTC) + timedelta(hours=sla_hours) if sla_hours else None,
                )
            )
        await db.flush()

    async def resolve_approvers(
        self, db: AsyncSession, instance: WorkflowInstance, approver: dict[str, Any]
    ) -> list[tuple[uuid.UUID | None, str | None]]:
        """``{"type":"user","value":<uuid>}`` resolves here; ``role`` / ``scope_rule`` resolution lands in Phase 04
        (users holding the role whose scope contains the entity's department/college)."""
        kind, value = approver.get("type"), approver.get("value")
        if kind == "user" and value:
            return [(uuid.UUID(str(value)), None)]
        if kind in {"role", "scope_rule"} and value:
            return [(None, str(value))]
        return []

    async def _apply_delegation(
        self, db: AsyncSession, instance: WorkflowInstance, approver_id: uuid.UUID | None
    ) -> uuid.UUID | None:
        if approver_id is None:
            return None
        today = datetime.now(UTC).date()
        delegate = (
            await db.execute(
                select(WorkflowDelegation.to_user_id).where(
                    and_(
                        WorkflowDelegation.institution_id == instance.institution_id,
                        WorkflowDelegation.from_user_id == approver_id,
                        WorkflowDelegation.is_active.is_(True),
                        WorkflowDelegation.from_on <= today,
                        WorkflowDelegation.to_on >= today,
                    )
                )
            )
        ).scalar_one_or_none()
        return delegate or approver_id

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
            raise APIError(400, ErrorCode.VALIDATION, f"decision must be one of {sorted(DECISIONS)}")
        instance = (
            await db.execute(select(WorkflowInstance).where(WorkflowInstance.id == instance_id).with_for_update())
        ).scalar_one_or_none()
        if instance is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Workflow instance not found")
        if instance.status != "pending":
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"Workflow already {instance.status}")
        step = await self._pending_step_for(db, instance, actor)
        now = datetime.now(UTC)
        definition = (
            await db.execute(select(WorkflowDefinition).where(WorkflowDefinition.id == instance.definition_id))
        ).scalar_one()
        key = definition.key
        if decision == "delegate":
            if not delegate_to:
                raise APIError(400, ErrorCode.VALIDATION, "delegate_to is required")
            step.status, step.acted_by, step.acted_at, step.comment = "delegated", actor.id, now, comment
            db.add(
                WorkflowStep(
                    institution_id=instance.institution_id,
                    instance_id=instance.id,
                    step_order=step.step_order,
                    approver_user_id=delegate_to,
                    status="pending",
                    sla_due_at=step.sla_due_at,
                )
            )
            await db.flush()
            return instance
        step.status = "approved" if decision == "approve" else "rejected"
        step.acted_by, step.acted_at, step.comment = actor.id, now, comment
        if decision == "reject":
            instance.status, instance.closed_at = "rejected", now
            await db.flush()
            await self._fire(db, key, "rejected", instance, actor)
            return instance
        spec = next((s for s in definition.steps if s.get("order") == step.step_order), {})
        if spec.get("mode") == "parallel":
            others_pending = (
                await db.execute(
                    select(WorkflowStep.id).where(
                        WorkflowStep.instance_id == instance.id,
                        WorkflowStep.step_order == step.step_order,
                        WorkflowStep.status == "pending",
                    )
                )
            ).first()
            if others_pending:
                await db.flush()
                return instance
        await self._fire(db, key, "step_approved", instance, actor)
        max_order = max((s.get("order", 0) for s in definition.steps), default=1)
        if step.step_order >= max_order:
            instance.status, instance.closed_at = "approved", now
            await db.flush()
            await self._fire(db, key, "approved", instance, actor)
        else:
            instance.current_step = step.step_order + 1
            await db.flush()
            await self._materialise_step(db, definition, instance, instance.current_step)
        return instance

    async def _pending_step_for(self, db: AsyncSession, instance: WorkflowInstance, actor: Any) -> WorkflowStep:
        q = select(WorkflowStep).where(
            WorkflowStep.instance_id == instance.id,
            WorkflowStep.step_order == instance.current_step,
            WorkflowStep.status == "pending",
        )
        steps = list((await db.execute(q)).scalars().all())
        role_slugs = set(getattr(actor, "roles", []) or [])
        for s in steps:
            if s.approver_user_id == actor.id or (s.approver_role_slug and s.approver_role_slug in role_slugs):
                return s
        if getattr(actor, "is_super_admin", False) and steps:
            return steps[0]
        raise APIError(403, ErrorCode.PERMISSION_DENIED, "You are not an approver for the current step")

    async def inbox(self, db: AsyncSession, principal: Any) -> list[WorkflowStep]:
        """All pending steps addressed to the user (directly, via delegation, or via one of their roles)."""
        role_slugs = list(getattr(principal, "roles", []) or [])
        conds = [WorkflowStep.approver_user_id == principal.id]
        if role_slugs:
            conds.append(WorkflowStep.approver_role_slug.in_(role_slugs))
        from sqlalchemy import or_

        q = (
            select(WorkflowStep)
            .join(WorkflowInstance, WorkflowInstance.id == WorkflowStep.instance_id)
            .where(
                WorkflowStep.institution_id == principal.institution_id,
                WorkflowStep.status == "pending",
                WorkflowInstance.status == "pending",
                WorkflowInstance.current_step == WorkflowStep.step_order,
                or_(*conds),
            )
            .order_by(WorkflowStep.sla_due_at.nulls_last(), WorkflowStep.created_at)
        )
        return list((await db.execute(q)).scalars().all())


engine = WorkflowEngine()
