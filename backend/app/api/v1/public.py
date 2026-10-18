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
    # Phase 06 — biometric device punches (device token) and the public careers page ({hr.recruitment})
    "POST /api/v1/attendance-devices/{id}/punches",
    # Phase 11 — student device punches (device token; {attendance.biometric|rfid} checked in the route)
    "POST /api/v1/attendance/devices/{id}/punches",
    "GET /api/v1/public/careers",
    "POST /api/v1/public/careers/{posting_id}/apply",
    # Phase 07 — public verification of the ID-card QR (HMAC-signed token; Phase 26 unifies document verification)
    "GET /api/v1/verify/{token}",
    # Phase 08 — public admissions (tenant from ?institution=<slug> / host; each route checks its admissions feature):
    # cycle listing / details, application start with OTP (captcha + rate limit), masked merit list, website enquiry
    "GET /api/v1/public/admissions/cycles",
    "GET /api/v1/public/admissions/cycles/{slug}",
    "POST /api/v1/public/admissions/{slug}/start",
    "GET /api/v1/public/admissions/{slug}/merit-lists/{id}",
    "POST /api/v1/public/enquiries",
    # Phase 10 — iCal feeds: a personal feed token (hash in ``calendar_feed_tokens``) or a signed section link
    "GET /api/v1/timetables/ical/{token}.ics",
    "GET /api/v1/timetables/sections/{id}.ics",
    # Phase 12 — payment gateway webhooks (provider signature verified; tenant from ?institution=<slug> / header)
    "POST /api/v1/webhooks/payments/{provider}",
    # Phase 14 — public hall-ticket verification (random token; masked identity)
    "GET /api/v1/hall-tickets/verify/{token}",
    # Phase 15 — public result lookup (reg. no + DOB; rate-limited + captcha; audience=public sessions only).
    # Grade-card QR verification reuses "GET /api/v1/verify/{token}" (Phase 07).
    "POST /api/v1/public/results/lookup",
}


def is_public(method: str, path: str) -> bool:
    return f"{method.upper()} {path}" in PUBLIC_ROUTES
