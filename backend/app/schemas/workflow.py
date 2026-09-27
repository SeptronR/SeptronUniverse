"""Workflow schemas — Prompts/04 §04.4 (definitions, instances, steps, actions, delegations, inbox)."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import ORMModel


class ApproverSpec(BaseModel):
    type: Literal["role", "scope_rule", "user"]
    value: str = Field(min_length=1, max_length=120)


class StepSpec(BaseModel):
    order: int = Field(ge=1, le=20)
    approver: ApproverSpec
    mode: Literal["sequential", "parallel"] = "sequential"
    sla_hours: float | None = Field(default=None, gt=0, le=24 * 90)
    escalate_to: ApproverSpec | None = None


class WorkflowDefinitionCreate(BaseModel):
    module: str = Field(min_length=2, max_length=60)
    key: str = Field(min_length=3, max_length=80, pattern=r"^[a-z0-9_]+\.[a-z0-9_.]+$")
    name: str = Field(min_length=2, max_length=120)
    description: str | None = None
    steps: list[StepSpec] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def _orders(self) -> "WorkflowDefinitionCreate":
        _check_orders(self.steps)
        return self


class WorkflowDefinitionUpdate(BaseModel):
    """Saving creates a new version; running instances keep the version they started with."""

    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = None
    steps: list[StepSpec] | None = Field(default=None, min_length=1, max_length=40)
    is_active: bool | None = None

    @model_validator(mode="after")
    def _orders(self) -> "WorkflowDefinitionUpdate":
        if self.steps:
            _check_orders(self.steps)
        return self


def _check_orders(steps: list[StepSpec]) -> None:
    orders = sorted({s.order for s in steps})
    if orders != list(range(1, len(orders) + 1)):
        raise ValueError("step orders must be consecutive from 1")
    for o in orders:
        modes = {s.mode for s in steps if s.order == o}
        if len(modes) > 1:
            raise ValueError(f"step {o} mixes sequential and parallel approvers")


class WorkflowDefinitionResponse(ORMModel):
    id: uuid.UUID
    module: str
    key: str
    name: str
    description: str | None = None
    steps: list[dict[str, Any]]
    version: int
    is_active: bool
    updated_at: datetime
    versions: list[int] = Field(default_factory=list)


class StepResponse(BaseModel):
    id: uuid.UUID
    order: int
    approver_user_id: uuid.UUID | None = None
    approver_name: str | None = None
    approver_role_slug: str | None = None
    status: str
    acted_by: uuid.UUID | None = None
    acted_by_name: str | None = None
    delegated_from: uuid.UUID | None = None
    acted_at: datetime | None = None
    comment: str | None = None
    sla_due_at: datetime | None = None
    escalated_to: uuid.UUID | None = None


class WorkflowInstanceResponse(BaseModel):
    id: uuid.UUID
    definition_id: uuid.UUID
    key: str
    module: str
    version: int
    entity_type: str
    entity_id: uuid.UUID
    title: str | None = None
    status: str
    current_step: int
    total_steps: int
    started_by: uuid.UUID | None = None
    started_by_name: str | None = None
    started_at: datetime
    closed_at: datetime | None = None
    context: dict[str, Any] | None = None
    steps: list[StepResponse] = Field(default_factory=list)
    can_act: bool = False
    can_cancel: bool = False


class WorkflowActRequest(BaseModel):
    decision: Literal["approve", "reject", "delegate"]
    comment: str | None = Field(default=None, max_length=2000)
    delegate_to: uuid.UUID | None = None

    @model_validator(mode="after")
    def _delegate(self) -> "WorkflowActRequest":
        if self.decision == "delegate" and not self.delegate_to:
            raise ValueError("delegate_to is required to delegate")
        if self.decision == "reject" and not (self.comment or "").strip():
            raise ValueError("a comment is required to reject")
        return self


class WorkflowCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class DelegationCreate(BaseModel):
    to_user_id: uuid.UUID
    module: str | None = Field(default=None, max_length=60, description="NULL = every module")
    from_on: date
    to_on: date

    @model_validator(mode="after")
    def _range(self) -> "DelegationCreate":
        if self.to_on < self.from_on:
            raise ValueError("to_on must be on or after from_on")
        return self


class DelegationResponse(ORMModel):
    id: uuid.UUID
    from_user_id: uuid.UUID
    to_user_id: uuid.UUID
    to_user_name: str | None = None
    from_user_name: str | None = None
    module: str | None = None
    from_on: date
    to_on: date
    is_active: bool
    created_at: datetime


class InboxItem(BaseModel):
    instance: WorkflowInstanceResponse
    step_id: uuid.UUID
    entity_summary: str | None = None
    route: str | None = None
    via: Literal["direct", "role", "delegation", "escalation"] = "direct"


class DevWorkflowStart(BaseModel):
    key: str = Field(max_length=80)
    context: dict[str, Any] = Field(default_factory=dict)
    title: str | None = Field(default=None, max_length=200)
    requester: uuid.UUID | None = Field(default=None, description="started_by (defaults to the caller)")
    entity_id: uuid.UUID | None = None
