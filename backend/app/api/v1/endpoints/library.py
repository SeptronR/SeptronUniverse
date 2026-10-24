"""Library — Prompts/19 §19.8.

``router`` (each route carries its ``library.*`` feature; visibility narrows in the services: own / wards / department
/ college / all, 404 otherwise) and ``public_router`` (OPAC — tenant from ``?institution=<slug>``, rate-limited).
Circulation writes honour ``Idempotency-Key``; imports, stock verification, sync and reports answer ``202`` with a
``job_id``. Fixed paths precede parameterised ones.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, permission_required
from app.core.features import feature_required
from app.core.idempotency import idempotency_key, store
from app.core.rate_limit import rate_limited
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.library import (
    BookCategoryIn,
    BookCategoryOut,
    BookCreate,
    BookImportRequest,
    BookIssueResponse,
    BookLostRequest,
    BookRenewRequest,
    BookResponse,
    BookReturnRequest,
    BookReturnResponse,
    BookUpdate,
    CirculationIssueRequest,
    CopyBulkCreate,
    CopyResponse,
    CopyStatusChange,
    EresourceIn,
    EresourceOut,
    ExternalMemberCreate,
    FineWaiveRequest,
    KohaSyncRequest,
    LibraryFineRow,
    LibraryIllDecision,
    LibraryIllRequestIn,
    LibraryIllResponse,
    LibraryJobAccepted,
    LibraryMemberResponse,
    LibraryMemberRulesUpdate,
    LibraryReservationCreate,
    LibraryReservationResponse,
    LibraryStatsResponse,
    OpacResult,
    OpacSearchResponse,
    StockVerificationRequest,
)
from app.services.library.catalogue_service import CatalogueService, MemberService
from app.services.library.circulation_service import CirculationService
from app.services.library.common import visibility_scopes
from app.services.library.operations_service import LibraryOpsService, opac_book, opac_new_arrivals, opac_search
from app.utils.response import ok

router = APIRouter(tags=["library"])
public_router = APIRouter(tags=["public"])

L = "library"
MANAGE = permission_required(L, "manage")
READ_ALL = any_permission_required((L, "view_all"), (L, "manage"), (L, "circulate"))
CATALOGUE = any_permission_required((L, "view_all"), (L, "manage"), (L, "circulate"), (L, "self"), (L, "view"))
CIRC = any_permission_required((L, "circulate"), (L, "manage"))
SELF = any_permission_required((L, "self"), (L, "view"), (L, "view_all"), (L, "manage"), (L, "circulate"))
FINES = any_permission_required((L, "fines"), (L, "manage"), (L, "view_all"), (L, "self"), (L, "view"))
WAIVE = any_permission_required((L, "fines"), (L, "manage"))
REPORTS = any_permission_required((L, "view_all"), (L, "manage"), ("reports", "export"))

CORE = [feature_required("library.core")]
FINEF = [feature_required("library.fines")]
ERES = [feature_required("library.eresources")]
ILL = [feature_required("library.inter_library_loan")]
KOHA = [feature_required("library.koha_sync")]
OPAC = [feature_required("library.opac")]


def _visible(principal: Principal, data: Any) -> dict[str, Any]:
    tabs = visibility_scopes(principal)
    res = ok(data)
    res.setdefault("meta", {})["visibility"] = {"self": True, "scopes": tabs, "default": tabs[0] if tabs else "self"}
    return res


def _accepted(job_id: uuid.UUID, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=202, content=ok(LibraryJobAccepted(job_id=job_id).model_dump(mode="json"), message=message)
    )


async def _job(
    db: AsyncSession, principal: Principal, job_type: str, params: dict[str, Any], queue: str = "reports"
) -> uuid.UUID:
    from app.core.jobs import enqueue

    return (await enqueue(db, principal, job_type, params, queue=queue)).id


# ---- categories ------------------------------------------------------------------------------------------------------------
@router.get(
    "/library/categories", summary="Categories", response_model=Envelope[list[BookCategoryOut]], dependencies=CORE
)
async def categories(
    request: Request, principal: Principal = Depends(CATALOGUE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CatalogueService(db, principal, request).categories())


@router.post(
    "/library/categories", summary="Create a category", response_model=Envelope[BookCategoryOut], dependencies=CORE
)
async def category_create(
    body: BookCategoryIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CatalogueService(db, principal, request).save_category(body))


@router.put(
    "/library/categories/{id}", summary="Edit a category", response_model=Envelope[BookCategoryOut], dependencies=CORE
)
async def category_update(
    id: uuid.UUID,
    body: BookCategoryIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CatalogueService(db, principal, request).save_category(body, id))


@router.delete(
    "/library/categories/{id}",
    summary="Delete (or deactivate) a category",
    response_model=Envelope[dict[str, Any]],
    dependencies=CORE,
)
async def category_delete(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await CatalogueService(db, principal, request).delete_category(id)
    return ok({"id": str(id)}, message="Category removed")


# ---- books & copies ----------------------------------------------------------------------------------------------------------
@router.post(
    "/library/books/import",
    status_code=202,
    summary="Import a CSV catalogue (job)",
    response_model=Envelope[LibraryJobAccepted],
    dependencies=CORE,
)
async def books_import(
    body: BookImportRequest,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return _accepted(
        await _job(db, principal, "library.import_catalogue", body.model_dump(mode="json")), "Import queued"
    )


@router.get("/library/books", summary="Catalogue", response_model=Envelope[list[BookResponse]], dependencies=CORE)
async def books(
    request: Request,
    q: str | None = None,
    category_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    page: int = 1,
    page_size: int = 50,
    principal: Principal = Depends(READ_ALL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    size = max(1, min(page_size, 200))
    rows, total = await CatalogueService(db, principal, request).list_books(
        q, category_id, resource_type, size, (max(page, 1) - 1) * size
    )
    res = _visible(principal, rows)
    res["meta"].update({"total": total, "page": page, "page_size": size})
    return res


@router.post(
    "/library/books",
    summary="Create a book (duplicate ISBN → warning)",
    status_code=201,
    response_model=Envelope[BookResponse],
    dependencies=CORE,
)
async def book_create(
    body: BookCreate, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    out = await CatalogueService(db, principal, request).create_book(body)
    return JSONResponse(status_code=201, content=ok(out.model_dump(mode="json"), message="Book created"))


@router.get("/library/books/{id}", summary="Book", response_model=Envelope[BookResponse], dependencies=CORE)
async def book_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(CATALOGUE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CatalogueService(db, principal, request).get_book(id))


@router.put("/library/books/{id}", summary="Edit a book", response_model=Envelope[BookResponse], dependencies=CORE)
async def book_update(
    id: uuid.UUID,
    body: BookUpdate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CatalogueService(db, principal, request).update_book(id, body))


@router.delete(
    "/library/books/{id}", summary="Delete a book", response_model=Envelope[dict[str, Any]], dependencies=CORE
)
async def book_delete(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await CatalogueService(db, principal, request).delete_book(id)
    return ok({"id": str(id)}, message="Book deleted")


@router.get(
    "/library/books/{id}/copies",
    summary="Copies of a book",
    response_model=Envelope[list[CopyResponse]],
    dependencies=CORE,
)
async def book_copies(
    id: uuid.UUID, request: Request, principal: Principal = Depends(READ_ALL), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CatalogueService(db, principal, request).copies(id))


@router.post(
    "/library/books/{id}/copies/bulk",
    summary="Add copies (accession numbers)",
    response_model=Envelope[list[CopyResponse]],
    dependencies=CORE,
)
async def copies_bulk(
    id: uuid.UUID,
    body: CopyBulkCreate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await CatalogueService(db, principal, request).bulk_copies(id, body), message=f"{body.count} copies added"
    )


@router.get(
    "/library/copies/resolve",
    summary="Resolve a scan (barcode / accession / RFID)",
    response_model=Envelope[CopyResponse],
    dependencies=CORE,
)
async def copy_resolve(
    request: Request,
    barcode: str | None = None,
    accession: str | None = None,
    rfid: str | None = None,
    principal: Principal = Depends(CIRC),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CatalogueService(db, principal, request).resolve(barcode, accession, rfid))


@router.put(
    "/library/copies/{id}/status",
    summary="Change a copy's status",
    response_model=Envelope[CopyResponse],
    dependencies=CORE,
)
async def copy_status(
    id: uuid.UUID,
    body: CopyStatusChange,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CatalogueService(db, principal, request).change_copy_status(id, body))


# ---- e-resources ------------------------------------------------------------------------------------------------------------
@router.get(
    "/library/eresources", summary="E-resources", response_model=Envelope[list[EresourceOut]], dependencies=ERES
)
async def eresources(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LibraryOpsService(db, principal, request).eresources())


@router.post(
    "/library/eresources", summary="Add an e-resource", response_model=Envelope[EresourceOut], dependencies=ERES
)
async def eresource_create(
    body: EresourceIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LibraryOpsService(db, principal, request).save_eresource(body))


@router.put(
    "/library/eresources/{id}", summary="Edit an e-resource", response_model=Envelope[EresourceOut], dependencies=ERES
)
async def eresource_update(
    id: uuid.UUID,
    body: EresourceIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LibraryOpsService(db, principal, request).save_eresource(body, id))


@router.delete(
    "/library/eresources/{id}",
    summary="Deactivate an e-resource",
    response_model=Envelope[dict[str, Any]],
    dependencies=ERES,
)
async def eresource_delete(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await LibraryOpsService(db, principal, request).delete_eresource(id)
    return ok({"id": str(id)})


@router.get("/library/eresources/{id}/open", summary="Open (authenticated redirect; logs usage)", dependencies=ERES)
async def eresource_open(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> RedirectResponse:
    url = await LibraryOpsService(db, principal, request).open_eresource(id)
    await db.commit()
    return RedirectResponse(url, status_code=302)


# ---- members ------------------------------------------------------------------------------------------------------------------
@router.get(
    "/library/members/me", summary="My library card", response_model=Envelope[LibraryMemberResponse], dependencies=CORE
)
async def member_me(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MemberService(db, principal, request).me())


@router.get(
    "/library/members/me/issues",
    summary="My books",
    response_model=Envelope[list[BookIssueResponse]],
    dependencies=CORE,
)
async def member_me_issues(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CirculationService(db, principal, request).my_issues())


@router.get(
    "/library/members/me/fines", summary="My fines", response_model=Envelope[list[LibraryFineRow]], dependencies=CORE
)
async def member_me_fines(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CirculationService(db, principal, request).fines(None, None, mine=True))


@router.get(
    "/library/members/wards",
    summary="My wards' library cards",
    response_model=Envelope[list[LibraryMemberResponse]],
    dependencies=CORE,
)
async def member_wards(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MemberService(db, principal, request).wards())


@router.get(
    "/library/members", summary="Members", response_model=Envelope[list[LibraryMemberResponse]], dependencies=CORE
)
async def members(
    request: Request,
    type: str | None = None,
    status: str | None = None,
    department_id: uuid.UUID | None = None,
    scope: str | None = None,
    principal: Principal = Depends(READ_ALL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return _visible(
        principal, await MemberService(db, principal, request).list_members(type, status, department_id, scope)
    )


@router.post(
    "/library/members",
    summary="Create an external / alumni member (deposit invoice)",
    response_model=Envelope[LibraryMemberResponse],
    dependencies=CORE,
)
async def member_create(
    body: ExternalMemberCreate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MemberService(db, principal, request).create_external(body))


@router.get(
    "/library/members/{id}", summary="Member", response_model=Envelope[LibraryMemberResponse], dependencies=CORE
)
async def member_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MemberService(db, principal, request).get(id))


@router.put(
    "/library/members/{id}/rules",
    summary="Member limits",
    response_model=Envelope[LibraryMemberResponse],
    dependencies=CORE,
)
async def member_rules(
    id: uuid.UUID,
    body: LibraryMemberRulesUpdate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MemberService(db, principal, request).update_rules(id, body))


@router.post(
    "/library/members/{id}/suspend",
    summary="Suspend",
    response_model=Envelope[LibraryMemberResponse],
    dependencies=CORE,
)
async def member_suspend(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MemberService(db, principal, request).set_active(id, False))


@router.post(
    "/library/members/{id}/activate",
    summary="Activate",
    response_model=Envelope[LibraryMemberResponse],
    dependencies=CORE,
)
async def member_activate(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MemberService(db, principal, request).set_active(id, True))


# ---- circulation --------------------------------------------------------------------------------------------------------------
async def _idem(request: Request, db: AsyncSession, out: Any, message: str) -> dict[str, Any]:
    response = ok(out.model_dump(mode="json"), message=message)
    await store(request, response, db)
    return response


@router.post(
    "/library/circulation/issue",
    summary="Issue (Idempotency-Key)",
    response_model=Envelope[BookIssueResponse],
    dependencies=CORE,
)
async def circ_issue(
    body: CirculationIssueRequest,
    request: Request,
    _k: str | None = Depends(idempotency_key),
    principal: Principal = Depends(CIRC),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _idem(request, db, await CirculationService(db, principal, request).issue(body), "Issued")


@router.post(
    "/library/circulation/return",
    summary="Return (Idempotency-Key)",
    response_model=Envelope[BookReturnResponse],
    dependencies=CORE,
)
async def circ_return(
    body: BookReturnRequest,
    request: Request,
    _k: str | None = Depends(idempotency_key),
    principal: Principal = Depends(CIRC),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _idem(request, db, await CirculationService(db, principal, request).return_copy(body), "Returned")


@router.post(
    "/library/circulation/renew",
    summary="Renew at the counter",
    response_model=Envelope[BookIssueResponse],
    dependencies=CORE,
)
async def circ_renew(
    body: BookRenewRequest,
    request: Request,
    _k: str | None = Depends(idempotency_key),
    principal: Principal = Depends(CIRC),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _idem(request, db, await CirculationService(db, principal, request).renew(body.issue_id), "Renewed")


@router.post(
    "/library/circulation/lost",
    summary="Mark lost (replacement invoice)",
    response_model=Envelope[BookIssueResponse],
    dependencies=CORE,
)
async def circ_lost(
    body: BookLostRequest,
    request: Request,
    _k: str | None = Depends(idempotency_key),
    principal: Principal = Depends(CIRC),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _idem(request, db, await CirculationService(db, principal, request).mark_lost(body), "Marked lost")


@router.post(
    "/library/circulation/self-renew",
    summary="Renew my book",
    response_model=Envelope[BookIssueResponse],
    dependencies=CORE,
)
async def circ_self_renew(
    body: BookRenewRequest, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(
        await CirculationService(db, principal, request).renew(body.issue_id, self_service=True), message="Renewed"
    )


@router.get(
    "/library/issues",
    summary="Issues (self / wards / department / all)",
    response_model=Envelope[list[BookIssueResponse]],
    dependencies=CORE,
)
async def issues(
    request: Request,
    status: str | None = None,
    member_id: uuid.UUID | None = None,
    overdue: bool = False,
    department_id: uuid.UUID | None = None,
    scope: str | None = None,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await CirculationService(db, principal, request).list_issues(status, member_id, overdue, department_id, scope)
    return _visible(principal, out)


@router.get("/library/issues/{id}", summary="Issue", response_model=Envelope[BookIssueResponse], dependencies=CORE)
async def issue_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CirculationService(db, principal, request).get_issue(id))


# ---- reservations --------------------------------------------------------------------------------------------------------------
@router.get(
    "/library/reservations",
    summary="Reservations (own, or the queue for circulation staff)",
    response_model=Envelope[list[LibraryReservationResponse]],
    dependencies=CORE,
)
async def reservations(
    request: Request,
    status: str | None = None,
    mine: bool = False,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CirculationService(db, principal, request).list_reservations(status, mine))


@router.post(
    "/library/reservations",
    summary="Reserve a title",
    response_model=Envelope[LibraryReservationResponse],
    dependencies=CORE,
)
async def reserve(
    body: LibraryReservationCreate,
    request: Request,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CirculationService(db, principal, request).reserve(body), message="Reserved")


@router.delete(
    "/library/reservations/{id}",
    summary="Cancel a reservation",
    response_model=Envelope[LibraryReservationResponse],
    dependencies=CORE,
)
async def reservation_cancel(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CirculationService(db, principal, request).cancel_reservation(id), message="Cancelled")


# ---- fines -------------------------------------------------------------------------------------------------------------------------
@router.get("/library/fines", summary="Fines", response_model=Envelope[list[LibraryFineRow]], dependencies=FINEF)
async def fines(
    request: Request,
    status: str | None = None,
    member_id: uuid.UUID | None = None,
    principal: Principal = Depends(FINES),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CirculationService(db, principal, request).fines(status, member_id))


@router.post(
    "/library/fines/{issue_id}/waive",
    summary="Waive a fine (librarian)",
    response_model=Envelope[LibraryFineRow],
    dependencies=FINEF,
)
async def fine_waive(
    issue_id: uuid.UUID,
    body: FineWaiveRequest,
    request: Request,
    principal: Principal = Depends(WAIVE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CirculationService(db, principal, request).waive(issue_id, body.reason), message="Fine waived")


# ---- ILL ---------------------------------------------------------------------------------------------------------------------------
@router.get(
    "/library/ill-requests",
    summary="Inter-library loan requests",
    response_model=Envelope[list[LibraryIllResponse]],
    dependencies=ILL,
)
async def ill_list(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LibraryOpsService(db, principal, request).ill_list())


@router.post(
    "/library/ill-requests",
    summary="Request an inter-library loan",
    response_model=Envelope[LibraryIllResponse],
    dependencies=ILL,
)
async def ill_create(
    body: LibraryIllRequestIn,
    request: Request,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LibraryOpsService(db, principal, request).ill_create(body))


@router.post(
    "/library/ill-requests/{id}/{action}",
    summary="decide | receive | return",
    response_model=Envelope[LibraryIllResponse],
    dependencies=ILL,
)
async def ill_action(
    id: uuid.UUID,
    action: str,
    request: Request,
    body: LibraryIllDecision | None = None,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if action not in ("decide", "receive", "return"):
        from app.core.errors import APIError, ErrorCode

        raise APIError(404, ErrorCode.NOT_FOUND, "Unknown action")
    return ok(await LibraryOpsService(db, principal, request).ill_action(id, action, body))


# ---- stock verification / sync / reports / stats -------------------------------------------------------------------------------
@router.post(
    "/library/stock-verification",
    status_code=202,
    summary="Stock verification (job)",
    response_model=Envelope[LibraryJobAccepted],
    dependencies=CORE,
)
async def stock_verification(
    body: StockVerificationRequest,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return _accepted(
        await _job(db, principal, "library.stock_verification", body.model_dump(mode="json")),
        "Stock verification queued",
    )


@router.get(
    "/library/stock-verification/{job_id}",
    summary="Stock verification result",
    response_model=Envelope[dict[str, Any]],
    dependencies=CORE,
)
async def stock_verification_get(
    job_id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await _job_result(db, principal, job_id, "library.stock_verification"))


@router.post(
    "/library/sync/koha",
    status_code=202,
    summary="Koha / DSpace sync (job)",
    response_model=Envelope[LibraryJobAccepted],
    dependencies=KOHA,
)
async def koha_sync(
    body: KohaSyncRequest, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    return _accepted(await _job(db, principal, "library.koha_sync", body.model_dump(mode="json")), "Sync queued")


@router.get(
    "/library/sync/status", summary="Last sync jobs", response_model=Envelope[list[dict[str, Any]]], dependencies=KOHA
)
async def koha_status(
    request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    from sqlalchemy import select

    from app.models.platform import BackgroundJob

    rows = (
        (
            await db.execute(
                select(BackgroundJob)
                .where(
                    BackgroundJob.job_type == "library.koha_sync",
                    BackgroundJob.institution_id == principal.institution_id,
                )
                .order_by(BackgroundJob.created_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    return ok(
        [
            {"job_id": str(j.id), "status": j.status, "result": j.result, "created_at": j.created_at.isoformat()}
            for j in rows
        ]
    )


@router.get(
    "/library/reports/{kind}",
    status_code=202,
    summary="Report export (job → XLSX)",
    response_model=Envelope[LibraryJobAccepted],
    dependencies=CORE,
)
async def report(
    kind: str, request: Request, principal: Principal = Depends(REPORTS), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    if kind not in ("accession_register", "circulation", "overdue", "eresource_usage", "naac_4_2"):
        from app.core.errors import APIError, ErrorCode

        raise APIError(404, ErrorCode.NOT_FOUND, "Unknown report")
    return _accepted(await _job(db, principal, "library.reports_export", {"kind": kind}), "Report queued")


@router.get(
    "/library/stats",
    summary="Library dashboard counts",
    response_model=Envelope[LibraryStatsResponse],
    dependencies=CORE,
)
async def stats(
    request: Request, principal: Principal = Depends(READ_ALL), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LibraryOpsService(db, principal, request).stats())


async def _job_result(db: AsyncSession, principal: Principal, job_id: uuid.UUID, job_type: str) -> dict[str, Any]:
    from sqlalchemy import select

    from app.core.errors import APIError, ErrorCode
    from app.core.files import storage
    from app.models.platform import BackgroundJob

    j = (
        await db.execute(
            select(BackgroundJob).where(
                BackgroundJob.id == job_id,
                BackgroundJob.job_type == job_type,
                BackgroundJob.institution_id == principal.institution_id,
            )
        )
    ).scalar_one_or_none()
    if j is None:
        raise APIError(404, ErrorCode.NOT_FOUND, "Job not found")
    return {
        "job_id": str(j.id),
        "status": j.status,
        "result": j.result,
        "file_url": storage.signed_url(j.result_url) if j.result_url else None,
    }


# ---- OPAC (public) ------------------------------------------------------------------------------------------------------------
@public_router.get(
    "/opac/search",
    summary="Public catalogue search",
    response_model=Envelope[OpacSearchResponse],
    dependencies=[*OPAC, rate_limited("opac_search", limit=60, window=60)],
)
async def opac(
    institution: str | None = None,
    q: str | None = None,
    category: str | None = None,
    author: str | None = None,
    year: int | None = None,
    resource_type: str | None = None,
    language: str | None = None,
    available_only: bool = False,
    page: int = 1,
) -> dict[str, Any]:
    return ok(
        await opac_search(
            institution, q, category, author, year, resource_type, language, available_only, 30, (max(page, 1) - 1) * 30
        )
    )


@public_router.get(
    "/opac/new-arrivals",
    summary="New arrivals",
    response_model=Envelope[list[OpacResult]],
    dependencies=[*OPAC, rate_limited("opac_search", limit=60, window=60)],
)
async def opac_arrivals(institution: str | None = None) -> dict[str, Any]:
    return ok(await opac_new_arrivals(institution))


@public_router.get(
    "/opac/books/{id}",
    summary="Public book page",
    response_model=Envelope[OpacResult],
    dependencies=[*OPAC, rate_limited("opac_search", limit=60, window=60)],
)
async def opac_book_get(id: uuid.UUID, institution: str | None = None) -> dict[str, Any]:
    return ok(await opac_book(institution, id))
