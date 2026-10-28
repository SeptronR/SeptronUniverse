"""Platform console — Prompts/38 §38.8 (``/platform/*`` super admin & support agent routes).

Every route runs on the platform session (``get_platform_db``, BYPASSRLS) behind ``platform_permission`` — the super
admin, or a support agent holding the action (read-only routes; writes are super admin only in the services).
Tenant institution admins never pass even though they hold ``institutions:manage`` / ``support:manage`` in their
own tenant. ``/platform/announcements/active`` and ``…/dismiss`` serve every signed-in user (tenant session).
"""

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, authenticated, platform_permission
from app.db.session import get_db, get_platform_db
from app.schemas.common import Envelope
from app.schemas.saas import (
    AnnouncementIn,
    AnnouncementOut,
    ChangePreviewOut,
    ConnectionDisable,
    DemoRequestOut,
    DemoRequestUpdate,
    FeaturePreviewOut,
    FeedbackAdminOut,
    FeedbackTriage,
    GeneratePeriodRequest,
    HealthRetryRequest,
    HealthRow,
    ImpersonationForceStop,
    ImpersonationOut,
    InstitutionAdminOut,
    InstitutionStatusChange,
    InvoiceOut,
    InvoicePayOut,
    InvoicePayRequest,
    JobAccepted,
    OutageOut,
    PlanIn,
    PlanOut,
    PlanUpdate,
    PlatformAuditRow,
    PlatformDashboardOut,
    PlatformSettingOut,
    PlatformSettingsIn,
    RegistrationAction,
    RegistrationOut,
    SubscriptionAssign,
    SubscriptionCancel,
    SubscriptionChange,
    SubscriptionOut,
    SubscriptionRenew,
    TenantErasureRequest,
    TenantExportRequest,
    TenantResetRequest,
    TicketOut,
    UsageCapsIn,
    UsageOut,
)
from app.services.saas.announcement_service import AnnouncementService
from app.services.saas.dashboard_service import PlatformDashboardService
from app.services.saas.health_service import HealthService
from app.services.saas.impersonation_service import ImpersonationService
from app.services.saas.institution_admin_service import InstitutionAdminService
from app.services.saas.platform_settings_service import PlatformSettingsService
from app.services.saas.registration_service import RegistrationService
from app.services.saas.subscription_service import SubscriptionService
from app.services.saas.support_service import SupportService
from app.services.saas.usage_service import UsageService
from app.utils.response import ok

router = APIRouter(prefix="/platform", tags=["platform-console"])
VIEW = platform_permission("platform", "view")
BILLING = platform_permission("platform", "billing")
MANAGE = platform_permission("platform", "manage", support=False)
SUPPORT = platform_permission("platform", "support")
INSTITUTIONS = platform_permission("institutions", "manage", support=False)


# ---- dashboard / alerts / audit -------------------------------------------------------------------------------------
@router.get(
    "/dashboard",
    summary="Platform KPIs (tenants, MRR / ARR, usage, health, tickets, chain integrity)",
    response_model=Envelope[PlatformDashboardOut],
)
async def dashboard(
    request: Request,
    refresh: bool = Query(default=False),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await PlatformDashboardService(db, principal, request).dashboard(refresh))


@router.get(
    "/alerts",
    summary="Platform alerts (audit chain breaks, anomalies, dead letters)",
    response_model=Envelope[list[dict[str, Any]]],
)
async def alerts(
    open_only: bool = Query(default=True),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await PlatformDashboardService(db, principal).list_alerts(open_only))


@router.post("/alerts/{alert_id}/resolve", summary="Resolve a platform alert", response_model=Envelope[dict[str, Any]])
async def resolve_alert(
    alert_id: str,
    request: Request,
    note: str | None = Query(default=None, max_length=500),
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(
        await PlatformDashboardService(db, principal, request).resolve_alert(alert_id, note), message="Alert resolved"
    )


@router.get(
    "/audit",
    summary="Platform audit (platform actions, support reads, impersonated writes)",
    response_model=Envelope[list[PlatformAuditRow]],
)
async def platform_audit(
    institution_id: uuid.UUID | None = None,
    actor: uuid.UUID | None = None,
    module: str | None = Query(default=None, max_length=60),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(
        await PlatformDashboardService(db, principal).audit_rows(
            institution_id, actor, date_from, date_to, module=module
        )
    )


# ---- institutions (Phase 03 routes extended) ------------------------------------------------------------------------
@router.get(
    "/onboarding/preview",
    summary="Features a template + plan would enable (diff vs plan)",
    response_model=Envelope[FeaturePreviewOut],
)
async def onboarding_preview(
    template: str = Query(pattern="^(university|autonomous|affiliated|standalone)$"),
    plan_code: str = Query(max_length=30),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await InstitutionAdminService(db, principal).feature_preview(template, plan_code))


@router.post(
    "/institutions/{id}/status",
    summary="Activate / suspend / archive / unarchive (reason required)",
    response_model=Envelope[InstitutionAdminOut],
)
async def institution_status(
    id: uuid.UUID,
    body: InstitutionStatusChange,
    request: Request,
    principal: Principal = Depends(INSTITUTIONS),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(
        await InstitutionAdminService(db, principal, request).change_status(id, body),
        message=f"Institution {body.action}d",
    )


@router.post(
    "/institutions/{id}/export",
    status_code=202,
    summary="Tenant export (job; encrypted zip, password e-mailed separately)",
    response_model=Envelope[JobAccepted],
)
async def institution_export(
    id: uuid.UUID,
    body: TenantExportRequest,
    request: Request,
    principal: Principal = Depends(INSTITUTIONS),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await InstitutionAdminService(db, principal, request).request_export(id, body), message="Export queued")


@router.post(
    "/institutions/{id}/reset",
    status_code=202,
    summary="Reset a demo tenant (job; typed slug)",
    response_model=Envelope[JobAccepted],
)
async def institution_reset(
    id: uuid.UUID,
    body: TenantResetRequest,
    request: Request,
    principal: Principal = Depends(INSTITUTIONS),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await InstitutionAdminService(db, principal, request).request_reset(id, body), message="Reset queued")


@router.post(
    "/institutions/{id}/erase",
    status_code=202,
    summary="Erase a tenant (job; typed slug; four-eyes)",
    response_model=Envelope[JobAccepted],
)
async def institution_erase(
    id: uuid.UUID,
    body: TenantErasureRequest,
    request: Request,
    principal: Principal = Depends(INSTITUTIONS),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    out = await InstitutionAdminService(db, principal, request).request_erase(id, body)
    return ok(out, message="Awaiting a second super admin" if out.status == "pending_approval" else "Erasure queued")


@router.put(
    "/institutions/{id}/usage-caps",
    summary="Per-tenant usage caps (API calls / day, messages, AI tokens, storage)",
    response_model=Envelope[dict[str, Any]],
)
async def usage_caps(
    id: uuid.UUID,
    body: UsageCapsIn,
    request: Request,
    principal: Principal = Depends(BILLING),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await UsageService(db, principal, request).set_caps(id, body), message="Caps saved")


# ---- plans --------------------------------------------------------------------------------------------------------
@router.get("/plans", summary="Subscription plans", response_model=Envelope[list[PlanOut]])
async def plans(principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_platform_db)) -> dict[str, Any]:
    return ok(await SubscriptionService(db, principal).plans())


@router.post("/plans", status_code=201, summary="Create a plan", response_model=Envelope[PlanOut])
async def create_plan(
    body: PlanIn, request: Request, principal: Principal = Depends(BILLING), db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    return ok(await SubscriptionService(db, principal, request).create_plan(body), message="Plan created")


@router.get("/plans/{id}", summary="Plan detail", response_model=Envelope[PlanOut])
async def get_plan(
    id: uuid.UUID, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    return ok(await SubscriptionService(db, principal).plan(id))


@router.put(
    "/plans/{id}",
    summary="Update a plan (features validated against the registry tiers)",
    response_model=Envelope[PlanOut],
)
async def update_plan(
    id: uuid.UUID,
    body: PlanUpdate,
    request: Request,
    principal: Principal = Depends(BILLING),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await SubscriptionService(db, principal, request).update_plan(id, body), message="Plan updated")


@router.post(
    "/plans/{id}/deactivate",
    summary="Deactivate a plan (existing subscriptions keep it)",
    response_model=Envelope[PlanOut],
)
async def deactivate_plan(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(BILLING),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await SubscriptionService(db, principal, request).deactivate_plan(id), message="Plan deactivated")


@router.get(
    "/plans/{id}/change-preview",
    summary="Features disabled, limit violations and proration of a plan change",
    response_model=Envelope[ChangePreviewOut],
)
async def change_preview(
    id: uuid.UUID,
    institution_id: uuid.UUID,
    principal: Principal = Depends(BILLING),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await SubscriptionService(db, principal).change_preview(id, institution_id))


# ---- subscriptions / invoices ---------------------------------------------------------------------------------------
@router.get(
    "/institutions/{id}/subscription",
    summary="Tenant subscription with invoices and usage vs limits",
    response_model=Envelope[SubscriptionOut],
)
async def get_subscription(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    return ok(await SubscriptionService(db, principal, request).subscription(id))


@router.post(
    "/institutions/{id}/subscription", summary="Assign a plan (trial or paid)", response_model=Envelope[SubscriptionOut]
)
async def assign_subscription(
    id: uuid.UUID,
    body: SubscriptionAssign,
    request: Request,
    principal: Principal = Depends(BILLING),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await SubscriptionService(db, principal, request).assign(id, body), message="Subscription assigned")


@router.post(
    "/institutions/{id}/subscription/change",
    summary="Change plan now (proration) or at the next cycle",
    response_model=Envelope[SubscriptionOut],
)
async def change_subscription(
    id: uuid.UUID,
    body: SubscriptionChange,
    request: Request,
    principal: Principal = Depends(BILLING),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await SubscriptionService(db, principal, request).change(id, body), message="Plan changed")


@router.post(
    "/institutions/{id}/subscription/renew",
    summary="Renew (new period + invoice)",
    response_model=Envelope[SubscriptionOut],
)
async def renew_subscription(
    id: uuid.UUID,
    body: SubscriptionRenew,
    request: Request,
    principal: Principal = Depends(BILLING),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await SubscriptionService(db, principal, request).renew(id, body), message="Subscription renewed")


@router.post(
    "/institutions/{id}/subscription/cancel",
    summary="Cancel now or at period end",
    response_model=Envelope[SubscriptionOut],
)
async def cancel_subscription(
    id: uuid.UUID,
    body: SubscriptionCancel,
    request: Request,
    principal: Principal = Depends(BILLING),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await SubscriptionService(db, principal, request).cancel(id, body), message="Cancellation recorded")


@router.get(
    "/institutions/{id}/subscription/invoices", summary="Tenant invoices", response_model=Envelope[list[InvoiceOut]]
)
async def tenant_invoices(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    return ok(await SubscriptionService(db, principal, request).invoices(id))


@router.post(
    "/institutions/{id}/subscription/invoices/{number:path}/pay",
    summary="Record a manual payment (or start a gateway order)",
    response_model=Envelope[InvoicePayOut],
)
async def tenant_invoice_pay(
    id: uuid.UUID,
    number: str,
    body: InvoicePayRequest,
    request: Request,
    principal: Principal = Depends(BILLING),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await SubscriptionService(db, principal, request).pay(number, body, id), message="Payment recorded")


@router.post(
    "/institutions/{id}/subscription/invoices/generate",
    status_code=202,
    summary="Generate the period's invoices (job)",
    response_model=Envelope[JobAccepted],
)
async def generate_invoices(
    id: uuid.UUID,
    body: GeneratePeriodRequest,
    request: Request,
    principal: Principal = Depends(BILLING),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    from app.core.jobs import enqueue

    await InstitutionAdminService(db, principal).institution(id)
    job = await enqueue(
        db, principal, "billing.invoice_generate", {"period": body.period, "institution_id": str(id)}, queue="reports"
    )
    await InstitutionAdminService(db, principal, request).audit(
        "invoice_generate", "institution", id, {"period": body.period, "job_id": str(job.id)}, institution_id=id
    )
    return ok(JobAccepted(job_id=job.id, job_type="billing.invoice_generate"), message="Invoice generation queued")


@router.get(
    "/billing/invoices",
    summary="Invoices across tenants (issued / paid / overdue)",
    response_model=Envelope[list[InvoiceOut]],
)
async def all_invoices(
    status: str | None = Query(default=None, pattern="^(issued|paid|overdue|void)$"),
    institution_id: uuid.UUID | None = None,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await SubscriptionService(db, principal).all_invoices(status, institution_id))


# ---- usage ----------------------------------------------------------------------------------------------------------
@router.get(
    "/usage", summary="Usage meters per tenant and month (cost, caps, overage)", response_model=Envelope[UsageOut]
)
async def usage(
    request: Request,
    institution_id: uuid.UUID | None = None,
    from_month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    to_month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await UsageService(db, principal, request).months(institution_id, from_month, to_month))


@router.post(
    "/usage/meter",
    status_code=202,
    summary="Meter the current (or given) month now (job)",
    response_model=Envelope[JobAccepted],
)
async def meter_now(
    period: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    principal: Principal = Depends(BILLING),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    from app.core.jobs import enqueue

    job = await enqueue(db, principal, "usage.meter_month", {"period": period}, queue="reports")
    return ok(JobAccepted(job_id=job.id, job_type="usage.meter_month"), message="Metering queued")


@router.get("/usage/export", status_code=202, summary="Usage export (CSV job)", response_model=Envelope[JobAccepted])
async def usage_export(
    from_month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    to_month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    from app.core.jobs import enqueue

    job = await enqueue(
        db, principal, "usage.export", {"from_month": from_month, "to_month": to_month}, queue="reports"
    )
    return ok(JobAccepted(job_id=job.id, job_type="usage.export"), message="Export queued")


# ---- impersonations -------------------------------------------------------------------------------------------------
@router.get(
    "/impersonations",
    summary="Impersonation sessions across tenants (writes count)",
    response_model=Envelope[list[ImpersonationOut]],
)
async def impersonations(
    institution_id: uuid.UUID | None = None,
    active: bool | None = None,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await ImpersonationService(db, principal).list_sessions(institution_id, active))


@router.post(
    "/impersonations/{id}/force-stop",
    summary="Force-stop an impersonation (token → 401)",
    response_model=Envelope[ImpersonationOut],
)
async def force_stop(
    id: uuid.UUID,
    body: ImpersonationForceStop,
    request: Request,
    principal: Principal = Depends(platform_permission("users", "impersonate", support=False)),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await ImpersonationService(db, principal, request).force_stop(id, body), message="Impersonation stopped")


# ---- feedback triage ------------------------------------------------------------------------------------------------
@router.get(
    "/feedback",
    summary="Feedback triage board (PII masked for support agents)",
    response_model=Envelope[list[FeedbackAdminOut]],
)
async def feedback_board(
    status: str | None = Query(default=None, max_length=20),
    category: str | None = Query(default=None, max_length=30),
    institution_id: uuid.UUID | None = None,
    rating: int | None = Query(default=None, ge=1, le=5),
    principal: Principal = Depends(SUPPORT),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await SupportService(db, principal).feedback_list(status, category, institution_id, rating))


@router.post(
    "/feedback/{id}/triage",
    summary="Triage feedback (status, note, optional response to the author)",
    response_model=Envelope[FeedbackAdminOut],
)
async def feedback_triage(
    id: uuid.UUID,
    body: FeedbackTriage,
    request: Request,
    principal: Principal = Depends(SUPPORT),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await SupportService(db, principal, request).triage(id, body), message="Feedback triaged")


@router.post(
    "/feedback/{id}/to-ticket", summary="Convert feedback to a support ticket", response_model=Envelope[TicketOut]
)
async def feedback_to_ticket(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(SUPPORT),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await SupportService(db, principal, request).feedback_to_ticket(id), message="Ticket created")


# ---- announcements --------------------------------------------------------------------------------------------------
@router.get(
    "/announcements/active",
    summary="Live platform announcements for the signed-in user (banner)",
    response_model=Envelope[list[AnnouncementOut]],
)
async def active_announcements(
    principal: Principal = Depends(authenticated()), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AnnouncementService(db, principal).active())


@router.post(
    "/announcements/{id}/dismiss",
    summary="Dismiss an announcement (this user only)",
    response_model=Envelope[dict[str, Any]],
)
async def dismiss_announcement(
    id: uuid.UUID, request: Request, principal: Principal = Depends(authenticated()), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await AnnouncementService(db, principal, request).dismiss(id)
    return ok({"id": str(id), "dismissed": True})


@router.get("/announcements", summary="Platform announcements", response_model=Envelope[list[AnnouncementOut]])
async def announcements(
    principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    return ok(await AnnouncementService(db, principal).list_all())


@router.post(
    "/announcements",
    status_code=201,
    summary="Publish an announcement (audience by plan / type / tenants / roles)",
    response_model=Envelope[AnnouncementOut],
)
async def create_announcement(
    body: AnnouncementIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await AnnouncementService(db, principal, request).create(body), message="Announcement published")


@router.put("/announcements/{id}", summary="Edit an announcement", response_model=Envelope[AnnouncementOut])
async def update_announcement(
    id: uuid.UUID,
    body: AnnouncementIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await AnnouncementService(db, principal, request).update(id, body), message="Announcement updated")


@router.delete("/announcements/{id}", status_code=204, summary="Delete an announcement")
async def delete_announcement(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_platform_db)
) -> Response:
    await AnnouncementService(db, principal, request).delete(id)
    return Response(status_code=204)


# ---- health ---------------------------------------------------------------------------------------------------------
@router.get("/health", summary="Integration health across tenants", response_model=Envelope[list[HealthRow]])
async def health(
    capability: str | None = Query(default=None, max_length=40),
    provider: str | None = Query(default=None, max_length=40),
    status: str | None = Query(default=None, pattern="^(configured|healthy|degraded|failed|disabled)$"),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await HealthService(db, principal).overview(capability, provider, status))


@router.get(
    "/health/outages",
    summary="Provider-wide outages (≥ 50 % of tenants failing)",
    response_model=Envelope[list[OutageOut]],
)
async def outages(principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_platform_db)) -> dict[str, Any]:
    return ok(await HealthService(db, principal).outages())


@router.get(
    "/health/connections/{id}/history",
    summary="Health-check history of a connection",
    response_model=Envelope[list[dict[str, Any]]],
)
async def health_history(
    id: uuid.UUID, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    return ok(await HealthService(db, principal).history(id))


@router.post(
    "/health/retry", status_code=202, summary="Re-probe connections now", response_model=Envelope[dict[str, Any]]
)
async def health_retry(
    body: HealthRetryRequest,
    request: Request,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await HealthService(db, principal, request).retry(body), message="Probes queued")


@router.post(
    "/health/connections/{id}/disable",
    summary="Disable a tenant connection (tenant notified)",
    response_model=Envelope[HealthRow],
)
async def health_disable(
    id: uuid.UUID,
    body: ConnectionDisable,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await HealthService(db, principal, request).disable(id, body), message="Connection disabled")


# ---- platform settings ----------------------------------------------------------------------------------------------
@router.get(
    "/settings", summary="Typed platform settings (secrets masked)", response_model=Envelope[list[PlatformSettingOut]]
)
async def platform_settings(
    principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    return ok(await PlatformSettingsService(db, principal).items())


@router.put(
    "/settings",
    summary="Update platform settings (*** keeps a secret)",
    response_model=Envelope[list[PlatformSettingOut]],
)
async def update_platform_settings(
    body: PlatformSettingsIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await PlatformSettingsService(db, principal, request).update(body), message="Platform settings saved")


# ---- registrations / demo requests ----------------------------------------------------------------------------------
@router.get(
    "/registrations", summary="Self-serve registration pipeline", response_model=Envelope[list[RegistrationOut]]
)
async def registrations(
    status: str | None = Query(default=None, pattern="^(pending|verified|paid|provisioned|failed|expired)$"),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await RegistrationService(db, principal).list_registrations(status))


@router.post(
    "/registrations/{id}/action",
    summary="Verify / provision / expire / retry a registration",
    response_model=Envelope[RegistrationOut],
)
async def registration_action(
    id: uuid.UUID,
    body: RegistrationAction,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await RegistrationService(db, principal, request).action(id, body), message=f"Registration {body.action}")


@router.get("/demo-requests", summary="Demo requests (CRM-lite)", response_model=Envelope[list[DemoRequestOut]])
async def demo_requests(
    status: str | None = Query(default=None, pattern="^(new|contacted|converted|dropped)$"),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await RegistrationService(db, principal).demo_list(status))


@router.put(
    "/demo-requests/{id}", summary="Update a demo request (status, notes)", response_model=Envelope[DemoRequestOut]
)
async def update_demo_request(
    id: uuid.UUID,
    body: DemoRequestUpdate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await RegistrationService(db, principal, request).demo_update(id, body), message="Demo request updated")
