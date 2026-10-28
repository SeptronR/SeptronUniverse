"""Phase 38 chart / report registrations and the support-ticket visibility module.

* **Charts** (Phase 35 registry, imported by ``services/analytics/charts_catalogue.py``): ``saas.usage_trend`` (monthly
  API calls / messages), ``saas.storage_trend`` and ``saas.invoices_by_status`` — the tenant reads its own rows
  (``settings:manage``; scope predicate on ``institution_id`` + RLS); :func:`platform_charts` evaluates the same
  queries without a tenant filter on the platform session for the super-admin dashboard (plus MRR by plan and tenants
  by status).
* **Reports** (Phase 36 registry, imported by ``services/reports/catalogue.py``): ``saas.usage_monthly`` and
  ``saas.invoices`` — the tenant's own usage meters and invoice ledger for the billing page exports.
* **Visibility** ``support``: self = tickets the user raised; ``support:view_all`` / ``support:manage`` widen to the
  institution.
"""

from typing import Any

from sqlalchemy import ColumnElement, text

from app.core.reports import ReportColumn as C
from app.core.reports import ReportContext, ReportData, register_report

PERM = ("settings:manage", "settings:view_all")

USAGE_SQL = (
    "SELECT to_char(m.period_month, 'YYYY-MM') AS label, sum(m.api_calls) AS api_calls, sum(m.sms_sent) AS sms, "
    "sum(m.whatsapp_sent) AS whatsapp, sum(m.emails_sent) AS emails FROM usage_meters m WHERE {where} "
    "AND m.period_month >= date_trunc('month', NOW()) - INTERVAL '11 months' GROUP BY 1 ORDER BY 1"
)
STORAGE_SQL = (
    "SELECT to_char(m.period_month, 'YYYY-MM') AS label, round(sum(m.storage_bytes) / 1073741824.0, 2) AS value "
    "FROM usage_meters m WHERE {where} AND m.period_month >= date_trunc('month', NOW()) - INTERVAL '11 months' "
    "GROUP BY 1 ORDER BY 1"
)
INVOICE_SQL = (
    "SELECT s.value->>'status' AS label, count(*) AS value FROM institution_settings s WHERE {where} "
    "AND s.category = 'saas_meta' AND s.key LIKE 'invoice:%' GROUP BY 1 ORDER BY 2 DESC"
)


def register_charts() -> None:
    from app.services.analytics.chart_helpers import sql_chart

    sql_chart(
        "saas.usage_trend",
        module="settings",
        permission=PERM,
        title="Usage per month (API calls, messages)",
        kind="line",
        sql=USAGE_SQL,
        cols={"institution": "m.institution_id"},
        dims=(),
        feature="core.settings",
        route="/admin/billing",
    )
    sql_chart(
        "saas.storage_trend",
        module="settings",
        permission=PERM,
        title="Storage used (GB)",
        kind="line",
        sql=STORAGE_SQL,
        cols={"institution": "m.institution_id"},
        dims=(),
        feature="core.settings",
        route="/admin/billing",
    )
    sql_chart(
        "saas.invoices_by_status",
        module="settings",
        permission=PERM,
        title="Invoices by status",
        kind="donut",
        sql=INVOICE_SQL,
        cols={"institution": "s.institution_id"},
        dims=(),
        feature="core.settings",
        route="/admin/billing",
    )


async def platform_charts(db: Any) -> list[dict[str, Any]]:
    """The ``saas.*`` charts across every tenant (platform session) + MRR by plan and tenants by status."""

    async def rows(sql: str) -> list[dict[str, Any]]:
        return [dict(r) for r in (await db.execute(text(sql.format(where="TRUE")))).mappings().all()]

    usage = await rows(USAGE_SQL)
    storage = await rows(STORAGE_SQL)
    invoices = await rows(INVOICE_SQL)
    mrr = [
        dict(r)
        for r in (
            await db.execute(
                text(
                    "SELECT p.code AS label, sum(CASE WHEN s.billing_cycle = 'monthly' THEN COALESCE(s.amount_paise, p.price_paise_monthly) "
                    "ELSE COALESCE(s.amount_paise, p.price_paise_yearly) / 12 END)::bigint AS value FROM (SELECT DISTINCT ON (institution_id) * "
                    "FROM institution_subscriptions ORDER BY institution_id, starts_on DESC, created_at DESC) s JOIN subscription_plans p "
                    "ON p.id = s.plan_id WHERE s.status IN ('active','grace') GROUP BY 1 ORDER BY 2 DESC"
                )
            )
        ).mappings()
    ]
    tenants = [
        dict(r)
        for r in (
            await db.execute(
                text("SELECT status AS label, count(*) AS value FROM institutions WHERE deleted_at IS NULL GROUP BY 1")
            )
        ).mappings()
    ]

    def series(name: str, data: list[dict[str, Any]], field: str = "value") -> dict[str, Any]:
        return {"name": name, "points": [{"label": str(d["label"]), "value": float(d.get(field) or 0)} for d in data]}

    return [
        {
            "key": "saas.usage_trend",
            "title": "Usage per month",
            "kind": "line",
            "series": [
                series("API calls", usage, "api_calls"),
                series("SMS", usage, "sms"),
                series("WhatsApp", usage, "whatsapp"),
                series("E-mails", usage, "emails"),
            ],
        },
        {
            "key": "saas.storage_trend",
            "title": "Storage used (GB)",
            "kind": "line",
            "series": [series("Storage", storage)],
        },
        {
            "key": "saas.invoices_by_status",
            "title": "Invoices by status",
            "kind": "donut",
            "series": [series("Invoices", invoices)],
        },
        {"key": "saas.mrr_by_plan", "title": "MRR by plan (paise)", "kind": "bar", "series": [series("MRR", mrr)]},
        {
            "key": "saas.tenants_by_status",
            "title": "Tenants by status",
            "kind": "donut",
            "series": [series("Tenants", tenants)],
        },
    ]


@register_report(
    "saas.usage_monthly",
    module="settings",
    name="Usage by month",
    category="billing",
    description="The institution's metered usage (seats, storage, messages, API calls) per month",
    permission=PERM,
    feature="core.settings",
    formats=("xlsx", "csv", "pdf", "json"),
)
async def usage_monthly(ctx: ReportContext) -> ReportData:
    rows = (
        (
            await ctx.db.execute(
                text(
                    "SELECT period_month, active_students, active_staff, storage_bytes, sms_sent, whatsapp_sent, emails_sent, api_calls "
                    "FROM usage_meters WHERE institution_id = :i ORDER BY period_month DESC LIMIT 36"
                ),
                {"i": ctx.institution_id},
            )
        )
        .mappings()
        .all()
    )
    return ReportData(
        columns=[
            C("period_month", "Month", "date"),
            C("active_students", "Students", "int"),
            C("active_staff", "Staff", "int"),
            C("storage_bytes", "Storage (bytes)", "int"),
            C("sms_sent", "SMS", "int"),
            C("whatsapp_sent", "WhatsApp", "int"),
            C("emails_sent", "E-mails", "int"),
            C("api_calls", "API calls", "int"),
        ],
        rows=[dict(r) for r in rows],
    )


@register_report(
    "saas.invoices",
    module="settings",
    name="Subscription invoices",
    category="billing",
    description="Platform invoices of the institution (number, period, GST, status, payment reference)",
    permission=PERM,
    feature="core.settings",
    formats=("xlsx", "csv", "pdf", "json"),
)
async def invoices(ctx: ReportContext) -> ReportData:
    rows = (
        await ctx.db.execute(
            text(
                "SELECT value FROM institution_settings WHERE institution_id = :i AND college_id IS NULL AND category = 'saas_meta' "
                "AND key LIKE 'invoice:%'"
            ),
            {"i": ctx.institution_id},
        )
    ).all()
    docs = sorted((r[0] for r in rows if isinstance(r[0], dict)), key=lambda d: str(d.get("issued_on")), reverse=True)
    return ReportData(
        columns=[
            C("number", "Invoice"),
            C("period", "Period"),
            C("kind", "Kind"),
            C("amount_paise", "Net", "money"),
            C("gst_paise", "GST", "money"),
            C("total_paise", "Total", "money"),
            C("status", "Status"),
            C("issued_on", "Issued", "date"),
            C("due_on", "Due", "date"),
            C("paid_on", "Paid", "date"),
            C("payment_ref", "Payment ref"),
        ],
        rows=[
            {
                k: d.get(k)
                for k in (
                    "number",
                    "period",
                    "kind",
                    "amount_paise",
                    "gst_paise",
                    "total_paise",
                    "status",
                    "issued_on",
                    "due_on",
                    "paid_on",
                    "payment_ref",
                )
            }
            for d in docs
        ],
    )


# ---- visibility ------------------------------------------------------------------------------------------------------
def _ticket_is_mine(principal: Any, model: Any) -> ColumnElement[bool]:
    return model.raised_by == principal.id  # type: ignore[no-any-return]


def register_visibility() -> None:
    from app.core.authz.visibility import ModuleVisibility, register_module
    from app.models.saas import SupportTicket

    register_module(
        ModuleVisibility(
            module="support",
            model=SupportTicket,
            self_predicate=_ticket_is_mine,
            scope_columns={"institution": "institution_id"},
        )
    )


register_visibility()
