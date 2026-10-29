"""Public read models of the website — Prompts/40 §40.5 ``public_read_repository`` + ``admission_entry_service`` +
``verification_service``. Every query names its columns (allow-list); nothing personal leaves the database except
the faculty directory's allow-listed fields of staff who did not opt out.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import text

from app.core.errors import APIError, ErrorCode
from app.core.features import is_enabled
from app.schemas.website import PublicAdmissionsOut

DIRECTORY_COLUMNS = {
    "name": "trim(concat_ws(' ', s.first_name, s.last_name))",
    "designation": "dg.name",
    "department": "d.name",
    "qualification": "fp.highest_qualification",
    "email_public": "NULL::text",  # institutional e-mail is published only when the profile marks it public (Phase 43)
    "profile_photo": "s.photo_url",
    "research_interests": "fp.specializations",
}


async def faculty_directory(svc: Any) -> list[dict[str, Any]]:
    fields = [f for f in (await svc.setting("faculty_directory_fields") or []) if f in DIRECTORY_COLUMNS]
    opt_out = [str(x) for x in (await svc.setting("faculty_directory_opt_out") or [])]
    if not fields:
        return []
    cols = ", ".join(f"{DIRECTORY_COLUMNS[f]} AS {f}" for f in fields)
    rows = await svc.db.execute(
        text(
            f"SELECT {cols} FROM staff s LEFT JOIN designations dg ON dg.id = s.designation_id "  # noqa: S608 - allow-listed
            "LEFT JOIN departments d ON d.id = s.department_id LEFT JOIN faculty_profiles fp ON fp.staff_id = s.id "
            "WHERE s.institution_id = :i AND s.deleted_at IS NULL AND s.status = 'active' AND s.staff_category = 'teaching' "
            "AND NOT (CAST(s.id AS text) = ANY(:o)) ORDER BY d.name NULLS LAST, s.first_name LIMIT 500"
        ),
        {"i": svc.inst, "o": opt_out},
    )
    return [dict(r) for r in rows.mappings().all()]


async def disclosures(svc: Any) -> list[dict[str, Any]]:
    items = (await svc.meta("disclosures", {}) or {}).get("items") or []
    out: list[dict[str, Any]] = []
    for it in items:
        if not it.get("is_published"):
            continue
        value: Any = it.get("text")
        if it.get("source") == "metric" and it.get("ref"):
            r = (
                await svc.db.execute(
                    text(
                        "SELECT value, period_label FROM metric_values WHERE institution_id = :i AND metric_key = :k "
                        "AND college_id IS NULL AND program_id IS NULL ORDER BY computed_at DESC NULLS LAST LIMIT 1"
                    ),
                    {"i": svc.inst, "k": it["ref"]},
                )
            ).first()
            value = {"value": r[0], "period": r[1]} if r else None
        elif it.get("source") in ("policy", "document"):
            value = {"url": it.get("ref")}
        out.append(
            {
                "key": it.get("key"),
                "title": it.get("title") or it.get("key"),
                "source": it.get("source"),
                "value": value,
            }
        )
    return out


async def admissions(svc: Any) -> PublicAdmissionsOut:
    rows = (
        (
            await svc.db.execute(
                text(
                    "SELECT c.slug, c.name, c.level, c.application_fee_paise, c.opens_at, c.closes_at, c.status, "
                    "c.required_documents, (SELECT json_agg(json_build_object('code', p.code, 'name', p.name, 'intake', acp.intake)) "
                    "FROM admission_cycle_programs acp JOIN programs p ON p.id = acp.program_id WHERE acp.cycle_id = c.id) AS programmes "
                    "FROM admission_cycles c WHERE c.institution_id = :i AND c.deleted_at IS NULL "
                    "AND c.status IN ('open', 'scheduled', 'published', 'closed') ORDER BY c.opens_at DESC NULLS LAST LIMIT 50"
                ),
                {"i": svc.inst},
            )
        )
        .mappings()
        .all()
    )
    now = datetime.now().astimezone()
    out = PublicAdmissionsOut(open=[], upcoming=[], closed=[])
    for r in rows:
        d = dict(r)
        opens, closes = d.get("opens_at"), d.get("closes_at")
        if d["status"] == "open" and (closes is None or closes > now):
            d["apply_url"] = f"/apply/{d['slug']}"
            out.open.append(d)
        elif opens and opens > now:
            out.upcoming.append(d)
        else:
            out.closed.append(d)
    return out


async def affiliated_colleges(svc: Any, code: str | None = None) -> list[dict[str, Any]]:
    if not await is_enabled(svc.inst, "affiliation.core"):
        raise APIError(404, ErrorCode.NOT_FOUND, "Not available")
    rows = (
        (
            await svc.db.execute(
                text(
                    "SELECT c.code, c.name, c.college_type AS institution_type, json_agg(json_build_object('programme', p.code, 'name', p.name, "
                    "'intake', a.sanctioned_intake, 'valid_to', a.valid_to, 'order_no', a.order_no)) AS programmes "
                    "FROM affiliation_program_approvals a JOIN colleges c ON c.id = a.college_id JOIN programs p ON p.id = a.program_id "
                    "WHERE a.institution_id = :i AND a.approval_status = 'approved' AND (a.valid_to IS NULL OR a.valid_to >= CURRENT_DATE) "
                    + ("AND c.code = :c " if code else "")
                    + "GROUP BY c.code, c.name, c.college_type ORDER BY c.name"
                ),
                {"i": svc.inst, "c": (code or "").upper()},
            )
        )
        .mappings()
        .all()
    )
    if code and not rows:
        raise APIError(404, ErrorCode.NOT_FOUND, "College not found")
    return [dict(r) for r in rows]
