"""Adapter registry + mocks for every integration capability (docs/Integrations_Catalogue.md).

Importing this package registers the adapters the shipped phases provide (Phase 02: the mock identity provider behind
``security.sso``); Phase 41 adds the real providers and the per-tenant connection resolution.
"""

from app.integrations import payments, sso  # noqa: F401  (Phase 02 mock identity provider, Phase 12 gateways)

__all__ = ["sso"]
