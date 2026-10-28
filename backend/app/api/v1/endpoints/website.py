"""Website administration — Prompts/40 §40.8 (``/website/*`` {website.core}; domains {website.custom_domain};
catalogue settings {website.course_catalog}; enquiries {website.enquiry}) and the platform marketing editor
(``/platform/marketing`` — super admin). The route dependency admits any website / CRM reader; the services apply
``manage`` vs ``publish`` and the college / department section scopes."""

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_audit
from app.core.authz.dependencies import Principal, any_permission_required, platform_permission
from app.core.features import feature_required
from app.db.session import get_db, get_platform_db
from app.schemas.common import Envelope
from app.schemas.website import (
    AlbumIn,
    AlbumOut,
    BulkReport,
    CatalogueSettingsIO,
    ContentItemIn,
    ContentItemOut,
    DisclosureSettingsIO,
    DomainIn,
    DomainOut,
    DomainVerifyResult,
    EnquiryStatusChange,
    EventMirrorRequest,
    FacultyDirectorySettingsIO,
    ImageBulkUpload,
    ImageIn,
    ImageOut,
    MarketingOut,
    MarketingSiteIO,
    NoticeBulkAction,
    NoticeIn,
    NoticeOut,
    SiteAnalyticsOut,
    SiteConfigIn,
    SiteConfigOut,
    SitePreviewToken,
    SitePublishRequest,
    SiteVersionOut,
    WebsiteEnquiryOut,
    WebsiteEventIn,
    WebsiteEventOut,
)
from app.services.website import marketing_service
from app.services.website.catalogue_service import CatalogueService
from app.services.website.content_service import ContentService, GalleryService, NoticeService, WebsiteEventService
from app.services.website.domain_service import DomainService
from app.services.website.enquiry_service import EnquiryService
from app.services.website.settings_admin import WebsiteSettingsService
from app.services.website.site_service import SiteService
from app.utils.response import ok

router = APIRouter(prefix="/website", tags=["website"])
marketing_router = APIRouter(prefix="/platform/marketing", tags=["website"])

READ = any_permission_required(("website", "view"), ("website", "update"), ("website", "manage"))
WRITE = any_permission_required(
    ("website", "create"), ("website", "update"), ("website", "manage"), ("website", "publish")
)
PUBLISH = any_permission_required(("website", "publish"))
MANAGE = any_permission_required(("website", "manage"))
CRM = any_permission_required(("website", "view"), ("admissions", "create"))
CATALOGUE = any_permission_required(("website", "manage"), ("academics", "manage"), ("website", "view"))
DISCLOSE = any_permission_required(("website", "manage"), ("accreditation", "manage"), ("website", "view"))
DOMAINS = [feature_required("website.custom_domain")]
CAT = [feature_required("website.course_catalog")]
ENQ = [feature_required("website.enquiry")]


# ---- config ---------------------------------------------------------------------------------------------------------
@router.get(
    "/config", summary="Site config (draft when unpublished changes exist)", response_model=Envelope[SiteConfigOut]
)
async def get_config(
    request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SiteService(db, principal, request).get())


@router.put("/config", summary="Save the draft", response_model=Envelope[SiteConfigOut])
async def put_config(
    body: SiteConfigIn, request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SiteService(db, principal, request).save_draft(body), message="Draft saved")


@router.post("/config/publish", summary="Publish the draft", response_model=Envelope[SiteConfigOut])
async def publish_config(
    body: SitePublishRequest,
    request: Request,
    principal: Principal = Depends(PUBLISH),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SiteService(db, principal, request).publish(body.notes), message="Published")


@router.post(
    "/config/rollback/{version}", summary="Republish an earlier version", response_model=Envelope[SiteConfigOut]
)
async def rollback_config(
    version: int, request: Request, principal: Principal = Depends(PUBLISH), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SiteService(db, principal, request).rollback(version), message="Rolled back")


@router.get("/config/versions", summary="Published versions", response_model=Envelope[list[SiteVersionOut]])
async def config_versions(
    request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SiteService(db, principal, request).versions())


@router.post(
    "/config/preview-token", summary="Signed preview link of the draft (2 h)", response_model=Envelope[SitePreviewToken]
)
async def preview_token(
    request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    from sqlalchemy import text

    slug = (
        await db.execute(text("SELECT slug FROM institutions WHERE id = :i"), {"i": principal.institution_id})
    ).scalar_one()
    return ok(await SiteService(db, principal, request).preview_token(slug))


# ---- content --------------------------------------------------------------------------------------------------------
@router.get("/content", summary="Content items (scoped to my sections)", response_model=Envelope[list[ContentItemOut]])
async def content_list(
    request: Request,
    section: str | None = Query(None, max_length=60),
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ContentService(db, principal, request).list(section))


@router.post(
    "/content", status_code=201, summary="Create a content item (sanitised)", response_model=Envelope[ContentItemOut]
)
async def content_create(
    body: ContentItemIn, request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ContentService(db, principal, request).create(body), message="Created")


@router.get("/content/{id}", summary="Content item", response_model=Envelope[ContentItemOut])
async def content_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    from app.schemas.website import ContentItemOut as Out

    return ok(Out.model_validate(await ContentService(db, principal, request)._get(id)))


@router.put("/content/{id}", summary="Update a content item", response_model=Envelope[ContentItemOut])
async def content_update(
    id: uuid.UUID,
    body: ContentItemIn,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ContentService(db, principal, request).update(id, body), message="Saved")


@router.delete("/content/{id}", status_code=204, summary="Delete a content item")
async def content_delete(
    id: uuid.UUID, request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_db)
) -> Response:
    await ContentService(db, principal, request).delete(id)
    return Response(status_code=204)


@router.post("/content/{id}/publish", summary="Publish a content item", response_model=Envelope[ContentItemOut])
async def content_publish(
    id: uuid.UUID, request: Request, principal: Principal = Depends(PUBLISH), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ContentService(db, principal, request).set_published(id, True))


@router.post("/content/{id}/unpublish", summary="Unpublish a content item", response_model=Envelope[ContentItemOut])
async def content_unpublish(
    id: uuid.UUID, request: Request, principal: Principal = Depends(PUBLISH), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ContentService(db, principal, request).set_published(id, False))


# ---- notices --------------------------------------------------------------------------------------------------------
@router.get("/notices", summary="Notices", response_model=Envelope[list[NoticeOut]])
async def notices_list(
    request: Request,
    category: str | None = Query(None, max_length=40),
    state: str | None = Query(None, pattern="^(draft|scheduled|live|expired)$"),
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await NoticeService(db, principal, request).list(category, state))


@router.post("/notices", status_code=201, summary="Create a notice", response_model=Envelope[NoticeOut])
async def notices_create(
    body: NoticeIn, request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await NoticeService(db, principal, request).create(body), message="Created")


@router.post("/notices/bulk", summary="Bulk publish / unpublish / expire / delete", response_model=Envelope[BulkReport])
async def notices_bulk(
    body: NoticeBulkAction, request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await NoticeService(db, principal, request).bulk(body))


@router.get("/notices/{id}", summary="Notice", response_model=Envelope[NoticeOut])
async def notices_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    svc = NoticeService(db, principal, request)
    return ok(await svc._out(await svc._get(id)))


@router.put("/notices/{id}", summary="Update a notice", response_model=Envelope[NoticeOut])
async def notices_update(
    id: uuid.UUID,
    body: NoticeIn,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await NoticeService(db, principal, request).update(id, body), message="Saved")


@router.delete("/notices/{id}", status_code=204, summary="Delete a notice")
async def notices_delete(
    id: uuid.UUID, request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_db)
) -> Response:
    await NoticeService(db, principal, request).delete(id)
    return Response(status_code=204)


@router.post(
    "/notices/{id}/announce",
    summary="Also announce to students / staff (Phase 24)",
    response_model=Envelope[dict[str, Any]],
)
async def notices_announce(
    id: uuid.UUID, request: Request, principal: Principal = Depends(PUBLISH), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await NoticeService(db, principal, request).announce(id), message="Announced")


# ---- events ---------------------------------------------------------------------------------------------------------
@router.get("/events", summary="Website events", response_model=Envelope[list[WebsiteEventOut]])
async def events_list(
    request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await WebsiteEventService(db, principal, request).list())


@router.post("/events", status_code=201, summary="Create a manual event", response_model=Envelope[WebsiteEventOut])
async def events_create(
    body: WebsiteEventIn, request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await WebsiteEventService(db, principal, request).create(body), message="Created")


@router.post("/events/mirror", summary="Mirror Phase 25 events", response_model=Envelope[list[WebsiteEventOut]])
async def events_mirror(
    body: EventMirrorRequest,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await WebsiteEventService(db, principal, request).mirror(body.event_ids, body.publish), message="Mirrored"
    )


@router.put("/events/{id}", summary="Update a website event", response_model=Envelope[WebsiteEventOut])
async def events_update(
    id: uuid.UUID,
    body: WebsiteEventIn,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await WebsiteEventService(db, principal, request).update(id, body))


@router.delete("/events/{id}", status_code=204, summary="Delete a website event")
async def events_delete(
    id: uuid.UUID, request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_db)
) -> Response:
    await WebsiteEventService(db, principal, request).delete(id)
    return Response(status_code=204)


# ---- gallery --------------------------------------------------------------------------------------------------------
@router.get("/gallery/albums", summary="Albums (with images)", response_model=Envelope[list[AlbumOut]])
async def albums(
    request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await GalleryService(db, principal, request).albums(with_images=True))


@router.post("/gallery/albums", status_code=201, summary="Create an album", response_model=Envelope[AlbumOut])
async def album_create(
    body: AlbumIn, request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await GalleryService(db, principal, request).create_album(body))


@router.put("/gallery/albums/{id}", summary="Update an album", response_model=Envelope[AlbumOut])
async def album_update(
    id: uuid.UUID,
    body: AlbumIn,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await GalleryService(db, principal, request).update_album(id, body))


@router.delete("/gallery/albums/{id}", status_code=204, summary="Delete an album")
async def album_delete(
    id: uuid.UUID, request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_db)
) -> Response:
    await GalleryService(db, principal, request).delete_album(id)
    return Response(status_code=204)


@router.post("/gallery/albums/{id}/images", status_code=201, summary="Add an image", response_model=Envelope[ImageOut])
async def image_add(
    id: uuid.UUID,
    body: ImageIn,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await GalleryService(db, principal, request).add_image(id, body))


@router.post(
    "/gallery/albums/{id}/bulk-upload", summary="Bulk upload a zip (job)", response_model=Envelope[dict[str, Any]]
)
async def image_bulk(
    id: uuid.UUID,
    body: ImageBulkUpload,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await GalleryService(db, principal, request).bulk_upload(id, body.zip_url), message="Upload queued")


@router.put("/gallery/images/{id}", summary="Update an image", response_model=Envelope[ImageOut])
async def image_update(
    id: uuid.UUID,
    body: ImageIn,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await GalleryService(db, principal, request).update_image(id, body))


@router.delete("/gallery/images/{id}", status_code=204, summary="Delete an image")
async def image_delete(
    id: uuid.UUID, request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_db)
) -> Response:
    await GalleryService(db, principal, request).delete_image(id)
    return Response(status_code=204)


# ---- enquiries ------------------------------------------------------------------------------------------------------
@router.get(
    "/enquiries",
    summary="Website enquiries (masked without admissions:view_pii)",
    dependencies=ENQ,
    response_model=Envelope[list[WebsiteEnquiryOut]],
)
async def enquiries(
    request: Request,
    status: str | None = Query(None, pattern="^(new|contacted|converted|spam|closed)$"),
    q: str | None = Query(None, max_length=120),
    principal: Principal = Depends(CRM),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EnquiryService(db, principal, request).list(status, q))


@router.put(
    "/enquiries/{id}/status",
    summary="Change an enquiry's status",
    dependencies=ENQ,
    response_model=Envelope[WebsiteEnquiryOut],
)
async def enquiry_status(
    id: uuid.UUID,
    body: EnquiryStatusChange,
    request: Request,
    principal: Principal = Depends(CRM),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EnquiryService(db, principal, request).set_status(id, body.status))


@router.post(
    "/enquiries/{id}/link-crm",
    summary="Link to the Phase 08 CRM",
    dependencies=ENQ,
    response_model=Envelope[WebsiteEnquiryOut],
)
async def enquiry_link(
    id: uuid.UUID, request: Request, principal: Principal = Depends(CRM), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await EnquiryService(db, principal, request).link_crm(id))


@router.post(
    "/enquiries/export",
    summary="Export enquiries (xlsx job)",
    dependencies=ENQ,
    response_model=Envelope[dict[str, Any]],
)
async def enquiry_export(
    request: Request, principal: Principal = Depends(CRM), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await EnquiryService(db, principal, request).export(), message="Export queued")


# ---- catalogue / disclosures / directory ----------------------------------------------------------------------------
@router.get(
    "/catalogue/settings",
    summary="Catalogue visibility settings",
    dependencies=CAT,
    response_model=Envelope[CatalogueSettingsIO],
)
async def catalogue_settings(
    request: Request, principal: Principal = Depends(CATALOGUE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CatalogueService(db, principal, request).settings_io())


@router.put(
    "/catalogue/settings",
    summary="Save catalogue visibility",
    dependencies=CAT,
    response_model=Envelope[CatalogueSettingsIO],
)
async def catalogue_settings_put(
    body: CatalogueSettingsIO,
    request: Request,
    principal: Principal = Depends(CATALOGUE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CatalogueService(db, principal, request).save_settings(body), message="Saved")


@router.get(
    "/catalogue/preview",
    summary="Catalogue as the public sees it",
    dependencies=CAT,
    response_model=Envelope[list[dict[str, Any]]],
)
async def catalogue_preview(
    request: Request, principal: Principal = Depends(CATALOGUE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CatalogueService(db, principal, request).list_programmes(None, None, None, None))


@router.get("/disclosures", summary="Disclosure items", response_model=Envelope[DisclosureSettingsIO])
async def disclosures_get(
    request: Request, principal: Principal = Depends(DISCLOSE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await WebsiteSettingsService(db, principal, request).disclosures())


@router.put("/disclosures", summary="Save disclosure items", response_model=Envelope[DisclosureSettingsIO])
async def disclosures_put(
    body: DisclosureSettingsIO,
    request: Request,
    principal: Principal = Depends(DISCLOSE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await WebsiteSettingsService(db, principal, request).save_disclosures(body), message="Saved")


@router.get(
    "/faculty-directory/settings",
    summary="Faculty directory fields / opt-outs",
    response_model=Envelope[FacultyDirectorySettingsIO],
)
async def directory_get(
    request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await WebsiteSettingsService(db, principal, request).directory())


@router.put(
    "/faculty-directory/settings",
    summary="Save the faculty directory settings",
    response_model=Envelope[FacultyDirectorySettingsIO],
)
async def directory_put(
    body: FacultyDirectorySettingsIO,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await WebsiteSettingsService(db, principal, request).save_directory(body), message="Saved")


# ---- domains --------------------------------------------------------------------------------------------------------
@router.get("/domains", summary="Custom domains", dependencies=DOMAINS, response_model=Envelope[list[DomainOut]])
async def domains(
    request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DomainService(db, principal, request).list())


@router.post(
    "/domains", status_code=201, summary="Add a custom domain", dependencies=DOMAINS, response_model=Envelope[DomainOut]
)
async def domain_add(
    body: DomainIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DomainService(db, principal, request).add(body), message="Add the DNS records shown")


@router.post(
    "/domains/{id}/verify",
    summary="Check the TXT record",
    dependencies=DOMAINS,
    response_model=Envelope[DomainVerifyResult],
)
async def domain_verify(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DomainService(db, principal, request).verify(id))


@router.post(
    "/domains/{id}/make-primary",
    summary="Make the primary domain",
    dependencies=DOMAINS,
    response_model=Envelope[DomainOut],
)
async def domain_primary(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DomainService(db, principal, request).make_primary(id))


@router.delete("/domains/{id}", status_code=204, summary="Remove a domain", dependencies=DOMAINS)
async def domain_delete(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> Response:
    await DomainService(db, principal, request).remove(id)
    return Response(status_code=204)


@router.get(
    "/analytics", summary="Page views, visitors, enquiry conversions", response_model=Envelope[SiteAnalyticsOut]
)
async def analytics(
    request: Request,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SiteService(db, principal, request).analytics(date_from, date_to))


# ---- platform marketing site ----------------------------------------------------------------------------------------
@marketing_router.get("", summary="Marketing site content (draft)", response_model=Envelope[MarketingOut])
async def marketing_get(
    principal: Principal = Depends(platform_permission("platform", "manage", support=False)),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await marketing_service.admin_get(db))


@marketing_router.put("", summary="Save the marketing draft", response_model=Envelope[MarketingOut])
async def marketing_put(
    body: MarketingSiteIO,
    principal: Principal = Depends(platform_permission("platform", "manage", support=False)),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    out = await marketing_service.save_draft(db, body, principal)
    await log_audit(
        db,
        principal=principal,
        module="platform",
        action="marketing_save",
        record_type="marketing_site",
        record_id=None,
    )
    return ok(out, message="Draft saved")


@marketing_router.post("/publish", summary="Publish the marketing site", response_model=Envelope[MarketingOut])
async def marketing_publish(
    principal: Principal = Depends(platform_permission("platform", "manage", support=False)),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    out = await marketing_service.publish(db, principal)
    await log_audit(
        db,
        principal=principal,
        module="platform",
        action="marketing_publish",
        record_type="marketing_site",
        record_id=None,
    )
    return ok(out, message="Published")
