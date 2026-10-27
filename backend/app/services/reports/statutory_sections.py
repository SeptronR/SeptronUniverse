"""Statutory section providers — Prompts/36 §36.6 ``statutory_service`` step 1 (``statutory_repository``).

Each provider returns one or more sections ``{key, title, columns, rows, totals?, metric_check?}`` of **aggregates
only** for the period, built from Phase 32 ``metric_values`` (by key prefix / key for the period) and the module tables
(Phase 07 students, 06 staff, 12 fees / scholarships, 23 finance metrics, 28 placement, 30 research, 31 PhD,
33 governance / RTI, 34 affiliation). ``metric_check`` names a Phase 32 metric whose value the section total must
equal (validated with the section).
"""

import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import text

from app.core.reports import ReportColumn as C

__all__ = ["Period", "SECTIONS", "parse_period"]


@dataclass
class Period:
    label: str
    start: date
    end: date
    year: int  # calendar / first year of the period


def parse_period(label: str, period_type: str) -> Period:
    m = re.match(r"^(\d{4})(?:-(\d{2}|\d{4}))?$", label.strip())
    if not m:
        raise ValueError("period_label must look like 2025-26 (or 2025 for calendar-year returns)")
    y = int(m.group(1))
    if period_type == "calendar_year":
        return Period(str(y), date(y, 1, 1), date(y, 12, 31), y)
    tail = f"{(y + 1) % 100:02d}"
    if period_type == "financial_year":
        return Period(f"{y}-{tail}", date(y, 4, 1), date(y + 1, 3, 31), y)
    return Period(f"{y}-{tail}", date(y, 7, 1), date(y + 1, 6, 30), y)


SectionFn = Callable[[Any, Period, uuid.UUID | None, str | None], Awaitable[list[dict[str, Any]]]]
SECTIONS: dict[str, SectionFn] = {}


def section(key: str) -> Callable[[SectionFn], SectionFn]:
    def deco(fn: SectionFn) -> SectionFn:
        SECTIONS[key] = fn
        return fn

    return deco


async def _rows(svc: Any, sql: str, binds: dict[str, Any]) -> list[dict[str, Any]]:
    res = await svc.db.execute(text(sql), {"i": svc.inst, **binds})
    keys = list(res.keys())
    return [dict(zip(keys, r, strict=False)) for r in res.all()]


def _college(alias: str, college_id: uuid.UUID | None) -> str:
    return f" AND {alias} = :c" if college_id else ""


def _sec(key: str, title: str, columns: list[C], rows: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
    totals = {c.key: sum(float(r.get(c.key) or 0) for r in rows) for c in columns if c.total}
    return {"key": key, "title": title, "columns": columns, "rows": rows, "totals": totals, **kw}


async def _metrics(
    svc: Any, p: Period, prefixes: tuple[str, ...], college_id: uuid.UUID | None
) -> list[dict[str, Any]]:
    like = " OR ".join(f"m.metric_key LIKE :p{i}" for i in range(len(prefixes)))
    binds: dict[str, Any] = {"per": p.label, **{f"p{i}": f"{x}%" for i, x in enumerate(prefixes)}}
    if college_id:
        binds["c"] = college_id
    return await _rows(
        svc,
        "SELECT m.metric_key, md.name, md.unit, m.value, m.numerator, m.denominator, m.source, "
        "(m.verified_at IS NOT NULL) AS verified FROM metric_values m JOIN metric_definitions md ON md.key = m.metric_key "
        f"WHERE m.institution_id = :i AND m.period_label = :per AND ({like}) AND m.program_id IS NULL "
        + ("AND m.college_id = :c " if college_id else "AND m.college_id IS NULL ")
        + "ORDER BY m.metric_key",
        binds,
    )


METRIC_COLS = [
    C("metric_key", "Metric"),
    C("name"),
    C("unit"),
    C("value", type="number"),
    C("numerator", type="number"),
    C("denominator", type="number"),
    C("source"),
    C("verified", type="bool"),
]


@section("institution")
async def institution(svc: Any, p: Period, college_id: uuid.UUID | None, _d: str | None) -> list[dict[str, Any]]:
    inst = await svc.institution()
    binds = {"c": college_id} if college_id else {}
    rows = await _rows(
        svc,
        "SELECT c.code, c.name, c.college_type, c.aishe_code, c.aicte_pid, "
        "(SELECT COUNT(*) FROM departments d WHERE d.college_id = c.id AND d.deleted_at IS NULL)::int AS departments, "
        "(SELECT COUNT(*) FROM programs pr WHERE pr.college_id = c.id AND pr.status = 'active')::int AS programmes "
        "FROM colleges c WHERE c.institution_id = :i AND c.deleted_at IS NULL"
        + _college("c.id", college_id)
        + " ORDER BY c.code",
        binds,
    )
    return [
        _sec(
            "institution",
            f"Institution — {inst.name}",
            [
                C("code"),
                C("name"),
                C("college_type", "Type"),
                C("aishe_code", "AISHE code"),
                C("aicte_pid", "AICTE PID"),
                C("departments", type="int", total=True),
                C("programmes", type="int", total=True),
            ],
            rows,
            mandatory=["aishe_code"],
        )
    ]


@section("programmes")
async def programmes(svc: Any, p: Period, college_id: uuid.UUID | None, _d: str | None) -> list[dict[str, Any]]:
    rows = await _rows(
        svc,
        "SELECT pr.code, pr.name, pr.level, pr.mode, pr.duration_years, pr.sanctioned_intake, pr.approving_body, "
        "(SELECT COUNT(*) FROM student_program_enrollments e WHERE e.program_id = pr.id AND e.status = 'active' "
        "AND e.deleted_at IS NULL)::int AS enrolled FROM programs pr WHERE pr.institution_id = :i AND pr.status = 'active' "
        "AND pr.deleted_at IS NULL" + _college("pr.college_id", college_id) + " ORDER BY pr.level, pr.code",
        {"c": college_id} if college_id else {},
    )
    return [
        _sec(
            "programmes",
            "Programmes and intake",
            [
                C("code"),
                C("name"),
                C("level"),
                C("mode"),
                C("duration_years", "Years", type="number"),
                C("sanctioned_intake", "Intake", type="int", total=True),
                C("approving_body", "Approving body"),
                C("enrolled", type="int", total=True),
            ],
            rows,
        )
    ]


@section("students")
async def students(svc: Any, p: Period, college_id: uuid.UUID | None, _d: str | None) -> list[dict[str, Any]]:
    binds = {"c": college_id} if college_id else {}
    base = (
        "FROM student_program_enrollments e JOIN students s ON s.id = e.student_id WHERE e.institution_id = :i "
        "AND e.status = 'active' AND e.deleted_at IS NULL AND s.deleted_at IS NULL"
        + _college("e.college_id", college_id)
    )
    by_cat = await _rows(
        svc,
        "SELECT COALESCE(s.category, 'unspecified') AS category, "
        "COUNT(*) FILTER (WHERE lower(s.gender) IN ('male', 'm'))::int AS male, "
        "COUNT(*) FILTER (WHERE lower(s.gender) IN ('female', 'f'))::int AS female, "
        "COUNT(*) FILTER (WHERE lower(COALESCE(s.gender, '')) NOT IN ('male', 'm', 'female', 'f'))::int AS other, "
        f"COUNT(*)::int AS total, COUNT(*) FILTER (WHERE s.is_pwd)::int AS pwd {base} GROUP BY 1 ORDER BY 1",
        binds,
    )
    by_state = await _rows(
        svc,
        "SELECT COALESCE(s.domicile_state, 'unspecified') AS state, "
        "COUNT(*) FILTER (WHERE lower(s.gender) IN ('male', 'm'))::int AS male, "
        "COUNT(*) FILTER (WHERE lower(s.gender) IN ('female', 'f'))::int AS female, "
        f"COUNT(*)::int AS total {base} GROUP BY 1 ORDER BY 1",
        binds,
    )
    by_level = await _rows(
        svc,
        "SELECT pr.level, COUNT(*)::int AS total, COUNT(*) FILTER (WHERE s.is_international)::int AS foreign_nationals "
        f"{base.replace('WHERE', 'JOIN programs pr ON pr.id = e.program_id WHERE', 1)} GROUP BY pr.level ORDER BY pr.level",
        binds,
    )
    gender_cols = [C("male", type="int", total=True), C("female", type="int", total=True)]
    return [
        _sec(
            "students",
            "Students by social category and gender",
            [
                C("category"),
                *gender_cols,
                C("other", type="int", total=True),
                C("total", type="int", total=True),
                C("pwd", "PwD", type="int", total=True),
            ],
            by_cat,
            metric_check="students.enrolment_by_category",
        ),
        _sec(
            "students_state",
            "Students by domicile state",
            [C("state"), *gender_cols, C("total", type="int", total=True)],
            by_state,
        ),
        _sec(
            "students_level",
            "Students by programme level",
            [
                C("level"),
                C("total", type="int", total=True),
                C("foreign_nationals", "Foreign nationals", type="int", total=True),
            ],
            by_level,
        ),
    ]


@section("staff")
async def staff(svc: Any, p: Period, college_id: uuid.UUID | None, _d: str | None) -> list[dict[str, Any]]:
    rows = await _rows(
        svc,
        "SELECT st.staff_category AS category, COALESCE(dg.cadre, 'unspecified') AS cadre, "
        "COUNT(*) FILTER (WHERE lower(st.gender) IN ('male', 'm'))::int AS male, "
        "COUNT(*) FILTER (WHERE lower(st.gender) IN ('female', 'f'))::int AS female, COUNT(*)::int AS total, "
        "COUNT(*) FILTER (WHERE st.employment_type = 'regular')::int AS regular "
        "FROM staff st LEFT JOIN designations dg ON dg.id = st.designation_id WHERE st.institution_id = :i "
        "AND st.deleted_at IS NULL AND st.status IN ('active', 'on_leave')"
        + _college("st.college_id", college_id)
        + " GROUP BY 1, 2 ORDER BY 1, 2",
        {"c": college_id} if college_id else {},
    )
    return [
        _sec(
            "staff",
            "Teaching and non-teaching staff",
            [
                C("category"),
                C("cadre"),
                C("male", type="int", total=True),
                C("female", type="int", total=True),
                C("total", type="int", total=True),
                C("regular", type="int", total=True),
            ],
            rows,
        )
    ]


@section("infrastructure")
async def infrastructure(svc: Any, p: Period, college_id: uuid.UUID | None, _d: str | None) -> list[dict[str, Any]]:
    rows = await _metrics(svc, p, ("infrastructure.", "infra.", "library.", "it."), college_id)
    return [_sec("infrastructure", "Infrastructure (Phase 32 metrics)", METRIC_COLS, rows)]


@section("finance")
async def finance(svc: Any, p: Period, college_id: uuid.UUID | None, _d: str | None) -> list[dict[str, Any]]:
    metrics = await _metrics(svc, p, ("finance.", "accounting.", "fees."), college_id)
    binds: dict[str, Any] = {"a": p.start, "b": p.end, **({"c": college_id} if college_id else {})}
    fees = await _rows(
        svc,
        "SELECT p.payment_mode AS mode, COUNT(*)::int AS receipts, COALESCE(SUM(p.amount_paise), 0)::bigint AS amount_paise "
        "FROM fee_payments p JOIN fee_invoices i ON i.id = p.invoice_id WHERE p.institution_id = :i "
        "AND p.status IN ('success', 'reconciled') AND p.payment_date BETWEEN :a AND :b"
        + _college("i.college_id", college_id)
        + " GROUP BY 1 ORDER BY 1",
        binds,
    )
    return [
        _sec("finance", "Finance (Phase 23 / 32 metrics)", METRIC_COLS, metrics),
        _sec(
            "fee_receipts",
            f"Fee receipts {p.start.isoformat()} – {p.end.isoformat()}",
            [C("mode"), C("receipts", type="int", total=True), C("amount_paise", "Amount (₹)", type="money")],
            fees,
        ),
    ]


@section("nirf_metrics")
async def nirf_metrics(
    svc: Any, p: Period, college_id: uuid.UUID | None, discipline: str | None
) -> list[dict[str, Any]]:
    rows = await _metrics(svc, p, ("nirf.",), college_id)
    return [_sec("nirf_metrics", f"NIRF parameters ({discipline or 'overall'})", METRIC_COLS, rows)]


@section("placement")
async def placement(svc: Any, p: Period, college_id: uuid.UUID | None, _d: str | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    note = None
    if await svc.feature_on("placement.core"):
        try:
            from app.services.placement.stats_service import StatsService

            st = await StatsService(svc.db, svc.principal, None, svc.inst).stats(None, None, college_id)
            rows = [dict(r) for r in st.nirf_rows]
        except Exception as exc:  # noqa: BLE001 - placement data optional; recorded as a validation warning
            note = str(exc)[:200]
    keys = (
        list(rows[0].keys()) if rows else ["program", "graduating", "placed", "higher_studies", "median_salary_paise"]
    )
    cols = []
    for k in keys:
        sample = next((r.get(k) for r in rows if r.get(k) is not None), None)
        numeric = isinstance(sample, int | float) and not isinstance(sample, bool)
        ctype = (
            "money"
            if k.endswith("_paise")
            else ("int" if isinstance(sample, int) and numeric else ("number" if numeric else "str"))
        )
        cols.append(C(k, type=ctype, total=ctype == "int"))
    return [_sec("placement", "Placement and higher studies (NIRF format)", cols, rows, note=note)]


@section("phd")
async def phd(svc: Any, p: Period, college_id: uuid.UUID | None, _d: str | None) -> list[dict[str, Any]]:
    binds: dict[str, Any] = {"a": p.start, "b": p.end, **({"c": college_id} if college_id else {})}
    status = await _rows(
        svc,
        "SELECT rs.status, rs.mode, COUNT(*)::int AS scholars FROM research_scholars rs JOIN student_program_enrollments e "
        "ON e.id = rs.student_program_enrollment_id WHERE rs.institution_id = :i"
        + _college("e.college_id", college_id)
        + " GROUP BY 1, 2 ORDER BY 1, 2",
        binds,
    )
    awarded = await _rows(
        svc,
        "SELECT d.department_id AS department_id, dp.code AS department, COUNT(*)::int AS awarded, "
        "COUNT(*) FILTER (WHERE lower(s.gender) IN ('female', 'f'))::int AS women FROM degrees_awarded da "
        "JOIN student_program_enrollments d ON d.id = da.student_program_enrollment_id JOIN students s ON s.id = d.student_id "
        "JOIN departments dp ON dp.id = d.department_id WHERE da.institution_id = :i AND da.award_type = 'phd' "
        "AND da.status IN ('council_approved', 'issued') AND da.date_of_award BETWEEN :a AND :b"
        + _college("d.college_id", college_id)
        + " GROUP BY 1, 2 ORDER BY 2",
        binds,
    )
    for r in awarded:
        r.pop("department_id", None)
    return [
        _sec(
            "phd_scholars",
            "Research scholars by status",
            [C("status"), C("mode"), C("scholars", type="int", total=True)],
            status,
        ),
        _sec(
            "phd",
            f"PhD degrees awarded {p.start.isoformat()} – {p.end.isoformat()}",
            [C("department"), C("awarded", type="int", total=True), C("women", type="int", total=True)],
            awarded,
        ),
    ]


@section("research")
async def research(svc: Any, p: Period, college_id: uuid.UUID | None, _d: str | None) -> list[dict[str, Any]]:
    rows = await _rows(
        svc,
        "SELECT x.metric, x.sub_key, SUM(x.count)::int AS count, SUM(x.amount_paise)::bigint AS amount_paise "
        "FROM mv_research_counts x WHERE x.institution_id = :i AND x.year = :y"
        + _college("x.college_id", college_id)
        + " GROUP BY 1, 2 ORDER BY 1, 2",
        {"y": p.year, **({"c": college_id} if college_id else {})},
    )
    return [
        _sec(
            "research",
            f"Research output {p.year}",
            [
                C("metric"),
                C("sub_key", "Kind"),
                C("count", type="int", total=True),
                C("amount_paise", "Amount (₹)", type="money"),
            ],
            rows,
        )
    ]


@section("governance")
async def governance(svc: Any, p: Period, college_id: uuid.UUID | None, _d: str | None) -> list[dict[str, Any]]:
    rows = await _rows(
        svc,
        "SELECT cm.committee_type, COUNT(DISTINCT cm.id)::int AS committees, COUNT(m.id)::int AS meetings, "
        "COUNT(r.id)::int AS resolutions FROM committees cm LEFT JOIN meetings m ON m.committee_id = cm.id "
        "AND m.held_on::date BETWEEN :a AND :b LEFT JOIN resolutions r ON r.meeting_id = m.id "
        "WHERE cm.institution_id = :i AND cm.is_active"
        + _college("cm.college_id", college_id)
        + " GROUP BY 1 ORDER BY 1",
        {"a": p.start, "b": p.end, **({"c": college_id} if college_id else {})},
    )
    return [
        _sec(
            "governance",
            "Statutory bodies and meetings",
            [
                C("committee_type", "Body"),
                C("committees", type="int", total=True),
                C("meetings", type="int", total=True),
                C("resolutions", type="int", total=True),
            ],
            rows,
        )
    ]


@section("scholarships")
async def scholarships(svc: Any, p: Period, college_id: uuid.UUID | None, _d: str | None) -> list[dict[str, Any]]:
    rows = await _rows(
        svc,
        "SELECT sc.provider, sc.scheme_code, sc.name AS scheme, COALESCE(s.category, 'unspecified') AS category, "
        "COUNT(*)::int AS applications, COUNT(*) FILTER (WHERE a.status IN ('sanctioned', 'disbursed'))::int AS sanctioned, "
        "COUNT(*) FILTER (WHERE a.status = 'disbursed')::int AS disbursed, COALESCE(SUM(a.sanctioned_paise), 0)::bigint AS amount_paise "
        "FROM scholarship_applications a JOIN scholarships sc ON sc.id = a.scholarship_id JOIN student_program_enrollments e "
        "ON e.id = a.student_program_enrollment_id JOIN students s ON s.id = e.student_id WHERE a.institution_id = :i "
        "AND a.created_at::date BETWEEN :a AND :b"
        + _college("e.college_id", college_id)
        + " GROUP BY 1, 2, 3, 4 ORDER BY 1, 3, 4",
        {"a": p.start, "b": p.end, **({"c": college_id} if college_id else {})},
    )
    return [
        _sec(
            "scholarships",
            "Scholarships (NSP / state / institution)",
            [
                C("provider"),
                C("scheme_code", "Scheme code"),
                C("scheme"),
                C("category"),
                C("applications", type="int", total=True),
                C("sanctioned", type="int", total=True),
                C("disbursed", type="int", total=True),
                C("amount_paise", "Sanctioned (₹)", type="money"),
            ],
            rows,
        )
    ]


@section("fee_structure")
async def fee_structure(svc: Any, p: Period, college_id: uuid.UUID | None, _d: str | None) -> list[dict[str, Any]]:
    rows = await _rows(
        svc,
        "SELECT pr.code AS program, COUNT(DISTINCT i.student_program_enrollment_id)::int AS students, "
        "COALESCE(SUM(i.total_paise), 0)::bigint AS billed_paise, "
        "COALESCE(ROUND(SUM(i.total_paise)::numeric / NULLIF(COUNT(DISTINCT i.student_program_enrollment_id), 0)), 0)::bigint AS per_student_paise "
        "FROM fee_invoices i JOIN student_program_enrollments e ON e.id = i.student_program_enrollment_id "
        "JOIN programs pr ON pr.id = e.program_id WHERE i.institution_id = :i AND i.status <> 'cancelled' "
        "AND i.created_at::date BETWEEN :a AND :b" + _college("e.college_id", college_id) + " GROUP BY 1 ORDER BY 1",
        {"a": p.start, "b": p.end, **({"c": college_id} if college_id else {})},
    )
    return [
        _sec(
            "fee_structure",
            "Fees charged per programme",
            [
                C("program", "Programme"),
                C("students", type="int", total=True),
                C("billed_paise", "Billed (₹)", type="money"),
                C("per_student_paise", "Per student (₹)", type="money", total=False),
            ],
            rows,
        )
    ]


@section("fee_collection")
async def fee_collection(svc: Any, p: Period, college_id: uuid.UUID | None, _d: str | None) -> list[dict[str, Any]]:
    return [
        dict(s, key="fee_collection", title="Fee collection by mode")
        for s in (await finance(svc, p, college_id, None))[1:]
    ]


@section("minority_students")
async def minority_students(svc: Any, p: Period, college_id: uuid.UUID | None, _d: str | None) -> list[dict[str, Any]]:
    rows = await _rows(
        svc,
        "SELECT COALESCE(s.minority_type, 'unspecified') AS minority_type, "
        "COUNT(*) FILTER (WHERE lower(s.gender) IN ('male', 'm'))::int AS male, "
        "COUNT(*) FILTER (WHERE lower(s.gender) IN ('female', 'f'))::int AS female, COUNT(*)::int AS total "
        "FROM student_program_enrollments e JOIN students s ON s.id = e.student_id WHERE e.institution_id = :i "
        "AND e.status = 'active' AND s.is_minority" + _college("e.college_id", college_id) + " GROUP BY 1 ORDER BY 1",
        {"c": college_id} if college_id else {},
    )
    return [
        _sec(
            "minority_students",
            "Minority students",
            [
                C("minority_type", "Community"),
                C("male", type="int", total=True),
                C("female", type="int", total=True),
                C("total", type="int", total=True),
            ],
            rows,
        )
    ]


_SCST = "upper(COALESCE({c}, '')) IN ('SC', 'ST')"


@section("category_students")
async def category_students(svc: Any, p: Period, college_id: uuid.UUID | None, _d: str | None) -> list[dict[str, Any]]:
    rows = await _rows(
        svc,
        "SELECT upper(s.category) AS category, pr.level, COUNT(*)::int AS total FROM student_program_enrollments e "
        "JOIN students s ON s.id = e.student_id JOIN programs pr ON pr.id = e.program_id WHERE e.institution_id = :i "
        "AND e.status = 'active' AND "
        + _SCST.format(c="s.category")
        + _college("e.college_id", college_id)
        + " GROUP BY 1, 2 ORDER BY 1, 2",
        {"c": college_id} if college_id else {},
    )
    return [
        _sec(
            "category_students",
            "SC / ST students",
            [C("category"), C("level"), C("total", type="int", total=True)],
            rows,
        )
    ]


@section("category_staff")
async def category_staff(svc: Any, p: Period, college_id: uuid.UUID | None, _d: str | None) -> list[dict[str, Any]]:
    # staff rows carry no social category column; the Phase 32 metric (reservation roster) is used when recorded
    rows = await _metrics(svc, p, ("hr.reservation", "staff.category"), college_id)
    return [_sec("category_staff", "SC / ST staff (reservation roster metrics)", METRIC_COLS, rows)]


@section("grievances_sc_st")
async def grievances_sc_st(svc: Any, p: Period, college_id: uuid.UUID | None, _d: str | None) -> list[dict[str, Any]]:
    rows = await _rows(
        svc,
        "SELECT g.category, g.status, COUNT(*)::int AS cases FROM grievances g WHERE g.institution_id = :i "
        "AND (g.committee = 'sc_st_cell' OR g.category = 'discrimination') AND g.created_at::date BETWEEN :a AND :b"
        + _college("g.college_id", college_id)
        + " GROUP BY 1, 2 ORDER BY 1, 2",
        {"a": p.start, "b": p.end, **({"c": college_id} if college_id else {})},
    )
    return [
        _sec(
            "grievances_sc_st",
            "SC / ST cell cases",
            [C("category"), C("status"), C("cases", type="int", total=True)],
            rows,
        )
    ]


@section("anti_ragging")
async def anti_ragging(svc: Any, p: Period, college_id: uuid.UUID | None, _d: str | None) -> list[dict[str, Any]]:
    binds = {"a": p.start, "b": p.end, **({"c": college_id} if college_id else {})}
    cases = await _rows(
        svc,
        "SELECT g.status, COUNT(*)::int AS cases, COUNT(*) FILTER (WHERE g.resolved_at IS NOT NULL)::int AS resolved "
        "FROM grievances g WHERE g.institution_id = :i AND g.category = 'ragging' AND g.created_at::date BETWEEN :a AND :b"
        + _college("g.college_id", college_id)
        + " GROUP BY 1 ORDER BY 1",
        binds,
    )
    bodies = await _rows(
        svc,
        "SELECT cm.name, cm.committee_type, cm.constituted_on, cm.valid_to, "
        "(SELECT COUNT(*) FROM meetings m WHERE m.committee_id = cm.id AND m.held_on::date BETWEEN :a AND :b)::int AS meetings "
        "FROM committees cm WHERE cm.institution_id = :i AND cm.committee_type = 'anti_ragging' AND cm.is_active"
        + _college("cm.college_id", college_id)
        + " ORDER BY cm.name",
        binds,
    )
    return [
        _sec(
            "anti_ragging_bodies",
            "Anti-ragging committee / squad",
            [
                C("name"),
                C("committee_type", "Type"),
                C("constituted_on", type="date"),
                C("valid_to", type="date"),
                C("meetings", type="int", total=True),
            ],
            bodies,
            mandatory_rows=True,
        ),
        _sec(
            "anti_ragging",
            "Ragging complaints",
            [C("status"), C("cases", type="int", total=True), C("resolved", type="int", total=True)],
            cases,
        ),
    ]


@section("rti")
async def rti(svc: Any, p: Period, college_id: uuid.UUID | None, _d: str | None) -> list[dict[str, Any]]:
    rows = await _rows(
        svc,
        "SELECT r.status, COUNT(*)::int AS requests, COUNT(*) FILTER (WHERE r.first_appeal IS NOT NULL)::int AS first_appeals, "
        "COUNT(*) FILTER (WHERE r.responded_on IS NOT NULL AND r.responded_on <= r.due_on)::int AS within_time, "
        "COALESCE(SUM(r.fee_paise), 0)::bigint AS fee_paise FROM rti_requests r WHERE r.institution_id = :i "
        "AND r.received_on BETWEEN :a AND :b GROUP BY 1 ORDER BY 1",
        {"a": p.start, "b": p.end},
    )
    return [
        _sec(
            "rti",
            f"RTI requests {p.start.isoformat()} – {p.end.isoformat()}",
            [
                C("status"),
                C("requests", type="int", total=True),
                C("first_appeals", "First appeals", type="int", total=True),
                C("within_time", "Within 30 days", type="int", total=True),
                C("fee_paise", "Fees (₹)", type="money"),
            ],
            rows,
        )
    ]


@section("affiliated_colleges")
async def affiliated_colleges(
    svc: Any, p: Period, college_id: uuid.UUID | None, _d: str | None
) -> list[dict[str, Any]]:
    rows = await _rows(
        svc,
        "SELECT c.code, c.name, c.college_type, c.affiliation_number, c.affiliated_since, c.aishe_code, "
        "(SELECT COUNT(*) FROM programs pr WHERE pr.college_id = c.id AND pr.status = 'active')::int AS programmes, "
        "(SELECT COUNT(*) FROM student_program_enrollments e WHERE e.college_id = c.id AND e.status = 'active')::int AS students "
        "FROM colleges c WHERE c.institution_id = :i AND c.deleted_at IS NULL AND c.college_type IN ('affiliated', 'autonomous') "
        "ORDER BY c.code",
        {},
    )
    return [
        _sec(
            "affiliated_colleges",
            "Affiliated and autonomous colleges",
            [
                C("code"),
                C("name"),
                C("college_type", "Type"),
                C("affiliation_number", "Affiliation no"),
                C("affiliated_since", "Since", type="date"),
                C("aishe_code", "AISHE code"),
                C("programmes", type="int", total=True),
                C("students", type="int", total=True),
            ],
            rows,
            mandatory=["affiliation_number"],
        )
    ]


@section("gst")
async def gst(svc: Any, p: Period, college_id: uuid.UUID | None, _d: str | None) -> list[dict[str, Any]]:
    rows = await _rows(
        svc,
        "SELECT to_char(i.created_at, 'YYYY-MM') AS month, COUNT(*)::int AS invoices, "
        "COALESCE(SUM(i.total_paise - i.discount_paise), 0)::bigint AS taxable_paise, COALESCE(SUM(i.tax_paise), 0)::bigint AS tax_paise, "
        "COUNT(*) FILTER (WHERE i.gst_number IS NOT NULL)::int AS b2b FROM fee_invoices i WHERE i.institution_id = :i "
        "AND i.tax_paise > 0 AND i.status <> 'cancelled' AND i.created_at::date BETWEEN :a AND :b"
        + _college("i.college_id", college_id)
        + " GROUP BY 1 ORDER BY 1",
        {"a": p.start, "b": p.end, **({"c": college_id} if college_id else {})},
    )
    return [
        _sec(
            "gst",
            "Outward supplies (GSTR-1 summary)",
            [
                C("month"),
                C("invoices", type="int", total=True),
                C("taxable_paise", "Taxable (₹)", type="money"),
                C("tax_paise", "Tax (₹)", type="money"),
                C("b2b", "B2B invoices", type="int", total=True),
            ],
            rows,
        )
    ]
