"""Identity-provider adapter for the SSO hook — Prompts/02 §02.6 rule 9 (``security.sso``).

Phase 02 ships the **mock** provider so the login flow can be exercised end to end without an IdP: ``authorize_url``
returns the callback URL with a ``code`` that carries the requested identity (``login_hint``) and ``exchange`` decodes
it into ``{email, name, groups}``. Phase 41 registers the real OIDC/SAML providers under the same two methods
(``@register_adapter("sso", "<provider>")``) and wires per-tenant credentials from ``integration_connections``.
"""

import base64
from typing import Any
from urllib.parse import urlencode

import structlog

from app.integrations.registry import register_adapter

log = structlog.get_logger()


@register_adapter("sso", "mock")
class MockIdentityProvider:
    capability = "sso"
    provider = "mock"

    def __init__(self, **config: Any):
        self.config = config

    async def health(self) -> tuple[bool, str]:
        return True, "mock"

    def authorize_url(self, *, state: str, redirect_uri: str, login_hint: str | None = None, **_: Any) -> str:
        code = "mock-" + base64.urlsafe_b64encode((login_hint or "").encode()).decode()
        return f"{redirect_uri}?{urlencode({'provider': self.provider, 'code': code, 'state': state})}"

    async def exchange(self, *, code: str, **_: Any) -> dict[str, Any]:
        try:
            email = base64.urlsafe_b64decode(code.removeprefix("mock-").encode()).decode()
        except Exception:  # noqa: BLE001 - a malformed code yields no identity and the service answers 401
            email = ""
        log.info("sso_mock_exchange", email=email[:3] + "…" if email else None)
        return {"email": email, "name": email.split("@")[0] if email else None, "groups": []}
