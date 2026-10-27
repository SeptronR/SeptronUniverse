"""Dashboard service (``core.dashboard``) — Prompts/35 §35.6 dashboard_service.

1. ``for_role``: the dashboard of the principal's highest role (multi-role users switch with ``?role=``), merged
   platform defaults (registry ← ``platform_settings['dashboards.defaults'][role]``) ← institution layout
   (``analytics_meta`` ``layout:<role>``) ← user pins / hidden (``users.preferences['dashboard']``); widgets whose
   permission / feature fail are dropped; stats batch-read from ``mv_kpi_daily`` (one query) at institution / college
   scope and from the scoped number charts otherwise; charts render one by one with a per-widget timeout (a slow or
   failing widget renders ``unavailable``, never blocks the page); ``meta.visibility`` scopes for the whole page;
   ``alerts[]`` = KPI breaches + pending approvals + read-only / maintenance notices.
2. Layout editor (``settings:manage``): reorder / resize / hide per role; reset to defaults.
3. Charts need ``analytics.core``: with it off the dashboard still renders stat cards and lists (charts ``unavailable``).
"""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text

from app.core.dashboards import ACTION_KEYS, DASHBOARD_REGISTRY, LIST_KEYS, STAT_KEYS, WidgetSpec
from app.core.errors import APIError
from app.models.platform import User
from app.services.analytics.chart_service import ChartService, ensure_catalogue
from app.services.analytics.common import AnalyticsBase, forbidden, rule
from app.services.analytics.kpi_service import KPI_TARGET_COLUMNS, KpiService

__all__ = ["DashboardService"]

WIDGET_TIMEOUT_S = 2.5
_TARGET_BY_COLUMN = {col: (k, d) for k, (col, d) in KPI_TARGET_COLUMNS.items()}


class DashboardService(AnalyticsBase):
    # ---- composition --------------------------------------------------------------------------------------------------
    async def defaults(self, role: str) -> list[WidgetSpec]:
        ensure_catalogue()
        base = list(
            DASHBOARD_REGISTRY.get(role) or DASHBOARD_REGISTRY.get("faculty" if self.staffish() else "student", [])
        )
        overrides = await self.platform_setting("dashboards.defaults")
        if isinstance(overrides, dict) and isinstance(overrides.get(role), list):
            keys = [str(k) for k in overrides[role]]
            by_key = {w.key: w for w in base}
            base = [by_key[k] for k in keys if k in by_key] + [w for w in base if w.key not in keys]
        return base

    async def institution_layout(self, role: str) -> dict[str, Any]:
        return await self.meta("layout", role)

    async def user_prefs(self) -> dict[str, Any]:
        if self.actor_id is None:
            return {}
        prefs = (await self.db.execute(select(User.preferences).where(User.id == self.actor_id))).scalar_one_or_none()
        d = (prefs or {}).get("dashboard") if isinstance(prefs, dict) else None
        return d if isinstance(d, dict) else {}

    async def compose(self, role: str, *, with_user: bool = True) -> tuple[list[WidgetSpec], dict[str, Any]]:
        widgets = await self.defaults(role)
        layout = await self.institution_layout(role)
        sizes: dict[str, str] = {}
        if layout.get("widgets"):
            order = [w["key"] for w in layout["widgets"] if not w.get("hidden")]
            hidden = {w["key"] for w in layout["widgets"] if w.get("hidden")}
            sizes = {w["key"]: w.get("size") for w in layout["widgets"] if w.get("size")}
            by_key = {w.key: w for w in widgets}
            widgets = [by_key[k] for k in order if k in by_key] + [
                w for w in widgets if w.key not in order and w.key not in hidden
            ]
        if with_user:
            prefs = await self.user_prefs()
            pinned = [k for k in prefs.get("pinned_keys", []) if isinstance(k, str)]
            hidden_u = set(prefs.get("hidden_keys", []))
            by_key = {w.key: w for w in widgets}
            widgets = [by_key[k] for k in pinned if k in by_key] + [w for w in widgets if w.key not in pinned]
            widgets = [w for w in widgets if w.key not in hidden_u]
        return widgets, {"columns": int(layout.get("columns") or 4), "sizes": sizes}

    def _permission_ok(self, w: WidgetSpec) -> tuple[bool, tuple[str, ...], str | None]:
        from app.core.charts import CHART_REGISTRY

        perms: tuple[str, ...] = w.permission
        feature = w.feature
        if not perms:
            if w.chart_key and w.chart_key in CHART_REGISTRY:
                perms = CHART_REGISTRY[w.chart_key].permission
                feature = feature or CHART_REGISTRY[w.chart_key].feature
            elif w.stat_key and w.stat_key in STAT_KEYS:
                perms = STAT_KEYS[w.stat_key].permission
                feature = feature or STAT_KEYS[w.stat_key].feature
            elif w.list_key and w.list_key in LIST_KEYS:
                perms = LIST_KEYS[w.list_key].permission
                feature = feature or LIST_KEYS[w.list_key].feature
            elif w.action_key and w.action_key in ACTION_KEYS:
                perms = ACTION_KEYS[w.action_key].permission
                feature = feature or ACTION_KEYS[w.action_key].feature
        return self.holds_any(perms) if perms else True, perms, feature

    # ---- render -------------------------------------------------------------------------------------------------------
    async def for_role(
        self,
        role: str | None = None,
        scope: str | None = None,
        dims: dict[str, Any] | None = None,
        only: str | None = None,
    ) -> dict[str, Any]:
        if not self.can("dashboard", "view"):
            raise forbidden("dashboard:view required")
        chosen = self.primary_role(role)
        widgets, layout = await self.compose(chosen)
        analytics_on = await self.feature_on("analytics.core")
        dims = {k: v for k, v in (dims or {}).items() if v not in (None, "")}
        kpi_row = await self._kpi_for(scope)
        charts = ChartService(self.db, self.principal, self.request, self.inst)
        charts._own_cache = self._own_cache
        out_widgets: list[dict[str, Any]] = []
        for w in widgets:
            if only and w.key != only:
                continue
            ok, perms, feature = self._permission_ok(w)
            if not ok or not await self.feature_on(feature):
                continue
            item: dict[str, Any] = {
                "key": w.key,
                "kind": w.kind,
                "size": layout["sizes"].get(w.key) or w.size,
                "title": w.title,
                "permission_ok": True,
                "stale": False,
                "generated_at": datetime.now(UTC),
            }
            try:
                if w.stat_key:
                    item.update(
                        await asyncio.wait_for(self._stat(w.stat_key, kpi_row, charts, scope, dims), WIDGET_TIMEOUT_S)
                    )
                elif w.chart_key:
                    if not analytics_on:
                        item.update({"unavailable": True, "reason": "analytics.core is off"})
                    else:
                        data = await asyncio.wait_for(
                            charts.render(w.chart_key, scope=scope or w.default_scope, dims=dims), WIDGET_TIMEOUT_S
                        )
                        item.update(
                            {
                                "title": w.title or data.title,
                                "chart_kind": data.kind,
                                "data": data.__dict__,
                                "drilldown": data.drilldown,
                                "stale": data.stale,
                                "generated_at": data.generated_at,
                            }
                        )
                elif w.list_key:
                    ld = LIST_KEYS.get(w.list_key)
                    items = await asyncio.wait_for(ld.provider(self), WIDGET_TIMEOUT_S) if ld and ld.provider else []
                    item.update(
                        {
                            "title": w.title or (ld.title if ld else w.key),
                            "items": items,
                            "route": ld.route if ld else None,
                        }
                    )
                elif w.action_key:
                    ad = ACTION_KEYS.get(w.action_key)
                    item.update(
                        {
                            "title": w.title or (ad.label if ad else w.key),
                            "route": ad.route if ad else None,
                            "icon": ad.icon if ad else None,
                        }
                    )
            except TimeoutError:
                item.update({"unavailable": True, "reason": "timeout"})
            except APIError as exc:
                item.update({"unavailable": True, "reason": exc.message})
            except Exception as exc:  # noqa: BLE001 - one broken widget never blocks the page
                item.update({"unavailable": True, "reason": type(exc).__name__})
            out_widgets.append(item)
        targets = await KpiService(self.db, self.principal, self.request, self.inst).targets(self._single_college())
        return {
            "role": chosen,
            "roles": [r for r in self.roles() if r in DASHBOARD_REGISTRY],
            "layout": {
                "columns": layout["columns"],
                "widgets": [{"key": w["key"], "size": w["size"], "position": i} for i, w in enumerate(out_widgets)],
            },
            "widgets": out_widgets,
            "targets": targets,
            "alerts": await self.alerts(),
            "visibility": self.visibility_meta(self._page_module(chosen)),
            "risk": await self._own_risk() if self.is_student() else None,
        }

    def _page_module(self, role: str) -> str:
        return {
            "accountant": "fees",
            "hr_officer": "hr",
            "admissions_officer": "admissions",
            "placement_officer": "placement",
            "hostel_warden": "hostel",
            "librarian": "library",
            "controller_of_examinations": "exams",
            "exam_cell": "exams",
            "research_cell": "research",
            "estate_officer": "facilities",
            "transport_manager": "transport",
            "alumni_coordinator": "alumni",
            "iqac_coordinator": "accreditation",
        }.get(role, "students")

    def _single_college(self) -> uuid.UUID | None:
        from app.services.analytics.common import scope_ids

        ids = [] if self.principal is None else scope_ids(self.principal, "college")
        return ids[0] if len(ids) == 1 and not self.all_access("students") else None

    async def _kpi_for(self, scope: str | None) -> dict[str, Any] | None:
        """``mv_kpi_daily`` row when the page scope is institution / college; ``None`` → scoped number charts."""
        resolved = await self.resolve_scope("students", scope)
        kpi = KpiService(self.db, self.principal, self.request, self.inst)
        try:
            if resolved.level == "all":
                return await kpi.row(None)
            if resolved.level == "college" and resolved.college_ids:
                return await kpi.rows_for(resolved.college_ids)
        except Exception:  # noqa: BLE001 - read model missing / not refreshed yet → per-stat fallback
            return None
        return None

    async def _stat(
        self, key: str, kpi_row: dict[str, Any] | None, charts: ChartService, scope: str | None, dims: dict[str, Any]
    ) -> dict[str, Any]:
        stat = STAT_KEYS.get(key)
        if stat is None:
            return {"unavailable": True, "reason": "unknown stat"}
        value: Any = None
        source = "mv_kpi_daily"
        resolved = await self.resolve_scope(stat.module, scope)
        if kpi_row and stat.column and resolved.level in ("all", "college") and not dims:
            value = kpi_row.get(stat.column)
            if stat.fmt == "inr" and value is not None:
                value = float(value) / 100.0
        elif stat.scoped_chart:
            data = await charts.render(stat.scoped_chart, scope=scope, dims=dims)
            source = stat.scoped_chart
            value = data.series[0].get("value") if data.series else 0
        else:
            return {"unavailable": True, "reason": "no scoped source", "label": stat.label}
        target_key = stat.target_key
        targets = await KpiService(self.db, self.principal, self.request, self.inst).targets(self._single_college())
        target = targets.get(target_key) if target_key else None
        spark: list[list[Any]] = []
        if stat.column and resolved.level in ("all", "college"):
            spark = await KpiService(self.db, self.principal, self.request, self.inst).history(
                stat.column, resolved.college_ids[0] if resolved.level == "college" and resolved.college_ids else None
            )
        delta = None
        if len(spark) >= 2 and spark[-2][1] is not None and value is not None:
            try:
                delta = round(float(value) - float(spark[-2][1]), 2)
            except (TypeError, ValueError):
                delta = None
        return {
            "title": stat.label,
            "stat": {
                "value": value,
                "format": stat.fmt,
                "target": target,
                "direction": stat.direction,
                "on_target": None
                if target is None or value is None
                else (float(value) >= float(target)) == (stat.direction == "higher"),
                "delta": delta,
                "sparkline": spark,
                "source": source,
                "scope": resolved.level,
                "class_average": await self._class_average(key) if self.is_student() or self.is_parent() else None,
            },
            "route": stat.route,
            "drilldown": {"route": stat.route} if stat.route else None,
        }

    async def _class_average(self, key: str) -> float | None:
        """Student / parent comparison: the batch average — never another student's numbers."""
        own = await self.own()
        ids = list(own["enrollments"])
        if not ids or key != "attendance_avg_pct":
            return None
        row = (
            await self.db.execute(
                text(
                    "SELECT ROUND(AVG(a.pct), 2) FROM mv_attendance_term a WHERE a.institution_id = :i AND a.batch_id IN "
                    "(SELECT batch_id FROM student_program_enrollments WHERE id = ANY(:e)) AND a.term_id IN "
                    "(SELECT id FROM academic_terms WHERE institution_id = :i AND is_current)"
                ),
                {"i": self.inst, "e": ids},
            )
        ).first()
        return float(row[0]) if row and row[0] is not None else None

    async def _own_risk(self) -> dict[str, Any] | None:
        """Own risk level only when ``risk.show_to_student`` (Phase 27 setting) and early warning is on."""
        if not await self.feature_on("analytics.early_warning") or not await self.a_setting(
            "risk", "show_to_student", False
        ):
            return None
        own = await self.own()
        if not own["enrollments"]:
            return None
        row = (
            await self.db.execute(
                text(
                    "SELECT level, computed_at FROM risk_flags WHERE student_program_enrollment_id = ANY(:e) "
                    "ORDER BY computed_at DESC LIMIT 1"
                ),
                {"e": list(own["enrollments"])},
            )
        ).first()
        return {"level": row[0], "computed_at": row[1]} if row else None

    async def alerts(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if self.can("analytics", "view"):
            try:
                for a in await KpiService(self.db, self.principal, self.request, self.inst).alerts(active=True):
                    out.append({"kind": "kpi", **a})
            except APIError:
                pass
        try:
            from app.services.workflow_service import WorkflowService

            n = len(await WorkflowService(self.db, self.principal, self.request).inbox())
            if n:
                out.append({"kind": "approvals", "count": n, "route": "/approvals"})
        except Exception:  # noqa: BLE001 - the inbox is optional on the dashboard
            pass
        try:
            from app.services.read_only_service import ReadOnlyService

            state = await ReadOnlyService(self.db, self.principal).state(self.inst)
            if state.platform or state.institution:
                out.append(
                    {
                        "kind": "read_only",
                        "message": state.reason or "Read-only / maintenance mode",
                        "ends_at": state.ends_at,
                    }
                )
        except Exception:  # noqa: BLE001
            pass
        return out

    # ---- pins / layouts -------------------------------------------------------------------------------------------------
    async def put_pins(self, pinned: list[str], hidden: list[str]) -> dict[str, Any]:
        if self.actor_id is None:
            raise forbidden()
        user = (await self.db.execute(select(User).where(User.id == self.actor_id).with_for_update())).scalar_one()
        prefs = dict(user.preferences or {})
        prefs["dashboard"] = {"pinned_keys": pinned[:50], "hidden_keys": hidden[:50]}
        user.preferences = prefs
        await self.db.flush()
        return dict(prefs["dashboard"])

    async def get_layout(self, role: str) -> dict[str, Any]:
        self._require_layout_admin()
        widgets, layout = await self.compose(role, with_user=False)
        stored = await self.institution_layout(role)
        hidden = {w["key"] for w in stored.get("widgets", []) if w.get("hidden")}
        defaults = await self.defaults(role)
        return {
            "role": role,
            "columns": layout["columns"],
            "widgets": [
                {
                    "key": w.key,
                    "kind": w.kind,
                    "size": layout["sizes"].get(w.key) or w.size,
                    "position": i,
                    "hidden": False,
                }
                for i, w in enumerate(widgets)
            ]
            + [
                {"key": w.key, "kind": w.kind, "size": w.size, "position": None, "hidden": True}
                for w in defaults
                if w.key in hidden
            ],
            "customised": bool(stored),
        }

    async def put_layout(self, role: str, widgets: list[dict[str, Any]], columns: int | None) -> dict[str, Any]:
        self._require_layout_admin()
        known = {w.key for w in await self.defaults(role)}
        unknown = [w["key"] for w in widgets if w.get("key") not in known]
        if unknown:
            raise rule("Unknown widget keys for this role", "UNKNOWN_WIDGET", 422, keys=unknown)
        await self.put_meta(
            "layout",
            role,
            {
                "columns": columns or 4,
                "widgets": widgets,
                "updated_by": str(self.actor_id),
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )
        await self._emit("analytics.layout_updated", {"role": role}, "institution", self.inst)
        return await self.get_layout(role)

    async def reset_layout(self, role: str) -> dict[str, Any]:
        self._require_layout_admin()
        await self.db.execute(
            text("DELETE FROM institution_settings WHERE institution_id = :i AND category = :c AND key = :k"),
            {"i": self.inst, "c": self.meta_category, "k": f"layout:{role}"},
        )
        await self._emit("analytics.layout_updated", {"role": role, "reset": True}, "institution", self.inst)
        return await self.get_layout(role)

    def _require_layout_admin(self) -> None:
        if not self.can("settings", "manage"):
            raise forbidden("settings:manage required")
