"""Adapter registry + mocks for every integration capability (docs/Integrations_Catalogue.md).

Importing this package registers the adapters the shipped phases provide (Phase 02: the mock identity provider behind
``security.sso``); Phase 41 adds the real providers and the per-tenant connection resolution.
"""

from app.integrations import (  # noqa: F401  (Phase 02 SSO, 12 gateways, 30, 39)
    bibliographic,
    payments,
    providers,  # noqa: F401, E402  (Phase 41 real providers + functional mocks)
    sso,
    webpush,
)

__all__ = ["sso"]
