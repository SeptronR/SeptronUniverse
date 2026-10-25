"""Phase 03 platform seeds and per-institution defaults — Prompts/03 §03.2 and §03.6 ``seed_institution_defaults``.

Two layers, same pattern as ``install_service`` (synchronous connection → usable from Alembic, ``seed_platform.py`` and
``/install``; the async services call them through ``AsyncConnection.run_sync``):

* **platform** (revision ``0003_phase03_settings_seed``): ``platform_settings['settings_template']``,
  ``['theme_tokens']``, ``['theme_default']`` and ``['number_sequence_template']`` from ``app/core/settings_template.py``,
  plus the Phase 03 grant backfill (``institutions:view`` for the roles already cloned into tenants);
* **institution** (``seed_institution_defaults(conn, institution_id, pack)``, called by onboarding and the demo
  seeder): every template setting with a non-null default as an ``institution_settings`` row (``college_id`` NULL),
  the pack's default grading scales (``grading_scales``, institution-wide — ``regulation_id`` NULL) and the
  institution-wide number sequences. Idempotent (``ON CONFLICT DO NOTHING`` / existence checks).

Pack assets owned by later phases are **not** copied here: assessment schemes need a regulation (``assessment_schemes
.regulation_id`` NOT NULL — Phase 05 seeds them from ``pack.default_assessment_schemes`` when the first regulation is
created); accreditation frameworks are platform rows seeded by the canonical DDL (§36.4); document / notification
templates arrive with Phase 26 (Phase 04 ships the platform notification templates and copies the 18 workflow
templates into ``workflow_definitions``). ``seed_institution_defaults`` reports the deferred assets.
"""

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.packs import get_pack
from app.core.rbac.registry import BACKFILL_GRANTS, template_permissions
from app.core.settings_template import (
    NUMBER_SEQUENCE_TEMPLATE,
    PLATFORM_THEME_DEFAULT,
    SETTINGS_TEMPLATE,
    THEME_TOKENS,
    sequence_template_json,
    template_json,
)


def _put_platform_setting(conn: Connection, key: str, value: Any) -> None:
    conn.execute(
        text(
            "INSERT INTO platform_settings (key, value) VALUES (:k, CAST(:v AS jsonb)) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()"
        ),
        {"k": key, "v": json.dumps(value)},
    )


def seed_phase03_platform(conn: Connection) -> dict[str, int]:
    """Platform templates of Phase 03 (idempotent; the code registry wins over a stale stored copy)."""
    _put_platform_setting(conn, "settings_template", template_json())
    _put_platform_setting(conn, "theme_tokens", THEME_TOKENS)
    _put_platform_setting(conn, "theme_default", PLATFORM_THEME_DEFAULT)
    _put_platform_setting(conn, "number_sequence_template", sequence_template_json())
    return {
        "settings_keys": len(SETTINGS_TEMPLATE),
        "themes": len(THEME_TOKENS),
        "sequence_patterns": len(NUMBER_SEQUENCE_TEMPLATE),
    }


def backfill_role_grants(conn: Connection, revision: str) -> int:
    """Add the grants a revision introduced to the tenant system roles whose template carries them."""
    keys = BACKFILL_GRANTS.get(revision, frozenset())
    added = 0
    for key in sorted(keys):
        module, action = key.split(":", 1)
        perm = conn.execute(
            text("SELECT id FROM permissions WHERE module = :m AND action = :a"), {"m": module, "a": action}
        ).first()
        if perm is None:
            continue
        slugs = [s for s in _template_slugs(conn) if key in template_permissions(s)]
        if not slugs:
            continue
        res = conn.execute(
            text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "SELECT r.id, :p FROM roles r WHERE r.institution_id IS NOT NULL AND r.is_system "
                "AND r.deleted_at IS NULL AND r.slug = ANY(:slugs) ON CONFLICT DO NOTHING"
            ),
            {"p": perm[0], "slugs": slugs},
        )
        added += res.rowcount or 0
    return added


def _template_slugs(conn: Connection) -> list[str]:
    from app.core.rbac.registry import ROLE_TEMPLATES

    return [slug for slug in ROLE_TEMPLATES if slug != "super_admin"]


def seed_institution_defaults(
    conn: Connection, institution_id: uuid.UUID | str, pack_code: str | None
) -> dict[str, Any]:
    """Settings rows, pack grading scales and number sequences for one institution (Prompts/03 §03.6 rule 2)."""
    pack = get_pack(pack_code)
    iid = str(institution_id)
    settings_rows = [
        {
            "i": iid,
            "c": d.category,
            "k": d.key,
            "v": json.dumps(_pack_default(d.category, d.key, d.default, pack)),
            "t": d.value_type,
            "p": d.is_public,
        }
        for d in SETTINGS_TEMPLATE
        if _pack_default(d.category, d.key, d.default, pack) is not None
    ]
    created_settings = 0
    for row in settings_rows:
        # the table's UNIQUE (institution_id, college_id, category, key) does not fire for NULL college_id — check first
        exists = conn.execute(
            text(
                "SELECT 1 FROM institution_settings WHERE institution_id = :i AND college_id IS NULL "
                "AND category = :c AND key = :k"
            ),
            row,
        ).first()
        if exists is None:
            conn.execute(
                text(
                    "INSERT INTO institution_settings (institution_id, college_id, category, key, value, value_type, is_public) "
                    "VALUES (:i, NULL, :c, :k, CAST(:v AS jsonb), :t, :p)"
                ),
                row,
            )
            created_settings += 1
    scales = 0
    for n, scale in enumerate(pack.default_grading_scales):
        ranges = [{"grade": b["grade"], "min_pct": b["min_pct"], "grade_point": b["points"]} for b in scale.bands]
        res = conn.execute(
            text(
                "INSERT INTO grading_scales (institution_id, name, scale_type, ranges, max_grade_point, is_default) "
                "VALUES (:i, :n, 'absolute', CAST(:r AS jsonb), :mx, :d) ON CONFLICT (institution_id, name) DO NOTHING"
            ),
            {
                "i": iid,
                "n": scale.name[:80],
                "r": json.dumps(ranges),
                "mx": max(b["points"] for b in scale.bands),
                "d": n == 0,
            },
        )
        scales += res.rowcount or 0
    sequences = 0
    for s in NUMBER_SEQUENCE_TEMPLATE:
        exists = conn.execute(
            text("SELECT 1 FROM number_sequences WHERE institution_id = :i AND college_id IS NULL AND scope_key = :k"),
            {"i": iid, "k": s.scope_key},
        ).first()
        if exists is None:
            conn.execute(
                text(
                    "INSERT INTO number_sequences (institution_id, college_id, scope_key, pattern, next_value, padding, reset_policy) "
                    "VALUES (:i, NULL, :k, :p, 1, :pad, :r)"
                ),
                {"i": iid, "k": s.scope_key, "p": s.pattern, "pad": s.padding, "r": s.reset_policy},
            )
            sequences += 1
    workflows = seed_workflow_definitions(conn, iid)  # Phase 04
    hr = seed_hr_defaults(conn, iid, pack.code)  # Phase 06
    from app.services.fees.defaults import seed_fee_defaults

    fees = seed_fee_defaults(conn, iid)  # Phase 12
    return {
        "pack": pack.code,
        "workflow_definitions": workflows,
        "hr": hr,
        "fees": fees,
        "settings": created_settings,
        "grading_scales": scales,
        "number_sequences": sequences,
        "deferred": ["assessment_schemes (Phase 05)", "document templates (Phase 26)"],
        "frameworks": [f.code for f in pack.accreditation_frameworks],
    }


def _pack_default(category: str, key: str, default: Any, pack: Any) -> Any:
    """Pack-specific defaults over the template (quiet hours, retention, academic minimums, GST)."""
    if category == "communication" and key == "quiet_hours" and pack.comms_compliance.quiet_hours:
        start, end = pack.comms_compliance.quiet_hours
        return {"start": f"{start:02d}:00", "end": f"{end:02d}:00"}
    if category == "academics" and key == "attendance_min_pct_default":
        return pack.default_regulation_rules.get("attendance_min_pct", default)
    if category == "fees" and key == "gst_enabled":
        return pack.tax.tax_name == "GST"
    if category == "hr" and key == "workload_norms":
        return dict(pack.hr.workload_norms) or default
    if category == "hr" and key == "week_offs":
        return list(pack.hr.week_offs)
    if category == "payroll" and key == "pt_state":
        return (pack.hr.statutory.get("pt") or {}).get("default_state", default)
    return default


# ---- Phase 04: notification templates + workflow templates ------------------------------------------------------------
def seed_phase04_platform(conn: Connection) -> dict[str, int]:
    """Platform notification templates (``institution_id`` NULL, one row per event × language, version 1) and
    ``platform_settings['workflow_templates']`` — Prompts/04 §04.2. Existing rows are left untouched (operators may
    have edited the platform copy)."""
    from app.core.notifications.catalogue import EVENTS
    from app.core.workflow.templates import WORKFLOW_TEMPLATES

    created = 0
    for ev in EVENTS:
        for lang, body in (("en", ev.body), ("hi", ev.hi_body)):
            if body is None:
                continue
            exists = conn.execute(
                text(
                    "SELECT 1 FROM notification_templates WHERE institution_id IS NULL AND event_trigger = :e "
                    "AND language = :l"
                ),
                {"e": ev.key, "l": lang},
            ).first()
            if exists is not None:
                continue
            conn.execute(
                text(
                    "INSERT INTO notification_templates (institution_id, event_trigger, name, channels, subject_template, "
                    "body_template, variables, language, version, is_active) VALUES (NULL, :e, :n, CAST(:c AS jsonb), :s, "
                    ":b, CAST(:v AS jsonb), :l, 1, TRUE)"
                ),
                {
                    "e": ev.key,
                    "n": ev.name,
                    "c": json.dumps(list(ev.channels)),
                    "s": ev.subject,
                    "b": body,
                    "v": json.dumps(list(ev.variables)),
                    "l": lang,
                },
            )
            created += 1
    _put_platform_setting(conn, "workflow_templates", list(WORKFLOW_TEMPLATES))
    return {"notification_templates": created, "workflow_templates": len(WORKFLOW_TEMPLATES)}


def seed_workflow_definitions(conn: Connection, institution_id: uuid.UUID | str) -> int:
    """Copy every shipped workflow template missing in the institution as version 1 (idempotent)."""
    from app.core.workflow.templates import WORKFLOW_TEMPLATES

    created = 0
    for tmpl in WORKFLOW_TEMPLATES:
        exists = conn.execute(
            text("SELECT 1 FROM workflow_definitions WHERE institution_id = :i AND key = :k"),
            {"i": str(institution_id), "k": tmpl["key"]},
        ).first()
        if exists is not None:
            continue
        conn.execute(
            text(
                "INSERT INTO workflow_definitions (institution_id, module, key, name, steps, version, is_active) "
                "VALUES (:i, :m, :k, :n, CAST(:s AS jsonb), 1, TRUE)"
            ),
            {
                "i": str(institution_id),
                "m": tmpl["module"],
                "k": tmpl["key"],
                "n": tmpl["name"],
                "s": json.dumps(tmpl["steps"]),
            },
        )
        created += 1
    return created


# ---- Phase 06: HR templates (designations, leave types, payroll components) ---------------------------------------
def seed_hr_defaults(conn: Connection, institution_id: uuid.UUID | str, pack_code: str | None) -> dict[str, int]:
    """Copy the pack's designation, leave-type and payroll-component templates into one institution — Prompts/06
    §06.2 (idempotent: ``ON CONFLICT`` on each table's natural key; rows an institution edited are left alone)."""
    pack = get_pack(pack_code)
    iid = str(institution_id)
    out = {"designations": 0, "leave_types": 0, "payroll_components": 0}
    for d in pack.hr.designations:
        res = conn.execute(
            text(
                "INSERT INTO designations (institution_id, name, code, cadre, category, level) "
                "VALUES (:i, :n, :c, :cadre, :cat, :lvl) ON CONFLICT (institution_id, name) DO NOTHING"
            ),
            {
                "i": iid,
                "n": d["name"],
                "c": d.get("code"),
                "cadre": d.get("cadre"),
                "cat": d["category"],
                "lvl": d.get("level"),
            },
        )
        out["designations"] += res.rowcount or 0
    for t in pack.hr.leave_types:
        res = conn.execute(
            text(
                "INSERT INTO leave_types (institution_id, code, name, annual_quota, accrual, carry_forward_max, is_paid, "
                "is_encashable, requires_document, applies_to) VALUES (:i, :code, :name, :q, :acc, :cf, :paid, :enc, :doc, "
                "CAST(:ap AS jsonb)) ON CONFLICT (institution_id, code) DO NOTHING"
            ),
            {
                "i": iid,
                "code": t["code"],
                "name": t["name"],
                "q": t.get("annual_quota"),
                "acc": t.get("accrual", "yearly"),
                "cf": t.get("carry_forward_max"),
                "paid": t.get("is_paid", True),
                "enc": t.get("is_encashable", False),
                "doc": t.get("requires_document", False),
                "ap": json.dumps(t["applies_to"]) if t.get("applies_to") else None,
            },
        )
        out["leave_types"] += res.rowcount or 0
    for c in pack.hr.payroll_components:
        res = conn.execute(
            text(
                "INSERT INTO payroll_components (institution_id, code, name, component_type, calc_type, formula, "
                "is_statutory, statutory_kind, is_taxable, sequence) VALUES (:i, :code, :name, :ct, :calc, "
                "CAST(:f AS jsonb), :st, :kind, :tax, :seq) ON CONFLICT (institution_id, code) DO NOTHING"
            ),
            {
                "i": iid,
                "code": c["code"],
                "name": c["name"],
                "ct": c["component_type"],
                "calc": c.get("calc_type", "fixed"),
                "f": json.dumps(c["formula"]) if c.get("formula") is not None else None,
                "st": c.get("calc_type") == "statutory",
                "kind": c.get("statutory_kind"),
                "tax": c.get("is_taxable", True),
                "seq": c.get("sequence", 1),
            },
        )
        out["payroll_components"] += res.rowcount or 0
    return out


# ---- Phase 07: undertaking + ID-card document templates (platform rows) -----------------------------------------------
ID_CARD_HTML = (
    '<div class="card"><header><strong>{{ institution }}</strong><br><small>{{ college }}</small></header>'
    '<img class="photo" src="{{ photo_url }}" alt=""><h2>{{ name }}</h2>'
    "<dl><dt>Reg. no</dt><dd>{{ registration_number }}</dd><dt>Programme</dt><dd>{{ program }}</dd>"
    "<dt>Batch</dt><dd>{{ batch }}</dd><dt>Blood group</dt><dd>{{ blood_group }}</dd>"
    "<dt>Valid until</dt><dd>{{ valid_until }}</dd></dl>"
    '<img class="qr" src="{{ qr_data_url }}" alt="QR"></div>'
)
ID_CARD_VARIABLES = [
    "institution",
    "college",
    "name",
    "registration_number",
    "program",
    "batch",
    "blood_group",
    "valid_until",
    "photo_url",
    "qr_data_url",
]
UNDERTAKING_VARIABLES = ["student_name", "registration_number", "institution_name", "program_name", "academic_year"]


def seed_student_templates(conn: Connection) -> int:
    """Platform ``document_templates`` (``institution_id`` NULL) — one ``undertaking`` row per pack undertaking and an
    ``id_card`` row (Prompts/07 §07.2). ``layout`` carries ``{undertaking_type, pack, text_version}`` so the service
    picks the institution's pack; existing rows are left untouched (Phase 26 owns template editing)."""
    created = 0
    for pack_code in ("IN", "GENERIC"):
        pack = get_pack(pack_code)
        for kind, spec in pack.students.undertakings.items():
            exists = conn.execute(
                text(
                    "SELECT 1 FROM document_templates WHERE institution_id IS NULL AND template_type = 'undertaking' "
                    "AND layout->>'undertaking_type' = :k AND layout->>'pack' = :p"
                ),
                {"k": kind, "p": pack.code},
            ).first()
            if exists is not None:
                continue
            conn.execute(
                text(
                    "INSERT INTO document_templates (institution_id, template_type, name, layout, html_template, "
                    "variables, is_default, version, is_active) VALUES (NULL, 'undertaking', :n, CAST(:l AS jsonb), :b, "
                    "CAST(:v AS jsonb), TRUE, 1, TRUE)"
                ),
                {
                    "n": spec["name"][:120],
                    "l": json.dumps({"undertaking_type": kind, "pack": pack.code, "text_version": spec["version"]}),
                    "b": spec["body"],
                    "v": json.dumps(UNDERTAKING_VARIABLES),
                },
            )
            created += 1
    exists = conn.execute(
        text("SELECT 1 FROM document_templates WHERE institution_id IS NULL AND template_type = 'id_card'")
    ).first()
    if exists is None:
        conn.execute(
            text(
                "INSERT INTO document_templates (institution_id, template_type, name, layout, html_template, css, "
                "page_size, variables, is_default, version, is_active) VALUES (NULL, 'id_card', "
                "'Student ID card (CR80)', CAST(:l AS jsonb), :h, :c, 'ID_CR80', CAST(:v AS jsonb), TRUE, 1, TRUE)"
            ),
            {
                "l": json.dumps({"variant": "student", "size": "CR80"}),
                "h": ID_CARD_HTML,
                "c": "@page{size:85.6mm 54mm;margin:0}.card{font:7pt sans-serif}.qr{width:22mm;float:right}",
                "v": json.dumps(ID_CARD_VARIABLES),
            },
        )
        created += 1
    return created


ADMISSION_FORM_TEMPLATE: dict[str, Any] = {
    "steps": ["account", "personal", "qualifications", "preferences", "documents", "review", "pay"],
    "fields": {
        "personal": [
            "first_name",
            "last_name",
            "dob",
            "gender",
            "category",
            "is_pwd",
            "quota_claimed",
            "domicile_state",
        ],
        "contact": ["phone", "email", "address", "guardian_name", "guardian_relation", "guardian_phone"],
        "qualifications": ["qualifying_exams", "entrance"],
    },
    "max_preferences": 5,
    "strict_eligibility": False,
    "refund_policy": {"processing_fee_paise": 50000, "after_acceptance_pct": 50},
    "required_documents": {
        "ug": [
            {"doc_type": "photo", "label": "Photograph", "required": True},
            {"doc_type": "marksheet_12", "label": "Class XII marksheet", "required": True},
            {"doc_type": "marksheet_10", "label": "Class X marksheet", "required": True},
            {"doc_type": "category_certificate", "label": "Category certificate", "required": False},
            {
                "doc_type": "diploma_certificate",
                "label": "Diploma certificate",
                "required": True,
                "entry_types": ["lateral"],
            },
        ],
        "pg": [
            {"doc_type": "photo", "label": "Photograph", "required": True},
            {"doc_type": "degree_certificate", "label": "Degree certificate", "required": True},
            {"doc_type": "marksheet_ug", "label": "UG marksheets", "required": True},
            {"doc_type": "entrance_scorecard", "label": "Entrance score card", "required": False},
        ],
        "phd": [
            {"doc_type": "photo", "label": "Photograph", "required": True},
            {"doc_type": "degree_certificate", "label": "PG degree certificate", "required": True},
            {"doc_type": "research_proposal", "label": "Research proposal", "required": True},
        ],
    },
}


def seed_admission_form_template(conn: Connection) -> None:
    """``platform_settings['admission_form_template']`` — the default ``form_config`` / required documents by level
    a new admission cycle starts from (Prompts/08 §08.2)."""
    _put_platform_setting(conn, "admission_form_template", ADMISSION_FORM_TEMPLATE)


def seed_document_templates(conn: Connection) -> int:
    """Phase 26 platform ``document_templates`` (``institution_id`` NULL): one default per ``template_type`` (layout
    blocks + compiled HTML + CSS + variables catalogue), IN-pack bilingual variants (``secondary_language='hi'``) and
    staff / scholar ID-card variants. Existing platform rows of a type / variant are left untouched."""
    from app.services.documents.defaults import platform_defaults

    created = 0
    for d in platform_defaults():
        variant = (d["layout"] or {}).get("variant")
        exists = conn.execute(
            text(
                "SELECT 1 FROM document_templates WHERE institution_id IS NULL AND template_type = :t "
                "AND is_bilingual = :b AND COALESCE(layout->>'variant', '') = :v"
            ),
            {"t": d["template_type"], "b": d["is_bilingual"], "v": variant or ""},
        ).first()
        if exists is not None:
            continue
        conn.execute(
            text(
                "INSERT INTO document_templates (institution_id, template_type, name, layout, html_template, css, "
                "page_size, is_bilingual, secondary_language, variables, is_default, version, is_active) VALUES "
                "(NULL, :t, :n, CAST(:l AS jsonb), :h, :c, :p, :b, :s, CAST(:v AS jsonb), :d, 1, TRUE)"
            ),
            {
                "t": d["template_type"],
                "n": d["name"],
                "l": json.dumps(d["layout"]),
                "h": d["html_template"],
                "c": d["css"],
                "p": d["page_size"],
                "b": d["is_bilingual"],
                "s": d["secondary_language"],
                "v": json.dumps(d["variables"]),
                "d": not d["is_bilingual"] and variant in (None, "student"),
            },
        )
        created += 1
    return created
