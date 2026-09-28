"""``PUBLIC_ROUTES`` registry — routes that intentionally carry no ``permission_required`` (no auth).

``scripts/check_authz_coverage.py`` fails CI for any ``/api/v1`` route that is neither protected nor listed here.
Entries are ``"METHOD /api/v1/path"`` exactly as FastAPI reports them (path params as ``{name}``).
Phases append their public routes (login/OTP, public config, website, verification landing, payment webhooks, ...).
"""

PUBLIC_ROUTES: set[str] = {
    # Phase 01 — platform configuration for clients before sign-in
    "GET /api/v1/public/config",
    "GET /api/v1/platform/read-only",
    "GET /api/v1/mobile/config",
    "POST /api/v1/mobile/config",
    # Phase 02 — authentication (rate-limited; captcha on the public forms when configured)
    "POST /api/v1/auth/login",
    "POST /api/v1/auth/send-otp",
    "POST /api/v1/auth/verify-otp",
    "POST /api/v1/auth/refresh",
    "POST /api/v1/auth/forgot-password",
    "POST /api/v1/auth/reset-password",
    "GET /api/v1/auth/sso/{provider}/start",
    "GET /api/v1/auth/sso/{provider}/callback",
    # one-time bootstrap, guarded by INSTALL_SECRET_KEY
    "POST /api/v1/install",
    # Phase 03 — public settings (is_public keys + resolved theme) for login pages / the website
    "GET /api/v1/settings/public",
    # Phase 04 — signed one-click unsubscribe and provider callbacks (HMAC signature verified in the service)
    "GET /api/v1/notification-preferences/unsubscribe",
    "POST /api/v1/webhooks/{provider}/{channel}",
    # Phase 05 — public course catalogue (tenant from ?institution=<slug> / host; {academics.public_catalog})
    "GET /api/v1/public/catalog",
    "GET /api/v1/public/catalog/programs/{code}",
    "GET /api/v1/public/catalog/courses/{regulation}/{code}",
}


def is_public(method: str, path: str) -> bool:
    return f"{method.upper()} {path}" in PUBLIC_ROUTES
