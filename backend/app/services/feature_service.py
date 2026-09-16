"""Effective feature computation — docs/Feature_Flags.md §1.2 (Phase 02 adds the toggle endpoints and change log).

Effective(key) = platform_enabled AND institution_enabled; a missing row falls back to the registry default
(``default_enabled``) — plan tiers are applied when the flags are seeded (``seed_platform.py`` / onboarding).
"""

import uuid
from typing import Any

from sqlalchemy import select

from app.core.features import FEATURE_REGISTRY
from app.db.session import SessionLocal
from app.models.platform import InstitutionFeatureFlag


async def compute_effective_features(institution_id: uuid.UUID | str | Any) -> set[str]:
    keys = {k for k, f in FEATURE_REGISTRY.items() if f.default_enabled or f.is_core}
    try:
        inst = uuid.UUID(str(institution_id))
    except (TypeError, ValueError):
        return keys
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(
                    InstitutionFeatureFlag.feature_key,
                    InstitutionFeatureFlag.platform_enabled,
                    InstitutionFeatureFlag.institution_enabled,
                ).where(InstitutionFeatureFlag.institution_id == inst)
            )
        ).all()
    for key, platform_enabled, institution_enabled in rows:
        if key in FEATURE_REGISTRY and FEATURE_REGISTRY[key].is_core:
            continue
        if platform_enabled and institution_enabled:
            keys.add(key)
        else:
            keys.discard(key)
    return keys
