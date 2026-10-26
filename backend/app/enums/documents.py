"""Document templates, issued documents, serial registers and certificate requests — enums and shipped defaults
(Prompts/26 §26.3 / §26.2)."""

from enum import StrEnum
from typing import Any


class TemplateType(StrEnum):
    ID_CARD = "id_card"
    BONAFIDE = "bonafide"
    CHARACTER = "character"
    CONDUCT = "conduct"
    NOC = "noc"
    TC = "tc"
    MIGRATION = "migration"
    COURSE_COMPLETION = "course_completion"
    PROVISIONAL = "provisional"
    DEGREE = "degree"
    GRADE_CARD = "grade_card"
    TRANSCRIPT = "transcript"
    HALL_TICKET = "hall_ticket"
    RECEIPT = "receipt"
    EXPERIENCE = "experience"
    SERVICE = "service"
    INTERNSHIP_NOC = "internship_noc"
    HOSTEL_ALLOTMENT = "hostel_allotment"
    EVENT_CERTIFICATE = "event_certificate"
    UNDERTAKING = "undertaking"
    MEDICAL_CERTIFICATE = "medical_certificate"
    FEE_STRUCTURE_LETTER = "fee_structure_letter"
    OFFER_LETTER = "offer_letter"
    # Phase 29: donation 80G receipt (bilingual variant) and the alumni membership card
    DONATION_RECEIPT_80G = "donation_receipt_80g"
    ALUMNI_MEMBERSHIP_CARD = "alumni_membership_card"
    CUSTOM = "custom"


class PageSize(StrEnum):
    A4 = "A4"
    A5 = "A5"
    LETTER = "Letter"
    ID_CR80 = "ID_CR80"
    CUSTOM = "custom"


class RequestStatus(StrEnum):
    REQUESTED = "requested"
    FEE_PENDING = "fee_pending"
    APPROVED = "approved"
    GENERATED = "generated"
    ISSUED = "issued"
    REJECTED = "rejected"


class Delivery(StrEnum):
    DIGITAL = "digital"
    PICKUP = "pickup"
    POST = "post"


class SerialStatus(StrEnum):
    RESERVED = "reserved"
    USED = "used"
    VOID = "void"


TEMPLATE_TYPES: tuple[str, ...] = tuple(t.value for t in TemplateType)
# statutory serial registers (documents.serial_registers)
REGISTERS: tuple[str, ...] = ("degree", "provisional", "transcript", "tc", "migration", "bonafide")
# HOD / class advisor see issued documents of their students for these types only
DEPARTMENT_TYPES: frozenset[str] = frozenset({"bonafide", "conduct", "character"})
EXAM_TYPES: frozenset[str] = frozenset({"hall_ticket", "grade_card", "transcript", "degree", "provisional"})
STAFF_TYPES: frozenset[str] = frozenset({"experience", "service", "noc"})
# per-download watermark ("Downloaded by …") applies to these
SENSITIVE_TYPES: frozenset[str] = frozenset({"transcript", "grade_card"})
# several live documents per entity are normal for these (copies)
MULTI_TYPES: frozenset[str] = frozenset({"bonafide", "receipt", "custom", "noc", "internship_noc"})
BILINGUAL_TYPES: tuple[str, ...] = ("bonafide", "degree", "provisional", "tc", "donation_receipt_80g")

PERSON_TYPES: tuple[str, ...] = ("student", "staff", "alumni")

# variables catalogue sources → keys (with an example) — what the sandbox exposes to a template
COMMON_VARIABLES: list[dict[str, str]] = [
    {"key": "institution.name", "label": "Institution name", "source": "institution", "example": "Septron University"},
    {"key": "institution.address", "label": "Institution address", "source": "institution", "example": "Hyderabad"},
    {"key": "document.number", "label": "Document number", "source": "register", "example": "BON/2026/00012"},
    {"key": "document.serial_no", "label": "Serial number", "source": "register", "example": "BON-000123"},
    {"key": "document.issued_on", "label": "Issue date", "source": "register", "example": "25-10-2026"},
    {"key": "document.verify_url", "label": "Verification URL", "source": "register", "example": "/verify/…"},
    {"key": "document.qr", "label": "Verification QR (data URL)", "source": "register", "example": "data:image/png…"},
    {"key": "signatories.registrar.name", "label": "Registrar", "source": "signatories", "example": "Dr. A. Rao"},
    {"key": "signatories.principal.name", "label": "Principal", "source": "signatories", "example": "Dr. B. Iyer"},
    {"key": "signatories.coe.name", "label": "Controller of Examinations", "source": "signatories", "example": "Dr. C"},
    {"key": "purpose", "label": "Purpose", "source": "request", "example": "Bank loan"},
]
STUDENT_VARIABLES: list[dict[str, str]] = [
    {"key": "student.name", "label": "Student name", "source": "student", "example": "Asha Kumari"},
    {"key": "student.name_secondary", "label": "Name (secondary script)", "source": "student", "example": "आशा"},
    {"key": "student.registration_number", "label": "Registration no.", "source": "student", "example": "22CS001"},
    {"key": "student.dob", "label": "Date of birth", "source": "student", "example": "01-01-2005"},
    {"key": "student.gender", "label": "Gender", "source": "student", "example": "female"},
    {"key": "student.guardian_name", "label": "Parent / guardian", "source": "student", "example": "R. Kumar"},
    {"key": "student.photo_url", "label": "Photo", "source": "student", "example": "/files/…"},
    {"key": "enrolment.program", "label": "Programme", "source": "enrolment", "example": "B.Tech CSE"},
    {"key": "enrolment.batch", "label": "Batch", "source": "enrolment", "example": "2022-26"},
    {"key": "enrolment.department", "label": "Department", "source": "enrolment", "example": "CSE"},
    {"key": "enrolment.admission_date", "label": "Admission date", "source": "enrolment", "example": "01-08-2022"},
    {"key": "enrolment.status", "label": "Enrolment status", "source": "enrolment", "example": "active"},
    {"key": "enrolment.cgpa", "label": "CGPA", "source": "term results", "example": "8.42"},
    {"key": "enrolment.academic_year", "label": "Academic year", "source": "enrolment", "example": "2026-27"},
]
STAFF_VARIABLES: list[dict[str, str]] = [
    {"key": "staff.name", "label": "Staff name", "source": "staff", "example": "Dr. P. Sharma"},
    {"key": "staff.employee_id", "label": "Employee id", "source": "staff", "example": "EMP0042"},
    {"key": "staff.designation", "label": "Designation", "source": "staff", "example": "Assistant Professor"},
    {"key": "staff.department", "label": "Department", "source": "staff", "example": "CSE"},
    {"key": "staff.joining_date", "label": "Joining date", "source": "staff", "example": "01-07-2018"},
    {"key": "staff.exit_date", "label": "Relieving date", "source": "staff", "example": "30-06-2026"},
]
TYPE_VARIABLES: dict[str, list[dict[str, str]]] = {
    "event_certificate": [
        {"key": "event.title", "label": "Event", "source": "event", "example": "TechFest 2026"},
        {"key": "event.type", "label": "Event type", "source": "event", "example": "workshop"},
        {"key": "event.from_on", "label": "From", "source": "event", "example": "01-10-2026"},
        {"key": "event.to_on", "label": "To", "source": "event", "example": "02-10-2026"},
        {"key": "participant.name", "label": "Participant", "source": "event", "example": "Asha Kumari"},
    ],
    "hostel_allotment": [
        {"key": "hostel.name", "label": "Hostel", "source": "hostel", "example": "Ganga Hostel"},
        {"key": "hostel.room", "label": "Room / bed", "source": "hostel", "example": "G-101 / B"},
    ],
    "grade_card": [{"key": "term.sgpa", "label": "SGPA", "source": "term results", "example": "8.1"}],
    "transcript": [{"key": "enrolment.credits_earned", "label": "Credits", "source": "term results", "example": "160"}],
    "degree": [
        {"key": "award.degree", "label": "Degree", "source": "degree", "example": "Bachelor of Technology"},
        {"key": "award.class", "label": "Class", "source": "degree", "example": "First class with distinction"},
        {"key": "award.date", "label": "Date of award", "source": "degree", "example": "15-08-2026"},
    ],
}

# request rules per type (institution_settings documents.request_rules; per-type override of the shipped defaults)
DEFAULT_REQUEST_RULES: dict[str, dict[str, Any]] = {
    "bonafide": {
        "fee_paise": 5000,
        "approver": "registrar",
        "sla_days": 2,
        "allowed_for": ["student"],
        "auto_generate": True,
        "allow_parent": True,
        "recommend_hod": False,
    },
    "conduct": {
        "fee_paise": 5000,
        "approver": "registrar",
        "sla_days": 3,
        "allowed_for": ["student", "alumni"],
        "auto_generate": True,
    },
    "character": {
        "fee_paise": 5000,
        "approver": "registrar",
        "sla_days": 3,
        "allowed_for": ["student", "alumni"],
        "auto_generate": True,
    },
    "course_completion": {
        "fee_paise": 10000,
        "approver": "registrar",
        "sla_days": 5,
        "allowed_for": ["student", "alumni"],
        "requires_status": ["completed", "graduated"],
    },
    "tc": {
        "fee_paise": 20000,
        "approver": "registrar",
        "sla_days": 7,
        "allowed_for": ["student", "alumni"],
        "requires_no_dues": True,
        "requires_status": ["completed", "graduated", "transferred", "withdrawn"],
        "hold_types": ["all"],
    },
    "migration": {
        "fee_paise": 50000,
        "approver": "registrar",
        "sla_days": 7,
        "allowed_for": ["student", "alumni"],
        "requires_no_dues": True,
        "requires_status": ["completed", "graduated", "transferred"],
        "hold_types": ["all"],
    },
    "transcript": {
        "fee_paise": 50000,
        "approver": "controller_of_examinations",
        "sla_days": 7,
        "allowed_for": ["student", "alumni"],
        "hold_types": ["transcript", "all"],
    },
    "provisional": {
        "fee_paise": 30000,
        "approver": "controller_of_examinations",
        "sla_days": 7,
        "allowed_for": ["student", "alumni"],
        "requires_status": ["completed", "graduated"],
        "hold_types": ["graduation", "all"],
    },
    "internship_noc": {
        "fee_paise": 0,
        "approver": "registrar",
        "sla_days": 2,
        "allowed_for": ["student"],
        "auto_generate": True,
        "recommend_hod": True,
    },
    "fee_structure_letter": {
        "fee_paise": 0,
        "approver": "registrar",
        "sla_days": 2,
        "allowed_for": ["student"],
        "auto_generate": True,
        "allow_parent": True,
    },
    "experience": {"fee_paise": 0, "approver": "hr_officer", "sla_days": 5, "allowed_for": ["staff"]},
    "service": {"fee_paise": 0, "approver": "hr_officer", "sla_days": 5, "allowed_for": ["staff"]},
    "noc": {"fee_paise": 0, "approver": "hr_officer", "sla_days": 3, "allowed_for": ["staff"]},
}

DEFAULT_SIGNATORIES: dict[str, dict[str, Any]] = {
    "registrar": {"name": "Registrar", "designation": "Registrar", "signature_url": None},
    "principal": {"name": "Principal", "designation": "Principal", "signature_url": None},
    "coe": {"name": "Controller of Examinations", "designation": "Controller of Examinations", "signature_url": None},
}
