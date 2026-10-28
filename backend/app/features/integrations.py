"""Feature keys registered by Phase 41 (docs/Feature_Flags.md integrations / data groups).

``integrations.payments`` (Phase 12), ``integrations.koha_dspace_shodhganga`` (Phase 19 / 31),
``integrations.scopus_crossref_orcid`` / ``integrations.plagiarism`` (Phase 30) and ``data.export_portability``
(Phase 38) already exist; this module registers the remaining integration keys and the migration toolkit. Enabling a
provider connection never enables the module key that depends on it (super admin / plan decides).
"""

from app.core.features import register_feature

_P, _S = "professional", "standard"
for _key, _name, _desc, _on, _tier, _deps in (
    ("integrations.api_keys_webhooks", "API keys & webhooks", "outbound integration", False, _P, ()),
    ("integrations.sso", "SSO providers", "OIDC/SAML", False, _P, ()),
    ("integrations.lti", "LTI 1.3", "LMS interoperability", False, _P, ()),
    ("integrations.video_conf", "Video conferencing", "Zoom/Meet", False, _S, ()),
    ("integrations.digilocker_nad", "DigiLocker / NAD / ABC", "government depositories", False, _P, ()),
    ("integrations.nsp", "NSP", "scholarship portal", False, _P, ()),
    ("integrations.swayam_nptel", "SWAYAM / NPTEL", "MOOC credit import", False, _S, ()),
    ("integrations.biometric_rfid", "Biometric / RFID devices", "device protocols", False, _S, ()),
    ("integrations.face_verification", "Face verification", "face-match adapter", False, _P, ()),
    ("integrations.esign", "eSign / DSC", "digital signatures", False, _P, ()),
    ("integrations.aadhaar_ekyc", "Aadhaar eKYC", "identity verification", False, _P, ()),
    ("integrations.email_domain_auth", "Email domain auth", "SPF/DKIM/DMARC per tenant domain", False, _S, ("comms.email",)),
    (
        "integrations.workspace_provisioning",
        "Workspace provisioning",
        "Google/M365 accounts",
        False,
        _P,
        ("integrations.sso",),
    ),
):
    register_feature(
        key=_key, group="integrations", name=_name, description=_desc, default_enabled=_on, min_plan_tier=_tier, depends_on=_deps
    )

register_feature(
    key="data.migration_toolkit",
    group="data",
    name="Migration toolkit",
    description="templates, validation, apply, rollback",
    default_enabled=True,
    min_plan_tier="standard",
    depends_on=("core.background_jobs",),
)
