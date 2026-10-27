"""Shared plumbing of the Phase 36 services — the ``report_repository`` of Prompts/36 §36.5.

On the Phase 35 :class:`~app.services.analytics.common.AnalyticsBase`: ``resolve_scope(module, requested)`` gives the
:class:`~app.core.charts.ResolvedScope` of a report's **source module** (never wider than the caller's
``meta.visibility``; ``?scope=all`` from an HOD silently becomes ``department``), and providers narrow every query with
it. Here:

* report access = ``reports:run`` (``reports:view`` for the catalogue) **and** one of the report's module permissions,
  with the report's feature on (403 ``FEATURE_DISABLED`` otherwise);
* scope parameters (``college_id`` / ``department_id`` / ``program_id`` / ``batch_id``) are narrowed silently: a
  college admin of B asking for college A gets B; an HOD's department pick outside their departments is dropped;
* PII columns are masked (``mask_value``) unless the caller holds ``<module>:view_pii``;
* report runs are ``background_jobs`` rows (``job_type`` in ``REPORT_JOB_TYPES``) — self predicate ``requested_by``,
  ``reports:view_all`` / ``reports:manage`` / auditor for all;
* side store (``institution_settings`` category ``reports_meta`` — ``reports`` holds the typed settings): ``schedule:<id>``, ``saved:<id>``, ``statutory:<code>:
  <period>[:<discipline>]``; favourites / recent runs in ``users.preferences['reports']``;
* files: per-tenant prefix ``reports/``, signed URLs valid for ``reports.retention_days`` (``reports.retention_purge``
  deletes them after that; the run row keeps its checksum).
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select

from app.core.authz.masking import mask_value
from app.core.charts import ResolvedScope
from app.core.errors import APIError, ErrorCode
from app.core.reports import MODEL_REGISTRY, REPORT_REGISTRY, ReportColumn, ReportDef
from app.models.platform import BackgroundJob, User
from app.models.reports import REPORT_JOB_TYPES
from app.services.analytics.common import AnalyticsBase, forbidden, is_auditor, not_found, now_utc, rule, scope_ids

__all__ = [
    "ReportsBase",
    "ensure_registry",
    "forbidden",
    "is_auditor",
    "not_found",
    "now_utc",
    "rule",
]

META = "reports_meta"
PII_KIND = {"phone": "phone", "mobile": "phone", "email": "email", "aadhaar": "generic", "pan": "generic"}


def ensure_registry() -> None:
    """Import the registrations once (module reports, registers, legacy aliases, builder models)."""
    import app.services.reports.catalogue  # noqa: F401
    import app.services.reports.models  # noqa: F401


class ReportsBase(AnalyticsBase):
    audit_module = "reports"
    module = "reports"
    meta_category = META

    # ---- permissions ----------------------------------------------------------------------------------------------------
    def is_admin(self) -> bool:
        p = self.principal
        return p is None or getattr(p, "is_super_admin", False) or bool(p.has("reports", "manage"))

    def sees_all_runs(self) -> bool:
        p = self.principal
        return self.is_admin() or bool(p.has("reports", "view_all")) or is_auditor(p)

    def require_catalogue(self) -> None:
        if not (self.can("reports", "view") or self.can("reports", "run")):
            raise forbidden("reports:view required")

    def require_run(self) -> None:
        if not self.can("reports", "run"):
            raise forbidden("reports:run required")

    def require_writer(self) -> None:
        """Auditors read and run, never write (saved reports, schedules, shares)."""
        if is_auditor(self.principal) and not self.is_admin():
            raise forbidden("Auditors have read-only access to reports")

    async def visible_def(self, d: ReportDef) -> bool:
        return self.holds_any(d.permission) if d.permission else True

    async def report_def(self, key: str) -> ReportDef:
        ensure_registry()
        d = REPORT_REGISTRY.get(key)
        if d is None:
            raise not_found("Report")
        if d.feature and not await self.feature_on(d.feature):
            raise APIError(
                403, ErrorCode.FEATURE_DISABLED, f"Feature {d.feature} is not enabled", {"feature": d.feature}
            )
        if not await self.visible_def(d):
            raise forbidden(f"{' | '.join(d.permission)} required for {key}")
        return d

    # ---- scope ----------------------------------------------------------------------------------------------------------
    async def scope_for(self, d: ReportDef, requested: str | None = None) -> ResolvedScope:
        return await self.resolve_scope(d.module, requested)

    async def narrow_params(self, scope: ResolvedScope, params: dict[str, Any]) -> dict[str, Any]:
        """Drop / replace scope picks outside the caller's reach (silent, like ``?scope=``)."""
        out = dict(params)
        cid = out.get("college_id")
        if scope.level == "college":
            allowed = [str(c) for c in scope.college_ids]
            if cid and str(cid) not in allowed:
                out["college_id"] = allowed[0] if len(allowed) == 1 else None
        did = out.get("department_id")
        if scope.level == "department" and did and str(did) not in {str(d) for d in scope.department_ids}:
            out["department_id"] = None
        return {k: v for k, v in out.items() if v not in (None, "")}

    # ---- masking ----------------------------------------------------------------------------------------------------------
    def masked_columns(self, module: str, columns: list[ReportColumn]) -> list[str]:
        p = self.principal
        if p is None or getattr(p, "is_super_admin", False) or p.has(module, "view_pii"):
            return []
        return [c.key for c in columns if c.pii]

    def apply_mask(self, rows: list[dict[str, Any]], masked: list[str]) -> list[dict[str, Any]]:
        if not masked:
            return rows
        return [
            {k: (mask_value(v, PII_KIND.get(k.split(".")[-1], "generic")) if k in masked else v) for k, v in r.items()}
            for r in rows
        ]

    # ---- side store ---------------------------------------------------------------------------------------------------------
    async def r_setting(self, key: str, default: Any) -> Any:
        return await self.a_setting("reports", key, default)

    async def header(self, title: str, scope: ResolvedScope | None, params: dict[str, Any]) -> dict[str, Any]:
        from app.models.platform import InstitutionProfile

        inst = await self.institution()
        prof = (
            await self.db.execute(select(InstitutionProfile).where(InstitutionProfile.institution_id == self.inst))
        ).scalar_one_or_none()
        who = (await self.user_display([self.actor_id])).get(self.actor_id) if self.actor_id else None
        return {
            "institution": inst.name,
            "address": None,
            "logo": getattr(prof, "letterhead_url", None) or getattr(inst, "logo_url", None),
            "title": title,
            "scope": f"Scope: {scope.level}" if scope else None,
            "generated_by": f"Generated by {who}" if who else "Generated by the system",
            "generated_on": f"on {(await self.today()).isoformat()}",
            "draft": bool(params.get("draft")),
        }

    async def upload(self, folder: str, filename: str, content: bytes, mime: str) -> tuple[str, str]:
        """→ (storage key, signed URL valid for the retention window)."""
        from app.core.files import build_key, get_storage

        days = int(await self.r_setting("retention_days", 30) or 30)
        key = build_key(self.inst, f"reports/{folder}", filename)
        storage = get_storage()
        await storage.put(key, content, mime)
        return key, storage.signed_url(key, days * 86400)

    # ---- preferences ------------------------------------------------------------------------------------------------------
    async def prefs(self) -> dict[str, Any]:
        if self.actor_id is None:
            return {}
        v = (await self.db.execute(select(User.preferences).where(User.id == self.actor_id))).scalar_one_or_none()
        return dict((v or {}).get("reports") or {})

    async def put_prefs(self, value: dict[str, Any]) -> None:
        if self.actor_id is None:
            raise forbidden()
        user = (await self.db.execute(select(User).where(User.id == self.actor_id).with_for_update())).scalar_one()
        prefs = dict(user.preferences or {})
        prefs["reports"] = value
        user.preferences = prefs
        await self.db.flush()

    async def remember_run(self, key: str, job_id: uuid.UUID | None) -> None:
        p = await self.prefs()
        recent = [r for r in p.get("recent") or [] if r.get("key") != key]
        recent.insert(0, {"key": key, "job_id": str(job_id) if job_id else None, "at": now_utc().isoformat()})
        p["recent"] = recent[:20]
        await self.put_prefs(p)

    # ---- runs ---------------------------------------------------------------------------------------------------------------
    def runs_query(self, mine: bool) -> Any:
        stmt = select(BackgroundJob).where(
            BackgroundJob.institution_id == self.inst, BackgroundJob.job_type.in_(REPORT_JOB_TYPES)
        )
        if mine or not self.sees_all_runs():
            stmt = stmt.where(BackgroundJob.requested_by == self.actor_id)
        return stmt

    async def run_row(self, job_id: uuid.UUID) -> BackgroundJob:
        j: BackgroundJob | None = (
            await self.db.execute(self.runs_query(False).where(BackgroundJob.id == job_id))
        ).scalar_one_or_none()
        if j is None:
            raise not_found("Report run")
        return j

    async def role_holders(self, slug: str) -> list[uuid.UUID]:
        """Users holding a role (or a sign-off alias such as ``principal``) in this institution."""
        from app.enums.reports import ROLE_ALIASES

        out: list[uuid.UUID] = []
        for s in ROLE_ALIASES.get(slug, (slug,)):
            out += [u for u in await self.role_users(s) if u not in out]
        return out

    def holds_role(self, slug: str) -> bool:
        from app.enums.reports import ROLE_ALIASES

        held = set(self.roles())
        return bool(held & set(ROLE_ALIASES.get(slug, (slug,))))

    @staticmethod
    def utc(v: Any) -> datetime | None:
        if v in (None, ""):
            return None
        if isinstance(v, datetime):
            return v
        try:
            d = datetime.fromisoformat(str(v))
        except ValueError:
            return None
        return d if d.tzinfo else d.replace(tzinfo=UTC)


__all__ += ["MODEL_REGISTRY", "or_", "scope_ids"]
