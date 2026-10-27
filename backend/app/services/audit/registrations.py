"""Phase 37 report and chart registrations — imported by ``services/reports/catalogue.py`` (Phase 36 registry guard)
and ``services/analytics/charts_catalogue.py`` (Phase 35 chart registry).

Reports: ``audit.explorer`` (the explorer export — rows narrowed by the explorer's own scope rules and masked by the
record module's ``view_pii``) and ``exams.audit_trail`` (the per-session exam audit report, one section per audit
section). Charts: audit volume by module / per day, security events (login failures, PII unmasks) and impersonated
writes — all institution-wide only (``audit_logs:view_all``; the explorer's self rows are not charted).
"""

from typing import Any

from app.core.reports import ReportColumn as C
from app.core.reports import ReportContext, ReportData, register_report
from app.services.analytics.chart_helpers import sql_chart

AUDIT_COLS = [
    C("occurred_at", "When", "datetime"),
    C("module", "Module"),
    C("action", "Action"),
    C("record_type", "Record type"),
    C("record_id", "Record"),
    C("user", "User"),
    C("impersonated", "Impersonated", "bool"),
    C("summary", "Summary"),
    C("ip", "IP (masked)"),
    C("old_values", "Before", "json"),
    C("new_values", "After", "json"),
    C("hash", "Hash"),
]
EXAM_COLS = [
    C("at", "When", "datetime"),
    C("actor", "Actor"),
    C("action", "Action"),
    C("subject", "Subject"),
    C("details", "Details"),
    C("ip", "IP (masked)"),
    C("gap", "Gap", "bool"),
]


@register_report(
    "audit.explorer",
    module="audit_logs",
    name="Audit trail export",
    category="audit",
    description="Audit rows for the chosen filters (masked unless you hold the record module's view_pii)",
    permission=("audit_logs:export", "audit_logs:view_all", "audit_logs:manage"),
    feature="core.audit_logs",
    layout="landscape",
    formats=("csv", "xlsx", "json", "pdf"),
    date_column="occurred_at",
    params_schema={
        "properties": {
            "module": {"type": "string"},
            "action": {"type": "string"},
            "user_id": {"type": "string", "format": "uuid", "x-picker": "user"},
            "record_type": {"type": "string"},
            "record_id": {"type": "string", "format": "uuid"},
            "q": {"type": "string"},
            "impersonator_only": {"type": "boolean"},
        }
    },
)
async def audit_explorer(ctx: ReportContext) -> ReportData:
    from app.services.audit.audit_service import AuditService

    svc = AuditService(ctx.db, ctx.principal, institution_id=ctx.institution_id)
    rows = await svc.export_rows(dict(ctx.params), None, ctx.limit)
    truncated = bool(ctx.limit and len(rows) > ctx.limit)
    return ReportData(columns=list(AUDIT_COLS), rows=rows[: ctx.limit] if truncated else rows, truncated=truncated)


@register_report(
    "exams.audit_trail",
    module="exams",
    name="Exam audit report",
    category="exams",
    description="Per exam session: marks, QP print, custody, valuation, moderation, decode, runs, publication, post-result",
    permission=("exams:audit", "exams:manage"),
    feature="exams.sessions",
    layout="landscape",
    formats=("pdf", "xlsx", "json"),
    preview=False,
    params_schema={
        "properties": {
            "exam_session_id": {"type": "string", "format": "uuid", "x-picker": "exam_session"},
            "sections": {"type": "string", "description": "comma-separated sections (default all)"},
        },
        "required": ["exam_session_id"],
    },
)
async def exam_audit_trail(ctx: ReportContext) -> ReportData:
    import uuid

    from app.services.audit.exam_audit_service import ExamAuditService

    svc = ExamAuditService(ctx.db, ctx.principal, institution_id=ctx.institution_id)
    wanted = [s.strip() for s in str(ctx.param("sections", "") or "").split(",") if s.strip()] or None
    sections = await svc.export_sections(uuid.UUID(str(ctx.param("exam_session_id"))), wanted)
    out: list[dict[str, Any]] = [
        {"title": s["title"], "columns": [c.as_dict() for c in EXAM_COLS], "rows": s["rows"]} for s in sections
    ]
    summary = {s["title"]: s["summary"] for s in sections}
    first = sections[0]["rows"] if sections else []
    return ReportData(columns=list(EXAM_COLS), rows=first, sections=out, summary=summary, title="Exam audit report")


def register_charts() -> None:
    """Called from the Phase 35 chart catalogue (charts are registered once, at catalogue import)."""
    perm = ("audit_logs:view_all", "audit_logs:manage")
    cols: dict[str, str | None] = {"institution": "l.institution_id"}
    sql_chart(
        "audit.actions_by_module",
        module="audit_logs",
        permission=perm,
        title="Audit activity by module",
        kind="bar",
        sql="SELECT l.module AS label, COUNT(*) AS value FROM audit_logs l WHERE {where} AND l.occurred_at BETWEEN :_from AND :_to "
        "GROUP BY 1 ORDER BY 2 DESC LIMIT 20",
        cols=cols,
        period="last_30d",
        dims=("period",),
        feature="core.audit_logs",
        route="/admin/audit-logs",
    )
    sql_chart(
        "audit.daily_volume",
        module="audit_logs",
        permission=perm,
        title="Audit rows per day",
        kind="line",
        sql="SELECT l.occurred_at::date AS label, COUNT(*) AS value FROM audit_logs l WHERE {where} AND l.occurred_at "
        "BETWEEN :_from AND :_to GROUP BY 1 ORDER BY 1",
        cols=cols,
        period="last_30d",
        dims=("period",),
        feature="core.audit_logs",
    )
    sql_chart(
        "security.login_failures_daily",
        module="audit_logs",
        permission=("audit_logs:security", "audit_logs:manage"),
        title="Login failures per day",
        kind="stacked",
        sql="SELECT l.occurred_at::date AS label, l.outcome AS series, COUNT(*) AS value FROM login_history l WHERE {where} "
        "AND l.outcome <> 'success' AND l.occurred_at BETWEEN :_from AND :_to GROUP BY 1, 2 ORDER BY 1",
        cols=cols,
        period="last_30d",
        dims=("period",),
        feature="security.session_management",
        route="/admin/security",
    )
    sql_chart(
        "security.pii_unmasks_daily",
        module="audit_logs",
        permission=("audit_logs:security", "audit_logs:manage"),
        title="Personal-data unmasks per day",
        kind="bar",
        sql="SELECT l.occurred_at::date AS label, COUNT(*) AS value FROM audit_logs l WHERE {where} AND l.action = 'view_pii' "
        "AND l.occurred_at BETWEEN :_from AND :_to GROUP BY 1 ORDER BY 1",
        cols=cols,
        period="last_30d",
        dims=("period",),
        feature="core.audit_logs",
    )
    sql_chart(
        "security.impersonated_writes",
        module="audit_logs",
        permission=("audit_logs:security", "audit_logs:manage"),
        title="Writes made while impersonating",
        kind="number",
        sql="SELECT 'impersonated' AS label, COUNT(*) AS value FROM audit_logs l WHERE {where} AND l.impersonator_id IS NOT NULL "
        "AND l.action NOT IN ('view', 'view_pii', 'download') AND l.occurred_at BETWEEN :_from AND :_to",
        cols=cols,
        period="last_30d",
        dims=("period",),
        feature="core.audit_logs",
    )
