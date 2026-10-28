"""DPDP purposes, notices and DSR defaults — Prompts/43 §43.2.

Written to ``platform_settings['privacy.purposes' | 'privacy.notices' | 'privacy.dsr']`` by ``0043``; institutions
override notice texts in ``institution_settings`` category ``privacy`` (key ``notice:<key>``). Services read the
platform rows and fall back to these constants.
"""

from typing import Any

# key → (mandatory, legal basis, en text, hi text)
PURPOSES: dict[str, tuple[bool, str, str, str]] = {
    "academic": (
        True,
        "contract",
        "Academic administration: admission, teaching, examinations, results and records.",
        "शैक्षणिक प्रशासन: प्रवेश, शिक्षण, परीक्षा, परिणाम और अभिलेख।",
    ),
    "communication_transactional": (
        True,
        "contract",
        "Service messages about your studies, fees and campus services.",
        "आपकी पढ़ाई, शुल्क और परिसर सेवाओं से संबंधित सेवा संदेश।",
    ),
    "communication_marketing": (
        False,
        "consent",
        "Newsletters, events and promotional messages.",
        "समाचार पत्र, कार्यक्रम और प्रचार संदेश।",
    ),
    "photo_media": (
        False,
        "consent",
        "Use of your photographs and videos in publications and on the website.",
        "प्रकाशनों और वेबसाइट पर आपकी तस्वीरों और वीडियो का उपयोग।",
    ),
    "health": (
        False,
        "consent",
        "Health-centre and counselling records for your care.",
        "आपकी देखभाल के लिए स्वास्थ्य केंद्र और परामर्श अभिलेख।",
    ),
    "third_party_placement": (
        False,
        "consent",
        "Sharing your profile with recruiters for placements and internships.",
        "प्लेसमेंट और इंटर्नशिप के लिए भर्तीकर्ताओं के साथ आपकी प्रोफ़ाइल साझा करना।",
    ),
    "analytics_external": (
        False,
        "consent",
        "External analytics on the website and apps.",
        "वेबसाइट और ऐप पर बाहरी विश्लेषण।",
    ),
    "biometric": (
        False,
        "consent",
        "Face or fingerprint verification for attendance and access.",
        "उपस्थिति और प्रवेश के लिए चेहरे या फिंगरप्रिंट सत्यापन।",
    ),
    "location": (
        False,
        "consent",
        "Device location for geo-fenced attendance and transport tracking.",
        "जियो-फेंस्ड उपस्थिति और परिवहन ट्रैकिंग के लिए डिवाइस स्थान।",
    ),
    "guardian_access": (
        False,
        "consent",
        "Your parent / guardian can see your attendance, results and fees.",
        "आपके माता-पिता / अभिभावक आपकी उपस्थिति, परिणाम और शुल्क देख सकते हैं।",
    ),
}
PURPOSE_VERSION = "1.0"

NOTICE_KEYS = (
    "privacy_policy",
    "terms",
    "dpdp_notice",
    "cookie_policy",
    "website_enquiry_notice",
    "applicant_notice",
    "recruiter_data_sharing",
)
NOTICE_TEXTS: dict[str, str] = {
    "privacy_policy": "How we collect, use, share and protect personal data, and how to exercise your rights.",
    "terms": "Terms of use of the institution's portals and apps.",
    "dpdp_notice": "Notice under the Digital Personal Data Protection Act, 2023: purposes, data processed, your rights "
    "(access, correction, erasure, grievance) and the contact of the privacy officer.",
    "cookie_policy": "The website uses essential cookies; analytics cookies only with your consent.",
    "website_enquiry_notice": "Your enquiry details are used to respond to you and are kept for 12 months.",
    "applicant_notice": "Application data is used for admission processing and retained as per the admission policy.",
    "recruiter_data_sharing": "Recruiters receive only the fields students consented to share and must not reuse them.",
}

DSR_DEFAULTS: dict[str, Any] = {
    "due_days": 30,
    "extension_days": 30,
    "identity_verification": "otp",
    "erasure_mode": "anonymise",
    "academic_records_retained_years": 10,
}

# consent purposes gating module behaviour (withdrawal effects, Prompts/43 §43.6 privacy 1)
GATED_PURPOSES = (
    "communication_marketing",
    "photo_media",
    "third_party_placement",
    "analytics_external",
    "biometric",
    "location",
)


def purposes_json() -> list[dict[str, Any]]:
    return [
        {"key": k, "mandatory": m, "legal_basis": b, "text_version": PURPOSE_VERSION, "texts": {"en": en, "hi": hi}}
        for k, (m, b, en, hi) in PURPOSES.items()
    ]


def notices_json() -> dict[str, Any]:
    return {
        k: {"key": k, "version": "1.0", "texts": {"en": NOTICE_TEXTS[k]}, "effective_from": None} for k in NOTICE_KEYS
    }
