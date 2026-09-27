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
    return {
        "pack": pack.code,
        "workflow_definitions": workflows,
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
