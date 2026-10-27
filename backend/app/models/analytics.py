"""Read-only mappings over the Phase 35 materialized read models — Prompts/35 §35.3.

The views are defined in ``app/services/analytics/read_models.py`` (``Database_Schema.sql`` §37, Alembic ``0035``). Every
mapping sets ``info.is_view`` so ``check_schema_drift.py`` and Alembic autogenerate skip it (also listed in
``scripts/phase_manifest.py`` ``VIEWS``). The ``UNIQUE`` refresh-index columns serve as the ORM primary key; nullable
dimension columns are declared optional. Never written through the ORM — refreshed with ``REFRESH MATERIALIZED VIEW
CONCURRENTLY`` only.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

_VIEW = {"info": {"is_view": True}}

__all__ = [
    "EnrolmentDaily",
    "AttendanceTerm",
    "FeesPosition",
    "ExamProgress",
    "ResultsSummary",
    "HrSnapshot",
    "AdmissionsFunnel",
    "PlacementFunnel",
    "HostelOccupancy",
    "ResearchCounts",
    "ServiceDeskSla",
    "RiskCohort",
    "KpiDaily",
]


class EnrolmentDaily(Base):
    __tablename__ = "mv_enrolment_daily"
    __table_args__ = _VIEW
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    college_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    program_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    category: Mapped[str] = mapped_column(String, primary_key=True)
    gender: Mapped[str] = mapped_column(String, primary_key=True)
    quota: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    enrolments: Mapped[int | None] = mapped_column(Integer)


class AttendanceTerm(Base):
    __tablename__ = "mv_attendance_term"
    __table_args__ = _VIEW
    institution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    college_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    department_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    program_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    term_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    offering_department_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    offering_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    enrollment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    sessions_held: Mapped[int | None] = mapped_column(Integer)
    sessions_present: Mapped[int | None] = mapped_column(Integer)
    pct: Mapped[Decimal | None] = mapped_column(Numeric)
    shortfall_pct: Mapped[Decimal | None] = mapped_column(Numeric)
    is_short: Mapped[bool | None] = mapped_column(Boolean)
    eligibility: Mapped[str | None] = mapped_column(String)
    last_computed: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FeesPosition(Base):
    __tablename__ = "mv_fees_position"
    __table_args__ = _VIEW
    institution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    college_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    department_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    program_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    enrollment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    billed_paise: Mapped[int | None] = mapped_column(BigInteger)
    paid_paise: Mapped[int | None] = mapped_column(BigInteger)
    balance_paise: Mapped[int | None] = mapped_column(BigInteger)
    overdue_paise: Mapped[int | None] = mapped_column(BigInteger)
    aging_0_30_paise: Mapped[int | None] = mapped_column(BigInteger)
    aging_31_60_paise: Mapped[int | None] = mapped_column(BigInteger)
    aging_61_90_paise: Mapped[int | None] = mapped_column(BigInteger)
    aging_90_plus_paise: Mapped[int | None] = mapped_column(BigInteger)
    invoices: Mapped[int | None] = mapped_column(Integer)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExamProgress(Base):
    __tablename__ = "mv_exam_progress"
    __table_args__ = _VIEW
    institution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    college_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    term_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    exam_session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str | None] = mapped_column(String)
    exam_kind: Mapped[str | None] = mapped_column(String)
    status: Mapped[str | None] = mapped_column(String)
    registrations: Mapped[int | None] = mapped_column(Integer)
    confirmed: Mapped[int | None] = mapped_column(Integer)
    eligibility_applied: Mapped[int | None] = mapped_column(Integer)
    hall_tickets: Mapped[int | None] = mapped_column(Integer)
    scripts: Mapped[int | None] = mapped_column(Integer)
    scripts_valuated: Mapped[int | None] = mapped_column(Integer)
    discrepancies: Mapped[int | None] = mapped_column(Integer)
    valuation_pct: Mapped[Decimal | None] = mapped_column(Numeric)
    results_stage: Mapped[str | None] = mapped_column(String)


class ResultsSummary(Base):
    __tablename__ = "mv_results_summary"
    __table_args__ = _VIEW
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    college_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    program_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    term_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    students: Mapped[int | None] = mapped_column(Integer)
    passed: Mapped[int | None] = mapped_column(Integer)
    pass_pct: Mapped[Decimal | None] = mapped_column(Numeric)
    avg_sgpa: Mapped[Decimal | None] = mapped_column(Numeric)
    top_sgpa: Mapped[Decimal | None] = mapped_column(Numeric)
    arrears: Mapped[int | None] = mapped_column(Integer)
    sgpa_lt5: Mapped[int | None] = mapped_column(Integer)
    sgpa_5_6: Mapped[int | None] = mapped_column(Integer)
    sgpa_6_7: Mapped[int | None] = mapped_column(Integer)
    sgpa_7_8: Mapped[int | None] = mapped_column(Integer)
    sgpa_8_9: Mapped[int | None] = mapped_column(Integer)
    sgpa_9_plus: Mapped[int | None] = mapped_column(Integer)


class HrSnapshot(Base):
    __tablename__ = "mv_hr_snapshot"
    __table_args__ = _VIEW
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    college_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    designation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    cadre: Mapped[str] = mapped_column(String, primary_key=True)
    staff_category: Mapped[str] = mapped_column(String, primary_key=True)
    headcount: Mapped[int | None] = mapped_column(Integer)
    on_leave_today: Mapped[int | None] = mapped_column(Integer)
    present_today: Mapped[int | None] = mapped_column(Integer)
    leaves_pending: Mapped[int | None] = mapped_column(Integer)


class AdmissionsFunnel(Base):
    __tablename__ = "mv_admissions_funnel"
    __table_args__ = _VIEW
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    college_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    cycle_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    program_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    category: Mapped[str] = mapped_column(String, primary_key=True)
    quota: Mapped[str] = mapped_column(String, primary_key=True)
    applications: Mapped[int | None] = mapped_column(Integer)
    verified: Mapped[int | None] = mapped_column(Integer)
    merit: Mapped[int | None] = mapped_column(Integer)
    allotted: Mapped[int | None] = mapped_column(Integer)
    admitted: Mapped[int | None] = mapped_column(Integer)
    started: Mapped[int | None] = mapped_column(Integer)


class PlacementFunnel(Base):
    __tablename__ = "mv_placement_funnel"
    __table_args__ = _VIEW
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    college_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    drive_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    drive_status: Mapped[str | None] = mapped_column(String)
    drive_on: Mapped[date | None] = mapped_column(Date)
    eligible: Mapped[int | None] = mapped_column(Integer)
    applied: Mapped[int | None] = mapped_column(Integer)
    in_rounds: Mapped[int | None] = mapped_column(Integer)
    offers: Mapped[int | None] = mapped_column(Integer)
    accepted: Mapped[int | None] = mapped_column(Integer)
    ctc_lt5l: Mapped[int | None] = mapped_column(Integer)
    ctc_5_10l: Mapped[int | None] = mapped_column(Integer)
    ctc_10_20l: Mapped[int | None] = mapped_column(Integer)
    ctc_20l_plus: Mapped[int | None] = mapped_column(Integer)
    max_ctc_paise: Mapped[int | None] = mapped_column(BigInteger)


class HostelOccupancy(Base):
    __tablename__ = "mv_hostel_occupancy"
    __table_args__ = _VIEW
    institution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    college_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    hostel_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    block_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    hostel_name: Mapped[str | None] = mapped_column(String)
    block_name: Mapped[str | None] = mapped_column(String)
    warden_staff_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    beds: Mapped[int | None] = mapped_column(Integer)
    occupied: Mapped[int | None] = mapped_column(Integer)
    leave_out_today: Mapped[int | None] = mapped_column(Integer)
    complaints_open: Mapped[int | None] = mapped_column(Integer)


class ResearchCounts(Base):
    __tablename__ = "mv_research_counts"
    __table_args__ = _VIEW
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    college_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric: Mapped[str] = mapped_column(String, primary_key=True)
    sub_key: Mapped[str] = mapped_column(String, primary_key=True)
    count: Mapped[int | None] = mapped_column(Integer)
    amount_paise: Mapped[int | None] = mapped_column(BigInteger)


class ServiceDeskSla(Base):
    __tablename__ = "mv_service_desk_sla"
    __table_args__ = _VIEW
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    college_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    category: Mapped[str] = mapped_column(String, primary_key=True)
    open: Mapped[int | None] = mapped_column(Integer)
    breached: Mapped[int | None] = mapped_column(Integer)
    resolved: Mapped[int | None] = mapped_column(Integer)
    within_sla: Mapped[int | None] = mapped_column(Integer)
    mttr_hours: Mapped[Decimal | None] = mapped_column(Numeric)


class RiskCohort(Base):
    __tablename__ = "mv_risk_cohort"
    __table_args__ = _VIEW
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    college_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    term_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    program_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    category: Mapped[str] = mapped_column(String, primary_key=True)
    hostel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    level: Mapped[str] = mapped_column(String, primary_key=True)
    students: Mapped[int | None] = mapped_column(Integer)
    attendance_mean: Mapped[Decimal | None] = mapped_column(Numeric)
    cia_mean: Mapped[Decimal | None] = mapped_column(Numeric)
    dues_mean: Mapped[Decimal | None] = mapped_column(Numeric)
    standing_mean: Mapped[Decimal | None] = mapped_column(Numeric)
    hostel_mean: Mapped[Decimal | None] = mapped_column(Numeric)
    engagement_mean: Mapped[Decimal | None] = mapped_column(Numeric)
    score_mean: Mapped[Decimal | None] = mapped_column(Numeric)
    acknowledged: Mapped[int | None] = mapped_column(Integer)
    acknowledged_pct: Mapped[Decimal | None] = mapped_column(Numeric)
    interventions: Mapped[int | None] = mapped_column(Integer)


class KpiDaily(Base):
    __tablename__ = "mv_kpi_daily"
    __table_args__ = _VIEW
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    college_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    college_key: Mapped[str] = mapped_column(String, primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    students_active: Mapped[Decimal | None] = mapped_column(Numeric)
    students_total: Mapped[Decimal | None] = mapped_column(Numeric)
    programmes: Mapped[Decimal | None] = mapped_column(Numeric)
    staff_active: Mapped[Decimal | None] = mapped_column(Numeric)
    faculty_count: Mapped[Decimal | None] = mapped_column(Numeric)
    staff_present_today: Mapped[Decimal | None] = mapped_column(Numeric)
    staff_on_leave_today: Mapped[Decimal | None] = mapped_column(Numeric)
    leaves_pending: Mapped[Decimal | None] = mapped_column(Numeric)
    attendance_avg_pct: Mapped[Decimal | None] = mapped_column(Numeric)
    attendance_shortfall: Mapped[Decimal | None] = mapped_column(Numeric)
    fee_billed_paise: Mapped[Decimal | None] = mapped_column(Numeric)
    fee_collected_paise: Mapped[Decimal | None] = mapped_column(Numeric)
    fee_overdue_paise: Mapped[Decimal | None] = mapped_column(Numeric)
    fee_defaulters: Mapped[Decimal | None] = mapped_column(Numeric)
    fee_collection_pct: Mapped[Decimal | None] = mapped_column(Numeric)
    fee_collected_today_paise: Mapped[Decimal | None] = mapped_column(Numeric)
    exam_sessions_active: Mapped[Decimal | None] = mapped_column(Numeric)
    valuation_pct: Mapped[Decimal | None] = mapped_column(Numeric)
    result_pass_pct: Mapped[Decimal | None] = mapped_column(Numeric)
    avg_sgpa: Mapped[Decimal | None] = mapped_column(Numeric)
    applications: Mapped[Decimal | None] = mapped_column(Numeric)
    admitted: Mapped[Decimal | None] = mapped_column(Numeric)
    enquiries_open: Mapped[Decimal | None] = mapped_column(Numeric)
    placement_offers: Mapped[Decimal | None] = mapped_column(Numeric)
    placement_accepted: Mapped[Decimal | None] = mapped_column(Numeric)
    placement_pct: Mapped[Decimal | None] = mapped_column(Numeric)
    hostel_beds: Mapped[Decimal | None] = mapped_column(Numeric)
    hostel_occupied: Mapped[Decimal | None] = mapped_column(Numeric)
    hostel_out_today: Mapped[Decimal | None] = mapped_column(Numeric)
    hostel_complaints_open: Mapped[Decimal | None] = mapped_column(Numeric)
    library_issued: Mapped[Decimal | None] = mapped_column(Numeric)
    library_overdue: Mapped[Decimal | None] = mapped_column(Numeric)
    grievances_open: Mapped[Decimal | None] = mapped_column(Numeric)
    grievances_breached: Mapped[Decimal | None] = mapped_column(Numeric)
    grievance_sla_pct: Mapped[Decimal | None] = mapped_column(Numeric)
    service_open: Mapped[Decimal | None] = mapped_column(Numeric)
    service_breached: Mapped[Decimal | None] = mapped_column(Numeric)
    risk_high: Mapped[Decimal | None] = mapped_column(Numeric)
    risk_medium: Mapped[Decimal | None] = mapped_column(Numeric)
    publications_year: Mapped[Decimal | None] = mapped_column(Numeric)
    projects_active: Mapped[Decimal | None] = mapped_column(Numeric)
    scholars_active: Mapped[Decimal | None] = mapped_column(Numeric)
    holds_active: Mapped[Decimal | None] = mapped_column(Numeric)


VIEW_MODELS: dict[str, type[Base]] = {
    m.__tablename__: m
    for m in (
        EnrolmentDaily,
        AttendanceTerm,
        FeesPosition,
        ExamProgress,
        ResultsSummary,
        HrSnapshot,
        AdmissionsFunnel,
        PlacementFunnel,
        HostelOccupancy,
        ResearchCounts,
        ServiceDeskSla,
        RiskCohort,
        KpiDaily,
    )
}
