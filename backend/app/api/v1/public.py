"""``PUBLIC_ROUTES`` registry — routes that intentionally carry no ``permission_required`` (no auth).

``scripts/check_authz_coverage.py`` fails CI for any ``/api/v1`` route that is neither protected nor listed here.
Entries are ``"METHOD /api/v1/path"`` exactly as FastAPI reports them (path params as ``{name}``).
Phases append their public routes (login/OTP, public config, website, verification landing, payment webhooks, ...).
"""

PUBLIC_ROUTES: set[str] = {
    "POST /api/v1/auth/login",  # Phase 00 placeholder (401 until Phase 02 ships authentication)
    # Phase 01 — platform configuration for clients before sign-in
    "GET /api/v1/public/config",
    "GET /api/v1/platform/read-only",
    "GET /api/v1/mobile/config",
    "POST /api/v1/mobile/config",
}


def is_public(method: str, path: str) -> bool:
    return f"{method.upper()} {path}" in PUBLIC_ROUTES
