"""``PUBLIC_ROUTES`` registry — routes that intentionally carry no ``permission_required`` (no auth).

``scripts/check_authz_coverage.py`` fails CI for any ``/api/v1`` route that is neither protected nor listed here.
Entries are ``"METHOD /api/v1/path"`` exactly as FastAPI reports them (path params as ``{name}``).
Phases append their public routes (login/OTP, public config, website, verification landing, payment webhooks, ...).
"""

PUBLIC_ROUTES: set[str] = {
    # Phase 41 — inbound provider webhooks (signature verified by the connection's adapter; idempotent by event id)
    "POST /api/v1/webhooks/in/{provider}/{connection_id}",
    # Phase 43: published privacy notices (website / app) and sampled CSP violation reports
    "GET /api/v1/public/privacy/notices/{key}",
    "POST /api/v1/security/csp-report",
    "POST /api/v1/internal/security/scans",  # X-Ops-Token (CI)
    # Phase 44: public status page and the internal ops reports (X-Ops-Token)
    "GET /api/v1/public/status",
    "GET /api/v1/public/status/history",
    "GET /api/v1/public/status/feed.rss",
    "POST /api/v1/internal/ops/deploy-report",
    "POST /api/v1/internal/ops/backup-report",
    "POST /api/v1/internal/ops/restore-drill",
    "POST /api/v1/internal/ops/alert-events",
    "POST /api/v1/internal/ops/heartbeat/{queue}",
    "POST /api/v1/internal/ops/release",
    # Phase 40 — public website (tenant by ?slug / verified custom host / header; published rows, aggregates and tokens
    # only; the enquiry form and result lookup are captcha + rate limited), marketing / pricing (platform) and the
    # edge endpoints (X-Edge-Token)
    "GET /api/v1/public/site",
    "GET /api/v1/public/site/notices",
    "GET /api/v1/public/site/notices.rss",
    "GET /api/v1/public/site/notices/{notice_slug}",
    "GET /api/v1/public/site/events",
    "GET /api/v1/public/site/gallery",
    "GET /api/v1/public/site/gallery/{album}",
    "GET /api/v1/public/site/pages/{section}/{page_slug}",
    "GET /api/v1/public/site/disclosures",
    "GET /api/v1/public/site/faculty",
    "GET /api/v1/public/site/colleges",
    "GET /api/v1/public/site/departments/{code}",
    "POST /api/v1/public/site/enquiries",
    "GET /api/v1/public/catalogue",
    "GET /api/v1/public/catalogue/programmes/{code}",
    "GET /api/v1/public/catalogue/courses/{code}",
    "GET /api/v1/public/site/admissions",
    "GET /api/v1/public/site/affiliated-colleges",
    "GET /api/v1/public/site/verify/college/{code}",
    "POST /api/v1/public/site/results/lookup",
    "GET /api/v1/public/marketing",
    "GET /api/v1/public/pricing",
    "GET /api/v1/internal/domains",
    "POST /api/v1/internal/domains/{id}/ssl-status",
    # Phase 39 — PWA manifest / service-worker config / VAPID public key / icons and locale packs (tenant by
    # ?institution=<slug> or header; no PII)
    "GET /api/v1/public/manifest.json",
    "GET /api/v1/public/pwa-config",
    "GET /api/v1/public/push/vapid-key",
    "GET /api/v1/public/pwa-icons/{institution_id}/{size}.png",
    "GET /api/v1/public/locales/{lng}.json",
    # Phase 38 — self-serve registration / demo requests / pricing (captcha + rate limits) and the platform gateway
    # webhook (provider signature verified)
    "GET /api/v1/public/plans",
    "POST /api/v1/public/registrations",
    "GET /api/v1/public/registrations/{id}/status",
    "POST /api/v1/public/registrations/{id}/verify",
    "POST /api/v1/public/registrations/{id}/pay",
    "POST /api/v1/public/demo-requests",
    "POST /api/v1/public/billing/webhook",
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
    # Phase 16 — masked rank lists published ``public`` (setting ``exams.rank_list_public``). Transcript QR
    # verification (``tr`` + 48 hex tokens) reuses "GET /api/v1/verify/{token}".
    "GET /api/v1/public/results/rank-lists/{id}",
    # Phase 18 — degree / provisional QR tokens resolve through "GET /api/v1/verify/{token}"; employers verify in bulk
    # (rate-limited + captcha).
    "POST /api/v1/verify/bulk",
    # Phase 27 — anonymous grievances (captcha, rate-limited) and tracking by ticket + secret (tenant from
    # ?institution=<slug>; {grievances.core}/{grievances.anonymous} inside); alumni / employer survey links (tenant from
    # the token; single use; {surveys.core} inside)
    "POST /api/v1/grievances/anonymous",
    "GET /api/v1/grievances/track",
    "GET /api/v1/surveys/external/{token}",
    "POST /api/v1/surveys/external/{token}/respond",
    # Phase 26 — unified verification by file hash (rate-limited; no PII in the answer)
    "POST /api/v1/verify/hash",
    # Phase 19 — public OPAC (tenant from ?institution=<slug>; rate-limited)
    "GET /api/v1/opac/search",
    "GET /api/v1/opac/new-arrivals",
    "GET /api/v1/opac/books/{id}",
    # Phase 21 — GPS device ingest (X-Device-Token = gps_devices.token_hash; {transport.gps_live} checked inside)
    "POST /api/v1/transport/gps/device-ingest",
    # Phase 22 — supplier self-registration (tenant by institution slug; rate-limited + captcha; {inventory.vendor_portal} inside)
    "POST /api/v1/vendor/register",
    # Phase 24 — WhatsApp webhook (verify token on GET; X-Hub-Signature-256 on POST; {comms.whatsapp_bot} inside)
    "GET /api/v1/webhooks/whatsapp/{connection_id}",
    "POST /api/v1/webhooks/whatsapp/{connection_id}",
    # Phase 25 — iCal feeds ({calendar.ical} / {calendar.personal_feed} inside) and the website events list / external
    # registration (tenant by institution slug; rate-limited; {events.core} inside)
    "GET /api/v1/calendar/feed/{token}.ics",
    "GET /api/v1/calendar/ical/institution.ics",
    "GET /api/v1/calendar/ical/college/{college_id}.ics",
    "GET /api/v1/events/public",
    "POST /api/v1/events/public/{id}/register",
    # Phase 29 — alumni claim + OTP (tenant by institution slug; rate-limited + captcha; no enumeration) and the website
    # campaigns / donation form ({alumni.fundraising} inside; captcha; Idempotency-Key)
    "POST /api/v1/alumni/claim",
    "POST /api/v1/alumni/claim/verify",
    "GET /api/v1/fundraising/campaigns/public",
    "POST /api/v1/fundraising/donate/public",
    # Phase 31 — external examiner token pages (tenant by institution slug; unguessable token; {phd.external_examiners}
    # inside) and the plagiarism adapter callback (signature verified for live providers; {phd.thesis_plagiarism} inside)
    "GET /api/v1/phd/examiners/respond/{token}",
    "POST /api/v1/phd/examiners/respond/{token}",
    "POST /api/v1/phd/examiners/respond/{token}/report",
    "POST /api/v1/webhooks/plagiarism/{connection_id}",
    # Phase 32 — mandatory disclosures website feed (tenant by institution slug; aggregates only; {accreditation.aishe} inside)
    "GET /api/v1/accreditation/disclosures/public",
    # Phase 33 — published policies flagged for the website (tenant by institution slug; {governance.policies} inside)
    "GET /api/v1/policies/public",
    # Phase 34 — approved affiliated colleges / programmes for the website (tenant by institution slug; {affiliation.core})
    "GET /api/v1/affiliation/public/colleges",
    # Phase 35 — website counters (tenant by institution slug; only analytics.public_counter_keys, no college breakdown;
    # {analytics.core} inside)
    "GET /api/v1/analytics/public-counters",
}


def is_public(method: str, path: str) -> bool:
    return f"{method.upper()} {path}" in PUBLIC_ROUTES
