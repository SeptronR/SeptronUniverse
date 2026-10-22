"""LMS-lite, lesson plans and course files — section 14 of Database_Schema.sql (Prompts/13 §13.3).

DDL notes: ``content_views UNIQUE (content_id, student_program_enrollment_id)``; ``assignment_submissions UNIQUE
(assignment_id, student_program_enrollment_id, attempt)``; ``quiz_attempts UNIQUE (quiz_id,
student_program_enrollment_id, attempt_no)``; ``course_files.offering_id`` is UNIQUE; ``class_sessions.
lesson_plan_item_id`` references ``lesson_plans`` (Phase 10 column).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, UUIDPrimaryKeyMixin
from app.models.registration import _fk, _now, _updated


def _uuid() -> Any:
    return mapped_column(UUID(as_uuid=True))


class CourseModule(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "course_modules"

    offering_id: Mapped[uuid.UUID] = _fk("course_offerings.id", "CASCADE", nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    sequence: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class CourseContent(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "course_contents"

    module_id: Mapped[uuid.UUID] = _fk("course_modules.id", "CASCADE", nullable=False)
    content_type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    file_url: Mapped[str | None] = mapped_column(Text)
    duration_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    release_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    co_ids: Mapped[list[str] | None] = mapped_column(JSONB)
    sequence: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class ContentView(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "content_views"
    __table_args__ = (UniqueConstraint("content_id", "student_program_enrollment_id"),)

    content_id: Mapped[uuid.UUID] = _fk("course_contents.id", "CASCADE", nullable=False)
    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    first_viewed_at: Mapped[datetime] = _now()
    last_viewed_at: Mapped[datetime] = _now()
    progress_pct: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


class LmsAssignment(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "lms_assignments"

    offering_id: Mapped[uuid.UUID] = _fk("course_offerings.id", "CASCADE", nullable=False)
    offering_assessment_id: Mapped[uuid.UUID | None] = _fk("offering_assessments.id")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    instructions: Mapped[str | None] = mapped_column(Text)
    attachments: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_marks: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    allow_late: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    late_penalty_pct_per_day: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    max_file_mb: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=10)
    rubric: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    co_ids: Mapped[list[str] | None] = mapped_column(JSONB)
    is_group: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    similarity_check: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    created_by: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class AssignmentSubmission(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "assignment_submissions"
    __table_args__ = (UniqueConstraint("assignment_id", "student_program_enrollment_id", "attempt"),)

    assignment_id: Mapped[uuid.UUID] = _fk("lms_assignments.id", "CASCADE", nullable=False)
    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    files: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    text_answer: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime] = _now()
    is_late: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attempt: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    marks: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    rubric_scores: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    feedback: Mapped[str | None] = mapped_column(Text)
    graded_by: Mapped[uuid.UUID | None] = _uuid()
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    similarity_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    similarity_report_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="submitted")


class Quiz(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "quizzes"

    offering_id: Mapped[uuid.UUID] = _fk("course_offerings.id", "CASCADE", nullable=False)
    question_paper_id: Mapped[uuid.UUID] = _fk("question_papers.id", nullable=False)
    offering_assessment_id: Mapped[uuid.UUID | None] = _fk("offering_assessments.id")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    attempts_allowed: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    shuffle_questions: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_result: Mapped[str] = mapped_column(String(20), nullable=False, default="after_close")
    proctoring: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    created_by: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class QuizAttempt(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "quiz_attempts"
    __table_args__ = (UniqueConstraint("quiz_id", "student_program_enrollment_id", "attempt_no"),)

    quiz_id: Mapped[uuid.UUID] = _fk("quizzes.id", "CASCADE", nullable=False)
    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    attempt_no: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    started_at: Mapped[datetime] = _now()
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answers: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    auto_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    manual_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    total_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    proctor_events: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="in_progress")


class CourseAnnouncement(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "course_announcements"

    offering_id: Mapped[uuid.UUID] = _fk("course_offerings.id", "CASCADE", nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    posted_by: Mapped[uuid.UUID | None] = _uuid()
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    posted_at: Mapped[datetime] = _now()


class DiscussionThread(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "discussion_threads"

    offering_id: Mapped[uuid.UUID] = _fk("course_offerings.id", "CASCADE", nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by: Mapped[uuid.UUID | None] = _uuid()
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class DiscussionPost(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "discussion_posts"

    thread_id: Mapped[uuid.UUID] = _fk("discussion_threads.id", "CASCADE", nullable=False)
    parent_post_id: Mapped[uuid.UUID | None] = _fk("discussion_posts.id", "CASCADE")
    author_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    attachments: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    is_answer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    upvotes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LessonPlan(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "lesson_plans"

    offering_id: Mapped[uuid.UUID] = _fk("course_offerings.id", "CASCADE", nullable=False)
    unit_no: Mapped[int | None] = mapped_column(SmallInteger)
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    planned_date: Mapped[date | None] = mapped_column(Date)
    planned_hours: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False, default=1)
    delivery_method: Mapped[str | None] = mapped_column(String(30))
    co_id: Mapped[uuid.UUID | None] = _fk("course_outcomes.id")
    resources: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    actual_date: Mapped[date | None] = mapped_column(Date)
    actual_session_id: Mapped[uuid.UUID | None] = _fk("class_sessions.id")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    sequence: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class CourseFile(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "course_files"

    offering_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    checklist: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    completion_pct: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    audited_by: Mapped[uuid.UUID | None] = _uuid()
    audited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remarks: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = _updated()
