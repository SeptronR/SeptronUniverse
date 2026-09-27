"""Roles, permission matrix and scoped assignments — Prompts/02 §02.6 ``rbac_service``.

Business rules
1. Roles are per institution (cloned from the 51 platform templates by ``seed_institution_roles``); listing/reading
   needs ``roles:view``, editing ``roles:update`` / ``roles:manage``. **System roles cannot be deleted or renamed**
   (name/slug immutable → 409 RULE_VIOLATION); a role with assignments cannot be deleted (409).
2. ``clone`` copies a role (permissions included) into a new non-system role of the institution.
3. Permission matrix: ``get_matrix`` returns rows = modules × columns = catalogue actions with ``granted``;
   ``set_matrix`` applies only the cells sent (partial update), audits the diff (``old``/``new`` key lists) and emits
   ``role.updated``. ``users:impersonate`` / ``features:manage`` are platform-only and cannot be granted to tenant
   roles (422).
4. Assignments: ``assign`` validates the scope against the role (docs/Roles_and_Permissions.md §4 through
   ``allowed_scope_types``): unit-scoped roles (dean → faculty, hod → department, class_advisor → offering,
   committee_secretary → committee, college_admin → college) need a ``scope_id`` that exists **inside the institution**
   (422 otherwise); ``self`` roles carry no scope id; duplicates → 409. Events ``user_role.assigned`` /
   ``user_role.revoked``; every change audited.
5. ``seed_institution_roles(institution_id)`` — idempotent: every template missing in the tenant is cloned with its
   grants (Phase 03 calls it on institution creation; the demo seeder calls it for ``demo-uni``).
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.audit import log_audit
from app.core.authz.dependencies import Principal
from app.core.errors import APIError, ErrorCode
from app.core.rbac.registry import (
    ACTIONS_BY_MODULE,
    MODULES,
    PLATFORM_ONLY_PERMISSIONS,
    PLATFORM_ROLES,
    STANDARD_ACTIONS,
    allowed_scope_types,
)
from app.models.platform import Role, User, UserRole
from app.repositories.role_repository import PermissionRepository, RoleRepository
from app.repositories.user_repository import UserRepository
from app.repositories.user_role_repository import UserRoleRepository
from app.schemas.rbac import (
    MatrixAction,
    MatrixModule,
    PermissionCatalogue,
    PermissionResponse,
    RoleCloneRequest,
    RoleCreate,
    RolePermissionMatrix,
    RolePermissionMatrixUpdate,
    RoleResponse,
    RoleUpdate,
    UserRoleAssign,
    UserRoleResponse,
)
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta


class RbacService:
    def __init__(self, db: AsyncSession, principal: Principal | None = None):
        self.db, self.principal = db, principal
        self.roles = RoleRepository(db, principal)
        self.perms = PermissionRepository(db)
        self.assignments = UserRoleRepository(db)

    @property
    def institution_id(self) -> uuid.UUID | None:
        return self.principal.institution_id if self.principal else None

    def _tenant(self, request: Request | None) -> uuid.UUID:
        """Institution the call operates on: the principal's, or ``X-Institution-Id`` for the super admin."""
        inst = self.institution_id
        if inst is None and request is not None and self.principal is not None and self.principal.is_super_admin:
            raw = getattr(request.state, "institution_id", None)
            inst = uuid.UUID(str(raw)) if raw else None
        if inst is None:
            raise APIError(422, ErrorCode.VALIDATION, "An institution context is required (X-Institution-Id)")
        return inst

    # ---- catalogue --------------------------------------------------------------------------------------------
    async def catalogue(self) -> PermissionCatalogue:
        rows = await self.perms.all()
        return PermissionCatalogue(
            modules=list(MODULES),
            standard_actions=list(STANDARD_ACTIONS),
            permissions=[PermissionResponse.model_validate(p) for p in rows],
        )

    # ---- rule 1 -----------------------------------------------------------------------------------------------
    async def list_roles(
        self, params: PageParams, q: str | None, request: Request | None = None
    ) -> tuple[list[RoleResponse], PaginationMeta]:
        inst = self._tenant(request)
        rows, pagination = await self.roles.list_roles(params, inst, q)
        keys = await self.roles.permission_keys_many([r.id for r in rows])
        out = []
        for r in rows:
            resp = RoleResponse.model_validate(r)
            resp.permission_count = len(keys.get(r.id, set()))
            resp.assignment_count = await self.roles.assignment_count(r.id)
            out.append(resp)
        return out, pagination

    async def get_role(self, role_id: uuid.UUID, request: Request | None = None) -> RoleResponse:
        role = await self._role(role_id, request)
        resp = RoleResponse.model_validate(role)
        resp.permission_count = len(await self.roles.permission_keys(role.id))
        resp.assignment_count = await self.roles.assignment_count(role.id)
        return resp

    async def _role(self, role_id: uuid.UUID, request: Request | None) -> Role:
        role = await self.roles.get_role(role_id, self._tenant(request))
        if role is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Role not found")
        return role

    async def create_role(self, body: RoleCreate, request: Request | None = None) -> RoleResponse:
        inst = self._tenant(request)
        if await self.roles.get_by_slug(body.slug, inst):
            raise APIError(409, ErrorCode.CONFLICT, f"A role with slug {body.slug!r} already exists", {"field": "slug"})
        self._check_grantable(body.permissions)
        role = await self.roles.create_role(
            institution_id=inst,
            name=body.name,
            slug=body.slug,
            description=body.description,
            is_system=False,
            default_scope_type=body.default_scope_type,
            portal=body.portal,
            created_by=self.principal.id if self.principal else None,
        )
        if body.permissions:
            found = await self.perms.by_keys(body.permissions)
            await self.roles.add_permissions(role.id, [p.id for p in found.values()])
        await self._audit_role(
            "create",
            role,
            old=None,
            new={"name": role.name, "slug": role.slug, "permissions": sorted(body.permissions)},
            request=request,
        )
        return await self.get_role(role.id, request)

    async def update_role(self, role_id: uuid.UUID, body: RoleUpdate, request: Request | None = None) -> RoleResponse:
        role = await self._role(role_id, request)
        if role.is_system and body.name is not None and body.name != role.name:
            raise APIError(409, ErrorCode.RULE_VIOLATION, "System roles cannot be renamed", {"field": "name"})
        old = {
            "name": role.name,
            "description": role.description,
            "default_scope_type": role.default_scope_type,
            "portal": role.portal,
            "is_active": role.is_active,
        }
        values = dict(body.model_dump(exclude_unset=True, exclude={"version"}))
        await self.roles.update(role, expected_version=body.version, **values)
        await self._audit_role("update", role, old=old, new={**old, **values}, request=request)
        return await self.get_role(role.id, request)

    async def delete_role(self, role_id: uuid.UUID, request: Request | None = None) -> None:
        role = await self._role(role_id, request)
        if role.is_system:
            raise APIError(409, ErrorCode.RULE_VIOLATION, "System roles cannot be deleted")
        if await self.roles.assignment_count(role.id):
            raise APIError(409, ErrorCode.RULE_VIOLATION, "Role is assigned to users; revoke the assignments first")
        await self.roles.soft_delete(role, self.principal.id if self.principal else None)
        await self._audit_role("delete", role, old={"name": role.name, "slug": role.slug}, new=None, request=request)

    # ---- rule 2 -----------------------------------------------------------------------------------------------
    async def clone_role(
        self, role_id: uuid.UUID, body: RoleCloneRequest, request: Request | None = None
    ) -> RoleResponse:
        source = await self._role(role_id, request)
        inst = self._tenant(request)
        if await self.roles.get_by_slug(body.slug, inst):
            raise APIError(409, ErrorCode.CONFLICT, f"A role with slug {body.slug!r} already exists", {"field": "slug"})
        role = await self.roles.create_role(
            institution_id=inst,
            name=body.name,
            slug=body.slug,
            description=source.description,
            is_system=False,
            default_scope_type=source.default_scope_type,
            portal=source.portal,
            created_by=self.principal.id if self.principal else None,
        )
        keys = await self.roles.permission_keys(source.id)
        found = await self.perms.by_keys(sorted(keys))
        await self.roles.add_permissions(role.id, [p.id for p in found.values()])
        await self._audit_role(
            "clone",
            role,
            old=None,
            new={"source_role_id": str(source.id), "permissions": sorted(keys)},
            request=request,
        )
        return await self.get_role(role.id, request)

    # ---- rule 3 -----------------------------------------------------------------------------------------------
    async def get_matrix(self, role_id: uuid.UUID, request: Request | None = None) -> RolePermissionMatrix:
        role = await self._role(role_id, request)
        granted = await self.roles.permission_keys(role.id)
        return RolePermissionMatrix(
            role_id=role.id,
            modules=[
                MatrixModule(
                    module=m,
                    actions=[MatrixAction(action=a, granted=f"{m}:{a}" in granted) for a in ACTIONS_BY_MODULE[m]],
                )
                for m in MODULES
            ],
        )

    async def set_matrix(
        self, role_id: uuid.UUID, body: RolePermissionMatrixUpdate, request: Request | None = None
    ) -> RolePermissionMatrix:
        role = await self._role(role_id, request)
        if body.version is not None and role.version != body.version:
            raise APIError(
                409, ErrorCode.STALE_VERSION, "Role was modified by someone else", {"current_version": role.version}
            )
        current = await self.roles.permission_keys(role.id)
        wanted_on: set[str] = set()
        wanted_off: set[str] = set()
        for mod in body.modules:
            if mod.module not in ACTIONS_BY_MODULE:
                raise APIError(422, ErrorCode.VALIDATION, f"Unknown module {mod.module!r}", {"field": "modules"})
            for cell in mod.actions:
                key = f"{mod.module}:{cell.action}"
                if cell.action not in ACTIONS_BY_MODULE[mod.module]:
                    raise APIError(422, ErrorCode.VALIDATION, f"Unknown action {key!r}", {"field": "modules"})
                (wanted_on if cell.granted else wanted_off).add(key)
        add = sorted(wanted_on - current)
        remove = sorted(wanted_off & current)
        self._check_grantable(add)
        found = await self.perms.by_keys(add + remove)
        await self.roles.add_permissions(role.id, [found[k].id for k in add if k in found])
        await self.roles.remove_permissions(role.id, [found[k].id for k in remove if k in found])
        role.updated_at = datetime.now(UTC)
        await self.db.flush()
        await self._audit_role(
            "permissions",
            role,
            old={"removed": remove, "before": sorted(current)},
            new={"added": add, "after": sorted((current | wanted_on) - wanted_off)},
            request=request,
        )
        return await self.get_matrix(role.id, request)

    def _check_grantable(self, keys: list[str]) -> None:
        bad = sorted(k for k in keys if k in PLATFORM_ONLY_PERMISSIONS)
        if bad and not (self.principal and self.principal.is_super_admin):
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "Platform-only permissions cannot be granted to institution roles",
                {"permissions": bad},
            )

    async def _audit_role(
        self,
        action: str,
        role: Role,
        *,
        old: dict[str, Any] | None,
        new: dict[str, Any] | None,
        request: Request | None,
    ) -> None:
        if self.principal is None:
            return
        await log_audit(
            self.db,
            principal=self.principal,
            module="roles",
            action=action,
            record_type="role",
            record_id=role.id,
            old=old,
            new=new,
            request=request,
        )
        await events.emit(
            self.db,
            institution_id=role.institution_id,
            event_type="role.updated",
            payload={"role_id": str(role.id), "slug": role.slug, "action": action},
            aggregate_type="role",
            aggregate_id=role.id,
            actor_user_id=self.principal.id,
        )

    # ---- rule 4 -----------------------------------------------------------------------------------------------
    async def list_assignments(self, user: User) -> list[UserRoleResponse]:
        rows = await self.assignments.for_user(user.id)
        out = []
        for ur, r in rows:
            out.append(
                UserRoleResponse(
                    id=ur.id,
                    role_id=r.id,
                    role_slug=r.slug,
                    role_name=r.name,
                    scope_type=ur.scope_type,
                    scope_id=ur.scope_id,
                    scope_label=await self.assignments.scope_label(ur.scope_type, ur.scope_id),
                    valid_from=ur.valid_from,
                    valid_to=ur.valid_to,
                    assigned_at=ur.assigned_at,
                )
            )
        return out

    async def assign(self, user: User, body: UserRoleAssign, request: Request | None = None) -> UserRoleResponse:
        inst = user.institution_id
        role = await self.roles.get_role(body.role_id, inst)
        if role is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Role not found in this institution", {"field": "role_id"})
        if role.slug in PLATFORM_ROLES and inst is not None:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "Platform roles cannot be assigned to institution users",
                {"field": "role_id"},
            )
        scope_type = body.scope_type or (role.default_scope_type if role.default_scope_type != "self" else "self")
        allowed = allowed_scope_types(role.slug, role.default_scope_type)
        if scope_type not in allowed:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"Role {role.slug!r} must be assigned with scope {' or '.join(allowed)}",
                {"field": "scope_type", "allowed": list(allowed)},
            )
        scope_id = body.scope_id
        if scope_type in {"institution", "self"}:
            scope_id = None
        else:
            if scope_id is None:
                raise APIError(
                    422, ErrorCode.VALIDATION, f"scope_id is required for scope {scope_type!r}", {"field": "scope_id"}
                )
            if inst is None or not await self.assignments.scope_exists(scope_type, scope_id, inst):
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    f"{scope_type} {scope_id} does not exist in this institution",
                    {"field": "scope_id", "scope_type": scope_type},
                )
        if body.valid_from and body.valid_to and body.valid_to <= body.valid_from:
            raise APIError(422, ErrorCode.VALIDATION, "valid_to must be after valid_from", {"field": "valid_to"})
        if await self.assignments.exists(user.id, role.id, scope_type, scope_id):
            raise APIError(409, ErrorCode.CONFLICT, "This role is already assigned with the same scope")
        row = await self.assignments.create(
            institution_id=inst,
            user_id=user.id,
            role_id=role.id,
            scope_type=scope_type,
            scope_id=scope_id,
            valid_from=body.valid_from,
            valid_to=body.valid_to,
            assigned_by=self.principal.id if self.principal else None,
        )
        await self._audit_assignment("assign", user, row, role, request)
        return UserRoleResponse(
            id=row.id,
            role_id=role.id,
            role_slug=role.slug,
            role_name=role.name,
            scope_type=row.scope_type,
            scope_id=row.scope_id,
            scope_label=await self.assignments.scope_label(row.scope_type, row.scope_id),
            valid_from=row.valid_from,
            valid_to=row.valid_to,
            assigned_at=row.assigned_at,
        )

    async def revoke(self, user: User, assignment_id: uuid.UUID, request: Request | None = None) -> None:
        row = await self.assignments.get(assignment_id, user.id)
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Assignment not found")
        role = await self.roles.get_role(row.role_id, user.institution_id)
        await self.assignments.delete(row)
        await self._audit_assignment("revoke", user, row, role, request)

    async def _audit_assignment(
        self, action: str, user: User, row: UserRole, role: Role | None, request: Request | None
    ) -> None:
        payload = {
            "user_id": str(user.id),
            "assignment_id": str(row.id),
            "role_id": str(row.role_id),
            "role_slug": role.slug if role else None,
            "scope_type": row.scope_type,
            "scope_id": str(row.scope_id) if row.scope_id else None,
        }
        if self.principal is not None:
            await log_audit(
                self.db,
                principal=self.principal,
                module="roles",
                action=action,
                record_type="user_role",
                record_id=row.id,
                old=payload if action == "revoke" else None,
                new=payload if action == "assign" else None,
                request=request,
            )
        await events.emit(
            self.db,
            institution_id=user.institution_id,
            event_type=f"user_role.{'assigned' if action == 'assign' else 'revoked'}",
            payload=payload,
            aggregate_type="user",
            aggregate_id=user.id,
            actor_user_id=self.principal.id if self.principal else None,
        )

    # ---- rule 5 -----------------------------------------------------------------------------------------------
    async def seed_institution_roles(self, institution_id: uuid.UUID) -> int:
        """Clone every missing template (with its grants) into the institution; returns the number created."""
        existing = await self.roles.institution_role_slugs(institution_id)
        created = 0
        for tmpl in await self.roles.templates():
            if tmpl.slug in existing or tmpl.slug in PLATFORM_ROLES:
                continue
            role = await self.roles.create_role(
                institution_id=institution_id,
                name=tmpl.name,
                slug=tmpl.slug,
                description=tmpl.description,
                is_system=True,
                default_scope_type=tmpl.default_scope_type,
                portal=tmpl.portal,
                created_by=self.principal.id if self.principal else None,
            )
            keys = await self.roles.permission_keys(tmpl.id)
            found = await self.perms.by_keys(sorted(keys))
            await self.roles.add_permissions(role.id, [p.id for p in found.values()])
            created += 1
        return created


async def user_for_assignment(db: AsyncSession, principal: Principal, user_id: uuid.UUID) -> User:
    """The target user through the visibility predicate (404 when invisible)."""
    return await UserRepository(db, principal).get(user_id)
