# SeptronUniverse — Integrations Catalogue

All external systems are reached through **adapters** registered in `app/integrations/registry.py` (`@register_adapter(capability, provider)`). Each capability has an interface; each provider implements it; every provider ships with a **mock** so features work end-to-end in dev/demo before real credentials exist (an Orbit lesson: several providers were never run live). Per-tenant credentials live in `integration_connections` (encrypted), with health checks and a super-admin health page.

## 1. Interfaces (capabilities)

| Capability | Interface (key methods) | Used by |
|---|---|---|
| `PaymentGateway` | `create_order`, `verify_signature`, `refund`, `fetch_status`, `webhook_parse` | fees, admissions, hostel, convocation, certificates |
| `UpiCollect` | `generate_qr(amount, ref)`, `poll_status` | fee counter, student app |
| `SmsProvider` | `send(template_id, to, vars)`, `delivery_status`, `dlt_register` | comms |
| `WhatsAppProvider` | `send_template`, `send_session_message`, `webhook_parse`, `template_status` | comms, bot |
| `EmailProvider` | `send`, `bounce_webhook`, `domain_auth_status` | comms |
| `PushProvider` | `send`, `subscribe_topic`, `register_device` | comms, mobile |
| `IdentityProvider` | `authorize_url`, `exchange_code`, `userinfo`, `saml_metadata` | SSO |
| `LtiPlatform` / `LmsSync` | `launch`, `deep_link`, `sync_courses`, `sync_grades` | LMS ↔ Moodle |
| `VideoConference` | `create_meeting`, `join_link`, `attendance_report` | LMS sessions |
| `CredentialDepository` | `push_credential`, `revoke`, `status` | DigiLocker/NAD |
| `CreditBank` | `push_credits`, `revoke_credits`, `fetch_learner` | ABC |
| `ScholarshipPortal` | `fetch_applications`, `push_verification`, `disbursement_status` | NSP |
| `MoocProvider` | `fetch_completions(learner)`, `verify_certificate` | SWAYAM/NPTEL |
| `PublicationLookup` | `lookup_doi`, `fetch_author_works(orcid|scopus_id)` | research |
| `PlagiarismChecker` | `submit(file)`, `report(id)` | thesis, assignments |
| `RepositoryPublisher` | `deposit(metadata, file)`, `status` | Shodhganga/DSpace |
| `LibrarySystem` | `sync_catalogue`, `sync_members`, `circulation_events` | Koha |
| `AttendanceDevice` | `pull_punches`, `push_users`, `webhook_parse` | biometric/RFID |
| `FaceVerifier` | `enrol(photo)`, `verify(photo, template)` | hall attendance |
| `ESignProvider` | `sign(pdf, signer)`, `verify(pdf)` | degrees, certificates |
| `EkycProvider` | `initiate`, `verify_otp`, `fetch_profile` | admissions (optional) |
| `AccountingExport` | `export_vouchers(period)` | Tally/Zoho |
| `WorkspaceProvisioner` | `create_account`, `suspend`, `add_to_group` | Google Workspace / M365 |
| `MapTiles` | tile URL provider | transport |
| `LlmProvider` | `chat(messages, tools)` | AI assistant |

## 2. Providers

| Capability | Providers (initial) | Notes / prerequisites |
|---|---|---|
| PaymentGateway | Razorpay (first), PayU, Cashfree, Stripe (GENERIC) | merchant KYC; webhook secret; signature verification mandatory (Orbit P0 finding) |
| UpiCollect | Razorpay QR, bank VPA static QR | |
| SmsProvider | MSG91, Twilio | DLT entity & template registration (India) |
| WhatsAppProvider | Meta Cloud API | business verification; template approval registry |
| EmailProvider | SMTP, SendGrid, Amazon SES | per-tenant domain SPF/DKIM/DMARC (`integrations.email_domain_auth`) |
| PushProvider | FCM, WebPush (VAPID), Expo (optional) | |
| IdentityProvider | Google OIDC, Microsoft Entra OIDC, generic OIDC, SAML 2.0 | JIT user linking by email; role mapping table |
| LtiPlatform / LmsSync | LTI 1.3 (Advantage), Moodle web services | keys/JWKS; course & grade mapping |
| VideoConference | Zoom, Google Meet, MS Teams | OAuth app per tenant |
| CredentialDepository | DigiLocker Issuer API (NAD) | issuer onboarding with DigiLocker; sandbox first |
| CreditBank | ABC API | via DigiLocker/APAAR ecosystem |
| ScholarshipPortal | NSP (file/API as available) | institution nodal officer credentials |
| MoocProvider | SWAYAM/NPTEL certificate verification | certificate QR/ID verification |
| PublicationLookup | Crossref (DOI), ORCID public API, Scopus (licensed), Google Scholar (scrape-free: manual) | |
| PlagiarismChecker | DrillBit, Urkund/Ouriginal, Turnitin | institution licence |
| RepositoryPublisher | Shodhganga (INFLIBNET), DSpace | coordinator account |
| LibrarySystem | Koha REST | |
| AttendanceDevice | ZKTeco/ESSL (ADMS push), generic CSV import, RFID readers (HTTP) | device tokens |
| FaceVerifier | optional cloud/on-prem provider | consent required |
| ESignProvider | eSign (Aadhaar-based ASP), DSC token signing | DSC procurement |
| EkycProvider | Aadhaar eKYC via AUA/KUA (optional) | regulatory approval |
| AccountingExport | Tally XML, Zoho Books API | |
| WorkspaceProvisioner | Google Workspace Admin SDK, Microsoft Graph | |
| MapTiles | OSM (default), Mapbox | |
| LlmProvider | Groq, OpenAI, Azure OpenAI, local (Ollama) | feature `comms.ai_assistant` |

## 3. Platform APIs offered by SeptronUniverse

| Item | Design |
|---|---|
| OpenAPI | `/api/v1/openapi.json` + Redoc; tags per module; exported for TS/Dart generation |
| API keys | `api_keys(institution_id, name, hashed_key, scopes[], rate_limit, expires_at, last_used_at)`; scoped to permission modules; `X-API-Key` header; audited |
| Webhooks | `webhooks(institution_id, url, secret, events[], is_active)`; `webhook_deliveries(webhook_id, event_id, status, attempts, response_code, next_retry_at)`; HMAC-SHA256 signature; exponential retry; dead-letter after N attempts; event catalogue (student.admitted, registration.approved, result.published, fee.paid, hostel.checked_in, …) sourced from the domain-event outbox |
| Data import | `data_imports(entity, file_url, mapping, status, report)`; templates per entity; validation → dry-run → apply → rollback |
| Data export | tenant/user export jobs (JSON/CSV) for portability and DSR |

## 4. Connection management
- `integration_connections(institution_id, capability, provider, config_encrypted, status, last_health_at, last_error)`; secrets encrypted with a per-environment key (env/vault), never logged.
- Health checks: Beat job per connection (`ping`), surfaced on super-admin **Integration health** and institution **Integrations** pages.
- Circuit breaker + timeout + retry policy per provider; failures produce dead-letter items with admin retry.
- Sandbox mode per connection (`is_sandbox`) so demo tenants never hit production providers.

## 5. Real-world onboarding tracker
`Real_World_Launch_Plan.md` tracks, per provider: owner, documents, application date, sandbox status, live status, first live transaction — so integrations are not "done in code but never live".

## 6. Verification (API + UI)
For every adapter: (1) mock provider passes the capability's functional script (create → status → webhook); (2) connection page shows health; (3) feature gated by its `integrations.*` key returns 403 when disabled; (4) sandbox credentials run one live sandbox transaction before marking "live-ready".
