"""Adapter registry + mocks for every integration capability (docs/Integrations_Catalogue.md).

Importing this package registers the adapters the shipped phases provide (Phase 02: the mock identity provider behind
``security.sso``); Phase 41 adds the real providers and the per-tenant connection resolution.
"""

from app.integrations import bibliographic, payments, sso, webpush  # noqa: F401  (Phase 02 SSO, 12 gateways, 30, 39)

__all__ = ["sso"]
