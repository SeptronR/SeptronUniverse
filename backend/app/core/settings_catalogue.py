"""Settings catalogue — Prompts/37 §37.2 / §37.6 ``settings_service`` rule 1.

Metadata for every key of :data:`~app.core.settings_template.SETTINGS_TEMPLATE` (Phases 03–37): category, type,
default, validation (``min`` / ``max`` / ``choices``), ``scope`` (``platform`` keys are read-only for tenants,
``college`` keys may be overridden per college, the rest are ``institution``), ``locked_by`` (``plan`` / ``env`` /
``none``), ``requires_restart``, help text, ``depends_on`` and ``sensitive`` (changes need a reason). Revision ``0037``
stores :func:`catalogue_json` in ``platform_settings['settings_catalogue']``; the service builds the same entries in
code so a key added by a later phase is catalogued without a migration.
"""

from dataclasses import dataclass, field
from typing import Any

from app.core.settings_template import SETTINGS_TEMPLATE, SettingDef
from app.enums.audit import (
    COLLEGE_SCOPED_CATEGORIES,
    ENV_LOCKED_KEYS,
    PLAN_LOCKED_KEYS,
    PLATFORM_SCOPED_KEYS,
    RESTART_KEYS,
    SENSITIVE_CATEGORIES,
    SETTING_DEPENDENCIES,
)

__all__ = ["CATALOGUE", "CatalogueEntry", "catalogue_json", "entry"]


@dataclass(frozen=True)
class CatalogueEntry:
    defn: SettingDef
    scope: str = "institution"  # platform | institution | college
    locked_by: str = "none"  # plan | env | none
    lock_reason: str | None = None
    requires_restart: bool = False
    depends_on: list[str] = field(default_factory=list)
    dependency_hint: str | None = None
    sensitive: bool = False

    @property
    def full_key(self) -> str:
        return self.defn.full_key

    def as_dict(self) -> dict[str, Any]:
        d = self.defn
        return {
            "key": d.full_key,
            "category": d.category,
            "name": d.key,
            "type": d.value_type,
            "default": d.default,
            "label": d.label or d.key.replace("_", " ").capitalize(),
            "help": d.label or None,
            "choices": list(d.choices),
            "min": d.min,
            "max": d.max,
            "is_public": d.is_public,
            "feature": d.feature,
            "scope": self.scope,
            "locked_by": self.locked_by,
            "lock_reason": self.lock_reason,
            "requires_restart": self.requires_restart,
            "depends_on": list(self.depends_on),
            "dependency_hint": self.dependency_hint,
            "sensitive": self.sensitive,
        }


def _entry(d: SettingDef) -> CatalogueEntry:
    k = d.full_key
    scope = (
        "platform"
        if k in PLATFORM_SCOPED_KEYS
        else ("college" if d.category in COLLEGE_SCOPED_CATEGORIES else "institution")
    )
    locked_by, reason = "none", None
    if k in ENV_LOCKED_KEYS:
        locked_by, reason = "env", "Set by the platform environment"
    elif k in PLAN_LOCKED_KEYS:
        locked_by, reason = "plan", PLAN_LOCKED_KEYS[k]
    elif scope == "platform":
        locked_by, reason = "env", "Platform-scoped key"
    dep = SETTING_DEPENDENCIES.get(k)
    return CatalogueEntry(
        defn=d,
        scope=scope,
        locked_by=locked_by,
        lock_reason=reason,
        requires_restart=k in RESTART_KEYS,
        depends_on=[dep[0]] if dep else [],
        dependency_hint=dep[1] if dep else None,
        sensitive=d.category in SENSITIVE_CATEGORIES,
    )


CATALOGUE: dict[str, CatalogueEntry] = {d.full_key: _entry(d) for d in SETTINGS_TEMPLATE}


def entry(category: str, key: str) -> CatalogueEntry | None:
    return CATALOGUE.get(f"{category}.{key}")


def catalogue_json() -> dict[str, dict[str, Any]]:
    """``platform_settings['settings_catalogue']`` — full key → metadata."""
    return {k: e.as_dict() for k, e in CATALOGUE.items()}
