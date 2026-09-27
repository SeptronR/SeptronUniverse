"""Feature flags — docs/Feature_Flags.md §1; Prompts/02 §02.6 ``feature_service``.

Effective(key) = platform_enabled AND institution_enabled. A missing row falls back to the plan: a key listed in the
tenant's plan ``enabled_features`` (or, without a subscription, the registry ``default_enabled``) is on.
``compute_effective_features`` runs on its own tenant-pinned session (RLS hides another tenant's rows from the app
role) and is cached 60 s in Redis by ``core/features.py``; every change invalidates the cache directly **and** emits
``feature_flag.changed`` so other processes (workers) drop theirs too.

Business rules
1. ``list_definitions`` — registry ∪ ``platform_features`` (keys of modules not yet shipped are documented but
   ``registered=false``).
2. ``list_institution_flags`` — every definition with the tenant's row (or the plan/default fallback) → effective.
3. ``set_platform_flag`` (super admin): core keys are immutable (409); enabling a key whose ``depends_on`` are not all
   effective answers ``409 RULE_VIOLATION`` listing them unless ``confirm_dependencies=true`` (then they are enabled
   transitively, each logged); disabling a key that enabled keys depend on answers ``409 RULE_VIOLATION`` listing the
   dependants. Rows written by the super admin carry ``source='override'``. Each change → ``feature_flag_changes``,
   ``log_audit``, event ``feature_flag.changed``, cache invalidation.
4. ``set_institution_flag`` (institution admin, ``features:institution_toggle``): may switch off, or back on, what the
   platform enabled — enabling while ``platform_enabled=false`` → 409; core keys immutable.
5. ``apply_plan_defaults`` — rows ``source='plan'`` for every key of the plan; overrides are kept.
6. ``matrix`` — institutions × features (platform session, super admin).
"""

import uuid
from collections.abc import Sequence
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.audit import log_audit
from app.core.authz.dependencies import Principal
from app.core.errors import APIError, ErrorCode
from app.core.features import FEATURE_REGISTRY, invalidate_features_cache
from app.db.session import SessionLocal, set_tenant
from app.models.platform import InstitutionFeatureFlag, PlatformFeature
from app.repositories.feature_flag_repository import FeatureFlagRepository
from app.schemas.features import (
    ApplyPlanDefaultsResponse,
    FeatureDefResponse,
    FeatureFlagChangeResponse,
    FeatureMatrixResponse,
    InstitutionFeatureFlagResponse,
    InstitutionFeaturesResponse,
    MatrixInstitution,
)

TIER_ORDER = ["starter", "standard", "professional", "university"]


async def compute_effective_features(institution_id: uuid.UUID | str | Any) -> set[str]:
    """Effective keys of a tenant on a fresh tenant-pinned session (used by the Redis-cached ``effective_features``)."""
    try:
        inst = uuid.UUID(str(institution_id))
    except (TypeError, ValueError):
        return {k for k, f in FEATURE_REGISTRY.items() if f.default_enabled or f.is_core}
    async with SessionLocal() as db:
        await set_tenant(db, inst)
        repo = FeatureFlagRepository(db)
        defs = await repo.definitions()
        flags = await repo.flags(inst)
        _, plan_keys = await repo.plan_features(inst)
    return _effective(defs, flags, plan_keys)


def _effective(
    defs: Sequence[PlatformFeature], flags: dict[str, InstitutionFeatureFlag], plan_keys: Sequence[str]
) -> set[str]:
    keys: set[str] = set()
    plan = set(plan_keys)
    for d in defs:
        if d.is_core:
            keys.add(d.key)
            continue
        row = flags.get(d.key)
        if row is not None:
            if row.platform_enabled and row.institution_enabled:
                keys.add(d.key)
        elif (d.key in plan) if plan else d.default_enabled:
            keys.add(d.key)
    for k, f in FEATURE_REGISTRY.items():  # registered keys missing from the table (fresh DB before seeding)
        if f.is_core:
            keys.add(k)
    return keys


class FeatureService:
    def __init__(self, db: AsyncSession, principal: Principal | None = None):
        self.db, self.principal = db, principal
        self.repo = FeatureFlagRepository(db)

    # ---- rule 1 ---------------------------------------------------------------------------------------------
    async def list_definitions(self) -> list[FeatureDefResponse]:
        return [self._def(d) for d in await self.repo.definitions()]

    @staticmethod
    def _def(d: PlatformFeature) -> FeatureDefResponse:
        return FeatureDefResponse(
            key=d.key,
            group=d.group_name,
            name=d.name,
            description=d.description,
            default_enabled=d.default_enabled,
            min_plan_tier=d.min_plan_tier,
            depends_on=list(d.depends_on or []),
            is_core=d.is_core,
            registered=d.key in FEATURE_REGISTRY,
        )

    # ---- rule 2 ---------------------------------------------------------------------------------------------
    async def list_institution_flags(
        self, institution_id: uuid.UUID, with_changes: bool = True
    ) -> InstitutionFeaturesResponse:
        defs = await self.repo.definitions()
        flags = await self.repo.flags(institution_id)
        plan_code, plan_keys = await self.repo.plan_features(institution_id)
        effective = _effective(defs, flags, plan_keys)
        plan_tier = plan_code if plan_code in TIER_ORDER else "university"
        out: list[InstitutionFeatureFlagResponse] = []
        for d in defs:
            row = flags.get(d.key)
            plan_allows = TIER_ORDER.index(d.min_plan_tier) <= TIER_ORDER.index(plan_tier)
            out.append(
                InstitutionFeatureFlagResponse(
                    key=d.key,
                    group=d.group_name,
                    name=d.name,
                    description=d.description,
                    min_plan_tier=d.min_plan_tier,
                    depends_on=list(d.depends_on or []),
                    is_core=d.is_core,
                    platform_enabled=True if d.is_core else (row.platform_enabled if row else (d.key in effective)),
                    institution_enabled=True if d.is_core else (row.institution_enabled if row else True),
                    effective=d.key in effective,
                    source=row.source if row else "default",
                    config=row.config if row else None,
                    plan_allows=plan_allows,
                    set_at=row.set_at if row else None,
                )
            )
        changes = (
            [
                FeatureFlagChangeResponse.model_validate(c, from_attributes=True)
                for c in await self.repo.changes(institution_id)
            ]
            if with_changes
            else []
        )
        return InstitutionFeaturesResponse(
            institution_id=institution_id, plan_code=plan_code, flags=out, changes=changes
        )

    async def effective(self, institution_id: uuid.UUID) -> set[str]:
        defs = await self.repo.definitions()
        flags = await self.repo.flags(institution_id)
        _, plan_keys = await self.repo.plan_features(institution_id)
        return _effective(defs, flags, plan_keys)

    # ---- rule 3 ---------------------------------------------------------------------------------------------
    async def set_platform_flag(
        self,
        institution_id: uuid.UUID,
        key: str,
        *,
        enabled: bool,
        reason: str | None,
        config: dict[str, Any] | None,
        confirm_dependencies: bool,
        request: Request | None = None,
    ) -> InstitutionFeatureFlagResponse:
        d = await self._definition(key)
        if d.is_core:
            raise APIError(
                409, ErrorCode.RULE_VIOLATION, f"{key} is a core feature and cannot be toggled", {"feature": key}
            )
        defs = await self.repo.definitions()
        by_key = {x.key: x for x in defs}
        effective = await self.effective(institution_id)
        touched: list[str] = []
        if enabled:
            missing = self._missing_dependencies(key, by_key, effective)
            if missing and not confirm_dependencies:
                raise APIError(
                    409,
                    ErrorCode.RULE_VIOLATION,
                    f"Enabling {key} requires its dependencies to be enabled first",
                    {"feature": key, "missing_dependencies": missing, "hint": "retry with confirm_dependencies=true"},
                )
            for dep in missing:
                await self._write(
                    institution_id, dep, enabled=True, reason=f"dependency of {key}", config=None, request=request
                )
                touched.append(dep)
        else:
            dependants = sorted(
                x.key for x in defs if key in (x.depends_on or []) and x.key in effective and not x.is_core
            )
            if dependants:
                raise APIError(
                    409,
                    ErrorCode.RULE_VIOLATION,
                    f"{key} cannot be disabled while enabled features depend on it",
                    {"feature": key, "dependants": dependants},
                )
        row = await self._write(institution_id, key, enabled=enabled, reason=reason, config=config, request=request)
        touched.append(key)
        flags = await self.repo.flags(institution_id)
        _, plan_keys = await self.repo.plan_features(institution_id)
        eff = _effective(defs, flags, plan_keys)
        return InstitutionFeatureFlagResponse(
            key=key,
            group=d.group_name,
            name=d.name,
            description=d.description,
            min_plan_tier=d.min_plan_tier,
            depends_on=list(d.depends_on or []),
            is_core=False,
            platform_enabled=row.platform_enabled,
            institution_enabled=row.institution_enabled,
            effective=key in eff,
            source=row.source,
            config=row.config,
            set_at=row.set_at,
        )

    def _missing_dependencies(self, key: str, by_key: dict[str, PlatformFeature], effective: set[str]) -> list[str]:
        """Transitive ``depends_on`` keys that are not effective (dependency order, no duplicates)."""
        order: list[str] = []
        seen: set[str] = set()

        def visit(k: str) -> None:
            for dep in by_key[k].depends_on or [] if k in by_key else []:
                if dep in seen or dep in effective or (dep in by_key and by_key[dep].is_core):
                    continue
                seen.add(dep)
                visit(dep)
                order.append(dep)

        visit(key)
        return order

    async def _write(
        self,
        institution_id: uuid.UUID,
        key: str,
        *,
        enabled: bool,
        reason: str | None,
        config: dict[str, Any] | None,
        request: Request | None,
    ) -> InstitutionFeatureFlag:
        before = (await self.repo.flags(institution_id)).get(key)
        old = _snapshot(before)
        row = await self.repo.upsert(
            institution_id,
            key,
            platform_enabled=enabled,
            institution_enabled=None,  # the institution's own switch survives platform toggles (new rows default on)
            source="override",
            config=config,
            set_by=self.principal.id if self.principal else None,
        )
        await self._after_change(institution_id, key, old, _snapshot(row), reason, request)
        return row

    # ---- rule 4 ---------------------------------------------------------------------------------------------
    async def set_institution_flag(
        self, institution_id: uuid.UUID, key: str, *, enabled: bool, reason: str | None, request: Request | None = None
    ) -> InstitutionFeatureFlagResponse:
        d = await self._definition(key)
        if d.is_core:
            raise APIError(
                409, ErrorCode.RULE_VIOLATION, f"{key} is a core feature and cannot be toggled", {"feature": key}
            )
        flags = await self.repo.flags(institution_id)
        before = flags.get(key)
        _, plan_keys = await self.repo.plan_features(institution_id)
        platform_on = before.platform_enabled if before else ((key in plan_keys) if plan_keys else d.default_enabled)
        if enabled and not platform_on:
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                f"{key} is disabled by the platform; ask the SeptronUniverse team to enable it",
                {"feature": key, "platform_enabled": False},
            )
        old = _snapshot(before)
        row = await self.repo.upsert(
            institution_id,
            key,
            institution_enabled=enabled,
            default_platform=platform_on,
            source=before.source if before else "plan",
            set_by=self.principal.id if self.principal else None,
        )
        await self._after_change(institution_id, key, old, _snapshot(row), reason, request)
        return InstitutionFeatureFlagResponse(
            key=key,
            group=d.group_name,
            name=d.name,
            description=d.description,
            min_plan_tier=d.min_plan_tier,
            depends_on=list(d.depends_on or []),
            is_core=False,
            platform_enabled=row.platform_enabled,
            institution_enabled=row.institution_enabled,
            effective=row.platform_enabled and row.institution_enabled,
            source=row.source,
            config=row.config,
            set_at=row.set_at,
        )

    # ---- rule 5 ---------------------------------------------------------------------------------------------
    async def apply_plan_defaults(
        self, institution_id: uuid.UUID, request: Request | None = None
    ) -> ApplyPlanDefaultsResponse:
        plan_code, plan_keys = await self.repo.plan_features(institution_id)
        defs = {d.key: d for d in await self.repo.definitions()}
        flags = await self.repo.flags(institution_id)
        applied = 0
        for key, d in defs.items():
            if d.is_core:
                continue
            row = flags.get(key)
            if row is not None and row.source == "override":
                continue  # overrides survive plan changes (Feature_Flags §1.3)
            wanted = (key in plan_keys) if plan_keys else d.default_enabled
            if row is not None and row.platform_enabled == wanted and row.source == "plan":
                continue
            old = _snapshot(row)
            new_row = await self.repo.upsert(
                institution_id,
                key,
                platform_enabled=wanted,
                source="plan",
                set_by=self.principal.id if self.principal else None,
            )
            await self.repo.log_change(
                institution_id,
                key,
                old,
                _snapshot(new_row),
                self.principal.id if self.principal else None,
                f"plan defaults ({plan_code})",
            )
            applied += 1
        await invalidate_features_cache(institution_id)
        await events.emit(
            self.db,
            institution_id=institution_id,
            event_type="feature_flag.changed",
            payload={"institution_id": str(institution_id), "keys": ["*"], "reason": "apply_plan_defaults"},
            aggregate_type="institution",
            aggregate_id=institution_id,
            actor_user_id=self.principal.id if self.principal else None,
        )
        if self.principal is not None:
            await log_audit(
                self.db,
                principal=self.principal,
                module="features",
                action="apply_plan_defaults",
                record_type="institution",
                record_id=institution_id,
                new={"plan": plan_code, "applied": applied},
                request=request,
            )
        effective = sorted(await self.effective(institution_id))
        return ApplyPlanDefaultsResponse(
            institution_id=institution_id, plan_code=plan_code, applied=applied, effective=effective
        )

    # ---- rule 6 ---------------------------------------------------------------------------------------------
    async def matrix(self) -> FeatureMatrixResponse:
        defs = await self.repo.definitions()
        institutions, by_inst = await self.repo.matrix()
        out: list[MatrixInstitution] = []
        for inst in institutions:
            plan_code, plan_keys = await self.repo.plan_features(inst.id)
            eff = _effective(defs, by_inst.get(inst.id, {}), plan_keys)
            out.append(
                MatrixInstitution(
                    id=inst.id, name=inst.name, slug=inst.slug, plan_code=plan_code, effective=sorted(eff)
                )
            )
        return FeatureMatrixResponse(features=[self._def(d) for d in defs], institutions=out)

    # ---- helpers ------------------------------------------------------------------------------------------
    async def _definition(self, key: str) -> PlatformFeature:
        d = await self.repo.definition(key)
        if d is None:
            raise APIError(404, ErrorCode.NOT_FOUND, f"Unknown feature key {key!r}", {"feature": key})
        return d

    async def _after_change(
        self,
        institution_id: uuid.UUID,
        key: str,
        old: dict[str, Any] | None,
        new: dict[str, Any] | None,
        reason: str | None,
        request: Request | None,
    ) -> None:
        actor = self.principal.id if self.principal else None
        await self.repo.log_change(institution_id, key, old, new, actor, reason)
        if self.principal is not None:
            await log_audit(
                self.db,
                principal=self.principal,
                module="features",
                action="toggle",
                record_type="institution_feature_flag",
                record_id=institution_id,
                old={"feature": key, **(old or {})},
                new={"feature": key, **(new or {})},
                request=request,
            )
        await events.emit(
            self.db,
            institution_id=institution_id,
            event_type="feature_flag.changed",
            payload={"institution_id": str(institution_id), "keys": [key], "old": old, "new": new, "reason": reason},
            aggregate_type="institution_feature_flag",
            aggregate_id=institution_id,
            actor_user_id=actor,
        )
        await invalidate_features_cache(institution_id)


def _snapshot(row: InstitutionFeatureFlag | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "platform_enabled": row.platform_enabled,
        "institution_enabled": row.institution_enabled,
        "source": row.source,
        "config": row.config,
    }


async def institution_exists(db: AsyncSession, institution_id: uuid.UUID) -> bool:
    from app.models.platform import Institution

    return (
        await db.execute(
            select(Institution.id).where(Institution.id == institution_id, Institution.deleted_at.is_(None))
        )
    ).first() is not None
