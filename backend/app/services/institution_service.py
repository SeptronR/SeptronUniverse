"""Institution profile, onboarding and platform tenant administration — Prompts/03 §03.6 ``institution_service``.

Business rules
1. ``get_profile`` / ``update_profile`` (``institutions:view`` / ``institutions:manage``): ``institutions`` + the 1:1
   ``institution_profile`` row; the audit row carries the old/new diff of the changed fields only; changing
   ``timezone`` is refused (409 RULE_VIOLATION) while any term is ``in_progress`` (attendance/timetable dates would
   shift under running classes); ``regulatory_pack`` must be a registered pack (422). Logo upload goes through the
   file service (images only, 2 MB). Emits ``institution.updated``.
2. ``onboard`` (super admin, platform session): institution (``status=active``) + profile; a non-university
   institution gets its main college (``college_type=main``, ``is_main``); ``seed_institution_roles`` (the 49 tenant
   templates with their grants); ``seed_institution_defaults(pack)`` (settings template rows, pack grading scales,
   number sequences — ``app/services/institution_defaults.py``); plan subscription + ``apply_plan_defaults``; the first
   ``institution_admin`` user (temporary password, ``must_change_password``) with a credential e-mail (Celery
   ``notifications.send_admin_credentials`` + a ``message_logs`` row); optional demo-data job
   (``institutions.seed_demo``); emits ``institution.created``. Slug unique → 409; unknown plan/pack → 422.
3. Platform list/detail/update (super admin); ``suspend`` sets ``status=suspended`` and revokes every open session of
   the tenant's users — login answers ``403`` (``reason: institution_suspended``) and existing access tokens stop
   resolving (``load_principal``); ``activate`` restores ``active``. Audited; ``institution.updated`` events.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog
from fastapi import Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.audit import log_audit
from app.core.config import settings
from app.core.errors import APIError, ErrorCode
from app.core.packs import pack_codes
from app.core.security import generate_temp_password, hash_password
from app.enums.institution import CollegeType, InstitutionStatus, InstitutionType
from app.models.platform import College, Institution, InstitutionProfile, User
from app.repositories.institution_repository import InstitutionRepository, MessageLogRepository
from app.repositories.role_repository import RoleRepository
from app.repositories.subscription_repository import SubscriptionRepository
from app.repositories.user_repository import UserRepository
from app.schemas.institution import (
    InstitutionProfileResponse,
    InstitutionProfileUpdate,
    LogoUploadResponse,
    OnboardingRequest,
    OnboardingResponse,
    PlatformInstitutionResponse,
    PlatformInstitutionUpdate,
)
from app.schemas.rbac import UserRoleAssign
from app.services.institution.context import tenant_id
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta

log = structlog.get_logger()

INSTITUTION_FIELDS = (
    "name",
    "short_name",
    "code",
    "regulatory_pack",
    "timezone",
    "locale",
    "currency",
    "parent_university_name",
    "aishe_code",
    "aicte_pid",
    "naac_id",
    "ugc_status",
    "gstin",
    "address",
    "contact",
    "website_url",
)
PROFILE_FIELDS = (
    "established_year",
    "vision",
    "mission",
    "accreditations",
    "recognitions",
    "social_links",
    "head_title",
    "head_name",
    "head_signature_url",
    "seal_url",
    "letterhead_url",
)
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp")
BRANDING_URL_TTL = 10 * 365 * 86400


def profile_response(inst: Institution, profile: InstitutionProfile | None) -> InstitutionProfileResponse:
    data = {c: getattr(inst, c) for c in InstitutionProfileResponse.model_fields if hasattr(inst, c)}
    for f in PROFILE_FIELDS:
        data[f] = getattr(profile, f) if profile is not None else None
    data["updated_at"] = max(inst.updated_at, profile.updated_at) if profile is not None else inst.updated_at
    return InstitutionProfileResponse.model_validate(data)


class InstitutionService:
    def __init__(self, db: AsyncSession, principal: Any, request: Request | None = None):
        self.db, self.principal, self.request = db, principal, request
        self.repo = InstitutionRepository(db)

    # ---- rule 1 ---------------------------------------------------------------------------------------------------
    async def _institution(self, for_update: bool = False) -> Institution:
        inst = await self.repo.get(tenant_id(self.principal, self.request), for_update=for_update)
        if inst is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Institution not found")
        return inst

    async def get_profile(self) -> InstitutionProfileResponse:
        inst = await self._institution()
        return profile_response(inst, await self.repo.profile(inst.id))

    async def update_profile(self, body: InstitutionProfileUpdate) -> InstitutionProfileResponse:
        inst = await self._institution(for_update=True)
        if body.version is not None and inst.version != body.version:
            raise APIError(
                409, ErrorCode.STALE_VERSION, "Record was modified by someone else", {"current_version": inst.version}
            )
        values = body.model_dump(exclude_unset=True, exclude={"version", "statutory_ids"})
        if body.statutory_ids is not None:
            values.update(body.statutory_ids.model_dump(exclude_unset=True))
        if "regulatory_pack" in values and values["regulatory_pack"] not in pack_codes():
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"Unknown regulatory pack {values['regulatory_pack']!r}",
                {"field": "regulatory_pack"},
            )
        if (
            "timezone" in values
            and values["timezone"] != inst.timezone
            and await self.repo.any_term_in_progress(inst.id)
        ):
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                "The timezone cannot change while a term is in progress",
                {"field": "timezone"},
            )
        profile = await self.repo.get_or_create_profile(inst.id)
        old: dict[str, Any] = {}
        new: dict[str, Any] = {}
        for key, value in values.items():
            target = inst if key in INSTITUTION_FIELDS else profile if key in PROFILE_FIELDS else None
            if target is None:
                continue
            current = getattr(target, key)
            if current != value:
                old[key], new[key] = current, value
                setattr(target, key, value)
        await self.db.flush()
        if new:
            await log_audit(
                self.db,
                principal=self.principal,
                module="institutions",
                action="update",
                record_type="institution",
                record_id=inst.id,
                old=old,
                new=new,
                request=self.request,
            )
            await self._emit(inst, "institution.updated", {"fields": sorted(new)})
        return profile_response(inst, profile)

    async def upload_logo(self, file: UploadFile, kind: str = "logo") -> LogoUploadResponse:
        from app.services.file_service import FileService

        inst = await self._institution(for_update=True)
        files = FileService(self.db)
        saved = await files.save(file, "branding", allowed_types=IMAGE_TYPES, max_mb=2, institution_id=inst.id)
        # branding is shown on public pages and printed documents: a long-lived signed URL (the default expires in
        # SIGNED_URL_TTL_SECONDS); re-uploading rotates it
        url = files.signed_url(saved.key, ttl=BRANDING_URL_TTL)
        profile = await self.repo.get_or_create_profile(inst.id)
        column = {
            "logo": "logo_url",
            "seal": "seal_url",
            "signature": "head_signature_url",
            "letterhead": "letterhead_url",
        }[kind]
        target: Any = inst if column == "logo_url" else profile
        old = getattr(target, column)
        setattr(target, column, url)
        await self.db.flush()
        await log_audit(
            self.db,
            principal=self.principal,
            module="institutions",
            action="upload_logo",
            record_type="institution",
            record_id=inst.id,
            old={column: old},
            new={column: url, "key": saved.key},
            request=self.request,
        )
        await self._emit(inst, "institution.updated", {"fields": [column]})
        log.info("institution_branding_uploaded", kind=kind, key=saved.key, url=url)
        return LogoUploadResponse(logo_url=url, key=saved.key, content_type=saved.content_type)

    # ---- rule 2 ---------------------------------------------------------------------------------------------------
    async def onboard(self, body: OnboardingRequest) -> OnboardingResponse:
        from app.services.feature_service import FeatureService
        from app.services.institution_defaults import seed_institution_defaults
        from app.services.rbac_service import RbacService

        pack = body.pack.upper()
        if pack not in pack_codes():
            raise APIError(422, ErrorCode.VALIDATION, f"Unknown regulatory pack {body.pack!r}", {"field": "pack"})
        plan = await SubscriptionRepository(self.db).plan_by_code(body.plan_code)
        if plan is None:
            raise APIError(422, ErrorCode.VALIDATION, f"Unknown plan {body.plan_code!r}", {"field": "plan_code"})
        if await self.repo.by_slug(body.institution.slug):
            raise APIError(
                409, ErrorCode.CONFLICT, f"Slug {body.institution.slug!r} is taken", {"field": "institution.slug"}
            )
        data = body.institution
        inst = await self.repo.create(
            name=data.name,
            short_name=data.short_name,
            slug=data.slug,
            code=data.code,
            institution_type=data.institution_type.value,
            regulatory_pack=pack,
            timezone=data.timezone,
            locale=data.locale,
            currency=data.currency.upper(),
            parent_university_name=data.parent_university_name,
            website_url=data.website_url,
            contact=data.contact,
            address=data.address,
            status=InstitutionStatus.ACTIVE.value,
        )
        await self.repo.get_or_create_profile(inst.id)
        main_college: College | None = None
        if data.institution_type != InstitutionType.UNIVERSITY:
            main_college = College(
                institution_id=inst.id,
                code=(data.code or "MAIN")[:20].upper(),
                name=data.name,
                slug=f"{data.slug}-main"[:60],
                college_type=CollegeType.MAIN.value,
                is_main=True,
                created_by=self.principal.id,
            )
            self.db.add(main_college)
            await self.db.flush()
        roles_created = await RbacService(self.db, self.principal).seed_institution_roles(inst.id)
        conn = await self.db.connection()
        defaults = await conn.run_sync(lambda c: seed_institution_defaults(c, inst.id, pack))
        today = datetime.now(UTC).date()
        await SubscriptionRepository(self.db).create(
            institution_id=inst.id,
            plan_id=plan.id,
            starts_on=today,
            ends_on=today + timedelta(days=365),
            status="active",
        )
        applied = await FeatureService(self.db, self.principal).apply_plan_defaults(inst.id, self.request)
        admin, temp_password = await self._first_admin(inst, body)
        demo_job_id = await self._demo_job(inst) if body.seed_demo else None
        await log_audit(
            self.db,
            principal=self.principal,
            module="institutions",
            action="onboard",
            record_type="institution",
            record_id=inst.id,
            new={
                "slug": inst.slug,
                "type": inst.institution_type,
                "pack": pack,
                "plan": plan.code,
                "admin_user_id": str(admin.id),
                "roles_created": roles_created,
                "defaults": {k: v for k, v in defaults.items() if k != "frameworks"},
                "seed_demo": body.seed_demo,
            },
            request=self.request,
        )
        await self._emit(
            inst,
            "institution.created",
            {"slug": inst.slug, "type": inst.institution_type, "pack": pack, "plan": plan.code},
        )
        return OnboardingResponse(
            institution=profile_response(inst, await self.repo.profile(inst.id)),
            main_college_id=main_college.id if main_college else None,
            roles_created=roles_created,
            defaults=defaults,
            plan_code=plan.code,
            features_enabled=len(applied.effective),
            admin_user_id=admin.id,
            admin_username=admin.username,
            admin_temp_password=temp_password,
            demo_job_id=demo_job_id,
        )

    async def _first_admin(self, inst: Institution, body: OnboardingRequest) -> tuple[User, str]:
        from app.services.rbac_service import RbacService

        if await UserRepository(self.db).username_taken(inst.id, body.admin.username):
            raise APIError(409, ErrorCode.CONFLICT, "Username already taken", {"field": "admin.username"})
        password = generate_temp_password(14)
        user = User(
            institution_id=inst.id,
            username=body.admin.username,
            email=str(body.admin.email),
            phone=body.admin.phone,
            display_name=body.admin.display_name,
            user_type="staff",
            password_hash=hash_password(password),
            is_verified=True,
            must_change_password=True,
            locale=inst.locale,
            timezone=inst.timezone,
            created_by=self.principal.id,
        )
        self.db.add(user)
        await self.db.flush()
        role = await RoleRepository(self.db).get_by_slug("institution_admin", inst.id)
        if role is None:
            raise APIError(500, ErrorCode.INTERNAL, "institution_admin role was not seeded")
        await RbacService(self.db, self.principal).assign(
            user, UserRoleAssign(role_id=role.id, scope_type="institution"), self.request
        )
        subject = f"Your {inst.name} administrator account"
        await MessageLogRepository(self.db).add(
            institution_id=inst.id,
            user_id=user.id,
            recipient=str(body.admin.email),
            channel="email",
            event_type="institution.admin_credentials",
            subject=subject,
            body_preview=f"Administrator account {user.username} created for {inst.name} (temporary password sent)",
            provider=settings.EMAIL_PROVIDER,
            provider_message_id=None,
            status="queued",
        )
        from app.services.auth_service import _send_task

        _send_task(
            "notifications.send_admin_credentials",
            {
                "institution_id": str(inst.id),
                "email": str(body.admin.email),
                "username": user.username,
                "temp_password": password,
                "institution_name": inst.name,
                "institution_slug": inst.slug,
            },
        )
        return user, password

    async def _demo_job(self, inst: Institution) -> uuid.UUID:
        from app.services.job_service import JobService

        row = await JobService(self.db, self.principal).enqueue(
            "institutions.seed_demo", {"institution_id": str(inst.id)}, queue="reports", request=self.request
        )
        return row.id

    # ---- rule 3 ---------------------------------------------------------------------------------------------------
    async def platform_list(
        self, params: PageParams, q: str | None, status: str | None
    ) -> tuple[list[PlatformInstitutionResponse], PaginationMeta]:
        rows, pagination = await self.repo.list_platform(params, q, status)
        return [self._platform_row(row[0], (row[1], row[2], row[3], row[4])) for row in rows], pagination

    def _platform_row(
        self, inst: Institution, counts: tuple[int, int, str | None, str | None]
    ) -> PlatformInstitutionResponse:
        r = PlatformInstitutionResponse.model_validate(inst)
        r.college_count, r.user_count, r.plan_code, r.subscription_status = counts
        return r

    async def platform_get(self, institution_id: uuid.UUID) -> PlatformInstitutionResponse:
        inst = await self._platform_institution(institution_id)
        return self._platform_row(inst, await self.repo.counts(inst.id))

    async def _platform_institution(self, institution_id: uuid.UUID) -> Institution:
        inst = await self.repo.get(institution_id, for_update=True)
        if inst is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Institution not found")
        return inst

    async def platform_update(
        self, institution_id: uuid.UUID, body: PlatformInstitutionUpdate
    ) -> PlatformInstitutionResponse:
        inst = await self._platform_institution(institution_id)
        if body.version is not None and inst.version != body.version:
            raise APIError(
                409, ErrorCode.STALE_VERSION, "Record was modified by someone else", {"current_version": inst.version}
            )
        values = body.model_dump(exclude_unset=True, exclude={"version"})
        if "regulatory_pack" in values and values["regulatory_pack"] not in pack_codes():
            raise APIError(422, ErrorCode.VALIDATION, "Unknown regulatory pack", {"field": "regulatory_pack"})
        old = {k: getattr(inst, k) for k in values}
        for k, v in values.items():
            setattr(inst, k, v)
        await self.db.flush()
        await self._audit_platform("update", inst, old, values)
        await self._emit(inst, "institution.updated", {"fields": sorted(values)})
        return self._platform_row(inst, await self.repo.counts(inst.id))

    async def set_status(
        self, institution_id: uuid.UUID, status: InstitutionStatus, reason: str | None
    ) -> PlatformInstitutionResponse:
        inst = await self._platform_institution(institution_id)
        if inst.status == status:
            raise APIError(409, ErrorCode.CONFLICT, f"The institution is already {status.value}")
        old = {"status": inst.status}
        inst.status = status.value
        revoked = 0
        if status == InstitutionStatus.SUSPENDED:
            revoked = await self.repo.revoke_sessions(inst.id, "institution_suspended")
        await self.db.flush()
        await self._audit_platform(
            "suspend" if status == InstitutionStatus.SUSPENDED else "activate",
            inst,
            old,
            {"status": status.value, "reason": reason, "sessions_revoked": revoked},
        )
        await self._emit(inst, "institution.updated", {"fields": ["status"], "status": status.value, "reason": reason})
        return self._platform_row(inst, await self.repo.counts(inst.id))

    async def _audit_platform(self, action: str, inst: Institution, old: dict[str, Any], new: dict[str, Any]) -> None:
        await log_audit(
            self.db,
            principal=self.principal,
            module="institutions",
            action=action,
            record_type="institution",
            record_id=inst.id,
            old={k: (v.isoformat() if isinstance(v, date) else v) for k, v in old.items()},
            new=new,
            request=self.request,
        )

    async def _emit(self, inst: Institution, event_type: str, payload: dict[str, Any]) -> None:
        await events.emit(
            self.db,
            institution_id=inst.id,
            event_type=event_type,
            payload={"institution_id": str(inst.id), **payload},
            aggregate_type="institution",
            aggregate_id=inst.id,
            actor_user_id=self.principal.id if self.principal else None,
        )
