"""User administration — Prompts/02 §02.6 ``user_service``.

Business rules
1. ``users`` visibility: self (``/auth/me``), ``users:view_all`` inside the role scope (institution admin, HR officer,
   registrar; college-scoped through role assignments); responses mask ``phone`` / ``email`` unless the caller holds
   ``users:view_pii`` **or** ``hr:view_pii`` (staff PII belongs to HR — verification step 13).
2. ``create``: username unique per institution; a missing password is generated (temporary, returned once to the
   caller, ``must_change_password=TRUE``); initial role assignments go through ``RbacService.assign`` (scope rules);
   seat limits are enforced by ``EntitlementService.enforce_seat_limit`` for student/staff accounts. Emits
   ``user.created``.
3. ``update``: contact/profile fields with optimistic ``version``; ``deactivate`` revokes every session and emits
   ``user.deactivated``; ``reactivate`` clears the flag. Platform users (``institution_id IS NULL``) are never
   editable through a tenant session.
4. ``admin_reset_password`` (``users:reset_password``): new temporary password, ``must_change_password=TRUE``, all
   sessions revoked, audited (the password itself is never logged).
5. ``credential_sheets`` (``users:create``): a ``users.credential_sheet`` job on the ``documents`` queue generates a
   temporary password for every listed user, sets ``must_change_password``, writes an XLSX (and a PDF when WeasyPrint
   is available) under the tenant's storage and records ``credential_sheets``; the tray shows progress.
6. Impersonation (``users:impersonate`` — super admin or support agent, platform session): an
   ``impersonation_logs`` row and an access token for the target carrying ``imp`` (impersonator), ``imp_log`` and, for
   support agents, ``imp_ro`` (every write refused with 403). Every write during impersonation is audited with
   ``impersonator_id``; ``POST /auth/impersonation/stop`` ends the log and blacklists the token.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.audit import log_audit
from app.core.authz.dependencies import Principal
from app.core.authz.masking import mask_pii
from app.core.errors import APIError, ErrorCode
from app.core.security import create_access_token, generate_temp_password, hash_password
from app.models.platform import User
from app.repositories.session_repository import SessionRepository
from app.repositories.subscription_repository import ImpersonationRepository
from app.repositories.user_repository import UserRepository
from app.repositories.user_role_repository import UserRoleRepository
from app.schemas.auth import ImpersonateResponse, MeUser, ScopeOut
from app.schemas.rbac import (
    AdminResetPasswordResponse,
    CredentialSheetRequest,
    CredentialSheetResponse,
    UserCreate,
    UserCreatedResponse,
    UserDetailResponse,
    UserResponse,
    UserUpdate,
)
from app.services.entitlement_service import EntitlementService
from app.services.rbac_service import RbacService
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta

PII_MODULES = ("users", "hr")
SEAT_KIND = {"student": "student", "learner": "student", "staff": "staff"}


class UserService:
    def __init__(self, db: AsyncSession, principal: Principal | None = None):
        self.db, self.principal = db, principal
        self.repo = UserRepository(db, principal)
        self.rbac = RbacService(db, principal)

    # ---- rule 1 -----------------------------------------------------------------------------------------------
    async def list(
        self,
        params: PageParams,
        scope: str | None,
        q: str | None,
        user_type: str | None,
        is_active: bool | None,
        role_slug: str | None,
    ) -> tuple[list[UserResponse], PaginationMeta, VisibilityMeta | None]:
        rows, pagination = await self.repo.list_users(params, scope, q, user_type, is_active, role_slug)
        out = []
        for u in rows:
            resp = UserResponse.model_validate(u)
            resp.role_slugs = [r.slug for _, r in await UserRoleRepository(self.db).for_user(u.id)]
            masked: UserResponse = mask_pii(resp, self.principal, PII_MODULES)
            out.append(masked)
        return out, pagination, self.repo.visibility_meta()

    async def get(self, user_id: uuid.UUID) -> UserDetailResponse:
        user = await self.repo.get(user_id)
        return await self._detail(user)

    async def _detail(self, user: User) -> UserDetailResponse:
        resp = UserDetailResponse.model_validate(user)
        resp.roles = await self.rbac.list_assignments(user)
        resp.role_slugs = [r.role_slug for r in resp.roles]
        masked: UserDetailResponse = mask_pii(resp, self.principal, PII_MODULES)
        return masked

    # ---- rule 2 -----------------------------------------------------------------------------------------------
    async def create(self, body: UserCreate, request: Request | None = None) -> UserCreatedResponse:
        assert self.principal is not None
        inst = self._tenant(request)
        if await self.repo.username_taken(inst, body.username):
            raise APIError(409, ErrorCode.CONFLICT, "Username already exists", {"field": "username"})
        seat_kind = SEAT_KIND.get(body.user_type)
        if seat_kind:
            await EntitlementService(self.db, self.principal).enforce_seat_limit(seat_kind, institution_id=inst)
        temp = None
        password = body.password
        if not password:
            temp = password = generate_temp_password()
        user = await self.repo.create(
            institution_id=inst,
            username=body.username,
            email=body.email,
            phone=body.phone,
            display_name=body.display_name,
            user_type=body.user_type,
            password_hash=hash_password(password),
            must_change_password=body.must_change_password or temp is not None,
            is_verified=False,
            locale=body.locale,
            timezone=body.timezone,
            valid_from=body.valid_from,
            valid_to=body.valid_to,
            created_by=self.principal.id,
        )
        for assignment in body.roles:
            await self.rbac.assign(user, assignment, request)
        await log_audit(
            self.db,
            principal=self.principal,
            module="users",
            action="create",
            record_type="user",
            record_id=user.id,
            new={"username": user.username, "user_type": user.user_type, "roles": [str(a.role_id) for a in body.roles]},
            request=request,
        )
        await events.emit(
            self.db,
            institution_id=inst,
            event_type="user.created",
            payload={"user_id": str(user.id), "user_type": user.user_type},
            aggregate_type="user",
            aggregate_id=user.id,
            actor_user_id=self.principal.id,
        )
        detail = await self._detail(user)
        return UserCreatedResponse(**detail.model_dump(), temporary_password=temp)

    # ---- rule 3 -----------------------------------------------------------------------------------------------
    async def update(self, user_id: uuid.UUID, body: UserUpdate, request: Request | None = None) -> UserDetailResponse:
        assert self.principal is not None
        user = await self.repo.get(user_id)
        self._editable(user)
        values = body.model_dump(exclude_unset=True, exclude={"version"})
        old = {k: getattr(user, k) for k in values}
        await self.repo.update(user, expected_version=body.version, **values)
        await log_audit(
            self.db,
            principal=self.principal,
            module="users",
            action="update",
            record_type="user",
            record_id=user.id,
            old={k: (str(v) if v is not None else None) for k, v in old.items()},
            new={k: (str(v) if v is not None else None) for k, v in values.items()},
            request=request,
        )
        return await self._detail(user)

    async def deactivate(self, user_id: uuid.UUID, request: Request | None = None) -> UserDetailResponse:
        assert self.principal is not None
        user = await self.repo.get(user_id)
        self._editable(user)
        if user.id == self.principal.id:
            raise APIError(409, ErrorCode.RULE_VIOLATION, "You cannot deactivate your own account")
        user.is_active = False
        await self.db.flush()
        await SessionRepository(self.db).revoke_all(user.id, "deactivated")
        await log_audit(
            self.db,
            principal=self.principal,
            module="users",
            action="deactivate",
            record_type="user",
            record_id=user.id,
            request=request,
        )
        await events.emit(
            self.db,
            institution_id=user.institution_id,
            event_type="user.deactivated",
            payload={"user_id": str(user.id)},
            aggregate_type="user",
            aggregate_id=user.id,
            actor_user_id=self.principal.id,
        )
        return await self._detail(user)

    async def reactivate(self, user_id: uuid.UUID, request: Request | None = None) -> UserDetailResponse:
        assert self.principal is not None
        user = await self.repo.get(user_id)
        self._editable(user)
        user.is_active = True
        await self.db.flush()
        await log_audit(
            self.db,
            principal=self.principal,
            module="users",
            action="reactivate",
            record_type="user",
            record_id=user.id,
            request=request,
        )
        return await self._detail(user)

    def _editable(self, user: User) -> None:
        if user.institution_id is None and not (self.principal and self.principal.is_super_admin):
            raise APIError(404, ErrorCode.NOT_FOUND, "User not found")

    def _tenant(self, request: Request | None) -> uuid.UUID:
        return self.rbac._tenant(request)  # noqa: SLF001

    # ---- rule 4 -----------------------------------------------------------------------------------------------
    async def admin_reset_password(
        self, user_id: uuid.UUID, request: Request | None = None
    ) -> AdminResetPasswordResponse:
        assert self.principal is not None
        user = await self.repo.get(user_id)
        self._editable(user)
        temp = generate_temp_password()
        user.password_hash = hash_password(temp)
        user.must_change_password = True
        user.password_changed_at = datetime.now(UTC)
        await self.db.flush()
        await SessionRepository(self.db).revoke_all(user.id, "admin_reset")
        await log_audit(
            self.db,
            principal=self.principal,
            module="users",
            action="reset_password",
            record_type="user",
            record_id=user.id,
            request=request,
        )
        return AdminResetPasswordResponse(user_id=user.id, temporary_password=temp, must_change_password=True)

    # ---- rule 5 -----------------------------------------------------------------------------------------------
    async def credential_sheets(
        self, body: CredentialSheetRequest, request: Request | None = None
    ) -> CredentialSheetResponse:
        assert self.principal is not None
        from app.models.platform import CredentialSheet
        from app.services.job_service import JobService

        inst = self._tenant(request)
        users = await self.repo.by_ids(body.ids)
        if len(users) != len(set(body.ids)):
            raise APIError(422, ErrorCode.VALIDATION, "One or more users are not visible to you", {"field": "ids"})
        sheet = CredentialSheet(
            institution_id=inst,
            batch_label=body.batch_label or f"{body.audience} {datetime.now(UTC):%Y-%m-%d %H:%M}",
            audience=body.audience,
            generated_by=self.principal.id,
        )
        self.db.add(sheet)
        await self.db.flush()
        job = await JobService(self.db, self.principal).enqueue(
            "users.credential_sheet",
            {"sheet_id": str(sheet.id), "user_ids": [str(u.id) for u in users], "audience": body.audience},
            queue="documents",
            request=request,
        )
        sheet.job_id = job.id
        await self.db.flush()
        await log_audit(
            self.db,
            principal=self.principal,
            module="users",
            action="credential_sheet",
            record_type="credential_sheet",
            record_id=sheet.id,
            new={"count": len(users), "audience": body.audience, "job_id": str(job.id)},
            request=request,
        )
        return CredentialSheetResponse(job_id=job.id, sheet_id=sheet.id, audience=body.audience, count=len(users))

    # ---- rule 6 (platform session) -------------------------------------------------------------------------------
    async def impersonate(
        self, target_user_id: uuid.UUID, reason: str, request: Request | None = None
    ) -> ImpersonateResponse:
        assert self.principal is not None
        p = self.principal
        if not (p.is_super_admin or "support_agent" in p.roles):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only platform users may impersonate")
        if p.impersonator_id is not None:
            raise APIError(409, ErrorCode.CONFLICT, "Already impersonating; stop the current impersonation first")
        target = await self.repo.get_any(target_user_id)
        if target is None or not target.is_active:
            raise APIError(404, ErrorCode.NOT_FOUND, "User not found")
        if target.is_super_admin:
            raise APIError(409, ErrorCode.RULE_VIOLATION, "Super admins cannot be impersonated")
        read_only = not p.is_super_admin
        ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() if request else None
        if request is not None and not ip:
            ip = request.client.host if request.client else None
        row = await ImpersonationRepository(self.db).start(
            institution_id=target.institution_id, impersonator_id=p.id, target_user_id=target.id, reason=reason, ip=ip
        )
        token = create_access_token(
            target.id,
            target.institution_id,
            False,
            extra={"imp": str(p.id), "imp_log": str(row.id), "imp_ro": read_only},
        )
        await log_audit(
            self.db,
            principal=p,
            module="users",
            action="impersonate",
            record_type="user",
            record_id=target.id,
            new={"impersonation_log_id": str(row.id), "reason": reason, "read_only": read_only},
            request=request,
        )
        # Phase 38: tenant admins are told (setting ``saas.notify_impersonation``); sessions auto-stop after 60 min
        from app.services.saas.impersonation_service import ImpersonationService

        await ImpersonationService(self.db, p, request).started(row, p.user, target)
        roles = [r.slug for _, r in await UserRoleRepository(self.db).for_user(target.id)]
        me = MeUser(
            id=target.id,
            institution_id=target.institution_id,
            username=target.username,
            email=target.email,
            phone=target.phone,
            display_name=target.display_name,
            avatar_url=target.avatar_url,
            user_type=target.user_type,
            is_super_admin=False,
            role_slugs=sorted(set(roles)),
            scopes=[
                ScopeOut(scope_type=ur.scope_type, scope_id=ur.scope_id)
                for ur, _ in await UserRoleRepository(self.db).for_user(target.id)
            ],
            mfa_enabled=target.mfa_enabled,
            must_change_password=target.must_change_password,
            impersonator_id=p.id,
            impersonation_read_only=read_only,
        )
        return ImpersonateResponse(access_token=token, user=me, impersonation_log_id=row.id, read_only=read_only)


def user_public(user: User) -> dict[str, Any]:
    return {"id": str(user.id), "username": user.username, "display_name": user.display_name}
