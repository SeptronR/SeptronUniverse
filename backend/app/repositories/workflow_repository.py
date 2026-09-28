"""Workflow definitions, instances, steps and delegations — Prompts/04 §04.5 (``module="workflow"``).

Instance visibility (Prompts/04 "Visibility rules"): the requester (``started_by``), current and past approvers
(``workflow_steps.approver_user_id`` / ``acted_by`` / ``escalated_to`` — the ownership link) and administrators
holding ``settings:manage`` (the permission catalogue has no ``workflow`` module; definitions are edited with it too).
"""

import uuid
from collections.abc import Sequence
from datetime import date

from sqlalchemy import ColumnElement, Select, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.models.platform import User, WorkflowDefinition, WorkflowDelegation, WorkflowInstance, WorkflowStep
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta


def participant_predicate(user_id: uuid.UUID) -> ColumnElement[bool]:
    return or_(
        WorkflowInstance.started_by == user_id,
        exists().where(
            WorkflowStep.instance_id == WorkflowInstance.id,
            or_(
                WorkflowStep.approver_user_id == user_id,
                WorkflowStep.acted_by == user_id,
                WorkflowStep.escalated_to == user_id,
            ),
        ),
    )


class WorkflowRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ---- definitions --------------------------------------------------------------------------------------------
    async def latest_definitions(
        self, institution_id: uuid.UUID, module: str | None = None
    ) -> Sequence[WorkflowDefinition]:
        sub = (
            select(WorkflowDefinition.key, func.max(WorkflowDefinition.version).label("v"))
            .where(WorkflowDefinition.institution_id == institution_id)
            .group_by(WorkflowDefinition.key)
            .subquery()
        )
        q = (
            select(WorkflowDefinition)
            .join(sub, (sub.c.key == WorkflowDefinition.key) & (sub.c.v == WorkflowDefinition.version))
            .where(WorkflowDefinition.institution_id == institution_id)
        )
        if module:
            q = q.where(WorkflowDefinition.module == module)
        return (await self.db.execute(q.order_by(WorkflowDefinition.module, WorkflowDefinition.key))).scalars().all()

    async def definition(self, institution_id: uuid.UUID, definition_id: uuid.UUID) -> WorkflowDefinition:
        row = (
            await self.db.execute(
                select(WorkflowDefinition).where(
                    WorkflowDefinition.institution_id == institution_id, WorkflowDefinition.id == definition_id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Workflow definition not found")
        return row

    async def versions(self, institution_id: uuid.UUID, key: str) -> Sequence[WorkflowDefinition]:
        return (
            (
                await self.db.execute(
                    select(WorkflowDefinition)
                    .where(WorkflowDefinition.institution_id == institution_id, WorkflowDefinition.key == key)
                    .order_by(WorkflowDefinition.version.desc())
                )
            )
            .scalars()
            .all()
        )

    async def definitions_by_id(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, WorkflowDefinition]:
        if not ids:
            return {}
        rows = (await self.db.execute(select(WorkflowDefinition).where(WorkflowDefinition.id.in_(ids)))).scalars()
        return {d.id: d for d in rows}

    # ---- instances ----------------------------------------------------------------------------------------------
    def instances(
        self,
        institution_id: uuid.UUID,
        viewer: uuid.UUID | None,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        status: str | None = None,
        mine: bool = False,
    ) -> Select[tuple[WorkflowInstance]]:
        q = select(WorkflowInstance).where(WorkflowInstance.institution_id == institution_id)
        if viewer is not None:
            q = q.where(participant_predicate(viewer))
        if mine and viewer is not None:
            q = q.where(WorkflowInstance.started_by == viewer)
        if entity_type:
            q = q.where(WorkflowInstance.entity_type == entity_type)
        if entity_id:
            q = q.where(WorkflowInstance.entity_id == entity_id)
        if status:
            q = q.where(WorkflowInstance.status == status)
        return q

    async def paginate(
        self, q: Select[tuple[WorkflowInstance]], params: PageParams
    ) -> tuple[Sequence[WorkflowInstance], PaginationMeta]:
        total = (await self.db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
        rows = (
            (
                await self.db.execute(
                    q.order_by(WorkflowInstance.started_at.desc()).offset(params.offset).limit(params.page_size)
                )
            )
            .scalars()
            .all()
        )
        return rows, PaginationMeta(
            page=params.page, page_size=params.page_size, total=total, total_pages=max(1, -(-total // params.page_size))
        )

    async def instance(
        self, institution_id: uuid.UUID, instance_id: uuid.UUID, viewer: uuid.UUID | None
    ) -> WorkflowInstance:
        row = (
            await self.db.execute(self.instances(institution_id, viewer).where(WorkflowInstance.id == instance_id))
        ).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Workflow instance not found")
        return row

    async def steps(self, instance_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[WorkflowStep]]:
        if not instance_ids:
            return {}
        rows = (
            await self.db.execute(
                select(WorkflowStep)
                .where(WorkflowStep.instance_id.in_(instance_ids))
                .order_by(WorkflowStep.step_order, WorkflowStep.created_at)
            )
        ).scalars()
        out: dict[uuid.UUID, list[WorkflowStep]] = {}
        for s in rows:
            out.setdefault(s.instance_id, []).append(s)
        return out

    async def user_names(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
        ids = [i for i in ids if i]
        if not ids:
            return {}
        rows = (await self.db.execute(select(User.id, User.display_name, User.username).where(User.id.in_(ids)))).all()
        return {r[0]: r[1] or r[2] for r in rows}

    # ---- delegations --------------------------------------------------------------------------------------------
    async def delegations(self, institution_id: uuid.UUID, user_id: uuid.UUID | None) -> Sequence[WorkflowDelegation]:
        q = select(WorkflowDelegation).where(
            WorkflowDelegation.institution_id == institution_id, WorkflowDelegation.is_active.is_(True)
        )
        if user_id is not None:
            q = q.where(or_(WorkflowDelegation.from_user_id == user_id, WorkflowDelegation.to_user_id == user_id))
        return (await self.db.execute(q.order_by(WorkflowDelegation.from_on.desc()))).scalars().all()

    async def delegation(self, institution_id: uuid.UUID, delegation_id: uuid.UUID) -> WorkflowDelegation:
        row = (
            await self.db.execute(
                select(WorkflowDelegation).where(
                    WorkflowDelegation.institution_id == institution_id, WorkflowDelegation.id == delegation_id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Delegation not found")
        return row

    async def overlapping_delegation(
        self, institution_id: uuid.UUID, from_user: uuid.UUID, module: str | None, start: date, end: date
    ) -> WorkflowDelegation | None:
        q = select(WorkflowDelegation).where(
            WorkflowDelegation.institution_id == institution_id,
            WorkflowDelegation.from_user_id == from_user,
            WorkflowDelegation.is_active.is_(True),
            WorkflowDelegation.from_on <= end,
            WorkflowDelegation.to_on >= start,
        )
        if module:
            q = q.where(or_(WorkflowDelegation.module.is_(None), WorkflowDelegation.module == module))
        return (await self.db.execute(q.limit(1))).scalar_one_or_none()
