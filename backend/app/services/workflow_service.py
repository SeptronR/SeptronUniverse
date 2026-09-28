"""Workflow administration and participation — Prompts/04 §04.6 (``core/workflow/engine.py`` does the routing).

Business rules
1. Definitions (``settings:view`` to read, ``settings:manage`` to edit; ``workflow.engine``): the latest version of
   every key with its version list; editing creates **version n+1** (older versions become inactive, running
   instances keep the version they started with); approver roles must exist in the institution and user approvers
   must be members (422); ``sla_hours`` > 0 (schema).
2. Inbox: the engine's open steps for the caller (direct, role pool, delegation, escalation) with entity summaries.
3. Instances: requester, current/past approvers and ``settings:manage`` administrators (404 otherwise); ``can_act``
   and ``can_cancel`` computed for the caller; ``delegated_from`` = the original approver when someone else acted.
4. ``act`` / ``cancel`` delegate to the engine (audited — ``workflow`` module).
5. Delegations (``workflow.delegation``): the caller delegates their approvals (all modules or one) for a date
   range to another active member; overlapping active delegations of the same scope → 409; only the delegator (or an
   administrator) removes one.
"""

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_audit
from app.core.errors import APIError, ErrorCode
from app.core.workflow import engine
from app.models.platform import Role, User, WorkflowDefinition, WorkflowDelegation, WorkflowInstance, WorkflowStep
from app.repositories.workflow_repository import WorkflowRepository
from app.schemas.workflow import (
    DelegationCreate,
    DelegationResponse,
    InboxItem,
    StepResponse,
    WorkflowActRequest,
    WorkflowDefinitionCreate,
    WorkflowDefinitionResponse,
    WorkflowDefinitionUpdate,
    WorkflowInstanceResponse,
)
from app.services.institution.context import tenant_id
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta


class WorkflowService:
    def __init__(self, db: AsyncSession, principal: Any, request: Request | None = None):
        self.db, self.principal, self.request = db, principal, request
        self.inst = tenant_id(principal, request)
        self.repo = WorkflowRepository(db)

    @property
    def is_admin(self) -> bool:
        return bool(self.principal.has("settings", "manage"))

    async def _audit(
        self,
        action: str,
        record_type: str,
        record_id: uuid.UUID,
        new: dict[str, Any],
        old: dict[str, Any] | None = None,
    ) -> None:
        await log_audit(
            self.db,
            principal=self.principal,
            module="workflow",
            action=action,
            record_type=record_type,
            record_id=record_id,
            old=old,
            new=new,
            request=self.request,
        )

    # ---- rule 1 ---------------------------------------------------------------------------------------------------
    async def _definition_response(self, d: WorkflowDefinition) -> WorkflowDefinitionResponse:
        r = WorkflowDefinitionResponse.model_validate(d)
        r.versions = [v.version for v in await self.repo.versions(self.inst, d.key)]
        return r

    async def definitions(self, module: str | None) -> list[WorkflowDefinitionResponse]:
        return [await self._definition_response(d) for d in await self.repo.latest_definitions(self.inst, module)]

    async def definition(self, definition_id: uuid.UUID) -> WorkflowDefinitionResponse:
        return await self._definition_response(await self.repo.definition(self.inst, definition_id))

    async def definition_versions(self, definition_id: uuid.UUID) -> list[WorkflowDefinitionResponse]:
        d = await self.repo.definition(self.inst, definition_id)
        return [WorkflowDefinitionResponse.model_validate(v) for v in await self.repo.versions(self.inst, d.key)]

    async def _validate_steps(self, steps: list[dict[str, Any]]) -> None:
        roles = set(
            (
                await self.db.execute(
                    select(Role.slug).where(Role.institution_id == self.inst, Role.deleted_at.is_(None))
                )
            ).scalars()
        )
        for s in steps:
            for spec in (s["approver"], s.get("escalate_to")):
                if not spec:
                    continue
                if spec["type"] == "role" and spec["value"] not in roles:
                    raise APIError(
                        422,
                        ErrorCode.VALIDATION,
                        f"Unknown role {spec['value']!r} in step {s['order']}",
                        {"field": "steps"},
                    )
                if spec["type"] == "user":
                    try:
                        uid = uuid.UUID(spec["value"])
                    except ValueError:
                        raise APIError(
                            422, ErrorCode.VALIDATION, f"Invalid user id in step {s['order']}", {"field": "steps"}
                        ) from None
                    ok = (
                        await self.db.execute(
                            select(User.id).where(
                                User.id == uid, User.institution_id == self.inst, User.is_active.is_(True)
                            )
                        )
                    ).first()
                    if ok is None:
                        raise APIError(
                            422,
                            ErrorCode.VALIDATION,
                            f"User approver of step {s['order']} is not an active member",
                            {"field": "steps"},
                        )
                if spec["type"] == "scope_rule" and not (
                    spec["value"] in ("entity.department.hod", "entity.college.principal", "requester.manager")
                    or spec["value"].startswith("context.")
                ):
                    raise APIError(
                        422, ErrorCode.VALIDATION, f"Unknown scope rule {spec['value']!r}", {"field": "steps"}
                    )

    async def create_definition(self, body: WorkflowDefinitionCreate) -> WorkflowDefinitionResponse:
        if await self.repo.versions(self.inst, body.key):
            raise APIError(
                409,
                ErrorCode.CONFLICT,
                f"Workflow {body.key!r} exists; edit it to create a new version",
                {"field": "key"},
            )
        steps = [s.model_dump(exclude_none=True) for s in body.steps]
        await self._validate_steps(steps)
        d = WorkflowDefinition(
            institution_id=self.inst,
            module=body.module,
            key=body.key,
            name=body.name,
            description=body.description,
            steps=steps,
            version=1,
            is_active=True,
            created_by=self.principal.id,
        )
        self.db.add(d)
        await self.db.flush()
        await self._audit("create", "workflow_definition", d.id, {"key": d.key, "steps": steps})
        return await self._definition_response(d)

    async def update_definition(
        self, definition_id: uuid.UUID, body: WorkflowDefinitionUpdate
    ) -> WorkflowDefinitionResponse:
        base = await self.repo.definition(self.inst, definition_id)
        latest = (await self.repo.versions(self.inst, base.key))[0]
        steps = [s.model_dump(exclude_none=True) for s in body.steps] if body.steps else latest.steps
        await self._validate_steps(steps)
        for v in await self.repo.versions(self.inst, base.key):
            v.is_active = False
        d = WorkflowDefinition(
            institution_id=self.inst,
            module=latest.module,
            key=latest.key,
            name=body.name or latest.name,
            description=body.description if body.description is not None else latest.description,
            steps=steps,
            version=latest.version + 1,
            is_active=True if body.is_active is None else body.is_active,
            created_by=self.principal.id,
        )
        self.db.add(d)
        await self.db.flush()
        await self._audit(
            "version",
            "workflow_definition",
            d.id,
            {"key": d.key, "version": d.version, "steps": steps},
            {"version": latest.version, "steps": latest.steps},
        )
        return await self._definition_response(d)

    # ---- rule 3 ---------------------------------------------------------------------------------------------------
    async def _instance_responses(self, rows: list[WorkflowInstance]) -> list[WorkflowInstanceResponse]:
        steps = await self.repo.steps([i.id for i in rows])
        defs = await self.repo.definitions_by_id(list({i.definition_id for i in rows}))
        ids: set[uuid.UUID] = set()
        for i in rows:
            if i.started_by:
                ids.add(i.started_by)
            for s in steps.get(i.id, []):
                ids |= {x for x in (s.approver_user_id, s.acted_by) if x}
        names = await self.repo.user_names(sorted(ids, key=str))
        delegators = {f for f, _ in await engine.delegators_of(self.db, self.inst, self.principal.id)}
        roles = set(getattr(self.principal, "roles", []) or [])
        out = []
        for i in rows:
            d = defs[i.definition_id]
            srows = steps.get(i.id, [])
            open_now = [s for s in srows if s.step_order == i.current_step and s.status in ("pending", "escalated")]
            can_act = i.status in ("pending", "escalated") and any(
                s.approver_user_id == self.principal.id
                or s.escalated_to == self.principal.id
                or (s.approver_user_id is None and s.approver_role_slug in roles)
                or s.approver_user_id in delegators
                for s in open_now
            )
            out.append(
                WorkflowInstanceResponse(
                    id=i.id,
                    definition_id=d.id,
                    key=d.key,
                    module=d.module,
                    version=d.version,
                    entity_type=i.entity_type,
                    entity_id=i.entity_id,
                    title=i.title,
                    status=i.status,
                    current_step=i.current_step,
                    total_steps=max((int(s.get("order", 0)) for s in d.steps), default=1),
                    started_by=i.started_by,
                    started_by_name=names.get(i.started_by) if i.started_by else None,
                    started_at=i.started_at,
                    closed_at=i.closed_at,
                    context=i.context,
                    steps=[self._step(s, names) for s in srows],
                    can_act=can_act,
                    can_cancel=i.status in ("pending", "escalated")
                    and (i.started_by == self.principal.id or self.principal.is_super_admin),
                )
            )
        return out

    @staticmethod
    def _step(s: WorkflowStep, names: dict[uuid.UUID, str]) -> StepResponse:
        delegated_from = (
            s.approver_user_id if (s.acted_by and s.approver_user_id and s.acted_by != s.approver_user_id) else None
        )
        return StepResponse(
            id=s.id,
            order=s.step_order,
            approver_user_id=s.approver_user_id,
            approver_name=names.get(s.approver_user_id) if s.approver_user_id else None,
            approver_role_slug=s.approver_role_slug,
            status=s.status,
            acted_by=s.acted_by,
            acted_by_name=names.get(s.acted_by) if s.acted_by else None,
            delegated_from=delegated_from,
            acted_at=s.acted_at,
            comment=s.comment,
            sla_due_at=s.sla_due_at,
            escalated_to=s.escalated_to,
        )

    async def instances(
        self, params: PageParams, entity_type: str | None, entity_id: uuid.UUID | None, status: str | None, mine: bool
    ) -> tuple[list[WorkflowInstanceResponse], PaginationMeta, VisibilityMeta]:
        viewer = None if (self.is_admin and not mine) else self.principal.id
        q = self.repo.instances(self.inst, viewer, entity_type, entity_id, status, mine)
        rows, pagination = await self.repo.paginate(q, params)
        visibility = VisibilityMeta(self=True, scopes=["all"] if self.is_admin else [], default="self")
        return await self._instance_responses(list(rows)), pagination, visibility

    async def instance(self, instance_id: uuid.UUID) -> WorkflowInstanceResponse:
        viewer = None if self.is_admin else self.principal.id
        return (await self._instance_responses([await self.repo.instance(self.inst, instance_id, viewer)]))[0]

    # ---- rule 2 ---------------------------------------------------------------------------------------------------
    async def inbox(self) -> list[InboxItem]:
        rows = await engine.inbox(self.db, self.principal)
        responses = {r.id: r for r in await self._instance_responses([i for _, i, _ in rows])}
        delegators = {f for f, _ in await engine.delegators_of(self.db, self.inst, self.principal.id)}
        out = []
        for step, instance, _ in rows:
            summary, route = await engine.summarise(self.db, instance.entity_type, instance.entity_id)
            via = (
                "direct"
                if step.approver_user_id == self.principal.id
                else (
                    "escalation"
                    if step.escalated_to == self.principal.id
                    else "delegation" if step.approver_user_id in delegators else "role"
                )
            )
            out.append(
                InboxItem(
                    instance=responses[instance.id],
                    step_id=step.id,
                    entity_summary=summary or instance.title,
                    route=route or f"/approvals/instances/{instance.id}",
                    via=via,  # type: ignore[arg-type]
                )
            )
        return out

    # ---- rule 4 ---------------------------------------------------------------------------------------------------
    async def act(self, instance_id: uuid.UUID, body: WorkflowActRequest) -> WorkflowInstanceResponse:
        await self.repo.instance(self.inst, instance_id, None)  # tenant check (404 across institutions)
        instance = await engine.act(
            self.db,
            instance_id=instance_id,
            actor=self.principal,
            decision=body.decision,
            comment=body.comment,
            delegate_to=body.delegate_to,
        )
        await self._audit(
            "act",
            "workflow_instance",
            instance.id,
            {"decision": body.decision, "comment": body.comment, "status": instance.status},
        )
        return (await self._instance_responses([instance]))[0]

    async def cancel(self, instance_id: uuid.UUID, reason: str | None) -> WorkflowInstanceResponse:
        await self.repo.instance(self.inst, instance_id, self.principal.id)
        instance = await engine.cancel(self.db, instance_id=instance_id, actor=self.principal, reason=reason)
        await self._audit("cancel", "workflow_instance", instance.id, {"reason": reason})
        return (await self._instance_responses([instance]))[0]

    # ---- rule 5 ---------------------------------------------------------------------------------------------------
    async def delegations(self, all_: bool) -> list[DelegationResponse]:
        rows = await self.repo.delegations(self.inst, None if (all_ and self.is_admin) else self.principal.id)
        names = await self.repo.user_names(sorted({x for r in rows for x in (r.from_user_id, r.to_user_id)}, key=str))
        out = []
        for r in rows:
            d = DelegationResponse.model_validate(r)
            d.from_user_name, d.to_user_name = names.get(r.from_user_id), names.get(r.to_user_id)
            out.append(d)
        return out

    async def create_delegation(self, body: DelegationCreate) -> DelegationResponse:
        if body.to_user_id == self.principal.id:
            raise APIError(422, ErrorCode.VALIDATION, "You cannot delegate to yourself", {"field": "to_user_id"})
        target = (
            await self.db.execute(
                select(User).where(
                    User.id == body.to_user_id, User.institution_id == self.inst, User.is_active.is_(True)
                )
            )
        ).scalar_one_or_none()
        if target is None:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "The delegate must be an active member of the institution",
                {"field": "to_user_id"},
            )
        if await self.repo.overlapping_delegation(self.inst, self.principal.id, body.module, body.from_on, body.to_on):
            raise APIError(409, ErrorCode.CONFLICT, "An active delegation already covers these dates")
        row = WorkflowDelegation(
            institution_id=self.inst,
            from_user_id=self.principal.id,
            to_user_id=body.to_user_id,
            module=body.module,
            from_on=body.from_on,
            to_on=body.to_on,
            is_active=True,
        )
        self.db.add(row)
        await self.db.flush()
        await self._audit("delegate", "workflow_delegation", row.id, body.model_dump(mode="json"))
        d = DelegationResponse.model_validate(row)
        d.to_user_name = target.display_name or target.username
        return d

    async def delete_delegation(self, delegation_id: uuid.UUID) -> None:
        row = await self.repo.delegation(self.inst, delegation_id)
        if row.from_user_id != self.principal.id and not self.is_admin:
            raise APIError(404, ErrorCode.NOT_FOUND, "Delegation not found")
        row.is_active = False
        await self.db.flush()
        await self._audit("revoke", "workflow_delegation", row.id, {"is_active": False})
