"""Feature registry + ``feature_required()`` — Prompts/00_PREREQUISITE_Project_Setup.md §3.10 (ADR 0003).

Every module and sub-feature is a registered key (docs/Feature_Flags.md). Effective(key) = platform_enabled AND
institution_enabled; ``is_core`` keys are never gated. Phases register their keys in ``app/features/<module>.py``
(imported by ``app/features/__init__.py``).
"""

from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any, cast

from fastapi import Depends, Request

from app.core.errors import APIError, ErrorCode
from app.db.session import redis_client

CACHE_TTL_SECONDS = 60


@dataclass(frozen=True)
class FeatureDef:
    key: str
    group: str
    name: str
    description: str = ""
    default_enabled: bool = True
    min_plan_tier: str = "starter"  # starter | standard | professional | university
    depends_on: tuple[str, ...] = field(default_factory=tuple)
    is_core: bool = False


FEATURE_REGISTRY: dict[str, FeatureDef] = {}


def register_feature(**kw: Any) -> FeatureDef:
    f = FeatureDef(**kw)
    assert f.key not in FEATURE_REGISTRY, f"duplicate feature {f.key}"
    FEATURE_REGISTRY[f.key] = f
    return f


async def effective_features(institution_id: Any) -> set[str]:
    """Cached per institution (60 s); invalidated by the ``feature_flag.changed`` event."""
    cache_key = f"features:{institution_id}"
    cached = await cast(Awaitable[set[str]], redis_client.smembers(cache_key))
    if cached:
        return set(cached)
    from app.services.feature_service import compute_effective_features

    keys = await compute_effective_features(institution_id)
    if keys:
        await cast(Awaitable[int], redis_client.sadd(cache_key, *keys))
        await cast(Awaitable[bool], redis_client.expire(cache_key, CACHE_TTL_SECONDS))
    return keys


async def invalidate_features_cache(institution_id: Any) -> None:
    await redis_client.delete(f"features:{institution_id}")


async def is_enabled(institution_id: Any, key: str) -> bool:
    """For Celery tasks and services: check a feature before acting (core keys are always on)."""
    if FEATURE_REGISTRY[key].is_core:
        return True
    return key in await effective_features(institution_id)


def feature_required(key: str) -> Any:
    """Router/route dependency: ``403 FEATURE_DISABLED`` unless the tenant has the key enabled.

    Without a tenant context (platform-level requests by the super admin) the key's platform default applies.
    """
    assert key in FEATURE_REGISTRY, f"unregistered feature {key}"

    async def _dep(request: Request) -> None:
        f = FEATURE_REGISTRY[key]
        if f.is_core:
            return
        inst = getattr(request.state, "institution_id", None)
        if not inst:
            # platform context (super admin / platform user without a tenant): the registry default decides
            enabled = f.default_enabled
        else:
            enabled = key in await effective_features(inst)
        if not enabled:
            raise APIError(403, ErrorCode.FEATURE_DISABLED, f"Feature '{key}' is not enabled", {"feature": key})

    _dep.__feature_key__ = key  # type: ignore[attr-defined]  # read by scripts/check_authz_coverage.py
    return Depends(_dep)


FeatureDependency = Callable[[Request], Coroutine[Any, Any, None]]

# Core keys registered here (non-toggleable); every phase registers its own keys in app/features/<module>.py
for _k, _g, _n in [
    ("core.auth", "core", "Authentication"),
    ("core.rbac", "core", "Roles & permissions"),
    ("core.institution", "core", "Institution structure"),
    ("core.settings", "core", "Settings"),
    ("core.audit_logs", "core", "Audit logs"),
    ("core.dashboard", "core", "Dashboards"),
    ("core.notifications_inapp", "core", "In-app notifications"),
    ("core.background_jobs", "core", "Background jobs"),
]:
    register_feature(key=_k, group=_g, name=_n, is_core=True)
