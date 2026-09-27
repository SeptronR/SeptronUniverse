"""Visibility registrations of Phase 04 (Prompts/04 "Visibility rules"; docs/Authorization_and_Visibility.md).

* ``notifications`` / ``notification_preferences`` / ``device_tokens`` — self only (queries always filter on the
  caller's user id);
* ``communication`` (message logs) — ``communication:view_all``, recipient masked without ``communication:view_pii``;
* ``workflow`` — self = the requester (``started_by``), ownership link = current/past approver
  (``workflow_steps.approver_user_id`` / ``acted_by`` / ``escalated_to``); ``settings:manage`` administrators see all.
"""

from typing import Any

from sqlalchemy import ColumnElement

from app.core.authz.visibility import ModuleVisibility, OwnershipLink, register_link, register_module
from app.models.communication import Notification
from app.models.platform import WorkflowInstance


def _mine(principal: Any, model: Any) -> ColumnElement[bool]:
    return model.user_id == principal.id  # type: ignore[no-any-return]


def _requester(principal: Any, model: Any) -> ColumnElement[bool]:
    return model.started_by == principal.id  # type: ignore[no-any-return]


def _approver(principal: Any, model: Any) -> ColumnElement[bool]:
    from app.repositories.workflow_repository import participant_predicate

    return participant_predicate(principal.id)


register_module(ModuleVisibility(module="notifications", model=Notification, self_predicate=_mine))
register_module(
    ModuleVisibility(
        module="workflow",
        model=WorkflowInstance,
        self_predicate=_requester,
        scope_columns={"institution": "institution_id"},
    )
)
register_link(OwnershipLink(module="workflow", name="approver", predicate=_approver))
