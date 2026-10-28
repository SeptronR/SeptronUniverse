# VAPT scope and rules of engagement

Prompts/43 §43.6 `vapt_service`. Findings are tracked in [`VAPT_Findings.csv`](VAPT_Findings.csv) and shown on
`/admin/security` (VAPT tab) and `GET /api/v1/security/vapt`. **Launch gate:** no open high / critical finding, every
fixed finding retested (`retest = pass`), mediums either fixed or accepted with a written risk sign-off.

## In scope (staging only — never production data)

| Asset | Entry points | Notes |
|---|---|---|
| API | `https://staging-api.<domain>/api/v1/*` (2 500+ routes, OpenAPI at `/api/v1/openapi.json`) | JWT bearer, `X-API-Key`, `X-Institution-Id` / slug headers |
| Web SPA | `https://staging.<domain>/` (admin + 11 portals) | CSP report-only → enforce |
| Mobile | Android AAB / iOS TestFlight build pointing at staging | certificate pinning optional (`PIN_SHA256`) |
| Public website | `/site/{slug}/…`, custom domains, sitemap / robots, enquiry + result lookup forms | captcha + rate limits |
| Webhooks | inbound `POST /webhooks/in/{provider}/{connection_id}`, outbound deliveries (HMAC `X-Septron-Signature`) | SSRF guard on URLs |
| WebSocket | `/ws` job / notification streams | token in first frame |

Out of scope: third-party provider infrastructure (payment gateways, SMS / e-mail providers, DigiLocker), denial of
service, physical / social engineering, the operator's office network.

## Test accounts

One demo user per role on the staging tenant `demo-uni` (`seed_demo_institution.py --type university --all`); the
credential sheet is handed over out of band — never committed (`LOCAL_TEST_CREDENTIALS.md` is git-ignored). Two
tenants are seeded so cross-tenant isolation can be attacked (`demo-uni`, `demo-auto`).

## Rules of engagement

* Window agreed in writing; testers' source IPs allow-listed on the staging WAF; rate limits stay on.
* No destructive payloads against shared data; erasure / reset endpoints only on the tester's own probe records.
* Critical findings are reported immediately (security contact in the engagement letter), others in the final report.
* Retest within 15 working days of fixes; results recorded in the `retest` column.

## Focus areas (from the threat model)

Tenant isolation (RLS, header spoofing, college scope), authorization on every route (the access matrix is the oracle),
IDOR on single-row GETs (must be 404), PII masking, file upload (MIME sniffing, size, SVG, EXIF), SSRF on webhook /
LTI / import URLs, template injection (notification / document templates), JWT handling (algorithm confusion, `kid`),
refresh-token reuse, MFA bypass, impersonation, rate limits on login / OTP / result lookup, exam decode / result
publish IP allow-lists, payment callback signature verification.
