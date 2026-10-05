"""HR enums — Prompts/06 §06.3 (values copied from the section 9 column comments of Database_Schema.sql)."""

from enum import StrEnum


class EmploymentType(StrEnum):
    REGULAR = "regular"
    CONTRACT = "contract"
    GUEST = "guest"
    VISITING = "visiting"
    ADJUNCT = "adjunct"
    OUTSOURCED = "outsourced"


HOURLY_EMPLOYMENT = frozenset({EmploymentType.GUEST, EmploymentType.VISITING})


class StaffCategory(StrEnum):
    TEACHING = "teaching"
    NON_TEACHING = "non_teaching"
    ADMINISTRATIVE = "administrative"


class StaffStatus(StrEnum):
    ACTIVE = "active"
    ON_LEAVE = "on_leave"
    SUSPENDED = "suspended"
    EXITED = "exited"


class Cadre(StrEnum):
    PROFESSOR = "professor"
    ASSOCIATE = "associate"
    ASSISTANT = "assistant"
    LECTURER = "lecturer"
    ADJUNCT = "adjunct"
    VISITING = "visiting"
    GUEST = "guest"


class ServiceBookEntryType(StrEnum):
    JOINING = "joining"
    PROMOTION = "promotion"
    INCREMENT = "increment"
    TRANSFER = "transfer"
    AWARD = "award"
    DISCIPLINARY = "disciplinary"
    LEAVE_WITHOUT_PAY = "leave_without_pay"
    EXIT = "exit"


class LeaveAccrual(StrEnum):
    YEARLY = "yearly"
    MONTHLY = "monthly"
    NONE = "none"


class LeaveStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class HalfDay(StrEnum):
    FIRST = "first_half"
    SECOND = "second_half"


class AttendanceStatus(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    HALF_DAY = "half_day"
    ON_LEAVE = "on_leave"
    ON_DUTY = "on_duty"
    HOLIDAY = "holiday"
    WEEK_OFF = "week_off"


class AttendanceSource(StrEnum):
    MANUAL = "manual"
    BIOMETRIC = "biometric"
    SELF_CHECKIN = "self_checkin"
    GEO = "geo"
    IMPORT = "import"


class DeviceType(StrEnum):
    BIOMETRIC = "biometric"
    RFID = "rfid"
    QR_KIOSK = "qr_kiosk"


class ComponentType(StrEnum):
    EARNING = "earning"
    DEDUCTION = "deduction"
    EMPLOYER_CONTRIBUTION = "employer_contribution"
    REIMBURSEMENT = "reimbursement"


class CalcType(StrEnum):
    FIXED = "fixed"
    PCT_OF_BASIC = "pct_of_basic"
    FORMULA = "formula"
    STATUTORY = "statutory"


class StatutoryKind(StrEnum):
    PF = "pf"
    ESI = "esi"
    PT = "pt"
    TDS = "tds"
    LWF = "lwf"


class PayrollStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    PAID = "paid"
    CANCELLED = "cancelled"


class LoanType(StrEnum):
    FESTIVAL = "festival"
    VEHICLE = "vehicle"
    HOUSING = "housing"
    SALARY_ADVANCE = "salary_advance"
    COMPUTER = "computer"


class LoanStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    CLOSED = "closed"
    REJECTED = "rejected"


class PostingStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    CLOSED = "closed"
    FILLED = "filled"
    CANCELLED = "cancelled"


class ApplicationStatus(StrEnum):
    APPLIED = "applied"
    SCREENED = "screened"
    SHORTLISTED = "shortlisted"
    INTERVIEWED = "interviewed"
    SELECTED = "selected"
    OFFERED = "offered"
    JOINED = "joined"
    REJECTED = "rejected"


# pipeline order of the recruitment kanban (rejected is terminal from any stage)
APPLICATION_PIPELINE: tuple[str, ...] = (
    "applied",
    "screened",
    "shortlisted",
    "interviewed",
    "selected",
    "offered",
    "joined",
)


class AppraisalStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    REVIEWED = "reviewed"
    APPROVED = "approved"


class CasStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    SCREENED = "screened"
    INTERVIEWED = "interviewed"
    APPROVED = "approved"
    REJECTED = "rejected"


class WorkloadStatus(StrEnum):
    DRAFT = "draft"
    HOD_APPROVED = "hod_approved"
    DEAN_APPROVED = "dean_approved"


class AllocationStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    DEAN_APPROVED = "dean_approved"
    APPLIED = "applied"
