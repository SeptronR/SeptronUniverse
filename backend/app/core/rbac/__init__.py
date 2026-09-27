"""RBAC registries — permission catalogue, role templates and scope rules (Prompts/02 §02.2, §02.6)."""

from app.core.rbac.registry import (
    BESPOKE_ACTIONS,
    MFA_REQUIRED_ROLES,
    MODULES,
    PERMISSIONS,
    ROLE_META,
    ROLE_TEMPLATES,
    SCOPE_TYPES,
    STANDARD_ACTIONS,
    RoleMeta,
    allowed_scope_types,
)

__all__ = [
    "BESPOKE_ACTIONS",
    "MFA_REQUIRED_ROLES",
    "MODULES",
    "PERMISSIONS",
    "ROLE_META",
    "ROLE_TEMPLATES",
    "SCOPE_TYPES",
    "STANDARD_ACTIONS",
    "RoleMeta",
    "allowed_scope_types",
]
