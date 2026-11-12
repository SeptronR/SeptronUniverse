"""Roles, permissions and user administration — Prompts/02 §02.8 (router included with ``feature_required("core.rbac")``).

Every route declares ``permission_required`` (``roles:*`` / ``users:*``); list endpoints return ``meta.visibility``.
Impersonation runs on the platform session (cross-tenant by nature) and is restricted to the super admin /
``support_agent`` inside ``UserService.impersonate``.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, permission_required
from app.db.session import get_db, get_platform_db
from app.schemas.auth import ImpersonateRequest, ImpersonateResponse
from app.schemas.common import Envelope
from app.schemas.rbac import (
    AdminResetPasswordResponse,
    CredentialSheetRequest,
    CredentialSheetResponse,
    PermissionCatalogue,
    RoleCloneRequest,
    RoleCreate,
    RolePermissionMatrix,
    RolePermissionMatrixUpdate,
    RoleResponse,
    RoleUpdate,
    UserCreate,
    UserCreatedResponse,
    UserDetailResponse,
    UserResponse,
    UserRoleAssign,
    UserRoleResponse,
    UserUpdate,
)
from app.services.rbac_service import RbacService, user_for_assignment
from app.services.user_service import UserService
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(tags=["rbac"])


# ---- permissions ---------------------------------------------------------------------------------------------
@router.get(
    "/permissions", summary="Permission catalogue (modules × actions)", response_model=Envelope[PermissionCatalogue]
)
async def permissions(
    principal: Principal = Depends(permission_required("roles", "view")), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RbacService(db, principal).catalogue())


# ---- roles ---------------------------------------------------------------------------------------------------
@router.get("/roles", summary="Roles of the institution", response_model=Envelope[list[RoleResponse]])
async def list_roles(
    request: Request,
    params: PageParams = Depends(page_params),
    q: str | None = Query(default=None, max_length=120),
    principal: Principal = Depends(permission_required("roles", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination = await RbacService(db, principal).list_roles(params, q, request)
    return ok(rows, pagination=pagination)


@router.post("/roles", status_code=201, summary="Create a role", response_model=Envelope[RoleResponse])
async def create_role(
    body: RoleCreate,
    request: Request,
    principal: Principal = Depends(permission_required("roles", "create")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RbacService(db, principal).create_role(body, request), message="Role created")


@router.get("/roles/{id}", summary="Role detail", response_model=Envelope[RoleResponse])
async def get_role(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("roles", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RbacService(db, principal).get_role(id, request))


@router.put(
    "/roles/{id}", summary="Update a role (system roles cannot be renamed)", response_model=Envelope[RoleResponse]
)
async def update_role(
    id: uuid.UUID,
    body: RoleUpdate,
    request: Request,
    principal: Principal = Depends(permission_required("roles", "update")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RbacService(db, principal).update_role(id, body, request), message="Role updated")


@router.delete("/roles/{id}", summary="Delete a role (non-system, unassigned)", response_model=Envelope[None])
async def delete_role(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("roles", "delete")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await RbacService(db, principal).delete_role(id, request)
    return ok(None, message="Role deleted")


@router.post(
    "/roles/{id}/clone",
    status_code=201,
    summary="Clone a role with its permissions",
    response_model=Envelope[RoleResponse],
)
async def clone_role(
    id: uuid.UUID,
    body: RoleCloneRequest,
    request: Request,
    principal: Principal = Depends(permission_required("roles", "clone")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RbacService(db, principal).clone_role(id, body, request), message="Role cloned")


@router.get(
    "/roles/{id}/permissions", summary="Permission matrix of a role", response_model=Envelope[RolePermissionMatrix]
)
async def get_matrix(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("roles", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RbacService(db, principal).get_matrix(id, request))


@router.put(
    "/roles/{id}/permissions",
    summary="Set the permission matrix (diff-audited)",
    response_model=Envelope[RolePermissionMatrix],
)
async def set_matrix(
    id: uuid.UUID,
    body: RolePermissionMatrixUpdate,
    request: Request,
    principal: Principal = Depends(permission_required("roles", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RbacService(db, principal).set_matrix(id, body, request), message="Permissions updated")


# ---- users ---------------------------------------------------------------------------------------------------
@router.get("/users", summary="Users of the institution", response_model=Envelope[list[UserResponse]])
async def list_users(
    params: PageParams = Depends(page_params),
    scope: str | None = Query(default=None, pattern="^(self|own|college|all)$"),
    q: str | None = Query(default=None, max_length=120),
    user_type: str | None = Query(default=None, max_length=30),
    is_active: bool | None = Query(default=None),
    role: str | None = Query(default=None, max_length=60, description="filter by role slug"),
    principal: Principal = Depends(permission_required("users", "view_all")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await UserService(db, principal).list(params, scope, q, user_type, is_active, role)
    return ok(rows, pagination=pagination, visibility=visibility)


@router.post(
    "/users",
    status_code=201,
    summary="Create a user (with roles and scopes)",
    response_model=Envelope[UserCreatedResponse],
)
async def create_user(
    body: UserCreate,
    request: Request,
    principal: Principal = Depends(permission_required("users", "create")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await UserService(db, principal).create(body, request), message="User created")


@router.post(
    "/users/credential-sheets",
    status_code=202,
    summary="Generate credential sheets (background job)",
    response_model=Envelope[CredentialSheetResponse],
)
async def credential_sheets(
    body: CredentialSheetRequest,
    request: Request,
    principal: Principal = Depends(permission_required("users", "create")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await UserService(db, principal).credential_sheets(body, request), message="Credential sheet queued")


# {id:uuid}: keep /users/me (portals: language / timezone / theme) from matching this route
@router.get("/users/{id:uuid}", summary="User detail with role assignments", response_model=Envelope[UserDetailResponse])
async def get_user(
    id: uuid.UUID,
    principal: Principal = Depends(permission_required("users", "view_all")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await UserService(db, principal).get(id))


@router.put("/users/{id:uuid}", summary="Update a user", response_model=Envelope[UserDetailResponse])
async def update_user(
    id: uuid.UUID,
    body: UserUpdate,
    request: Request,
    principal: Principal = Depends(permission_required("users", "update")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await UserService(db, principal).update(id, body, request), message="User updated")


@router.post(
    "/users/{id}/deactivate",
    summary="Deactivate a user and revoke its sessions",
    response_model=Envelope[UserDetailResponse],
)
async def deactivate_user(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("users", "update")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await UserService(db, principal).deactivate(id, request), message="User deactivated")


@router.post("/users/{id}/reactivate", summary="Reactivate a user", response_model=Envelope[UserDetailResponse])
async def reactivate_user(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("users", "update")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await UserService(db, principal).reactivate(id, request), message="User reactivated")


@router.post(
    "/users/{id}/reset-password",
    summary="Admin password reset (temporary password)",
    response_model=Envelope[AdminResetPasswordResponse],
)
async def reset_user_password(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("users", "reset_password")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await UserService(db, principal).admin_reset_password(id, request), message="Password reset")


@router.get("/users/{id}/roles", summary="Role assignments of a user", response_model=Envelope[list[UserRoleResponse]])
async def list_user_roles(
    id: uuid.UUID,
    principal: Principal = Depends(permission_required("roles", "assign")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    user = await user_for_assignment(db, principal, id)
    return ok(await RbacService(db, principal).list_assignments(user))


@router.post(
    "/users/{id}/roles",
    status_code=201,
    summary="Assign a role with a scope",
    response_model=Envelope[UserRoleResponse],
)
async def assign_user_role(
    id: uuid.UUID,
    body: UserRoleAssign,
    request: Request,
    principal: Principal = Depends(permission_required("roles", "assign")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    user = await user_for_assignment(db, principal, id)
    return ok(await RbacService(db, principal).assign(user, body, request), message="Role assigned")


@router.delete("/users/{id}/roles/{assignment_id}", summary="Revoke a role assignment", response_model=Envelope[None])
async def revoke_user_role(
    id: uuid.UUID,
    assignment_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("roles", "assign")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    user = await user_for_assignment(db, principal, id)
    await RbacService(db, principal).revoke(user, assignment_id, request)
    return ok(None, message="Role revoked")


@router.post(
    "/users/{id}/impersonate",
    summary="Impersonate a user (audited; support agents get read-only)",
    response_model=Envelope[ImpersonateResponse],
)
async def impersonate(
    id: uuid.UUID,
    body: ImpersonateRequest,
    request: Request,
    principal: Principal = Depends(permission_required("users", "impersonate")),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await UserService(db, principal).impersonate(id, body.reason, request), message="Impersonation started")
