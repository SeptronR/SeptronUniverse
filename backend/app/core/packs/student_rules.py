"""Student pack rules — Prompts/07 §07.2 / §07.6 (docs/Regulatory_Pack_IN.md "Students").

``StudentRules`` is the pack's data for Phase 07: the undertaking templates (texts the student e-accepts — revision
``0007`` stores them as platform ``document_templates`` rows of ``template_type='undertaking'``), the undertakings the
gates require by default, the age of majority (an adult student controls ``guardian_portal_consent``), the document
types offered by the upload form and the ID-card layout defaults. Texts are Jinja2 over ``student_name``,
``registration_number``, ``institution_name``, ``program_name`` and ``academic_year``.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StudentRules:
    # undertaking_type → {name, body, version}; e-accepted once per academic year (gates check the current year)
    undertakings: dict[str, dict[str, str]] = field(default_factory=dict)
    required_undertakings: tuple[str, ...] = ("anti_ragging", "conduct")
    majority_age: int = 18
    document_types: tuple[str, ...] = ()
    id_card: dict[str, Any] = field(default_factory=dict)


_ANTI_RAGGING = (
    "I, {{ student_name }} (registration number {{ registration_number }}), admitted to {{ program_name }} at "
    "{{ institution_name }} for the academic year {{ academic_year }}, have read the UGC Regulations on Curbing the "
    "Menace of Ragging in Higher Educational Institutions, 2009 and the institution's anti-ragging policy. I "
    "understand that ragging in any form is a criminal offence and is prohibited on and off campus, in hostels and in "
    "transport. I undertake that I will not indulge in, abet or propagate ragging, and that I will report any incident "
    "I witness to the Anti-Ragging Committee or the national helpline. I accept that if I am found guilty I am liable "
    "to the punishments the regulations prescribe, including suspension, expulsion and criminal proceedings."
)
_CONDUCT = (
    "I, {{ student_name }} ({{ registration_number }}), undertake to abide by the code of conduct, the academic "
    "regulations and the examination rules of {{ institution_name }} for the academic year {{ academic_year }}. I will "
    "maintain academic integrity, attend classes regularly, treat staff and fellow students with respect, refrain from "
    "the use of drugs and alcohol on campus, and protect institutional property. I understand that violations are "
    "dealt with by the disciplinary committee under the institution's rules."
)
_DATA_CONSENT = (
    "I consent to {{ institution_name }} processing my personal data — identity, contact, academic, attendance, "
    "examination, fee and health records — for admission, teaching, examinations, certification, scholarships, "
    "statutory reporting (AISHE, NIRF, UGC/AICTE, ABC/APAAR, DigiLocker) and communication, in accordance with the "
    "Digital Personal Data Protection Act, 2023. I understand that I may access, correct or ask for the erasure of my "
    "data where the law allows, and withdraw consent for optional purposes through my profile."
)
_PHOTO_CONSENT = (
    "I consent to {{ institution_name }} using my photograph on my identity card, examination documents and "
    "certificates, and in event photographs published on the institution's website, social media and reports. I may "
    "withdraw the consent for publicity use at any time through my profile."
)
_HOSTEL_RULES = (
    "I, {{ student_name }} ({{ registration_number }}), undertake to follow the hostel rules of {{ institution_name }} "
    "for the academic year {{ academic_year }}: in-time and out-pass procedures, visitor rules, mess discipline, room "
    "upkeep and the prohibition of ragging, alcohol, drugs and cooking appliances. I accept that the warden may inspect "
    "rooms and that violations may lead to fines or the cancellation of my allotment."
)

IN_STUDENT_RULES = StudentRules(
    undertakings={
        "anti_ragging": {"name": "Anti-ragging undertaking", "body": _ANTI_RAGGING, "version": "IN-2009-UGC"},
        "conduct": {"name": "Code of conduct undertaking", "body": _CONDUCT, "version": "IN-1"},
        "data_consent": {
            "name": "Data processing consent (DPDP Act 2023)",
            "body": _DATA_CONSENT,
            "version": "IN-DPDP",
        },
        "photo_consent": {"name": "Photograph consent", "body": _PHOTO_CONSENT, "version": "IN-1"},
        "hostel_rules": {"name": "Hostel rules undertaking", "body": _HOSTEL_RULES, "version": "IN-1"},
    },
    required_undertakings=("anti_ragging", "conduct"),
    majority_age=18,
    document_types=(
        "photo",
        "class_10_marksheet",
        "class_12_marksheet",
        "transfer_certificate",
        "migration_certificate",
        "conduct_certificate",
        "community_certificate",
        "income_certificate",
        "ews_certificate",
        "pwd_certificate",
        "aadhaar",
        "entrance_scorecard",
        "allotment_letter",
        "passport",
        "visa",
        "frro_registration",
        "medical_fitness",
        "other",
    ),
    id_card={"size": "CR80", "validity": "expected_graduation", "show_blood_group": True, "show_emergency": True},
)

GENERIC_STUDENT_RULES = StudentRules(
    undertakings={
        "conduct": {"name": "Code of conduct", "body": _CONDUCT, "version": "GEN-1"},
        "data_consent": {"name": "Data processing consent", "body": _DATA_CONSENT, "version": "GEN-1"},
        "photo_consent": {"name": "Photograph consent", "body": _PHOTO_CONSENT, "version": "GEN-1"},
    },
    required_undertakings=("conduct",),
    majority_age=18,
    document_types=("photo", "school_transcript", "passport", "visa", "other"),
    id_card={"size": "CR80", "validity": "expected_graduation", "show_blood_group": False, "show_emergency": True},
)
