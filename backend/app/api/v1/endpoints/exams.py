"""Exam administration — Prompts/14 §14.8 (router included with ``feature_required("exams.sessions")``; per-route
{exams.clash_detection}, {exams.registration_fee}, {exams.eligibility_snapshot}, {exams.hall_tickets},
{exams.seating}, {exams.invigilation}, {exams.remuneration}, {exams.qp_management}, {exams.qp_watermark_print_log},
{exams.online_proctored}, {affiliation.exam_centres}). Bulk papers / eligibility apply / hall tickets / seating /
invigilation / bulk registration answer ``202`` + ``job_id`` (dry runs inline). ``public_router`` holds the hall-ticket
verification (``PUBLIC_ROUTES``). Fixed paths precede parameterised ones.
"""

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, permission_required
from app.core.features import feature_required
from app.core.idempotency import idempotency_key, store
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.exams import (
    BulkPapersPreview,
    BulkPapersRequest,
    ClashReport,
    DateSheetUpdate,
    DutyCreate,
    DutyResponse,
    DutyUpdate,
    EligibilityApplyRequest,
    EligibilityApplySummary,
    ExamCentreIn,
    ExamCentreOut,
    ExamPaperCreate,
    ExamPaperResponse,
    ExamPaperUpdate,
    ExamRegistrationResponse,
    ExamSessionCreate,
    ExamSessionResponse,
    ExamSessionUpdate,
    HallAttendanceMark,
    HallAttendanceRowOut,
    HallTicketGenerateRequest,
    HallTicketVerifyResponse,
    InvigilationAutoAssignRequest,
    MalpracticeOut,
    MalpracticeReportCreate,
    OnlinePaperSetup,
    QpAssignmentCreate,
    QpAssignmentResponse,
    QpPrintRequest,
    QpPrintResponse,
    QpScrutinyRequest,
    ReasonBody,
    RegistrationAdminCreate,
    RegistrationSubmit,
    RemunerationSummary,
    RosterSummary,
    SeatAllocationRow,
    SeatingGenerateRequest,
    SeatingSummary,
    SeatMove,
    SessionStatusChange,
    SwapRequest,
)
from app.services.exams.duty_qp_service import ConductService, InvigilationService, QpService
from app.services.exams.hall_seating_service import HallTicketService, SeatingService
from app.services.exams.registration_service import ExamRegistrationService
from app.services.exams.session_service import ExamSessionService
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(tags=["exams"])
public_router = APIRouter(tags=["public"])

E = "exams"
READ = any_permission_required((E, "view"), (E, "view_all"), (E, "configure"), (E, "manage"), (E, "self"))
CONF = any_permission_required((E, "configure"), (E, "manage"))
MANAGE = permission_required(E, "manage")
SELF = permission_required(E, "self")
REG_VIEW = any_permission_required((E, "view_all"), (E, "manage"), (E, "view"), ("fees", "view_all"))
ELIG = permission_required(E, "eligibility")
HT = permission_required(E, "hall_tickets")
SEAT = permission_required(E, "seating")
SEAT_READ = any_permission_required((E, "seating"), (E, "conduct"), (E, "view_all"))
INV = permission_required(E, "invigilation")
INV_READ = any_permission_required((E, "invigilation"), (E, "view_all"), (E, "view"))
STAFF = any_permission_required((E, "invigilation"), (E, "conduct"), (E, "evaluate"), (E, "view"), (E, "qp"))
REMUN = any_permission_required((E, "invigilation"), (E, "view_all"), ("payroll", "view_all"))
QP = permission_required(E, "qp")
QP_SETTER = any_permission_required((E, "qp"), (E, "evaluate"))
QP_PRINT = permission_required(E, "qp_print")
CONDUCT = permission_required(E, "conduct")
MALPRACTICE = any_permission_required((E, "conduct"), (E, "malpractice"))
SEQ = [feature_required("exams.clash_detection")]
REGF = [feature_required("exams.registration_fee")]
ELIGF = [feature_required("exams.eligibility_snapshot")]
HTF = [feature_required("exams.hall_tickets")]
SEATF = [feature_required("exams.seating")]
INVF = [feature_required("exams.invigilation")]
REMF = [feature_required("exams.remuneration")]
QPF = [feature_required("exams.qp_management")]
PRINTF = [feature_required("exams.qp_watermark_print_log")]
ONLINE = [feature_required("exams.online_proctored")]
CENTRES = [feature_required("affiliation.exam_centres")]


def _queued(data: Any, message: str) -> JSONResponse:
    return JSONResponse(status_code=202, content=ok(data, message=message))


async def _enqueue(
    db: AsyncSession, principal: Principal, job: str, params: dict[str, Any], message: str
) -> JSONResponse:
    from app.core.jobs import enqueue

    j = await enqueue(db, principal, job, params)
    return _queued({"job_id": str(j.id)}, message)


def _pdf(data: bytes, name: str) -> Response:
    safe = "".join(c for c in name if c.isalnum() or c in "-_") or "document"
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f"inline; filename={safe}.pdf"})


# ---- sessions --------------------------------------------------------------------------------------------------------
@router.get("/exam-sessions", summary="Exam sessions", response_model=Envelope[list[ExamSessionResponse]])
async def list_sessions(
    request: Request,
    term_id: uuid.UUID | None = None,
    status: str | None = None,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ExamSessionService(db, principal, request).list_sessions(term_id, status))


@router.post(
    "/exam-sessions", status_code=201, summary="Create a session", response_model=Envelope[ExamSessionResponse]
)
async def create_session(
    body: ExamSessionCreate, request: Request, principal: Principal = Depends(CONF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ExamSessionService(db, principal, request).create(body), message="Session created")


@router.get("/exam-sessions/{id}", summary="Session", response_model=Envelope[ExamSessionResponse])
async def get_session(
    id: uuid.UUID, request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ExamSessionService(db, principal, request).get(id))


@router.put("/exam-sessions/{id}", summary="Update a session", response_model=Envelope[ExamSessionResponse])
async def update_session(
    id: uuid.UUID,
    body: ExamSessionUpdate,
    request: Request,
    principal: Principal = Depends(CONF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ExamSessionService(db, principal, request).update(id, body), message="Session updated")


@router.post(
    "/exam-sessions/{id}/status", summary="Move the status forward", response_model=Envelope[ExamSessionResponse]
)
async def change_status(
    id: uuid.UUID,
    body: SessionStatusChange,
    request: Request,
    principal: Principal = Depends(CONF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await ExamSessionService(db, principal, request).change_status(id, body.status),
        message=f"Status → {body.status}",
    )


@router.post("/exam-sessions/{id}/lock", summary="Lock the session", response_model=Envelope[ExamSessionResponse])
async def lock_session(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ExamSessionService(db, principal, request).lock(id), message="Locked")


# ---- papers / date-sheet ------------------------------------------------------------------------------------------------
@router.get("/exam-sessions/{id}/papers", summary="Papers", response_model=Envelope[list[ExamPaperResponse]])
async def papers(
    id: uuid.UUID, request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ExamSessionService(db, principal, request).papers(id))


@router.post(
    "/exam-sessions/{id}/papers", status_code=201, summary="Add a paper", response_model=Envelope[ExamPaperResponse]
)
async def create_paper(
    id: uuid.UUID,
    body: ExamPaperCreate,
    request: Request,
    principal: Principal = Depends(CONF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ExamSessionService(db, principal, request).create_paper(id, body), message="Paper added")


@router.post(
    "/exam-sessions/{id}/papers/bulk",
    summary="Papers from offerings + arrears (dry_run inline, else job)",
    response_model=Envelope[BulkPapersPreview],
)
async def papers_bulk(
    id: uuid.UUID,
    request: Request,
    body: BulkPapersRequest | None = None,
    dry_run: bool = False,
    principal: Principal = Depends(CONF),
    db: AsyncSession = Depends(get_db),
) -> Any:
    b = body or BulkPapersRequest()
    if dry_run or b.dry_run:
        b.dry_run = True
        return ok(await ExamSessionService(db, principal, request).papers_bulk(id, b), message="Preview")
    await ExamSessionService(db, principal, request).session(id, write=True)
    return await _enqueue(
        db, principal, "exams.papers_bulk", {"session_id": str(id), "body": b.model_dump()}, "Paper creation queued"
    )


@router.put("/exam-papers/{id}", summary="Update a paper", response_model=Envelope[ExamPaperResponse])
async def update_paper(
    id: uuid.UUID,
    body: ExamPaperUpdate,
    request: Request,
    principal: Principal = Depends(CONF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ExamSessionService(db, principal, request).update_paper(id, body), message="Paper updated")


@router.delete("/exam-papers/{id}", summary="Delete a paper without registrations", response_model=Envelope[None])
async def delete_paper(
    id: uuid.UUID, request: Request, principal: Principal = Depends(CONF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await ExamSessionService(db, principal, request).delete_paper(id)
    return ok(None, message="Paper deleted")


@router.put(
    "/exam-sessions/{id}/date-sheet",
    summary="Assign dates / slots / times",
    response_model=Envelope[list[ExamPaperResponse]],
)
async def date_sheet(
    id: uuid.UUID,
    body: DateSheetUpdate,
    request: Request,
    principal: Principal = Depends(CONF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ExamSessionService(db, principal, request).update_date_sheet(id, body), message="Date-sheet saved")


@router.post(
    "/exam-sessions/{id}/date-sheet/check-clashes",
    summary="Student clashes, holidays, unscheduled papers",
    dependencies=SEQ,
    response_model=Envelope[ClashReport],
)
async def check_clashes(
    id: uuid.UUID, request: Request, principal: Principal = Depends(CONF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ExamSessionService(db, principal, request).check_clashes(id))


@router.post(
    "/exam-sessions/{id}/date-sheet/publish",
    summary="Publish (409 DATE_SHEET_CLASH unless force by the COE)",
    response_model=Envelope[ClashReport],
)
async def publish_date_sheet(
    id: uuid.UUID,
    request: Request,
    force: bool = False,
    principal: Principal = Depends(CONF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await ExamSessionService(db, principal, request).publish_date_sheet(id, force=force),
        message="Date-sheet published",
    )


@router.get("/exam-sessions/{id}/date-sheet.pdf", summary="Date-sheet PDF", response_class=Response)
async def date_sheet_pdf(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> Response:
    return _pdf(await ExamSessionService(db, principal, request).date_sheet_pdf(id), f"date-sheet-{id}")


@router.get("/exam-sessions/{id}/date-sheet.ics", summary="Date-sheet ICS", response_class=Response)
async def date_sheet_ics(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> Response:
    data = await ExamSessionService(db, principal, request).date_sheet_ics(id)
    return Response(
        data, media_type="text/calendar", headers={"Content-Disposition": f"attachment; filename=date-sheet-{id}.ics"}
    )


# ---- self registration ----------------------------------------------------------------------------------------------------
@router.get(
    "/exam-registration/me",
    summary="My (ward's) registration, built from confirmed items + arrears",
    dependencies=REGF,
    response_model=Envelope[ExamRegistrationResponse],
)
async def my_registration(
    request: Request,
    session_id: uuid.UUID | None = None,
    student_id: uuid.UUID | None = None,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ExamRegistrationService(db, principal, request).mine(session_id, student_id))


@router.post(
    "/exam-registration/me/submit",
    summary="Submit (Idempotency-Key) → fee invoice / confirmed",
    dependencies=REGF,
    response_model=Envelope[ExamRegistrationResponse],
)
async def submit_registration(
    request: Request,
    body: RegistrationSubmit | None = None,
    session_id: uuid.UUID | None = None,
    _idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await ExamRegistrationService(db, principal, request).submit(session_id, body.item_ids if body else None)
    response = ok(out.model_dump(mode="json"), message=f"Registration {out.status}")
    await store(request, response, db)
    return response


@router.get(
    "/exam-registration/me/history",
    summary="My registrations",
    dependencies=REGF,
    response_model=Envelope[list[ExamRegistrationResponse]],
)
async def my_history(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ExamRegistrationService(db, principal, request).history())


@router.get(
    "/exam-registration/me/hall-ticket.pdf",
    summary="My hall ticket (after release)",
    dependencies=HTF,
    response_class=Response,
)
async def my_hall_ticket(
    request: Request,
    session_id: uuid.UUID | None = None,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> Response:
    from sqlalchemy import select

    from app.models.exams import ExamRegistration

    svc = ExamRegistrationService(db, principal, request)
    enrol = await svc.my_enrolment()
    s = await svc.session(session_id) if session_id else await svc.current_session_for(enrol)
    reg = (
        await db.execute(
            select(ExamRegistration).where(
                ExamRegistration.exam_session_id == s.id, ExamRegistration.student_program_enrollment_id == enrol.id
            )
        )
    ).scalar_one_or_none()
    if reg is None:
        from app.core.errors import APIError, ErrorCode

        raise APIError(404, ErrorCode.NOT_FOUND, "No registration")
    pdf, number = await HallTicketService(db, principal, request).pdf_for(reg, self_view=True)
    return _pdf(pdf, number)


@router.get(
    "/exam-registration/me/seat",
    summary="My published seats",
    dependencies=SEATF,
    response_model=Envelope[list[dict[str, Any]]],
)
async def my_seat(
    request: Request,
    paper_id: uuid.UUID | None = None,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SeatingService(db, principal, request).my_seat(paper_id))


# ---- admin registrations -----------------------------------------------------------------------------------------------------
@router.get(
    "/exam-sessions/{id}/registrations",
    summary="Registrations",
    response_model=Envelope[list[ExamRegistrationResponse]],
)
async def registrations(
    id: uuid.UUID,
    request: Request,
    status: str | None = None,
    college_id: uuid.UUID | None = None,
    program_id: uuid.UUID | None = None,
    search: str | None = None,
    scope: str | None = None,
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(REG_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, page, vis = await ExamRegistrationService(db, principal, request).list_page(
        id, params, status=status, college_id=college_id, program_id=program_id, search=search, scope=scope
    )
    return ok(rows, pagination=page, visibility=vis)


@router.get("/exam-registrations/{id}", summary="Registration", response_model=Envelope[ExamRegistrationResponse])
async def get_registration(
    id: uuid.UUID, request: Request, principal: Principal = Depends(REG_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ExamRegistrationService(db, principal, request).get(id))


@router.post(
    "/exam-registrations",
    status_code=201,
    summary="Admin registration",
    response_model=Envelope[ExamRegistrationResponse],
)
async def admin_create(
    body: RegistrationAdminCreate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ExamRegistrationService(db, principal, request).admin_create(body), message="Registered")


@router.post(
    "/exam-registrations/{id}/{action}",
    summary="cancel | debar | reinstate",
    response_model=Envelope[ExamRegistrationResponse],
)
async def registration_action(
    id: uuid.UUID,
    action: str,
    body: ReasonBody,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    to = {"cancel": "cancelled", "debar": "debarred", "reinstate": "reinstate"}.get(action)
    if to is None:
        from app.core.errors import APIError, ErrorCode

        raise APIError(404, ErrorCode.NOT_FOUND, f"Unknown action {action}")
    return ok(
        await ExamRegistrationService(db, principal, request).set_status(id, to, body.reason),
        message=f"Registration {action}",
    )


@router.post(
    "/exam-sessions/{id}/registrations/bulk",
    status_code=202,
    summary="Register every enrolment with confirmed items (job)",
    response_model=Envelope[dict[str, Any]],
)
async def bulk_register(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    await ExamSessionService(db, principal, request).session(id, write=True)
    return await _enqueue(
        db, principal, "exams.registrations_bulk", {"session_id": str(id)}, "Bulk registration queued"
    )


# ---- eligibility ----------------------------------------------------------------------------------------------------------------
@router.post(
    "/exam-sessions/{id}/eligibility/apply",
    status_code=202,
    summary="Apply the term eligibility snapshot (job)",
    dependencies=ELIGF,
    response_model=Envelope[dict[str, Any]],
)
async def eligibility_apply(
    id: uuid.UUID,
    request: Request,
    body: EligibilityApplyRequest | None = None,
    principal: Principal = Depends(ELIG),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    await ExamSessionService(db, principal, request).session(id, write=True)
    return await _enqueue(
        db,
        principal,
        "exams.eligibility_apply",
        {"session_id": str(id), "body": (body or EligibilityApplyRequest()).model_dump()},
        "Eligibility apply queued",
    )


@router.get(
    "/exam-sessions/{id}/eligibility/summary",
    summary="Items by eligibility",
    dependencies=ELIGF,
    response_model=Envelope[EligibilityApplySummary],
)
async def eligibility_summary(
    id: uuid.UUID, request: Request, principal: Principal = Depends(ELIG), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ExamRegistrationService(db, principal, request).eligibility_summary(id))


# ---- hall tickets ---------------------------------------------------------------------------------------------------------------
@router.post(
    "/exam-sessions/{id}/hall-tickets/generate",
    status_code=202,
    summary="Generate hall tickets (job)",
    dependencies=HTF,
    response_model=Envelope[dict[str, Any]],
)
async def generate_hall_tickets(
    id: uuid.UUID,
    request: Request,
    body: HallTicketGenerateRequest | None = None,
    principal: Principal = Depends(HT),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    await ExamSessionService(db, principal, request).session(id, write=True)
    return await _enqueue(
        db,
        principal,
        "exams.hall_tickets_generate",
        {"session_id": str(id), "body": (body or HallTicketGenerateRequest()).model_dump(mode="json")},
        "Hall tickets queued",
    )


@router.get(
    "/exam-registrations/{id}/hall-ticket.pdf",
    summary="Hall ticket of a registration",
    dependencies=HTF,
    response_class=Response,
)
async def hall_ticket(
    id: uuid.UUID, request: Request, principal: Principal = Depends(HT), db: AsyncSession = Depends(get_db)
) -> Response:
    from sqlalchemy import select

    from app.core.errors import APIError, ErrorCode
    from app.models.exams import ExamRegistration

    reg = (await db.execute(select(ExamRegistration).where(ExamRegistration.id == id))).scalar_one_or_none()
    if reg is None:
        raise APIError(404, ErrorCode.NOT_FOUND, "Registration not found")
    pdf, number = await HallTicketService(db, principal, request).pdf_for(reg, self_view=False)
    return _pdf(pdf, number)


@public_router.get(
    "/hall-tickets/verify/{token}",
    summary="Public hall-ticket verification (masked)",
    response_model=Envelope[HallTicketVerifyResponse],
)
async def verify_hall_ticket(token: str, request: Request, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    from sqlalchemy import select

    from app.db.session import bind_tenant, set_tenant
    from app.models.exams import ExamRegistration

    # the token is unguessable; read its tenant on the platform session, then pin it
    inst = (
        await db.execute(select(ExamRegistration.institution_id).where(ExamRegistration.hall_ticket_qr_token == token))
    ).scalar_one_or_none()
    if inst is None:
        return ok(HallTicketVerifyResponse(valid=False, reason="unknown or revoked"))
    bind_tenant(db, inst)
    await set_tenant(db, inst)
    return ok(await HallTicketService(db, None, request, inst).verify(token))


# ---- seating --------------------------------------------------------------------------------------------------------------------
@router.post(
    "/exam-sessions/{id}/seating/generate",
    summary="Generate seating (dry_run inline, else job)",
    dependencies=SEATF,
    response_model=Envelope[SeatingSummary],
)
async def seating_generate(
    id: uuid.UUID,
    body: SeatingGenerateRequest,
    request: Request,
    principal: Principal = Depends(SEAT),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = SeatingService(db, principal, request)
    if body.dry_run:
        return ok(await svc.generate(id, body), message="Preview")
    return ok(await svc.generate(id, body), message="Seating generated")


@router.get(
    "/exam-sessions/{id}/seating",
    summary="Seat allocations",
    dependencies=SEATF,
    response_model=Envelope[list[SeatAllocationRow]],
)
async def seating(
    id: uuid.UUID,
    request: Request,
    exam_date: date | None = Query(None, alias="date"),
    slot: str | None = None,
    principal: Principal = Depends(SEAT_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SeatingService(db, principal, request).rows(id, exam_date, slot))


@router.put(
    "/exam-seat-allocations/{id}",
    summary="Manual move (audited)",
    dependencies=SEATF,
    response_model=Envelope[SeatAllocationRow],
)
async def move_seat(
    id: uuid.UUID,
    body: SeatMove,
    request: Request,
    principal: Principal = Depends(SEAT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SeatingService(db, principal, request).move(id, body), message="Moved")


@router.post(
    "/exam-sessions/{id}/seating/publish",
    summary="Publish seating (hall tickets regenerated with venue)",
    dependencies=SEATF,
    response_model=Envelope[dict[str, int]],
)
async def publish_seating(
    id: uuid.UUID,
    request: Request,
    exam_date: date | None = Query(None, alias="date"),
    slot: str | None = None,
    principal: Principal = Depends(SEAT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    n = await SeatingService(db, principal, request).publish(id, exam_date, slot)
    return ok({"plans": n}, message=f"{n} plan(s) published")


@router.get(
    "/exam-seating-plans/{id}/chart.pdf", summary="Room seating chart", dependencies=SEATF, response_class=Response
)
async def chart(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SEAT_READ), db: AsyncSession = Depends(get_db)
) -> Response:
    return _pdf(await SeatingService(db, principal, request).chart_pdf(id), f"chart-{id}")


@router.get("/exam-seating-plans/{id}/door-list.pdf", summary="Door list", dependencies=SEATF, response_class=Response)
async def door_list(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SEAT_READ), db: AsyncSession = Depends(get_db)
) -> Response:
    return _pdf(await SeatingService(db, principal, request).chart_pdf(id, door=True), f"door-list-{id}")


# ---- invigilation -----------------------------------------------------------------------------------------------------------------
@router.post(
    "/exam-sessions/{id}/invigilation/auto-assign",
    summary="Auto-assign duties (dry_run inline, else job)",
    dependencies=INVF,
    response_model=Envelope[RosterSummary],
)
async def auto_assign(
    id: uuid.UUID,
    body: InvigilationAutoAssignRequest,
    request: Request,
    principal: Principal = Depends(INV),
    db: AsyncSession = Depends(get_db),
) -> Any:
    if body.dry_run:
        return ok(await InvigilationService(db, principal, request).auto_assign(id, body), message="Preview")
    await ExamSessionService(db, principal, request).session(id, write=True)
    return await _enqueue(
        db,
        principal,
        "exams.invigilation_auto_assign",
        {"session_id": str(id), "body": body.model_dump(mode="json")},
        "Auto-assignment queued",
    )


@router.get(
    "/exam-sessions/{id}/invigilation",
    summary="Duty roster",
    dependencies=INVF,
    response_model=Envelope[list[DutyResponse]],
)
async def roster(
    id: uuid.UUID,
    request: Request,
    exam_date: date | None = Query(None, alias="date"),
    room_id: uuid.UUID | None = None,
    principal: Principal = Depends(INV_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await InvigilationService(db, principal, request).roster(id, exam_date, room_id))


@router.get(
    "/invigilation-duties/me", summary="My duties", dependencies=INVF, response_model=Envelope[list[DutyResponse]]
)
async def my_duties(
    request: Request, principal: Principal = Depends(STAFF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await InvigilationService(db, principal, request).mine())


@router.post(
    "/invigilation-duties",
    status_code=201,
    summary="Add a duty",
    dependencies=INVF,
    response_model=Envelope[DutyResponse],
)
async def create_duty(
    body: DutyCreate, request: Request, principal: Principal = Depends(INV), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await InvigilationService(db, principal, request).create(body), message="Duty added")


@router.put(
    "/invigilation-duties/{id}", summary="Update a duty", dependencies=INVF, response_model=Envelope[DutyResponse]
)
async def update_duty(
    id: uuid.UUID,
    body: DutyUpdate,
    request: Request,
    principal: Principal = Depends(INV),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await InvigilationService(db, principal, request).update(id, body))


@router.delete("/invigilation-duties/{id}", summary="Remove a duty", dependencies=INVF, response_model=Envelope[None])
async def delete_duty(
    id: uuid.UUID, request: Request, principal: Principal = Depends(INV), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await InvigilationService(db, principal, request).delete(id)
    return ok(None, message="Duty removed")


@router.post(
    "/invigilation-duties/{id}/swap-request",
    summary="Request a swap (own duty)",
    dependencies=INVF,
    response_model=Envelope[DutyResponse],
)
async def swap_request(
    id: uuid.UUID,
    body: SwapRequest,
    request: Request,
    principal: Principal = Depends(STAFF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await InvigilationService(db, principal, request).swap_request(id, body), message="Swap requested")


@router.post(
    "/invigilation-duties/{id}/swap/{decision}",
    summary="Approve / reject a swap (availability checked)",
    dependencies=INVF,
    response_model=Envelope[DutyResponse],
)
async def swap_decide(
    id: uuid.UUID,
    decision: str,
    request: Request,
    with_staff_id: uuid.UUID | None = None,
    principal: Principal = Depends(INV),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await InvigilationService(db, principal, request).swap_decide(id, decision == "approve", with_staff_id),
        message=f"Swap {decision}d",
    )


@router.post(
    "/invigilation-duties/{id}/mark-absent",
    summary="Mark the invigilator absent",
    dependencies=INVF,
    response_model=Envelope[DutyResponse],
)
async def duty_absent(
    id: uuid.UUID, request: Request, principal: Principal = Depends(INV), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await InvigilationService(db, principal, request).mark_absent(id))


@router.get("/invigilation-duties/{id}/letter.pdf", summary="Duty letter", dependencies=INVF, response_class=Response)
async def duty_letter(
    id: uuid.UUID, request: Request, principal: Principal = Depends(STAFF), db: AsyncSession = Depends(get_db)
) -> Response:
    return _pdf(await InvigilationService(db, principal, request).letter_pdf(id), f"duty-{id}")


@router.get(
    "/exam-sessions/{id}/remuneration",
    summary="Remuneration by role / staff",
    dependencies=REMF,
    response_model=Envelope[RemunerationSummary],
)
async def remuneration(
    id: uuid.UUID, request: Request, principal: Principal = Depends(REMUN), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await InvigilationService(db, principal, request).remuneration(id))


# ---- question papers --------------------------------------------------------------------------------------------------------------
@router.get(
    "/qp-assignments/me",
    summary="My setter assignments (internal / external)",
    dependencies=QPF,
    response_model=Envelope[list[QpAssignmentResponse]],
)
async def my_qp(
    request: Request, principal: Principal = Depends(QP_SETTER), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await QpService(db, principal, request).mine())


@router.get(
    "/qp/download/{token}",
    summary="Single-use watermarked print download",
    dependencies=PRINTF,
    response_class=Response,
)
async def qp_download(
    token: str, request: Request, principal: Principal = Depends(QP_PRINT), db: AsyncSession = Depends(get_db)
) -> Response:
    return _pdf(await QpService(db, principal, request).download(token), "question-paper")


@router.get(
    "/exam-papers/{id}/qp-assignments",
    summary="Sets of a paper",
    dependencies=QPF,
    response_model=Envelope[list[QpAssignmentResponse]],
)
async def qp_list(
    id: uuid.UUID, request: Request, principal: Principal = Depends(QP_SETTER), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await QpService(db, principal, request).for_paper(id))


@router.post(
    "/exam-papers/{id}/qp-assignments",
    status_code=201,
    summary="Invite a setter for a set",
    dependencies=QPF,
    response_model=Envelope[QpAssignmentResponse],
)
async def qp_create(
    id: uuid.UUID,
    body: QpAssignmentCreate,
    request: Request,
    principal: Principal = Depends(QP),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await QpService(db, principal, request).create(id, body), message="Setter invited")


@router.put(
    "/qp-assignments/{id}",
    summary="Update an assignment",
    dependencies=QPF,
    response_model=Envelope[QpAssignmentResponse],
)
async def qp_update(
    id: uuid.UUID,
    body: QpAssignmentCreate,
    request: Request,
    principal: Principal = Depends(QP),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await QpService(db, principal, request).update(id, body))


@router.post(
    "/qp-assignments/{id}/upload",
    summary="Upload the paper (stored encrypted)",
    dependencies=QPF,
    response_model=Envelope[QpAssignmentResponse],
)
async def qp_upload(
    id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    principal: Principal = Depends(QP_SETTER),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await QpService(db, principal, request).upload(id, await file.read(), file.filename or "paper.pdf"),
        message="Uploaded",
    )


@router.post(
    "/qp-assignments/{id}/generate-from-blueprint",
    summary="Generate from the blueprint (frozen paper + PDF)",
    dependencies=QPF,
    response_model=Envelope[QpAssignmentResponse],
)
async def qp_generate(
    id: uuid.UUID, request: Request, principal: Principal = Depends(QP_SETTER), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await QpService(db, principal, request).generate_from_blueprint(id), message="Generated")


@router.post(
    "/qp-assignments/{id}/scrutinise",
    summary="Scrutiny approve / reject",
    dependencies=QPF,
    response_model=Envelope[QpAssignmentResponse],
)
async def qp_scrutinise(
    id: uuid.UUID,
    body: QpScrutinyRequest,
    request: Request,
    principal: Principal = Depends(QP),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await QpService(db, principal, request).scrutinise(id, body))


@router.post(
    "/qp-assignments/{id}/select",
    summary="Select the set (others rejected)",
    dependencies=QPF,
    response_model=Envelope[list[QpAssignmentResponse]],
)
async def qp_select(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await QpService(db, principal, request).select_set(id), message="Selected")


@router.post(
    "/qp-assignments/{id}/print",
    summary="Watermarked print → single-use token",
    dependencies=[*QPF, *PRINTF],
    response_model=Envelope[QpPrintResponse],
)
async def qp_print(
    id: uuid.UUID,
    body: QpPrintRequest,
    request: Request,
    principal: Principal = Depends(QP_PRINT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await QpService(db, principal, request).print(id, body), message="Print logged")


# ---- conduct --------------------------------------------------------------------------------------------------------------------
@router.get(
    "/exam-papers/{id}/attendance",
    summary="Hall attendance roster",
    response_model=Envelope[list[HallAttendanceRowOut]],
)
async def hall_roster(
    id: uuid.UUID,
    request: Request,
    room_id: uuid.UUID | None = None,
    principal: Principal = Depends(CONDUCT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ConductService(db, principal, request).roster(id, room_id))


@router.post(
    "/exam-papers/{id}/attendance",
    summary="Mark hall attendance (Idempotency-Key)",
    response_model=Envelope[list[HallAttendanceRowOut]],
)
async def mark_hall(
    id: uuid.UUID,
    body: HallAttendanceMark,
    request: Request,
    _idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(CONDUCT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await ConductService(db, principal, request).mark(id, body)
    response = ok([r.model_dump(mode="json") for r in out], message="Attendance saved")
    await store(request, response, db)
    return response


@router.get("/exam-papers/{id}/attendance-sheet.pdf", summary="Attendance sheet", response_class=Response)
async def hall_sheet(
    id: uuid.UUID, request: Request, principal: Principal = Depends(CONDUCT), db: AsyncSession = Depends(get_db)
) -> Response:
    return _pdf(await ConductService(db, principal, request).attendance_pdf(id), f"attendance-{id}")


@router.post(
    "/exam-papers/{id}/malpractice-reports",
    status_code=201,
    summary="Report malpractice",
    response_model=Envelope[MalpracticeOut],
)
async def malpractice(
    id: uuid.UUID,
    body: MalpracticeReportCreate,
    request: Request,
    principal: Principal = Depends(MALPRACTICE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ConductService(db, principal, request).report_malpractice(id, body), message="Reported")


@router.post(
    "/exam-papers/{id}/online/setup",
    summary="Link a quiz + proctoring",
    dependencies=ONLINE,
    response_model=Envelope[dict[str, Any]],
)
async def online_setup(
    id: uuid.UUID,
    body: OnlinePaperSetup,
    request: Request,
    principal: Principal = Depends(CONF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ConductService(db, principal, request).online_setup(id, body))


@router.get(
    "/exam-papers/{id}/online/access",
    summary="Access the online paper in its window",
    dependencies=ONLINE,
    response_model=Envelope[dict[str, Any]],
)
async def online_access(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ConductService(db, principal, request).online_access(id))


# ---- centres --------------------------------------------------------------------------------------------------------------------
@router.get(
    "/exam-sessions/{id}/centres",
    summary="Exam centres",
    dependencies=CENTRES,
    response_model=Envelope[list[ExamCentreOut]],
)
async def centres(
    id: uuid.UUID, request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ExamSessionService(db, principal, request).centres(id))


@router.post(
    "/exam-sessions/{id}/centres",
    status_code=201,
    summary="Add a centre (central sessions)",
    dependencies=CENTRES,
    response_model=Envelope[ExamCentreOut],
)
async def create_centre(
    id: uuid.UUID,
    body: ExamCentreIn,
    request: Request,
    principal: Principal = Depends(CONF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ExamSessionService(db, principal, request).save_centre(id, body), message="Centre added")


@router.put(
    "/exam-centres/{id}", summary="Update a centre", dependencies=CENTRES, response_model=Envelope[ExamCentreOut]
)
async def update_centre(
    id: uuid.UUID,
    body: ExamCentreIn,
    request: Request,
    principal: Principal = Depends(CONF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ExamSessionService(db, principal, request).save_centre(None, body, id))
