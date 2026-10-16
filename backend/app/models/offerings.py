"""Course offerings — section 11 of Database_Schema.sql (Prompts/09 §09.3).

An offering is course × term × college × department × section code with its faculty, seats and target batches /
sections. Column names mirror the DDL exactly (``check_schema_drift.py --phase 09``); relationships are not mapped —
repositories load related rows in batches.

DDL notes the services rely on:

* ``UNIQUE (institution_id, term_id, course_id, section_code)``;
* ``enrolled_count`` counts *seated* items (``selected`` / ``confirmed``) and ``waitlist_count`` the waiting rows; both
  change only while the offering row is locked ``FOR UPDATE`` so concurrent registrations never exceed ``max_seats``;
* ``course_offering_faculty.hours_per_week`` feeds the Phase 06 workload computation (``workload_repository``) and
  the ``staff_id`` is the "own offerings" ownership link of the students / registration modules.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, TenantModelMixin, UUIDPrimaryKeyMixin
from app.models.registration import _fk, _now


class CourseOffering(TenantModelMixin, Base):
    __tablename__ = "course_offerings"
    __table_args__ = (UniqueConstraint("institution_id", "term_id", "course_id", "section_code"),)

    college_id: Mapped[uuid.UUID] = _fk("colleges.id", "CASCADE", nullable=False)
    term_id: Mapped[uuid.UUID] = _fk("academic_terms.id", nullable=False)
    course_id: Mapped[uuid.UUID] = _fk("courses.id", nullable=False)
    department_id: Mapped[uuid.UUID] = _fk("departments.id", nullable=False)
    section_code: Mapped[str] = mapped_column(String(20), nullable=False, default="A")
    coordinator_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    max_seats: Mapped[int | None] = mapped_column(SmallInteger)
    enrolled_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    waitlist_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    delivery_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="offline")
    online_class_link: Mapped[str | None] = mapped_column(Text)
    assessment_scheme_id: Mapped[uuid.UUID | None] = _fk("assessment_schemes.id")
    is_arrear_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")


class CourseOfferingFaculty(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "course_offering_faculty"
    __table_args__ = (UniqueConstraint("offering_id", "staff_id", "role"),)

    offering_id: Mapped[uuid.UUID] = _fk("course_offerings.id", "CASCADE", nullable=False)
    staff_id: Mapped[uuid.UUID] = _fk("staff.id", "CASCADE", nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="instructor")
    hours_per_week: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = _now()


class CourseOfferingTarget(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "course_offering_targets"
    __table_args__ = (UniqueConstraint("offering_id", "batch_id", "section_id"),)

    offering_id: Mapped[uuid.UUID] = _fk("course_offerings.id", "CASCADE", nullable=False)
    batch_id: Mapped[uuid.UUID] = _fk("batches.id", "CASCADE", nullable=False)
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batch_sections.id", ondelete="CASCADE")
    )
    term_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
