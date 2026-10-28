"""Provider catalogue — Prompts/41 §41.2 / docs/Integrations_Catalogue.md §1–2.

One entry per (capability, provider): display name, the connection form's JSON Schema (``secret`` fields are
write-only and encrypted), sandbox support, inbound webhook path, docs link and prerequisites. Capability keys are
the registry's (``app/integrations/registry.py:CAPABILITIES``); ``CAPABILITY_INFO`` maps each to its catalogue name,
interface methods, timeout class, the integration feature key that gates its connections and the module features that
use it (``GET /integrations/capabilities``). Revision ``0041`` stores :func:`catalogue_json` in
``platform_settings['integrations.providers']``; the code is the source of truth.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CapabilityInfo:
    key: str
    name: str
    methods: tuple[str, ...]
    timeout: str
    feature: str | None
    used_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderInfo:
    capability: str
    code: str
    name: str
    fields: dict[str, dict[str, Any]] = field(default_factory=dict)
    sandbox_supported: bool = True
    webhook_path: str | None = None
    docs_url: str | None = None
    prerequisites: tuple[str, ...] = ()

    def config_schema(self) -> dict[str, Any]:
        props = {k: {kk: vv for kk, vv in v.items() if kk != "required"} for k, v in self.fields.items()}
        return {
            "type": "object",
            "properties": props,
            "required": [k for k, v in self.fields.items() if v.get("required")],
            "additionalProperties": True,
        }

    def secret_fields(self) -> list[str]:
        return [k for k, v in self.fields.items() if v.get("secret")]


def S(title: str, *, secret: bool = False, required: bool = True, fmt: str | None = None) -> dict[str, Any]:
    d: dict[str, Any] = {"type": "string", "title": title, "required": required}
    if secret:
        d["secret"] = True
        d["writeOnly"] = True
    if fmt:
        d["format"] = fmt
    return d


CAPABILITY_INFO: dict[str, CapabilityInfo] = {
    c.key: c
    for c in (
        CapabilityInfo(
            "payment",
            "PaymentGateway",
            ("create_order", "verify_signature", "refund", "fetch_status", "webhook_parse"),
            "payments",
            "integrations.payments",
            ("fees.online_payment", "admissions.online_application", "facilities.canteen_wallet"),
        ),
        CapabilityInfo(
            "upi", "UpiCollect", ("generate_qr", "poll_status"), "payments", "integrations.payments", ("fees.upi_qr",)
        ),
        CapabilityInfo("sms", "SmsProvider", ("send", "delivery_status", "dlt_register"), "sms", None, ("comms.sms",)),
        CapabilityInfo(
            "whatsapp",
            "WhatsAppProvider",
            ("send_template", "send_session_message", "webhook_parse", "template_status"),
            "whatsapp",
            None,
            ("comms.whatsapp", "comms.whatsapp_bot"),
        ),
        CapabilityInfo(
            "email", "EmailProvider", ("send", "bounce_webhook", "domain_auth_status"), "email", None, ("comms.email",)
        ),
        CapabilityInfo(
            "push",
            "PushProvider",
            ("send", "subscribe_topic", "register_device"),
            "push",
            None,
            ("comms.push", "portals.pwa_push"),
        ),
        CapabilityInfo(
            "sso",
            "IdentityProvider",
            ("authorize_url", "exchange", "userinfo", "saml_metadata"),
            "sso",
            "integrations.sso",
            ("security.sso",),
        ),
        CapabilityInfo(
            "lti",
            "LtiPlatform / LmsSync",
            ("launch", "deep_link", "sync_courses", "sync_grades"),
            "lti",
            "integrations.lti",
            ("lms.lti_moodle",),
        ),
        CapabilityInfo(
            "video_conf",
            "VideoConference",
            ("create_meeting", "join_link", "attendance_report"),
            "video",
            "integrations.video_conf",
            ("lms.online_class_links",),
        ),
        CapabilityInfo(
            "digilocker",
            "CredentialDepository",
            ("push_credential", "revoke", "status"),
            "digilocker",
            "integrations.digilocker_nad",
            ("degrees.digilocker_nad",),
        ),
        CapabilityInfo(
            "nad_abc",
            "CreditBank",
            ("push_credits", "revoke_credits", "fetch_learner"),
            "abc",
            "integrations.digilocker_nad",
            ("academics.abc_apaar",),
        ),
        CapabilityInfo(
            "nsp",
            "ScholarshipPortal",
            ("fetch_applications", "push_verification", "disbursement_status"),
            "nsp",
            "integrations.nsp",
            ("fees.nsp_integration",),
        ),
        CapabilityInfo(
            "swayam",
            "MoocProvider",
            ("fetch_completions", "verify_certificate"),
            "mooc",
            "integrations.swayam_nptel",
            ("academics.credit_transfer_mooc",),
        ),
        CapabilityInfo(
            "crossref",
            "PublicationLookup (DOI)",
            ("lookup_doi", "works", "citations"),
            "lookup",
            "integrations.scopus_crossref_orcid",
            ("research.publications",),
        ),
        CapabilityInfo(
            "orcid",
            "PublicationLookup (ORCID)",
            ("fetch_author_works", "works"),
            "lookup",
            "integrations.scopus_crossref_orcid",
            ("research.publications",),
        ),
        CapabilityInfo(
            "scopus",
            "PublicationLookup (Scopus)",
            ("fetch_author_works", "works", "citations"),
            "lookup",
            "integrations.scopus_crossref_orcid",
            ("research.api_score",),
        ),
        CapabilityInfo(
            "plagiarism",
            "PlagiarismChecker",
            ("submit", "report"),
            "plagiarism",
            "integrations.plagiarism",
            ("phd.thesis_plagiarism", "lms.similarity_check"),
        ),
        CapabilityInfo(
            "dspace",
            "RepositoryPublisher (DSpace)",
            ("deposit", "status"),
            "repository",
            "integrations.koha_dspace_shodhganga",
            ("phd.etd_upload",),
        ),
        CapabilityInfo(
            "shodhganga",
            "RepositoryPublisher (Shodhganga)",
            ("deposit", "status"),
            "repository",
            "integrations.koha_dspace_shodhganga",
            ("phd.etd_upload",),
        ),
        CapabilityInfo(
            "koha",
            "LibrarySystem",
            ("sync_catalogue", "sync_members", "circulation_events"),
            "library",
            "integrations.koha_dspace_shodhganga",
            ("library.koha_sync",),
        ),
        CapabilityInfo(
            "biometric",
            "AttendanceDevice (biometric)",
            ("pull_punches", "push_users", "webhook_parse"),
            "device",
            "integrations.biometric_rfid",
            ("attendance.biometric",),
        ),
        CapabilityInfo(
            "rfid",
            "AttendanceDevice (RFID)",
            ("pull_punches", "webhook_parse"),
            "device",
            "integrations.biometric_rfid",
            ("attendance.rfid",),
        ),
        CapabilityInfo(
            "face_verification",
            "FaceVerifier",
            ("enrol", "verify"),
            "face",
            "integrations.face_verification",
            ("exams.face_verification",),
        ),
        CapabilityInfo("esign", "ESignProvider", ("sign", "verify"), "esign", "integrations.esign", ("degrees.esign",)),
        CapabilityInfo(
            "aadhaar_ekyc",
            "EkycProvider",
            ("initiate", "verify_otp", "fetch_profile"),
            "ekyc",
            "integrations.aadhaar_ekyc",
            (),
        ),
        CapabilityInfo(
            "accounting", "AccountingExport", ("export_vouchers",), "accounting", None, ("accounting.tally_export",)
        ),
        CapabilityInfo(
            "workspace",
            "WorkspaceProvisioner",
            ("create_account", "suspend", "add_to_group"),
            "workspace",
            "integrations.workspace_provisioning",
            (),
        ),
        CapabilityInfo("maps", "MapTiles", ("tile_url",), "lookup", None, ("transport.gps_live",)),
        CapabilityInfo("llm", "LlmProvider", ("chat",), "llm", None, ("comms.ai_assistant",)),
        CapabilityInfo("storage", "Storage", ("put", "get", "delete"), "lookup", None, ()),
        CapabilityInfo("captcha", "Captcha", ("verify",), "lookup", None, ()),
    )
}

_URL = S("Base URL", fmt="uri", required=False)
PROVIDERS: tuple[ProviderInfo, ...] = (
    # payments
    ProviderInfo(
        "payment",
        "razorpay",
        "Razorpay",
        {
            "key_id": S("Key id"),
            "key_secret": S("Key secret", secret=True),
            "webhook_secret": S("Webhook secret", secret=True),
        },
        webhook_path="/api/v1/webhooks/payments/razorpay",
        docs_url="https://razorpay.com/docs/api/",
        prerequisites=("merchant KYC", "webhook secret"),
    ),
    ProviderInfo(
        "payment",
        "payu",
        "PayU",
        {"merchant_key": S("Merchant key"), "salt": S("Salt", secret=True)},
        webhook_path="/api/v1/webhooks/in/payu",
        docs_url="https://docs.payu.in/",
        prerequisites=("merchant KYC",),
    ),
    ProviderInfo(
        "payment",
        "cashfree",
        "Cashfree",
        {"app_id": S("App id"), "secret_key": S("Secret key", secret=True)},
        webhook_path="/api/v1/webhooks/in/cashfree",
        docs_url="https://docs.cashfree.com/",
        prerequisites=("merchant KYC",),
    ),
    ProviderInfo(
        "payment",
        "stripe",
        "Stripe (GENERIC pack)",
        {"secret_key": S("Secret key", secret=True), "webhook_secret": S("Webhook signing secret", secret=True)},
        webhook_path="/api/v1/webhooks/in/stripe",
        docs_url="https://stripe.com/docs/api",
    ),
    ProviderInfo(
        "upi",
        "razorpay_qr",
        "Razorpay QR",
        {"key_id": S("Key id"), "key_secret": S("Key secret", secret=True)},
        docs_url="https://razorpay.com/docs/api/qr-codes/",
    ),
    ProviderInfo(
        "upi",
        "static_vpa",
        "Bank VPA (static QR)",
        {"vpa": S("UPI VPA"), "payee_name": S("Payee name")},
        sandbox_supported=False,
    ),
    # messaging
    ProviderInfo(
        "sms",
        "msg91",
        "MSG91",
        {
            "auth_key": S("Auth key", secret=True),
            "sender_id": S("Sender id"),
            "dlt_entity_id": S("DLT entity id", required=False),
        },
        webhook_path="/api/v1/webhooks/msg91/sms",
        docs_url="https://docs.msg91.com/",
        prerequisites=("DLT entity & template registration",),
    ),
    ProviderInfo(
        "sms",
        "twilio",
        "Twilio",
        {"account_sid": S("Account SID"), "auth_token": S("Auth token", secret=True), "from_number": S("From number")},
        webhook_path="/api/v1/webhooks/twilio/sms",
        docs_url="https://www.twilio.com/docs/sms",
    ),
    ProviderInfo(
        "whatsapp",
        "meta",
        "Meta WhatsApp Cloud",
        {
            "phone_number_id": S("Phone number id"),
            "access_token": S("Access token", secret=True),
            "app_secret": S("App secret", secret=True),
            "verify_token": S("Verify token", secret=True),
        },
        webhook_path="/api/v1/webhooks/whatsapp/{connection_id}",
        docs_url="https://developers.facebook.com/docs/whatsapp/cloud-api",
        prerequisites=("business verification", "template approval"),
    ),
    ProviderInfo(
        "email",
        "smtp",
        "SMTP",
        {
            "host": S("Host"),
            "port": {"type": "integer", "title": "Port", "required": True},
            "username": S("Username", required=False),
            "password": S("Password", secret=True, required=False),
            "from_email": S("From address", fmt="email"),
        },
        sandbox_supported=False,
    ),
    ProviderInfo(
        "email",
        "sendgrid",
        "SendGrid",
        {"api_key": S("API key", secret=True), "from_email": S("From address", fmt="email")},
        webhook_path="/api/v1/webhooks/sendgrid/email",
        docs_url="https://docs.sendgrid.com/",
    ),
    ProviderInfo(
        "email",
        "ses",
        "Amazon SES",
        {
            "region": S("Region"),
            "access_key_id": S("Access key id"),
            "secret_access_key": S("Secret access key", secret=True),
            "from_email": S("From address", fmt="email"),
        },
        webhook_path="/api/v1/webhooks/ses/email",
    ),
    ProviderInfo(
        "push",
        "fcm",
        "Firebase Cloud Messaging",
        {"project_id": S("Project id"), "service_account_json": S("Service account JSON", secret=True)},
        docs_url="https://firebase.google.com/docs/cloud-messaging",
    ),
    ProviderInfo(
        "push",
        "webpush",
        "Web Push (VAPID)",
        {
            "vapid_public_key": S("VAPID public key", required=False),
            "vapid_private_key": S("VAPID private key", secret=True, required=False),
        },
    ),
    # identity / learning
    ProviderInfo(
        "sso",
        "google",
        "Google OIDC",
        {
            "client_id": S("Client id"),
            "client_secret": S("Client secret", secret=True),
            "hosted_domain": S("Hosted domain", required=False),
        },
        docs_url="https://developers.google.com/identity/openid-connect",
    ),
    ProviderInfo(
        "sso",
        "microsoft",
        "Microsoft Entra OIDC",
        {"tenant": S("Tenant id"), "client_id": S("Client id"), "client_secret": S("Client secret", secret=True)},
    ),
    ProviderInfo(
        "sso",
        "oidc",
        "Generic OIDC",
        {
            "issuer": S("Issuer URL", fmt="uri"),
            "client_id": S("Client id"),
            "client_secret": S("Client secret", secret=True),
        },
    ),
    ProviderInfo(
        "sso",
        "saml",
        "SAML 2.0",
        {
            "idp_metadata_url": S("IdP metadata URL", fmt="uri"),
            "sp_private_key": S("SP private key (PEM)", secret=True, required=False),
        },
    ),
    ProviderInfo(
        "lti",
        "lti13",
        "LTI 1.3 Advantage",
        {
            "issuer": S("Platform issuer"),
            "client_id": S("Client id"),
            "jwks_url": S("Platform JWKS URL", fmt="uri"),
            "tool_private_key": S("Tool private key (PEM)", secret=True),
        },
    ),
    ProviderInfo(
        "lti",
        "moodle",
        "Moodle web services",
        {"base_url": S("Moodle URL", fmt="uri"), "token": S("Web-service token", secret=True)},
    ),
    ProviderInfo(
        "video_conf",
        "zoom",
        "Zoom",
        {"account_id": S("Account id"), "client_id": S("Client id"), "client_secret": S("Client secret", secret=True)},
        webhook_path="/api/v1/webhooks/in/zoom",
    ),
    ProviderInfo(
        "video_conf",
        "meet",
        "Google Meet",
        {"service_account_json": S("Service account JSON", secret=True), "impersonate": S("Organiser e-mail")},
    ),
    ProviderInfo(
        "video_conf",
        "teams",
        "Microsoft Teams",
        {"tenant": S("Tenant id"), "client_id": S("Client id"), "client_secret": S("Client secret", secret=True)},
    ),
    # government / credentials
    ProviderInfo(
        "digilocker",
        "digilocker",
        "DigiLocker issuer (NAD)",
        {"issuer_id": S("Issuer id"), "api_key": S("API key", secret=True), "base_url": _URL},
        webhook_path="/api/v1/webhooks/in/digilocker",
        prerequisites=("issuer onboarding with DigiLocker",),
    ),
    ProviderInfo(
        "nad_abc",
        "abc",
        "Academic Bank of Credits",
        {"institution_code": S("ABC institution code"), "api_key": S("API key", secret=True), "base_url": _URL},
    ),
    ProviderInfo(
        "nsp",
        "nsp",
        "National Scholarship Portal",
        {
            "institution_code": S("NSP institute code"),
            "username": S("Nodal officer user"),
            "password": S("Password", secret=True),
        },
        prerequisites=("institution nodal officer credentials",),
    ),
    ProviderInfo("swayam", "swayam", "SWAYAM / NPTEL verification", {"base_url": _URL}),
    # research / library
    ProviderInfo("crossref", "crossref", "Crossref", {"mailto": S("Polite-pool e-mail", fmt="email", required=False)}),
    ProviderInfo(
        "orcid",
        "orcid",
        "ORCID public API",
        {"client_id": S("Client id", required=False), "client_secret": S("Client secret", secret=True, required=False)},
    ),
    ProviderInfo(
        "scopus",
        "scopus",
        "Scopus (licensed)",
        {"api_key": S("API key", secret=True), "inst_token": S("Institution token", secret=True, required=False)},
    ),
    ProviderInfo(
        "plagiarism",
        "drillbit",
        "DrillBit",
        {"base_url": _URL, "api_key": S("API key", secret=True)},
        webhook_path="/api/v1/webhooks/plagiarism/{connection_id}",
    ),
    ProviderInfo(
        "plagiarism",
        "turnitin",
        "Turnitin",
        {"base_url": S("Tenant URL", fmt="uri"), "api_key": S("API key", secret=True)},
        webhook_path="/api/v1/webhooks/plagiarism/{connection_id}",
    ),
    ProviderInfo("plagiarism", "urkund", "Ouriginal (Urkund)", {"api_key": S("API key", secret=True)}),
    ProviderInfo(
        "dspace",
        "dspace",
        "DSpace REST",
        {
            "base_url": S("DSpace URL", fmt="uri"),
            "username": S("User"),
            "password": S("Password", secret=True),
            "collection": S("Collection handle"),
        },
    ),
    ProviderInfo(
        "shodhganga",
        "shodhganga",
        "Shodhganga (SWORD)",
        {
            "sword_url": S("SWORD URL", fmt="uri"),
            "username": S("Coordinator user"),
            "password": S("Password", secret=True),
        },
        prerequisites=("coordinator account",),
    ),
    ProviderInfo(
        "koha",
        "koha",
        "Koha REST",
        {
            "base_url": S("Koha URL", fmt="uri"),
            "client_id": S("Client id"),
            "client_secret": S("Client secret", secret=True),
        },
    ),
    # devices / identity checks / signing
    ProviderInfo(
        "biometric",
        "zkteco",
        "ZKTeco / ESSL (ADMS push)",
        {"device_serials": S("Device serials (comma separated)", required=False)},
        webhook_path="/api/v1/webhooks/in/zkteco/{connection_id}",
    ),
    ProviderInfo(
        "biometric",
        "csv",
        "Generic CSV pull",
        {"date_format": S("Date format", required=False)},
        sandbox_supported=False,
    ),
    ProviderInfo(
        "rfid",
        "rfid_http",
        "RFID reader (HTTP)",
        {"shared_token": S("Shared token", secret=True)},
        webhook_path="/api/v1/webhooks/in/rfid_http/{connection_id}",
    ),
    ProviderInfo(
        "face_verification",
        "face_api",
        "Face verifier (cloud / on-prem)",
        {
            "base_url": S("Endpoint", fmt="uri"),
            "api_key": S("API key", secret=True),
            "threshold": {"type": "number", "title": "Match threshold"},
        },
        prerequisites=("consent required",),
    ),
    ProviderInfo(
        "esign",
        "aadhaar_esign",
        "Aadhaar eSign (ASP)",
        {"asp_id": S("ASP id"), "base_url": _URL, "signing_key": S("ASP signing key (PEM)", secret=True)},
        webhook_path="/api/v1/webhooks/in/aadhaar_esign",
    ),
    ProviderInfo(
        "esign",
        "dsc",
        "DSC token signing service",
        {"base_url": S("Signing service URL", fmt="uri"), "api_key": S("API key", secret=True)},
        prerequisites=("DSC procurement",),
    ),
    ProviderInfo(
        "aadhaar_ekyc",
        "aua_kua",
        "Aadhaar eKYC (AUA/KUA)",
        {"aua_code": S("AUA code"), "license_key": S("Licence key", secret=True), "base_url": _URL},
        prerequisites=("regulatory approval",),
    ),
    ProviderInfo("accounting", "tally", "Tally XML", {"company": S("Tally company name")}, sandbox_supported=False),
    ProviderInfo(
        "accounting",
        "zoho_books",
        "Zoho Books",
        {
            "organization_id": S("Organisation id"),
            "refresh_token": S("Refresh token", secret=True),
            "client_id": S("Client id"),
            "client_secret": S("Client secret", secret=True),
        },
    ),
    ProviderInfo(
        "workspace",
        "google_workspace",
        "Google Workspace Admin SDK",
        {
            "domain": S("Domain"),
            "service_account_json": S("Service account JSON", secret=True),
            "admin_email": S("Admin e-mail"),
        },
    ),
    ProviderInfo(
        "workspace",
        "microsoft_graph",
        "Microsoft Graph",
        {
            "tenant": S("Tenant id"),
            "client_id": S("Client id"),
            "client_secret": S("Client secret", secret=True),
            "domain": S("Domain"),
        },
    ),
    ProviderInfo("maps", "osm", "OpenStreetMap", {}, sandbox_supported=False),
    ProviderInfo("maps", "mapbox", "Mapbox", {"access_token": S("Access token", secret=True)}),
    ProviderInfo("llm", "groq", "Groq", {"api_key": S("API key", secret=True), "model": S("Model", required=False)}),
    ProviderInfo(
        "llm", "openai", "OpenAI", {"api_key": S("API key", secret=True), "model": S("Model", required=False)}
    ),
    ProviderInfo(
        "llm",
        "azure_openai",
        "Azure OpenAI",
        {"endpoint": S("Endpoint", fmt="uri"), "api_key": S("API key", secret=True), "deployment": S("Deployment")},
    ),
    ProviderInfo("llm", "ollama", "Ollama (local)", {"base_url": S("Ollama URL", fmt="uri")}, sandbox_supported=False),
    ProviderInfo(
        "storage",
        "s3",
        "S3-compatible storage",
        {
            "bucket": S("Bucket"),
            "access_key_id": S("Access key id"),
            "secret_access_key": S("Secret", secret=True),
            "endpoint": _URL,
        },
    ),
    ProviderInfo(
        "captcha", "turnstile", "Cloudflare Turnstile", {"site_key": S("Site key"), "secret": S("Secret", secret=True)}
    ),
)
BY_CODE: dict[tuple[str, str], ProviderInfo] = {(p.capability, p.code): p for p in PROVIDERS}


def provider_info(capability: str, provider: str) -> ProviderInfo | None:
    return BY_CODE.get((capability, provider))


def catalogue_json() -> list[dict[str, Any]]:
    out = []
    for cap, info in CAPABILITY_INFO.items():
        out.append(
            {
                "capability": cap,
                "name": info.name,
                "methods": list(info.methods),
                "feature": info.feature,
                "used_by": list(info.used_by),
                "providers": [
                    {
                        "code": p.code,
                        "name": p.name,
                        "config_schema": p.config_schema(),
                        "secret_fields": p.secret_fields(),
                        "sandbox_supported": p.sandbox_supported,
                        "webhook_path": p.webhook_path,
                        "docs_url": p.docs_url,
                        "prerequisites": list(p.prerequisites),
                    }
                    for p in PROVIDERS
                    if p.capability == cap
                ]
                + [
                    {
                        "code": "mock",
                        "name": "Mock (development)",
                        "config_schema": {"type": "object", "properties": {}},
                        "secret_fields": [],
                        "sandbox_supported": True,
                        "webhook_path": None,
                        "docs_url": None,
                        "prerequisites": [],
                    }
                ],
            }
        )
    return out
