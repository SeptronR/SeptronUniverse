"""Academic sessions — section 7 of Database_Schema.sql (``academic_years``, ``academic_terms``; Prompts/03 §03.3).

The partial unique index ``one_current_year`` (one ``is_current`` year per institution/college) lives in the canonical
DDL only (revision 0001); ``AcademicSessionService.set_current_year`` flips the previous row in the same transaction.
Later phases add the rest of section 7 (programmes, regulations, … — Phase 05) to this module.
"""

import uuid
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, SmallInteger, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import CollegeScopedMixin, TenantModelMixin


class AcademicYear(TenantModelMixin, CollegeScopedMixin, Base):
    __tablename__ = "academic_years"
    __table_args__ = (UniqueConstraint("institution_id", "college_id", "name"),)

    name: Mapped[str] = mapped_column(String(20), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AcademicTerm(TenantModelMixin, CollegeScopedMixin, Base):
    __tablename__ = "academic_terms"
    __table_args__ = (UniqueConstraint("institution_id", "college_id", "academic_year_id", "term_type", "sequence"),)

    academic_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("academic_years.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    term_type: Mapped[str] = mapped_column(String(20), nullable=False)  # odd | even | summer | trimester | annual
    sequence: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    registration_start: Mapped[date | None] = mapped_column(Date)
    registration_end: Mapped[date | None] = mapped_column(Date)
    add_drop_end: Mapped[date | None] = mapped_column(Date)
    last_instruction_date: Mapped[date | None] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # planned | registration | in_progress | exam | result_processing | closed
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="planned")
