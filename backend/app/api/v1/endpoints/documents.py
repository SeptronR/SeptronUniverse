"""Documents — Prompts/26 §26.8: templates {documents.templates}, render API, issued register + signed links
{documents.watermark_signed_links}, bulk {documents.bulk_generation}, serial registers {documents.serial_registers},
certificate requests {documents.certificate_requests}, stats and settings. Public verification lives in
``endpoints/verify.py``.
"""

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.features import feature_required
from app.core.idempotency import idempotency_key, store
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.documents import (
    CertReqCollected,
    CertReqCreate,
    CertReqDecision,
    CertReqGenerate,
    CertReqIssue,
    CertReqOut,
    CertReqTypeOut,
    DocBulkGenerateRequest,
    DocBulkJobOut,
    DocReconcileOut,
    DocReissueRequest,
    DocRenderRequest,
    DocRenderResult,
    DocRevokeRequest,
    DocSerialRegisterOut,
    DocSerialReserve,
    DocSerialRow,
    DocSerialVoid,
    DocSettingsOut,
    DocSignedLinkOut,
    DocSignedLinkRequest,
    DocTemplateIn,
    DocTemplateLint,
    DocTemplateOut,
    DocTemplatePreview,
    DocTemplatePublish,
    DocTemplateUpdate,
    DocTemplateUsage,
    DocumentStatsOut,
    DocVariablesCatalogue,
    IssuedDocumentOut,
)
from app.services.documents.bulk_service import BulkService
from app.services.documents.download_service import DownloadService
from app.services.documents.issued_service import IssuedService
from app.services.documents.registers_service import RegistersService
from app.services.documents.render_service import RenderService
from app.services.documents.request_service import RequestService
from app.services.documents.template_service import TemplateService
from app.utils.response import ok

router = APIRouter(tags=["documents"])

C, T = "certificates", "templates"
TPL_VIEW = any_permission_required((T, "view"), (T, "manage"), (C, "issue"), (C, "manage"))
TPL_MANAGE = any_permission_required((T, "manage"))
RENDER = any_permission_required((C, "issue"), (T, "render"), (C, "manage"))
DOC_VIEW = any_permission_required((C, "self"), (C, "view"), (C, "view_all"), (C, "issue"), (C, "manage"))
REGISTRAR = any_permission_required((C, "manage"))
ISSUE = any_permission_required((C, "issue"), (C, "manage"))
REG_VIEW = any_permission_required((C, "issue"), (C, "view_all"), (C, "manage"), (T, "manage"))
REG_MANAGE = any_permission_required((C, "issue"), (C, "manage"), (T, "manage"))
SELF = any_permission_required((C, "self"), (C, "manage"))
REQ_VIEW = any_permission_required(
    (C, "self"), (C, "view_all"), (C, "issue"), (C, "request_approve"), (C, "manage"), (C, "view")
)
DECIDE = any_permission_required((C, "request_approve"), (C, "manage"), (C, "view_all"))
STATS = any_permission_required((C, "view_all"), (C, "issue"), (C, "manage"))
SETTINGS = any_permission_required((T, "manage"), (C, "manage"))

TEMPLATES = [feature_required("documents.templates")]
BULK = [feature_required("documents.bulk_generation")]
SERIALS = [feature_required("documents.serial_registers")]
REQUESTS = [feature_required("documents.certificate_requests")]


def _vis(scopes: list[str], data: Any) -> dict[str, Any]:
    tabs = ["mine" if t == "self" else t for t in scopes]
    res = ok(data)
    res["meta"]["visibility"] = {"self": True, "scopes": tabs, "default": tabs[-1] if tabs else "mine"}
    return res


# ---- templates ----------------------------------------------------------------------------------------------------------
@router.get(
    "/documents/templates",
    summary="Templates (platform defaults + institution overrides, latest version)",
    response_model=Envelope[list[DocTemplateOut]],
    dependencies=TEMPLATES,
)
async def templates_list(
    request: Request,
    template_type: str | None = None,
    source: str | None = None,
    principal: Principal = Depends(TPL_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await TemplateService(db, principal, request).list_templates(template_type, source))


@router.get(
    "/documents/templates/variables/{template_type}",
    summary="Variables catalogue of a template type",
    response_model=Envelope[DocVariablesCatalogue],
    dependencies=TEMPLATES,
)
async def templates_variables(
    template_type: str, request: Request, principal: Principal = Depends(TPL_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(TemplateService(db, principal, request).catalogue(template_type))


@router.get(
    "/documents/templates/{id}", summary="Template", response_model=Envelope[DocTemplateOut], dependencies=TEMPLATES
)
async def templates_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(TPL_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await TemplateService(db, principal, request).get(id))


@router.post(
    "/documents/templates",
    status_code=201,
    summary="New template / clone (draft)",
    response_model=Envelope[DocTemplateOut],
    dependencies=TEMPLATES,
)
async def templates_create(
    body: DocTemplateIn,
    request: Request,
    principal: Principal = Depends(TPL_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await TemplateService(db, principal, request).create(body), message="Draft created")


@router.put(
    "/documents/templates/{id}",
    summary="Edit a template (a published version starts the next draft)",
    response_model=Envelope[DocTemplateOut],
    dependencies=TEMPLATES,
)
async def templates_update(
    id: uuid.UUID,
    body: DocTemplateUpdate,
    request: Request,
    principal: Principal = Depends(TPL_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await TemplateService(db, principal, request).update(id, body))


@router.post(
    "/documents/templates/{id}/publish",
    summary="Publish (lint errors → 422)",
    response_model=Envelope[DocTemplateOut],
    dependencies=TEMPLATES,
)
async def templates_publish(
    id: uuid.UUID,
    body: DocTemplatePublish,
    request: Request,
    principal: Principal = Depends(TPL_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await TemplateService(db, principal, request).publish(id, body.change_note), message="Published")


@router.get(
    "/documents/templates/{id}/versions",
    summary="Versions of the template family",
    response_model=Envelope[list[DocTemplateOut]],
    dependencies=TEMPLATES,
)
async def templates_versions(
    id: uuid.UUID, request: Request, principal: Principal = Depends(TPL_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await TemplateService(db, principal, request).versions(id))


@router.get(
    "/documents/templates/{id}/lint",
    summary="Lint (unknown variables, unsupported CSS)",
    response_model=Envelope[DocTemplateLint],
    dependencies=TEMPLATES,
)
async def templates_lint(
    id: uuid.UUID, request: Request, principal: Principal = Depends(TPL_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await TemplateService(db, principal, request).lint_template(id))


@router.post(
    "/documents/templates/{id}/preview", summary="Preview PDF / HTML (PREVIEW watermark)", dependencies=TEMPLATES
)
async def templates_preview(
    id: uuid.UUID,
    request: Request,
    body: DocTemplatePreview = Body(default_factory=DocTemplatePreview),
    principal: Principal = Depends(TPL_VIEW),
    db: AsyncSession = Depends(get_db),
) -> Response:
    data, media = await TemplateService(db, principal, request).preview(id, body)
    return Response(content=data, media_type=media, headers={"Content-Disposition": 'inline; filename="preview.pdf"'})


@router.get(
    "/documents/templates/{id}/usage",
    summary="Template usage",
    response_model=Envelope[DocTemplateUsage],
    dependencies=TEMPLATES,
)
async def templates_usage(
    id: uuid.UUID, request: Request, principal: Principal = Depends(TPL_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await TemplateService(db, principal, request).usage(id))


# ---- render -------------------------------------------------------------------------------------------------------------
@router.post(
    "/documents/render",
    status_code=201,
    summary="Render and register a document (Idempotency-Key)",
    response_model=Envelope[DocRenderResult],
    dependencies=TEMPLATES,
)
async def documents_render(
    body: DocRenderRequest,
    request: Request,
    key: str | None = Depends(idempotency_key),
    principal: Principal = Depends(RENDER),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = RenderService(db, principal, request)
    svc.require_writer()
    svc.require_type(body.template_type)
    res = await svc.render(
        body.template_type,
        body.entity_type,
        body.entity_id,
        template_id=body.template_id,
        register=body.register_,
        variables_override=body.variables_override,
        watermark=body.watermark,
        language=body.language,
        allow_multiple=body.allow_multiple,
        document_number=body.document_number,
    )
    out = ok(res, message="Existing document" if res.reused else "Issued")
    await store(request, out, db, 201)
    return out


# ---- issued register ----------------------------------------------------------------------------------------------------
@router.get(
    "/documents/issued",
    summary="Issued documents (ScopeTabs)",
    response_model=Envelope[list[IssuedDocumentOut]],
    dependencies=TEMPLATES,
)
async def issued_list(
    request: Request,
    template_type: str | None = None,
    person_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    revoked: bool | None = None,
    scope: str | None = None,
    q: str | None = None,
    limit: int = 200,
    offset: int = 0,
    principal: Principal = Depends(DOC_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = IssuedService(db, principal, request)
    rows = await svc.list_issued(
        template_type=template_type,
        person_id=person_id,
        entity_type=entity_type,
        date_from=date_from,
        date_to=date_to,
        revoked=revoked,
        scope=scope,
        q=q,
        limit=limit,
        offset=offset,
    )
    return _vis(svc.issued_scopes(), rows)


@router.get(
    "/documents/me", summary="My documents", response_model=Envelope[list[IssuedDocumentOut]], dependencies=TEMPLATES
)
async def documents_me(
    request: Request, principal: Principal = Depends(DOC_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await IssuedService(db, principal, request).list_issued(scope="self"))


@router.get(
    "/documents/wards",
    summary="Documents of my wards",
    response_model=Envelope[list[IssuedDocumentOut]],
    dependencies=TEMPLATES,
)
async def documents_wards(
    request: Request, principal: Principal = Depends(DOC_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await IssuedService(db, principal, request).list_issued(scope="wards"))


@router.get(
    "/documents/issued/{id}",
    summary="Issued document",
    response_model=Envelope[IssuedDocumentOut],
    dependencies=TEMPLATES,
)
async def issued_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(DOC_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await IssuedService(db, principal, request).get(id))


@router.post(
    "/documents/issued/{id}/revoke",
    summary="Revoke (registrar)",
    response_model=Envelope[IssuedDocumentOut],
    dependencies=TEMPLATES,
)
async def issued_revoke(
    id: uuid.UUID,
    body: DocRevokeRequest,
    request: Request,
    principal: Principal = Depends(REGISTRAR),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await RenderService(db, principal, request).revoke(id, body.reason)
    return ok(await IssuedService(db, principal, request).get(id), message="Revoked")


@router.post(
    "/documents/issued/{id}/reissue",
    summary="Reissue (revokes the old document; new one supersedes it)",
    response_model=Envelope[DocRenderResult],
    dependencies=TEMPLATES,
)
async def issued_reissue(
    id: uuid.UUID,
    body: DocReissueRequest,
    request: Request,
    principal: Principal = Depends(REGISTRAR),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await RenderService(db, principal, request).reissue(id, body.reason, body.variables_override),
        message="Reissued",
    )


@router.post(
    "/documents/issued/{id}/signed-link",
    summary="Time-limited signed download link (watermarked)",
    response_model=Envelope[DocSignedLinkOut],
    dependencies=TEMPLATES,
)
async def issued_signed_link(
    id: uuid.UUID,
    request: Request,
    body: DocSignedLinkRequest = Body(default_factory=DocSignedLinkRequest),
    principal: Principal = Depends(DOC_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DownloadService(db, principal, request).signed_link(id, body))


@router.get(
    "/documents/issued/{id}/signed-link",
    summary="Signed link with defaults (15 min)",
    response_model=Envelope[DocSignedLinkOut],
    dependencies=TEMPLATES,
)
async def issued_signed_link_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(DOC_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DownloadService(db, principal, request).signed_link(id, DocSignedLinkRequest()))


@router.get(
    "/documents/download/{signed}", summary="Download through a signed link (bound to the user)", dependencies=TEMPLATES
)
async def documents_download(
    signed: str, request: Request, principal: Principal = Depends(DOC_VIEW), db: AsyncSession = Depends(get_db)
) -> Response:
    data, name = await DownloadService(db, principal, request).download(signed)
    return Response(
        content=data, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"'}
    )


# ---- bulk -----------------------------------------------------------------------------------------------------------------
@router.post("/documents/bulk", status_code=202, summary="Bulk generation job", dependencies=BULK)
async def bulk_create(
    body: DocBulkGenerateRequest,
    request: Request,
    principal: Principal = Depends(ISSUE),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    j = await BulkService(db, principal, request).queue(body)
    return JSONResponse(status_code=202, content=ok(j.model_dump(mode="json"), message="Queued"))


@router.get(
    "/documents/bulk/{job_id}",
    summary="Bulk job progress / report",
    response_model=Envelope[DocBulkJobOut],
    dependencies=BULK,
)
async def bulk_get(
    job_id: uuid.UUID, request: Request, principal: Principal = Depends(ISSUE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await BulkService(db, principal, request).status(job_id))


@router.get("/documents/bulk/{job_id}/zip", summary="ZIP of the job's PDFs (signed redirect)", dependencies=BULK)
async def bulk_zip(
    job_id: uuid.UUID, request: Request, principal: Principal = Depends(ISSUE), db: AsyncSession = Depends(get_db)
) -> RedirectResponse:
    return RedirectResponse(await BulkService(db, principal, request).zip_url(job_id), status_code=307)


# ---- serial registers ----------------------------------------------------------------------------------------------------
@router.get(
    "/documents/registers",
    summary="Serial registers",
    response_model=Envelope[list[DocSerialRegisterOut]],
    dependencies=SERIALS,
)
async def registers_list(
    request: Request, principal: Principal = Depends(REG_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RegistersService(db, principal, request).registers())


@router.get(
    "/documents/registers/{register}",
    summary="Serials of a register",
    response_model=Envelope[list[DocSerialRow]],
    dependencies=SERIALS,
)
async def registers_rows(
    register: str,
    request: Request,
    status: str | None = None,
    principal: Principal = Depends(REG_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RegistersService(db, principal, request).rows(register, status))


@router.post(
    "/documents/registers/{register}/reserve",
    summary="Reserve serials",
    response_model=Envelope[list[DocSerialRow]],
    dependencies=SERIALS,
)
async def registers_reserve(
    register: str,
    body: DocSerialReserve,
    request: Request,
    principal: Principal = Depends(REG_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RegistersService(db, principal, request).reserve(register, body.count), message="Reserved")


@router.post(
    "/documents/registers/{register}/void",
    summary="Void a serial (reason)",
    response_model=Envelope[DocSerialRow],
    dependencies=SERIALS,
)
async def registers_void(
    register: str,
    body: DocSerialVoid,
    request: Request,
    principal: Principal = Depends(REG_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await RegistersService(db, principal, request).void(register, body.serial_no, body.reason), message="Voided"
    )


@router.put(
    "/documents/registers/{register}/book",
    summary="Physical book mapping (book no. / pages)",
    response_model=Envelope[dict[str, Any]],
    dependencies=SERIALS,
)
async def registers_book(
    register: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    principal: Principal = Depends(REG_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RegistersService(db, principal, request).set_book(register, body))


@router.get(
    "/documents/registers/{register}/reconcile",
    summary="Reconciliation (issued vs serials)",
    response_model=Envelope[DocReconcileOut],
    dependencies=SERIALS,
)
async def registers_reconcile(
    register: str, request: Request, principal: Principal = Depends(REG_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RegistersService(db, principal, request).reconcile(register))


@router.get("/documents/registers/{register}/export", status_code=202, summary="Export job (CSV)", dependencies=SERIALS)
async def registers_export(
    register: str, request: Request, principal: Principal = Depends(REG_VIEW), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    from app.core.jobs import enqueue

    await RegistersService(db, principal, request).rows(register)
    j = await enqueue(db, principal, "documents.registers_export", {"register": register}, queue="documents")
    return JSONResponse(status_code=202, content=ok({"job_id": str(j.id)}, message="Queued"))


# ---- stats / settings -----------------------------------------------------------------------------------------------------
@router.get(
    "/documents/stats", summary="Document statistics", response_model=Envelope[DocumentStatsOut], dependencies=TEMPLATES
)
async def documents_stats(
    request: Request, principal: Principal = Depends(STATS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await IssuedService(db, principal, request).stats())


@router.get(
    "/documents/settings", summary="Document settings", response_model=Envelope[DocSettingsOut], dependencies=TEMPLATES
)
async def documents_settings(
    request: Request, principal: Principal = Depends(SETTINGS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    from app.enums.documents import DEFAULT_SIGNATORIES

    svc = RequestService(db, principal, request)
    return ok(
        DocSettingsOut(
            request_rules=await svc.rules(),
            signatories=await svc.doc_setting("signatories", DEFAULT_SIGNATORIES),
            watermark=await svc.doc_setting("watermark", {}),
            verify_shows_pdf=bool(await svc.doc_setting("verify_shows_pdf", False)),
            allow_parent_requests=bool(await svc.doc_setting("allow_parent_requests", False)),
            college_overrides=bool(await svc.doc_setting("college_overrides", False)),
            signed_link_ttl_minutes=int(await svc.doc_setting("signed_link_ttl_minutes", 15)),
            preview_retention_days=int(await svc.doc_setting("preview_retention_days", 1)),
        )
    )


# ---- certificate requests ----------------------------------------------------------------------------------------------
@router.get(
    "/certificate-requests/types",
    summary="Requestable types with fees (for the caller)",
    response_model=Envelope[list[CertReqTypeOut]],
    dependencies=REQUESTS,
)
async def requests_types(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RequestService(db, principal, request).types())


@router.post(
    "/certificate-requests",
    status_code=201,
    summary="Request a certificate (Idempotency-Key)",
    response_model=Envelope[CertReqOut],
    dependencies=REQUESTS,
)
async def requests_create(
    body: CertReqCreate,
    request: Request,
    key: str | None = Depends(idempotency_key),
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    res = ok(await RequestService(db, principal, request).create(body), message="Requested")
    await store(request, res, db, 201)
    return res


@router.get(
    "/certificate-requests/me", summary="My requests", response_model=Envelope[list[CertReqOut]], dependencies=REQUESTS
)
async def requests_me(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RequestService(db, principal, request).mine())


@router.get(
    "/certificate-requests/wards",
    summary="Ward requests",
    response_model=Envelope[list[CertReqOut]],
    dependencies=REQUESTS,
)
async def requests_wards(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RequestService(db, principal, request).wards())


@router.get(
    "/certificate-requests",
    summary="Request queue (ScopeTabs)",
    response_model=Envelope[list[CertReqOut]],
    dependencies=REQUESTS,
)
async def requests_list(
    request: Request,
    status: str | None = None,
    template_type: str | None = None,
    person_type: str | None = None,
    department_id: uuid.UUID | None = None,
    scope: str | None = None,
    principal: Principal = Depends(REQ_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = RequestService(db, principal, request)
    rows = await svc.list_requests(status, template_type, person_type, department_id, scope)
    return _vis(svc.request_scopes(), rows)


@router.get("/certificate-requests/{id}", summary="Request", response_model=Envelope[CertReqOut], dependencies=REQUESTS)
async def requests_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(REQ_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RequestService(db, principal, request).get(id))


@router.delete(
    "/certificate-requests/{id}",
    summary="Cancel before approval",
    response_model=Envelope[CertReqOut],
    dependencies=REQUESTS,
)
async def requests_cancel(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RequestService(db, principal, request).cancel(id), message="Cancelled")


@router.post(
    "/certificate-requests/{id}/decide",
    summary="Approve / reject / recommend",
    response_model=Envelope[CertReqOut],
    dependencies=REQUESTS,
)
async def requests_decide(
    id: uuid.UUID,
    body: CertReqDecision,
    request: Request,
    principal: Principal = Depends(DECIDE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RequestService(db, principal, request).decide(id, body))


@router.post(
    "/certificate-requests/{id}/generate",
    summary="Generate the document",
    response_model=Envelope[CertReqOut],
    dependencies=REQUESTS,
)
async def requests_generate(
    id: uuid.UUID,
    request: Request,
    body: CertReqGenerate = Body(default_factory=CertReqGenerate),
    principal: Principal = Depends(ISSUE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RequestService(db, principal, request).generate(id, body), message="Generated")


@router.post(
    "/certificate-requests/{id}/issue",
    summary="Issue (digital / pickup notice / post)",
    response_model=Envelope[CertReqOut],
    dependencies=REQUESTS,
)
async def requests_issue(
    id: uuid.UUID,
    request: Request,
    body: CertReqIssue = Body(default_factory=CertReqIssue),
    principal: Principal = Depends(ISSUE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RequestService(db, principal, request).issue(id, body))


@router.post(
    "/certificate-requests/{id}/collected",
    summary="Pickup collected (signature)",
    response_model=Envelope[CertReqOut],
    dependencies=REQUESTS,
)
async def requests_collected(
    id: uuid.UUID,
    body: CertReqCollected,
    request: Request,
    principal: Principal = Depends(ISSUE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RequestService(db, principal, request).collected(id, body), message="Collected")
