"""LMS-lite, lesson plan and course-file schemas — Prompts/13 §13.4."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ModuleIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    sequence: int = 1
    is_published: bool = False


class ContentIn(BaseModel):
    content_type: Literal["file", "video", "link", "text", "scorm", "embed"]
    title: str = Field(min_length=1, max_length=200)
    body: str | None = None
    file_url: str | None = None
    duration_minutes: int | None = None
    release_at: datetime | None = None
    co_ids: list[str] | None = None
    sequence: int = 1


class ContentOut(ORMModel):
    id: uuid.UUID
    module_id: uuid.UUID
    content_type: str
    title: str
    body: str | None = None
    file_url: str | None = None
    duration_minutes: int | None = None
    release_at: datetime | None = None
    co_ids: list[str] | None = None
    sequence: int
    view_count: int
    my_progress: int | None = None


class ModuleOut(ORMModel):
    id: uuid.UUID
    offering_id: uuid.UUID
    title: str
    sequence: int
    is_published: bool
    contents: list[ContentOut] = Field(default_factory=list)
    completion_pct: float | None = None


class ContentViewPing(BaseModel):
    progress_pct: int = Field(ge=0, le=100)


class AssignmentIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    instructions: str | None = None
    attachments: list[dict[str, Any]] | None = None
    due_at: datetime | None = None
    max_marks: float | None = Field(None, gt=0)
    allow_late: bool = True
    late_penalty_pct_per_day: float | None = Field(None, ge=0, le=100)
    max_file_mb: int = Field(10, ge=1, le=100)
    rubric: list[dict[str, Any]] | None = Field(None, description="[{criterion, max}]")
    co_ids: list[str] | None = None
    is_group: bool = False
    similarity_check: bool = False
    offering_assessment_id: uuid.UUID | None = None


class AssignmentOut(ORMModel):
    id: uuid.UUID
    offering_id: uuid.UUID
    offering_assessment_id: uuid.UUID | None = None
    title: str
    instructions: str | None = None
    attachments: list[dict[str, Any]] | None = None
    due_at: datetime | None = None
    max_marks: float | None = None
    allow_late: bool
    late_penalty_pct_per_day: float | None = None
    max_file_mb: int
    rubric: list[dict[str, Any]] | None = None
    co_ids: list[str] | None = None
    similarity_check: bool
    status: str
    created_at: datetime
    submissions: int = 0
    my_submission: dict[str, Any] | None = None


class SubmissionCreate(BaseModel):
    text_answer: str | None = None
    files: list[dict[str, Any]] | None = None


class SubmissionOut(ORMModel):
    id: uuid.UUID
    assignment_id: uuid.UUID
    student_program_enrollment_id: uuid.UUID
    registration_number: str | None = None
    student_name: str | None = None
    files: list[dict[str, Any]] | None = None
    text_answer: str | None = None
    submitted_at: datetime
    is_late: bool
    attempt: int
    marks: float | None = None
    rubric_scores: dict[str, Any] | None = None
    feedback: str | None = None
    similarity_pct: float | None = None
    status: str


class GradeRow(BaseModel):
    submission_id: uuid.UUID
    marks: float | None = Field(None, ge=0)
    rubric_scores: dict[str, float] | None = None
    feedback: str | None = None
    status: Literal["graded", "returned", "resubmit"] = "graded"


class GradeBulk(BaseModel):
    rows: list[GradeRow] = Field(min_length=1)


class QuizIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    question_paper_id: uuid.UUID
    offering_assessment_id: uuid.UUID | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    duration_minutes: int = Field(ge=1, le=600)
    attempts_allowed: int = Field(1, ge=1, le=10)
    shuffle_questions: bool = True
    show_result: Literal["immediate", "after_close", "never"] = "after_close"
    proctoring: dict[str, Any] | None = None


class QuizOut(ORMModel):
    id: uuid.UUID
    offering_id: uuid.UUID
    question_paper_id: uuid.UUID
    offering_assessment_id: uuid.UUID | None = None
    title: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    duration_minutes: int
    attempts_allowed: int
    shuffle_questions: bool
    show_result: str
    proctoring: dict[str, Any] | None = None
    status: str
    total_marks: float | None = None
    my_attempts: list[dict[str, Any]] = Field(default_factory=list)


class QuizStartResponse(BaseModel):
    attempt_id: uuid.UUID
    attempt_no: int
    ends_at: datetime
    questions: list[dict[str, Any]] = Field(default_factory=list)
    answers: dict[str, Any] = Field(default_factory=dict)


class QuizAnswerSave(BaseModel):
    answers: dict[str, Any]
    proctor_events: list[dict[str, Any]] | None = None


class QuizSubmitResponse(BaseModel):
    attempt_id: uuid.UUID
    status: str
    auto_score: float | None = None
    total_score: float | None = None
    show_result: bool = False


class AttemptOut(ORMModel):
    id: uuid.UUID
    quiz_id: uuid.UUID
    student_program_enrollment_id: uuid.UUID
    registration_number: str | None = None
    student_name: str | None = None
    attempt_no: int
    started_at: datetime
    submitted_at: datetime | None = None
    answers: dict[str, Any] | None = None
    auto_score: float | None = None
    manual_score: float | None = None
    total_score: float | None = None
    proctor_events: list[dict[str, Any]] | None = None
    status: str


class ManualGrade(BaseModel):
    rows: list[dict[str, Any]] = Field(description="[{attempt_id, manual_score}]")


class PushToMarksResult(BaseModel):
    written: int = 0
    skipped: int = 0


class AnnouncementIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str | None = None
    pinned: bool = False


class AnnouncementOut(ORMModel):
    id: uuid.UUID
    offering_id: uuid.UUID
    title: str
    body: str | None = None
    pinned: bool
    posted_by: uuid.UUID | None = None
    posted_at: datetime


class ThreadIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str | None = None


class ThreadPatch(BaseModel):
    is_locked: bool | None = None
    is_pinned: bool | None = None


class ThreadOut(ORMModel):
    id: uuid.UUID
    offering_id: uuid.UUID
    title: str
    created_by: uuid.UUID | None = None
    is_locked: bool
    is_pinned: bool
    created_at: datetime
    posts: int = 0


class PostIn(BaseModel):
    body: str = Field(min_length=1)
    parent_post_id: uuid.UUID | None = None
    attachments: list[dict[str, Any]] | None = None


class PostOut(ORMModel):
    id: uuid.UUID
    thread_id: uuid.UUID
    parent_post_id: uuid.UUID | None = None
    author_user_id: uuid.UUID
    author_name: str | None = None
    body: str
    attachments: list[dict[str, Any]] | None = None
    is_answer: bool
    upvotes: int
    created_at: datetime


class OnlineLinkRequest(BaseModel):
    link: str | None = None
    provider: str | None = None


class LessonPlanIn(BaseModel):
    unit_no: int | None = None
    topic: str = Field(min_length=1, max_length=255)
    planned_date: date | None = None
    planned_hours: float = Field(1, gt=0)
    delivery_method: str | None = None
    co_id: uuid.UUID | None = None
    resources: list[dict[str, Any]] | None = None
    sequence: int = 1


class LessonPlanOut(ORMModel):
    id: uuid.UUID
    offering_id: uuid.UUID
    unit_no: int | None = None
    topic: str
    planned_date: date | None = None
    planned_hours: float
    delivery_method: str | None = None
    co_id: uuid.UUID | None = None
    resources: list[dict[str, Any]] | None = None
    actual_date: date | None = None
    actual_session_id: uuid.UUID | None = None
    status: str
    sequence: int


class LessonPlanReplace(BaseModel):
    items: list[LessonPlanIn]


class DeliverRequest(BaseModel):
    session_id: uuid.UUID | None = None
    actual_date: date | None = None


class DeviationRow(BaseModel):
    id: uuid.UUID
    sequence: int
    topic: str
    planned_date: date | None = None
    actual_date: date | None = None
    days_late: int | None = None
    status: str


class CourseFileChecklist(BaseModel):
    offering_id: uuid.UUID
    checklist: list[dict[str, Any]] = Field(default_factory=list)
    completion_pct: int = 0
    audited_by: uuid.UUID | None = None
    audited_at: datetime | None = None
    remarks: str | None = None


class CourseFileUpdate(BaseModel):
    checklist: list[dict[str, Any]] = Field(description="[{key, done, url?}] — manual items")


class CourseFileAudit(BaseModel):
    remarks: str | None = None
