"""Visibility registrations of Phase 01 (Prompts/01 "Visibility rules"; docs/Authorization_and_Visibility.md).

* ``jobs``     — self = requester; ``jobs:view_all`` widens to the institution (institution_admin / integration_admin);
                 super admin sees every tenant.
* ``feedback`` — self; ``settings:view_all`` sees the institution (checked in ``FeedbackRepository.list_visible``
                 because the widening permission belongs to another module).
``help_articles`` need no registration: everyone in the institution reads them (+ platform articles).
``notifications`` (self only) are registered by Phase 04 with the notifications module.
"""

from typing import Any

from sqlalchemy import ColumnElement

from app.core.authz.visibility import ModuleVisibility, register_module
from app.models.platform import BackgroundJob, FeedbackEntry


def _job_is_mine(principal: Any, model: Any) -> ColumnElement[bool]:
    return model.requested_by == principal.id  # type: ignore[no-any-return]


def _feedback_is_mine(principal: Any, model: Any) -> ColumnElement[bool]:
    return model.user_id == principal.id  # type: ignore[no-any-return]


register_module(
    ModuleVisibility(
        module="jobs",
        model=BackgroundJob,
        self_predicate=_job_is_mine,
        scope_columns={"institution": "institution_id"},
    )
)

register_module(
    ModuleVisibility(
        module="feedback",
        model=FeedbackEntry,
        self_predicate=_feedback_is_mine,
        scope_columns={"institution": "institution_id"},
    )
)
