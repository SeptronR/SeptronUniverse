"""Auth / RBAC / SaaS enums — Prompts/02 §02.3 (values copied from the Database_Schema.sql comments)."""

from enum import StrEnum


class UserType(StrEnum):
    STAFF = "staff"
    STUDENT = "student"
    GUARDIAN = "guardian"
    ALUMNI = "alumni"
    APPLICANT = "applicant"
    RECRUITER = "recruiter"
    EXTERNAL = "external"
    PLATFORM = "platform"


class ScopeType(StrEnum):
    INSTITUTION = "institution"
    COLLEGE = "college"
    FACULTY = "faculty"
    DEPARTMENT = "department"
    PROGRAM = "program"
    OFFERING = "offering"
    SELF = "self"
    COMMITTEE = "committee"
    HOSTEL = "hostel"


class LoginOutcome(StrEnum):
    SUCCESS = "success"
    BAD_PASSWORD = "bad_password"
    LOCKED = "locked"
    MFA_FAILED = "mfa_failed"
    MFA_REQUIRED = "mfa_required"
    SSO = "sso"
    OTP = "otp"
    EXPIRED = "expired"
    INACTIVE = "inactive"


class SubscriptionStatus(StrEnum):
    TRIAL = "trial"
    ACTIVE = "active"
    GRACE = "grace"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ConsentPurpose(StrEnum):
    ACADEMIC = "academic"
    COMMUNICATION = "communication"
    MARKETING = "marketing"
    HEALTH = "health"
    PHOTO = "photo"
    THIRD_PARTY = "third_party"


class DsrType(StrEnum):
    ACCESS = "access"
    EXPORT = "export"
    CORRECTION = "correction"
    ERASURE = "erasure"


class DsrStatus(StrEnum):
    RECEIVED = "received"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REJECTED = "rejected"


class FeatureSource(StrEnum):
    PLAN = "plan"
    OVERRIDE = "override"
