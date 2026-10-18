"""Attendance & eligibility enums — Prompts/11 §11.3 (values copied from the section 12 column comments of
Database_Schema.sql)."""

from enum import StrEnum


class AttendanceMark(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    LATE = "late"
    ON_DUTY = "on_duty"
    LEAVE = "leave"
    MEDICAL = "medical"
    EXEMPT = "exempt"


class AttendanceSource(StrEnum):
    MANUAL = "manual"
    BIOMETRIC = "biometric"
    QR = "qr"
    APP = "app"
    RFID = "rfid"


class OdReasonType(StrEnum):
    SPORTS = "sports"
    NSS = "nss"
    NCC = "ncc"
    PLACEMENT = "placement"
    CONFERENCE = "conference"
    OTHER = "other"


class OdStatus(StrEnum):
    REQUESTED = "requested"
    RECOMMENDED = "recommended"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"  # not in the DDL comment — a student withdrawing an open request


class EligibilityBand(StrEnum):
    ELIGIBLE = "eligible"
    CONDONABLE = "condonable"
    NOT_ELIGIBLE = "not_eligible"
    CONDONED = "condoned"


class CondonationReason(StrEnum):
    MEDICAL = "medical"
    SPORTS = "sports"
    BEREAVEMENT = "bereavement"
    OTHER = "other"


class CondonationStatus(StrEnum):
    REQUESTED = "requested"
    HOD_RECOMMENDED = "hod_recommended"
    APPROVED = "approved"
    REJECTED = "rejected"


class EligibilityDecision(StrEnum):
    ELIGIBLE = "eligible"
    DETAINED = "detained"
    CONDONED = "condoned"
    DEBARRED = "debarred"
    PENDING = "pending"


# Marks that count as attended in ``pct = (present + on_duty + late) / (total − exempt)``
ATTENDED = ("present", "on_duty", "late")
# Session attendance states that count towards the totals (session ``status`` ``conducted`` or attendance taken)
COUNTED_ATTENDANCE_STATUSES = ("taken", "finalized")
REASON_CODES = ("ATT_BELOW_MIN", "ATT_CONDONABLE", "CIA_FAIL", "FEE_DUE", "HOLD_EXAM", "DEBARRED")
