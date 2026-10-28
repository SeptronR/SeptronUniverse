# SeptronUniverse — Real-World Launch Readiness Plan (skeleton)

_Status: **skeleton** (Batch I, 2026-09-15). Scope: everything beyond functional QA needed to go live with real institutions — payment gateway live mode, government/regulatory integrations (DigiLocker/NAD, ABC/APAAR, NSP, DLT), messaging providers, devices, app-store releases, VAPT, DR, data migration, training, pilots, support. Rows are updated by the phases that own them (Phase 41 providers, Phase 43 VAPT/ISO, Phase 44 environments/DR/performance/go-no-go). Shape adapted from SeptronOrbit's `Real_World_Launch_Plan.md` — Orbit's lessons (Razorpay never run live, WhatsApp templates never approved, DLT lead time, Flutter never compiled, no restore ever tested) are the reason every row here needs a **live** evidence column, not just "implemented"._

Legend for status columns: `☐ not started` · `🟡 in progress` · `🧪 sandbox verified` · `✅ live verified` · `⛔ blocked`.

## 0. Where we stand

| Area | Code status (phase) | Real-world status | Evidence |
|---|---|---|---|
| Payments — Razorpay (fees, admissions, hostel, convocation, SaaS billing) | Phase 12/38/41 | ☐ never run in live mode | first live ₹1 transaction id |
| UPI collect (QR / VPA) | Phase 12/41 | ☐ | |
| SMS — MSG91/Twilio with **DLT** | Phase 04/24/41 | ☐ DLT entity + templates not registered | DLT entity id, template ids |
| WhatsApp — Meta Cloud API | Phase 04/24/41 | ☐ no business verification, no approved templates | WABA id, template approval list |
| Email — SMTP/SendGrid/SES with per-tenant SPF/DKIM/DMARC | Phase 04/41 | ☐ | spam-placement test log |
| Push — FCM / WebPush | Phase 24/39/42 | ☐ no physical device has received a push | device screenshot |
| DigiLocker / NAD issuer (degrees, certificates) | Phase 18/41 | ☐ issuer onboarding not started | sandbox pull → live pull |
| ABC / APAAR credit push | Phase 18/41 | ☐ | |
| NSP scholarship portal | Phase 12/41 | ☐ | |
| eSign / DSC on degrees & certificates | Phase 18/26/41 | ☐ | |
| SSO (Google / Microsoft OIDC, SAML) | Phase 02/41 | ☐ | |
| LMS/Moodle LTI, Zoom/Meet/Teams | Phase 13/41 | ☐ | |
| Biometric / RFID attendance devices | Phase 06/11/41 | ☐ never connected to a physical terminal | |
| GPS transport check-in, driver app | Phase 21/42 | ☐ | |
| Flutter app (Android/iOS) | Phase 42 | ☐ | first signed build + store internal test |
| Play Store / App Store listings | Phase 42/44 | ☐ | |
| VAPT (ASVS L2) | Phase 43 | 🟡 scope, ASVS self-assessment and findings tracker ready (`docs/Security/`); external test not run | report + retest |
| Backups & restore drill (RPO 15 min / RTO 4 h) | Phase 44 | ☐ no restore ever tested | drill record |
| Monitoring / alerting / status page | Phase 44 | ☐ | |
| Data migration from legacy systems (pilot) | Phase 41 | ☐ | reconciliation sign-off |

---

## 1. Environments (Phase 44)

| Env | API URL | Web URL | Site/status | Deploy trigger | Secrets custody | Status |
|---|---|---|---|---|---|---|
| dev | https://dev-api.universe.septronr.com | https://dev-app.universe.septronr.com | — | `develop` push → `build.yml` → orbit-infra | host vault (dev) | ☐ |
| demo (nightly reset) | https://demo-api.universe.septronr.com | https://demo-app.universe.septronr.com | https://demo.universe.septronr.com/site/demo-uni | `main` push | host vault (demo) | ☐ |
| staging | https://staging-api.universe.septronr.com | https://staging-app.universe.septronr.com | status: https://status.universe.septronr.com (staging) | `release/**` / tag | host vault (staging) | ☐ |
| prod | https://api.universe.septronr.com | https://app.universe.septronr.com | https://status.universe.septronr.com | tag + `prod` environment approval + change ticket | vault, 2-person access | ☐ |

Per-env feature-flag defaults (`platform_settings['features.env_defaults']`), read-only windows, and `orbit-infra` compose files (`compose/apps/universe-{dev,demo,staging,prod}.yml`) are recorded here when created.

---

## 2. Providers go-live tracker (Phase 41 owns; one row per capability × provider — `docs/Integrations_Catalogue.md` §5)

| Capability | Provider | Owner | Documents / prerequisites | Applied on | Sandbox verified | Live verified | First live transaction | Notes |
|---|---|---|---|---|---|---|---|---|
| PaymentGateway | Razorpay | | merchant KYC (PAN, bank, GST), webhook secret, settlement account | | ☐ | ☐ | | signature verification mandatory; refunds & disputes procedure |
| PaymentGateway | PayU / Cashfree (optional) | | | | ☐ | ☐ | | |
| UpiCollect | Razorpay QR / bank VPA | | | | ☐ | ☐ | | counter + student app |
| SmsProvider | MSG91 (DLT) | | DLT entity registration, sender id, template registration (lead time 1–2 weeks) | | ☐ | ☐ | | OTP + transactional templates per pack |
| SmsProvider | Twilio (fallback) | | | | ☐ | ☐ | | |
| WhatsAppProvider | Meta Cloud API | | Meta business verification, WABA, phone number, template approvals (biggest lead time) | | ☐ | ☐ | | messaging tier ramp; per-tenant numbers |
| EmailProvider | SendGrid / SES / SMTP | | sender domain SPF/DKIM/DMARC; per-tenant domain auth | | ☐ | ☐ | | spam placement test on Gmail/Outlook/Yahoo |
| PushProvider | FCM / WebPush (VAPID) | | Firebase project for the real bundle ids | | ☐ | ☐ | | foreground/background/killed states |
| IdentityProvider | Google / Microsoft OIDC, SAML | | tenant OAuth apps | | ☐ | ☐ | | JIT linking, role mapping |
| LtiPlatform / LmsSync | LTI 1.3 / Moodle | | keys/JWKS | | ☐ | ☐ | | |
| VideoConference | Zoom / Meet / Teams | | OAuth app per tenant | | ☐ | ☐ | | |
| CredentialDepository | DigiLocker issuer (NAD) | | issuer onboarding, sandbox credentials | | ☐ | ☐ | | degree/certificate push, revoke |
| CreditBank | ABC / APAAR | | via DigiLocker ecosystem | | ☐ | ☐ | | credit push after result publish |
| ScholarshipPortal | NSP | | nodal officer credentials | | ☐ | ☐ | | |
| MoocProvider | SWAYAM / NPTEL | | | | ☐ | ☐ | | certificate verification |
| PublicationLookup | Crossref / ORCID / Scopus | | Scopus licence | | ☐ | ☐ | | |
| PlagiarismChecker | DrillBit / Ouriginal / Turnitin | | institution licence | | ☐ | ☐ | | thesis + assignments |
| RepositoryPublisher | Shodhganga / DSpace | | coordinator account | | ☐ | ☐ | | |
| LibrarySystem | Koha | | | | ☐ | ☐ | | |
| AttendanceDevice | ZKTeco/ESSL (ADMS), RFID | | physical device, device token | | ☐ | ☐ | | duplicate/offline backlog tests |
| FaceVerifier | (optional) | | consent | | ☐ | ☐ | | |
| ESignProvider | eSign ASP / DSC | | DSC procurement | | ☐ | ☐ | | |
| EkycProvider | Aadhaar eKYC (optional) | | AUA/KUA approval | | ☐ | ☐ | | |
| AccountingExport | Tally / Zoho Books | | | | ☐ | ☐ | | |
| WorkspaceProvisioner | Google Workspace / M365 | | admin SDK / Graph app | | ☐ | ☐ | | |
| MapTiles | OSM / Mapbox | | Mapbox token | | ☐ | ☐ | | |
| LlmProvider | Groq / OpenAI / Azure / Ollama | | API keys; DPDP review | | ☐ | ☐ | | feature `comms.ai_assistant` |

---

## 3. Security (Phase 43)

| Item | Scope / owner | Date | Findings (P0/P1/P2) | Retest | Status |
|---|---|---|---|---|---|
| VAPT (external) | API, web, mobile, public site + custom domains, webhooks — `docs/Security/VAPT_Scope.md` | | | | ☐ |
| ASVS L2 self-assessment | `docs/Security/ASVS_L2_Checklist.md` | | | | ☐ |
| DPDP compliance review (consents, DSRs, breach notice) | privacy officer | | | | ☐ |
| Secrets & key custody (JWT `kid`, integration encryption key, backup keys, webhook secrets) | | | | | ☐ |
| ISO 27001 readiness (evidence pack: scans, drills, access matrix, audit chain) | | | | | ☐ |

## 4. Backups & DR (Phase 44)

| Item | Target | Observed | Date | Evidence | Status |
|---|---|---|---|---|---|
| Base backups + WAL archiving to S3-compatible storage (encrypted) | full weekly, incr 6-hourly, WAL continuous | | | `pgbackrest info` | ☐ |
| Uploads bucket versioning | previous versions 90 d | | | | ☐ |
| Restore drill (quarterly) | RPO ≤ 15 min, RTO ≤ 4 h | RPO __ min / RTO __ min | | `RestoreDrill` record + report | ☐ |
| DR runbook walked end-to-end on a throwaway host | once before launch | | | | ☐ |
| Per-tenant logical export (top-tier plan) | weekly | | | | ☐ |

## 5. Performance (Phase 43 load suite on the Phase 44-tuned staging stack; targets from `docs/Technical_Architecture.md` §17)

| Scenario | Target | Result | Date | Status |
|---|---|---|---|---|
| List p95 / detail p95 | < 300 ms / < 150 ms | | | ☐ |
| Registration rush | 5 000 concurrent students | | | ☐ |
| Result publish | 20 000 rows/min | | | ☐ |
| Hall-ticket bulk | 10 000 PDFs < 15 min | | | ☐ |
| Result run | 10 000 × 8 courses < 10 min | | | ☐ |
| Web LCP / mobile cold start | < 2.5 s / < 2 s | | | ☐ |
| Availability (staging soak) | 99.5 % | | | ☐ |

## 6. Data migration — pilot cutover (Phase 41 workbook)

| Item | Owner | Plan | Status |
|---|---|---|---|
| Legacy source inventory (system, entities, volumes) | | | ☐ |
| Workbook templates issued to the pilot institution | | | ☐ |
| Dry-run import + error report iterations | | | ☐ |
| Data freeze date / cutover window (read-only in legacy) | | | ☐ |
| Reconciliation sign-off (counts, fee balances, results parity) | | | ☐ |
| Rollback rehearsal | | | ☐ |

## 7. Training & enablement

| Audience | Format | Material (help articles, tours) | Session date | Status |
|---|---|---|---|---|
| Institution admin / registrar / COE | role-wise workshops | | | ☐ |
| HOD / faculty | department sessions + in-app tours | | | ☐ |
| Accounts / HR / campus services | | | | ☐ |
| Students / parents | portal guide, app onboarding | | | ☐ |
| Support team | runbooks, escalation matrix | | | ☐ |

## 8. Pilot institutions

| Institution | Type (affiliated / autonomous / university) | Plan | Go-live date | Success criteria | Status |
|---|---|---|---|---|---|
| (first pilot — one institution, whole funnel live: real payment, real device, real SMS/WhatsApp/push, app on staff/student phones) | | | | e.g. one full term: registration → attendance → exam → results published without manual workaround | ☐ |
| | | | | | ☐ |

## 9. Support & operations

| Item | Detail | Status |
|---|---|---|
| On-call rota & paging (critical alerts) | | ☐ |
| SLAs (P0 response/resolution, P1, P2) | | ☐ |
| Escalation matrix (support → engineering → provider) | | ☐ |
| Exam-day checklist owners (read-only for migrations, allow-lists, capacity, status notice) | | ☐ |
| Ticketing / support portal for institution admins | | ☐ |

## 10. Communications

| Item | Detail | Status |
|---|---|---|
| Public status page live (`status.universe.septronr.com`) | components, uptime bars, incidents, RSS | ☐ |
| Announcement templates (release notes, maintenance, incident opened/resolved) | Phase 38/44 templates | ☐ |
| Institution-admin incident notifications (`saas.notify_incidents`) | | ☐ |
| Release notes cadence & deprecation policy (90-day notice) | | ☐ |

---

## 11. Mobile app store readiness (Phase 42/44)

| Item | Android | iOS | Status |
|---|---|---|---|
| Developer accounts | Google Play ($25 one-time) | Apple Developer Program ($99/yr, Mac for archive) | ☐ |
| Signing custody | upload keystore in vault (loss = new package name) | distribution cert + profiles via `match` | ☐ |
| Firebase config for real bundle ids | `google-services.json` | `GoogleService-Info.plist` | ☐ |
| Store listing (screenshots phone + tablet, privacy policy URL, data-safety / privacy nutrition labels — student PII, location for transport) | | | ☐ |
| Deep links (`assetlinks.json`, AASA) | | | ☐ |
| Lanes: `beta` (internal testing / TestFlight) → `release` phased 10 → 50 → 100 % gated on crash-free ≥ 99.5 % | `mobile-release.yml` | | ☐ |
| Review lead time budgeted (education / minors policies) | 1–7 days | extra cycles | ☐ |

---

## 12. Sequencing (start the long-lead items now, in parallel)

1. Razorpay live KYC · Meta business verification + WhatsApp template submissions · DLT entity/template registration · DigiLocker issuer onboarding · Google Play + Apple accounts · Scopus/plagiarism licences.
2. When accounts/approvals land: live ₹1 payment dry runs (fees, admissions, hostel, SaaS) → messaging live sends (spam placement, DLT delivery reports) → push on physical devices → biometric device pilot → DigiLocker sandbox → live push.
3. Staging soak: load suite on the tuned stack → VAPT → restore drill → runbooks walked → status page live.
4. Pilot institution cutover (migration workbook, freeze, reconciliation) → staged mobile rollout → go/no-go.

## 13. Go / no-go checklist and sign-offs

| Gate | Evidence | Owner | Sign-off |
|---|---|---|---|
| QA release gate (`QA_Test_Plan.md` §7): 0 open P0/P1; `api_all`, `e2e all`, `visibility`, `immutability`, `golden` green | verify.yml run link | | ☐ |
| Security: VAPT retest passed; scans without high findings; secrets custody documented | | | ☐ |
| DR: restore drill within 100 days, RPO/RTO met | drill record | | ☐ |
| Performance: §5 targets met on staging | load report | | ☐ |
| Providers: every capability used by the pilot is ✅ live verified | §2 rows | | ☐ |
| Data migration reconciliation signed by the pilot institution | | | ☐ |
| Training delivered; support rota live; status page live | | | ☐ |
| Mobile: beta installed by pilot users; store listings approved | | | ☐ |
| **Go decision** | | | ☐ |
