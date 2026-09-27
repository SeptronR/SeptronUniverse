"""Visibility registrations of Phase 02 (Prompts/02 "Visibility rules"; docs/Authorization_and_Visibility.md).

* ``users`` — self = the user's own row; ``users:view_all`` widens to the institution scope, and a college-scoped
  assignment (college_admin, college-scoped officers) to the users holding a role assignment in that college
  (``user_roles.scope_type = 'college'``); super admin sees every tenant.
* ``roles`` — institution-wide read for every admin holding ``roles:view`` (handled in ``RoleRepository``).
* ``user_sessions`` / ``login_history`` / ``mfa_secrets`` — self only (``AuthService``); support views are masked.
"""

from typing import Any

from sqlalchemy import ColumnElement, false, select

from app.core.authz.visibility import ModuleVisibility, OwnershipLink, register_link, register_module
from app.models.platform import User, UserRole


def _user_is_me(principal: Any, model: Any) -> ColumnElement[bool]:
    return model.id == principal.id  # type: ignore[no-any-return]


def _college_members(principal: Any, model: Any) -> ColumnElement[bool]:
    """Users assigned a role inside one of the principal's college scopes (only with ``users:view_all``)."""
    if not principal.has("users", "view_all"):
        return false()
    college_ids = [sid for st, sid in principal.scopes if st == "college" and sid is not None]
    if not college_ids:
        return false()
    return model.id.in_(  # type: ignore[no-any-return]
        select(UserRole.user_id).where(UserRole.scope_type == "college", UserRole.scope_id.in_(college_ids))
    )


register_module(
    ModuleVisibility(
        module="users",
        model=User,
        self_predicate=_user_is_me,
        scope_columns={"institution": "institution_id"},
    )
)
register_link(OwnershipLink(module="users", name="college_membership", predicate=_college_members))
