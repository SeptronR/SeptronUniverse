"""LMS-lite, lesson plans, course files and projects — Prompts/13 §13.8 (router included with
``feature_required("lms.content")``; per-route {lms.assignments}, {lms.quizzes}, {lms.discussions},
{lms.online_class_links}, {lms.lesson_plans}, {lms.course_files}, {lms.similarity_check}; the project routes live on
``projects_router`` with {assessment.projects}).
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.features import feature_required
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.lms import (
    AnnouncementIn,
    AnnouncementOut,
    AssignmentIn,
    AssignmentOut,
    AttemptOut,
    ContentIn,
    ContentOut,
    ContentViewPing,
    CourseFileAudit,
    CourseFileChecklist,
    CourseFileUpdate,
    DeliverRequest,
    DeviationRow,
    GradeBulk,
    LessonPlanIn,
    LessonPlanOut,
    LessonPlanReplace,
    ManualGrade,
    ModuleIn,
    ModuleOut,
    OnlineLinkRequest,
    PostIn,
    PostOut,
    PushToMarksResult,
    QuizAnswerSave,
    QuizIn,
    QuizOut,
    QuizStartResponse,
    QuizSubmitResponse,
    SubmissionCreate,
    SubmissionOut,
    ThreadIn,
    ThreadOut,
    ThreadPatch,
)
from app.schemas.projects import MemberIn, ProjectIn, ProjectOut, ReviewIn
from app.services.assessment.lesson_service import LessonService
from app.services.assessment.lms_service import LmsService
from app.services.assessment.project_service import ProjectService
from app.utils.response import ok

router = APIRouter(tags=["lms"])
projects_router = APIRouter(tags=["projects"])

L = "lms"
VIEW = any_permission_required((L, "view"), (L, "view_all"), (L, "manage"), (L, "grade"))
MANAGE = any_permission_required((L, "manage"), (L, "grade"))
GRADE = any_permission_required((L, "grade"), (L, "manage"))
AUDIT = any_permission_required((L, "view_all"), (L, "manage"))
P = "projects"
P_VIEW = any_permission_required((P, "view"), (P, "view_all"), (P, "guide"), (P, "review"), (P, "manage"))
P_WRITE = any_permission_required((P, "guide"), (P, "manage"))
P_REVIEW = any_permission_required((P, "review"), (P, "guide"), (P, "manage"))
ASSIGN = [feature_required("lms.assignments")]
QUIZ = [feature_required("lms.quizzes")]
DISC = [feature_required("lms.discussions")]
LINKS = [feature_required("lms.online_class_links")]
PLAN = [feature_required("lms.lesson_plans")]
FILES = [feature_required("lms.course_files")]
SIM = [feature_required("lms.similarity_check")]


# ---- modules / contents ---------------------------------------------------------------------------------------------------
@router.get(
    "/course-offerings/{id}/modules",
    summary="Modules with contents (learners: published / released)",
    response_model=Envelope[list[ModuleOut]],
)
async def modules(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).modules(id))


@router.post("/course-offerings/{id}/modules", summary="Create a module", response_model=Envelope[ModuleOut])
async def create_module(
    id: uuid.UUID,
    body: ModuleIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).save_module(id, body), message="Module created")


@router.put("/modules/{id}", summary="Update a module", response_model=Envelope[ModuleOut])
async def update_module(
    id: uuid.UUID,
    body: ModuleIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).save_module(None, body, id), message="Module updated")


@router.delete("/modules/{id}", summary="Delete a module", response_model=Envelope[None])
async def delete_module(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await LmsService(db, principal, request).delete_module(id)
    return ok(None, message="Module deleted")


@router.get("/modules/{id}/contents", summary="Contents of a module", response_model=Envelope[list[ContentOut]])
async def contents(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).contents(id))


@router.post(
    "/modules/{id}/contents",
    summary="Add content (file / video / link / text / SCORM / embed)",
    response_model=Envelope[ContentOut],
)
async def create_content(
    id: uuid.UUID,
    body: ContentIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).save_content(id, body), message="Content added")


@router.put("/contents/{id}", summary="Update content", response_model=Envelope[ContentOut])
async def update_content(
    id: uuid.UUID,
    body: ContentIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).save_content(None, body, id), message="Content updated")


@router.delete("/contents/{id}", summary="Delete content", response_model=Envelope[None])
async def delete_content(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await LmsService(db, principal, request).delete_content(id)
    return ok(None, message="Content deleted")


@router.post("/contents/{id}/view", summary="Progress ping (learners)", response_model=Envelope[ContentOut])
async def view(
    id: uuid.UUID,
    body: ContentViewPing,
    request: Request,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).view(id, body))


# ---- assignments -----------------------------------------------------------------------------------------------------------
@router.get(
    "/course-offerings/{id}/assignments",
    summary="Assignments",
    dependencies=ASSIGN,
    response_model=Envelope[list[AssignmentOut]],
)
async def assignments(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).assignments(id))


@router.post(
    "/course-offerings/{id}/assignments",
    summary="Create an assignment (draft)",
    dependencies=ASSIGN,
    response_model=Envelope[AssignmentOut],
)
async def create_assignment(
    id: uuid.UUID,
    body: AssignmentIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).save_assignment(id, body), message="Assignment created")


@router.put(
    "/assignments/{id}", summary="Update an assignment", dependencies=ASSIGN, response_model=Envelope[AssignmentOut]
)
async def update_assignment(
    id: uuid.UUID,
    body: AssignmentIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).save_assignment(None, body, id), message="Assignment updated")


@router.post(
    "/assignments/{id}/publish", summary="Publish", dependencies=ASSIGN, response_model=Envelope[AssignmentOut]
)
async def publish_assignment(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).set_assignment_status(id, "published"), message="Published")


@router.post("/assignments/{id}/close", summary="Close", dependencies=ASSIGN, response_model=Envelope[AssignmentOut])
async def close_assignment(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).set_assignment_status(id, "closed"), message="Closed")


@router.get(
    "/assignments/{id}/submissions",
    summary="Submissions (learners: own)",
    dependencies=ASSIGN,
    response_model=Envelope[list[SubmissionOut]],
)
async def submissions(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).submissions(id))


@router.post(
    "/assignments/{id}/submit",
    summary="Submit (late flagged; penalty applied on grading)",
    dependencies=ASSIGN,
    response_model=Envelope[SubmissionOut],
)
async def submit(
    id: uuid.UUID,
    body: SubmissionCreate,
    request: Request,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).submit(id, body), message="Submitted")


@router.post(
    "/assignments/{id}/grade",
    summary="Bulk grade with rubric (writes linked internal marks)",
    dependencies=ASSIGN,
    response_model=Envelope[list[SubmissionOut]],
)
async def grade(
    id: uuid.UUID,
    body: GradeBulk,
    request: Request,
    principal: Principal = Depends(GRADE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).grade(id, body), message="Graded")


@router.post(
    "/assignments/{id}/similarity-check",
    status_code=202,
    summary="Similarity check (job)",
    dependencies=[*ASSIGN, *SIM],
    response_model=Envelope[dict[str, Any]],
)
async def similarity(
    id: uuid.UUID, request: Request, principal: Principal = Depends(GRADE), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    from app.core.jobs import enqueue

    await LmsService(db, principal, request)._assignment(id)
    job = await enqueue(db, principal, "lms.similarity_check", {"assignment_id": str(id)})
    return JSONResponse(status_code=202, content=ok({"job_id": str(job.id)}, message="Similarity check queued"))


# ---- quizzes ---------------------------------------------------------------------------------------------------------------
@router.get(
    "/course-offerings/{id}/quizzes", summary="Quizzes", dependencies=QUIZ, response_model=Envelope[list[QuizOut]]
)
async def quizzes(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).quizzes(id))


@router.post(
    "/course-offerings/{id}/quizzes",
    summary="Create a quiz from a frozen paper",
    dependencies=QUIZ,
    response_model=Envelope[QuizOut],
)
async def create_quiz(
    id: uuid.UUID,
    body: QuizIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).save_quiz(id, body), message="Quiz created")


@router.put("/quizzes/{id}", summary="Update a quiz", dependencies=QUIZ, response_model=Envelope[QuizOut])
async def update_quiz(
    id: uuid.UUID,
    body: QuizIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).save_quiz(None, body, id), message="Quiz updated")


@router.post("/quizzes/{id}/publish", summary="Publish", dependencies=QUIZ, response_model=Envelope[QuizOut])
async def publish_quiz(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).set_quiz_status(id, "published"), message="Published")


@router.post(
    "/quizzes/{id}/close",
    summary="Close (open attempts auto-submit)",
    dependencies=QUIZ,
    response_model=Envelope[QuizOut],
)
async def close_quiz(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).set_quiz_status(id, "closed"), message="Closed")


@router.post(
    "/quizzes/{id}/start",
    summary="Start / resume an attempt (shuffled, no answers)",
    dependencies=QUIZ,
    response_model=Envelope[QuizStartResponse],
)
async def start_quiz(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).start(id))


@router.put(
    "/quiz-attempts/{id}/answers",
    summary="Autosave answers (+ proctor events)",
    dependencies=QUIZ,
    response_model=Envelope[QuizStartResponse],
)
async def save_answers(
    id: uuid.UUID,
    body: QuizAnswerSave,
    request: Request,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).save_answers(id, body))


@router.post(
    "/quiz-attempts/{id}/submit",
    summary="Submit an attempt (auto-scored)",
    dependencies=QUIZ,
    response_model=Envelope[QuizSubmitResponse],
)
async def submit_attempt(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).submit_attempt(id), message="Submitted")


@router.get(
    "/quizzes/{id}/attempts",
    summary="Attempts (learners: own)",
    dependencies=QUIZ,
    response_model=Envelope[list[AttemptOut]],
)
async def attempts(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).attempts(id))


@router.post(
    "/quizzes/{id}/grade-manual",
    summary="Manual scores for short / long answers",
    dependencies=QUIZ,
    response_model=Envelope[list[AttemptOut]],
)
async def grade_manual(
    id: uuid.UUID,
    body: ManualGrade,
    request: Request,
    principal: Principal = Depends(GRADE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).grade_manual(id, body), message="Scores saved")


@router.post(
    "/quizzes/{id}/push-to-marks",
    summary="Best attempt → linked internal marks",
    dependencies=QUIZ,
    response_model=Envelope[PushToMarksResult],
)
async def push_to_marks(
    id: uuid.UUID, request: Request, principal: Principal = Depends(GRADE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    out = await LmsService(db, principal, request).push_to_marks(id)
    return ok(out, message=f"{out.written} mark(s) written")


# ---- announcements / discussions / links -----------------------------------------------------------------------------------
@router.get(
    "/course-offerings/{id}/announcements",
    summary="Course announcements",
    response_model=Envelope[list[AnnouncementOut]],
)
async def announcements(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).announcements(id))


@router.post(
    "/course-offerings/{id}/announcements",
    summary="Post an announcement (notifies the roster)",
    response_model=Envelope[AnnouncementOut],
)
async def announce(
    id: uuid.UUID,
    body: AnnouncementIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).announce(id, body), message="Posted")


@router.get(
    "/course-offerings/{id}/threads",
    summary="Discussion threads",
    dependencies=DISC,
    response_model=Envelope[list[ThreadOut]],
)
async def threads(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).threads(id))


@router.post(
    "/course-offerings/{id}/threads", summary="Start a thread", dependencies=DISC, response_model=Envelope[ThreadOut]
)
async def create_thread(
    id: uuid.UUID,
    body: ThreadIn,
    request: Request,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).create_thread(id, body), message="Thread started")


@router.put(
    "/threads/{id}", summary="Lock / pin (faculty moderation)", dependencies=DISC, response_model=Envelope[ThreadOut]
)
async def patch_thread(
    id: uuid.UUID,
    body: ThreadPatch,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).patch_thread(id, body))


@router.get(
    "/threads/{id}/posts", summary="Posts of a thread", dependencies=DISC, response_model=Envelope[list[PostOut]]
)
async def posts(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).posts(id))


@router.post(
    "/threads/{id}/posts", summary="Reply (locked thread → 409)", dependencies=DISC, response_model=Envelope[PostOut]
)
async def create_post(
    id: uuid.UUID,
    body: PostIn,
    request: Request,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).create_post(id, body), message="Posted")


@router.post("/posts/{id}/upvote", summary="Upvote", dependencies=DISC, response_model=Envelope[PostOut])
async def upvote(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).upvote(id))


@router.post(
    "/posts/{id}/mark-answer",
    summary="Mark as the answer (thread author / faculty)",
    dependencies=DISC,
    response_model=Envelope[PostOut],
)
async def mark_answer(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).mark_answer(id))


@router.post(
    "/course-offerings/{id}/online-link",
    summary="Set / create the offering's online class link",
    dependencies=LINKS,
    response_model=Envelope[dict[str, Any]],
)
async def online_link(
    id: uuid.UUID,
    body: OnlineLinkRequest,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).online_link(id, body), message="Link saved")


@router.post(
    "/class-sessions/{id}/meeting",
    summary="Create a meeting for a session (video_conf adapter)",
    dependencies=LINKS,
    response_model=Envelope[dict[str, Any]],
)
async def meeting(
    id: uuid.UUID,
    body: OnlineLinkRequest,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LmsService(db, principal, request).session_meeting(id, body), message="Meeting created")


# ---- lesson plans / course files ------------------------------------------------------------------------------------------------
@router.get(
    "/course-offerings/{id}/lesson-plan",
    summary="Lesson plan",
    dependencies=PLAN,
    response_model=Envelope[list[LessonPlanOut]],
)
async def lesson_plan(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LessonService(db, principal, request).plan(id))


@router.post(
    "/course-offerings/{id}/lesson-plan",
    summary="Replace the plan (delivered items kept)",
    dependencies=PLAN,
    response_model=Envelope[list[LessonPlanOut]],
)
async def replace_plan(
    id: uuid.UUID,
    body: LessonPlanReplace,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LessonService(db, principal, request).replace(id, body), message="Plan saved")


@router.get(
    "/course-offerings/{id}/lesson-plan/deviation",
    summary="Planned vs actual",
    dependencies=PLAN,
    response_model=Envelope[list[DeviationRow]],
)
async def deviation(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LessonService(db, principal, request).deviation(id))


@router.put(
    "/lesson-plans/{id}", summary="Update a plan item", dependencies=PLAN, response_model=Envelope[LessonPlanOut]
)
async def update_plan(
    id: uuid.UUID,
    body: LessonPlanIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LessonService(db, principal, request).update(id, body))


@router.post(
    "/lesson-plans/{id}/deliver",
    summary="Mark delivered against a session",
    dependencies=PLAN,
    response_model=Envelope[LessonPlanOut],
)
async def deliver(
    id: uuid.UUID,
    body: DeliverRequest,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LessonService(db, principal, request).deliver(id, body), message="Delivered")


@router.get(
    "/course-offerings/{id}/course-file",
    summary="Course-file checklist",
    dependencies=FILES,
    response_model=Envelope[CourseFileChecklist],
)
async def course_file(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LessonService(db, principal, request).course_file(id))


@router.put(
    "/course-offerings/{id}/course-file",
    summary="Tick manual checklist items",
    dependencies=FILES,
    response_model=Envelope[CourseFileChecklist],
)
async def put_course_file(
    id: uuid.UUID,
    body: CourseFileUpdate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LessonService(db, principal, request).update_course_file(id, body))


@router.post(
    "/course-files/{id}/audit", summary="HOD audit", dependencies=FILES, response_model=Envelope[CourseFileChecklist]
)
async def audit_file(
    id: uuid.UUID,
    body: CourseFileAudit,
    request: Request,
    principal: Principal = Depends(AUDIT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LessonService(db, principal, request).audit_file(id, body), message="Audited")


# ---- projects ----------------------------------------------------------------------------------------------------------------
@projects_router.get("/projects/me", summary="My (ward's) projects", response_model=Envelope[list[ProjectOut]])
async def my_projects(
    request: Request, principal: Principal = Depends(P_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ProjectService(db, principal, request).mine())


@projects_router.get(
    "/course-offerings/{id}/projects", summary="Projects of an offering", response_model=Envelope[list[ProjectOut]]
)
async def projects(
    id: uuid.UUID, request: Request, principal: Principal = Depends(P_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ProjectService(db, principal, request).list_for(id))


@projects_router.post(
    "/course-offerings/{id}/projects",
    summary="Create a project (members on the roster)",
    response_model=Envelope[ProjectOut],
)
async def create_project(
    id: uuid.UUID,
    body: ProjectIn,
    request: Request,
    principal: Principal = Depends(P_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProjectService(db, principal, request).create(id, body), message="Project created")


@projects_router.put("/projects/{id}", summary="Update a project", response_model=Envelope[ProjectOut])
async def update_project(
    id: uuid.UUID,
    body: ProjectIn,
    request: Request,
    principal: Principal = Depends(P_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProjectService(db, principal, request).update(id, body), message="Project updated")


@projects_router.put("/projects/{id}/members", summary="Replace members (1–4)", response_model=Envelope[ProjectOut])
async def project_members(
    id: uuid.UUID,
    body: MemberIn,
    request: Request,
    principal: Principal = Depends(P_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProjectService(db, principal, request).members(id, body), message="Members saved")


@projects_router.post(
    "/projects/{id}/reviews",
    summary="Record a review (marks → project_review component)",
    response_model=Envelope[ProjectOut],
)
async def review(
    id: uuid.UUID,
    body: ReviewIn,
    request: Request,
    principal: Principal = Depends(P_REVIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProjectService(db, principal, request).review(id, body), message="Review recorded")
