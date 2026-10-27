"""KPI service — Prompts/35 §35.6 ``kpi_service``.

* Values: ``mv_kpi_daily`` row of the institution (``college_key='all'``) or a college (university tenants: the college
  rows are the primary view for ``college_admin``; the institution row for the university office).
* Targets per institution / college (``analytics.targets`` through the settings service — the college override is a
  college-level setting row), alert recipients (``analytics.alert_recipients``: role slugs or user ids, per KPI or
  ``default``).
* Evaluation after each ``mv_kpi_daily`` refresh: a KPI below (``higher`` is better) / above (``lower``) its target
  opens a breach (side store ``alert:<kpi>:<scope>``) and sends ``analytics.kpi_threshold`` **once**; recovery closes
  it with ``analytics.kpi_recovered``.
* History: the daily values are appended to ``kpi_history:<scope>`` (120 days) for trend sparklines.
* Public counters (Phase 40 website): only ``analytics.public_counter_keys`` from the institution row; never per college.
"""

import uuid
from datetime import date
from typing import Any

from sqlalchemy import text

from app.core.dashboards import STAT_KEYS
from app.services.analytics.common import AnalyticsBase, forbidden, now_utc
from app.services.analytics.read_models import KPI_COLUMNS

__all__ = ["KPI_TARGET_COLUMNS", "KpiService"]

# analytics.targets key → (mv_kpi_daily column, direction)
KPI_TARGET_COLUMNS: dict[str, tuple[str, str]] = {
    "attendance_pct": ("attendance_avg_pct", "higher"),
    "fee_collection_pct": ("fee_collection_pct", "higher"),
    "result_pass_pct": ("result_pass_pct", "higher"),
    "placement_pct": ("placement_pct", "higher"),
    "grievance_sla_pct": ("grievance_sla_pct", "higher"),
    "valuation_pct": ("valuation_pct", "higher"),
    "fee_overdue_paise": ("fee_overdue_paise", "lower"),
    "risk_high": ("risk_high", "lower"),
}
DEFAULT_TARGETS = {
    "attendance_pct": 75,
    "fee_collection_pct": 90,
    "result_pass_pct": 85,
    "placement_pct": 70,
    "grievance_sla_pct": 95,
}
HISTORY_DAYS = 120


def _f(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


class KpiService(AnalyticsBase):
    # ---- values -------------------------------------------------------------------------------------------------------
    async def row(self, college_id: uuid.UUID | None = None) -> dict[str, Any]:
        key = str(college_id) if college_id else "all"
        r = (
            (
                await self.db.execute(
                    text(
                        "SELECT * FROM mv_kpi_daily WHERE institution_id = :i AND college_key = :k ORDER BY day DESC LIMIT 1"
                    ),
                    {"i": self.inst, "k": key},
                )
            )
            .mappings()
            .first()
        )
        return {k: (_f(v) if k in KPI_COLUMNS else v) for k, v in dict(r or {}).items()}

    async def rows_for(self, college_ids: list[uuid.UUID]) -> dict[str, Any]:
        """Sum (counts) / average (percentages) of the given colleges' rows — a college admin over several colleges."""
        if len(college_ids) == 1:
            return await self.row(college_ids[0])
        rows = (
            (
                await self.db.execute(
                    text("SELECT * FROM mv_kpi_daily WHERE institution_id = :i AND college_id = ANY(:c)"),
                    {"i": self.inst, "c": college_ids},
                )
            )
            .mappings()
            .all()
        )
        out: dict[str, Any] = {}
        for c in KPI_COLUMNS:
            vals = [_f(r[c]) or 0.0 for r in rows]
            if not vals:
                out[c] = 0.0
            elif c.endswith("_pct") or c in ("avg_sgpa",):
                out[c] = round(sum(vals) / len(vals), 2)
            else:
                out[c] = sum(vals)
        out["refreshed_at"] = max((r["refreshed_at"] for r in rows), default=None)
        return out

    # ---- targets ------------------------------------------------------------------------------------------------------
    async def targets(self, college_id: uuid.UUID | None = None) -> dict[str, Any]:
        from app.services.settings_service import SettingsService

        v = await SettingsService(self.db).value(self.inst, "analytics", "targets", college_id)
        return {**DEFAULT_TARGETS, **(v if isinstance(v, dict) else {})}

    async def recipients(self) -> dict[str, Any]:
        v = await self.a_setting("analytics", "alert_recipients", {})
        return v if isinstance(v, dict) else {}

    async def put_targets(
        self, targets: dict[str, Any], recipients: dict[str, Any] | None, college_id: uuid.UUID | None
    ) -> dict[str, Any]:
        from app.schemas.settings import SettingItem
        from app.services.settings_service import SettingsService

        if not self.can("settings", "manage"):
            raise forbidden("settings:manage required")
        clean = {k: float(v) for k, v in targets.items() if k in KPI_TARGET_COLUMNS and v is not None}
        items = [SettingItem(category="analytics", key="targets", value=clean, college_id=college_id)]
        if recipients is not None:
            items.append(SettingItem(category="analytics", key="alert_recipients", value=recipients))
        await SettingsService(self.db, self.principal).bulk_update(items, self.request)
        return {
            "targets": await self.targets(college_id),
            "alert_recipients": await self.recipients(),
            "college_id": college_id,
        }

    # ---- evaluation ---------------------------------------------------------------------------------------------------
    @staticmethod
    def breached(value: float | None, target: float, direction: str) -> bool:
        if value is None:
            return False
        return value < target if direction == "higher" else value > target

    async def evaluate(self) -> dict[str, int]:
        """After each ``mv_kpi_daily`` refresh: open / close breaches per institution and per college."""
        rows = (
            (await self.db.execute(text("SELECT * FROM mv_kpi_daily WHERE institution_id = :i"), {"i": self.inst}))
            .mappings()
            .all()
        )
        opened = closed = 0
        recipients = await self.recipients()
        for r in rows:
            cid = r["college_id"]
            scope = str(cid) if cid else "all"
            await self._history(scope, r)
            targets = await self.targets(cid)
            for tkey, target in targets.items():
                col, direction = KPI_TARGET_COLUMNS.get(tkey, (None, "higher"))
                if not col:
                    continue
                value = _f(r.get(col))
                alert_key = f"{tkey}:{scope}"
                current = await self.meta("alert", alert_key)
                if self.breached(value, float(target), direction):
                    if not current.get("open"):
                        await self.put_meta(
                            "alert",
                            alert_key,
                            {
                                "open": True,
                                "key": tkey,
                                "value": value,
                                "target": float(target),
                                "direction": direction,
                                "since": now_utc().isoformat(),
                                "scope": scope,
                            },
                        )
                        await self._alert(
                            "analytics.kpi_threshold", tkey, value, float(target), direction, cid, recipients
                        )
                        await self._emit(
                            "analytics.kpi_threshold_breached",
                            {
                                "key": tkey,
                                "value": value,
                                "target": float(target),
                                "college_id": str(cid) if cid else None,
                            },
                            "institution",
                            self.inst,
                        )
                        opened += 1
                    else:
                        await self.put_meta("alert", alert_key, {**current, "value": value})
                elif current.get("open"):
                    await self.put_meta(
                        "alert",
                        alert_key,
                        {**current, "open": False, "value": value, "recovered_at": now_utc().isoformat()},
                    )
                    await self._alert("analytics.kpi_recovered", tkey, value, float(target), direction, cid, recipients)
                    await self._emit(
                        "analytics.kpi_threshold_recovered",
                        {"key": tkey, "value": value, "target": float(target), "college_id": str(cid) if cid else None},
                        "institution",
                        self.inst,
                    )
                    closed += 1
        await self._emit("analytics.kpi_refreshed", {"rows": len(rows)}, "institution", self.inst)
        return {"opened": opened, "closed": closed}

    async def _alert(
        self,
        event: str,
        tkey: str,
        value: float | None,
        target: float,
        direction: str,
        college_id: uuid.UUID | None,
        recipients: dict[str, Any],
    ) -> None:
        who = recipients.get(tkey) or recipients.get("default") or ["institution_admin", "vice_chancellor", "registrar"]
        roles = [w for w in who if isinstance(w, str) and not _is_uuid(w)]
        users = [w for w in who if isinstance(w, str) and _is_uuid(w)]
        scope = ""
        if college_id:
            row = (await self.db.execute(text("SELECT code FROM colleges WHERE id = :c"), {"c": college_id})).first()
            scope = str(row[0]) if row else ""
            roles = [*roles, "college_admin"] if "college_admin" not in roles else roles
        ctx = {
            "kpi": tkey.replace("_", " "),
            "value": value if value is not None else "—",
            "target": target,
            "direction": "below" if direction == "higher" else "above",
            "scope": scope,
            "since": date.today().isoformat(),
        }
        audience: dict[str, Any] = {"roles": roles, "user_ids": users}
        await self._notify(event, [uuid.UUID(u) for u in users], ctx, audience=audience)

    async def _history(self, scope: str, r: Any) -> None:
        h = await self.meta("kpi_history", scope)
        series: dict[str, list[list[Any]]] = h.get("series") or {}
        day = str(r.get("day") or date.today())
        for col in KPI_COLUMNS:
            pts = [p for p in series.get(col, []) if p[0] != day]
            pts.append([day, _f(r.get(col))])
            series[col] = pts[-HISTORY_DAYS:]
        await self.put_meta("kpi_history", scope, {"series": series})

    async def history(self, column: str, college_id: uuid.UUID | None = None, days: int = 30) -> list[list[Any]]:
        h = await self.meta("kpi_history", str(college_id) if college_id else "all")
        return list((h.get("series") or {}).get(column, []))[-days:]

    async def alerts(self, active: bool | None = None) -> list[dict[str, Any]]:
        if not (self.can("analytics", "view") or self.can("settings", "manage")):
            raise forbidden("analytics:view required")
        metas = await self.metas("alert")
        out = []
        colleges = set(self.college_ids()) if not self.all_access("analytics") else None
        for _, m in metas.items():
            if active is not None and bool(m.get("open")) != active:
                continue
            if colleges is not None and m.get("scope") not in {str(c) for c in colleges}:
                continue
            out.append(
                {
                    "key": m.get("key"),
                    "value": m.get("value"),
                    "target": m.get("target"),
                    "direction": m.get("direction"),
                    "since": m.get("since"),
                    "scope": m.get("scope"),
                    "open": bool(m.get("open")),
                    "recovered_at": m.get("recovered_at"),
                }
            )
        return sorted(out, key=lambda a: (not a["open"], str(a.get("since") or "")))

    def college_ids(self) -> list[uuid.UUID]:
        from app.services.analytics.common import scope_ids

        return [] if self.principal is None else scope_ids(self.principal, "college")

    # ---- public counters -----------------------------------------------------------------------------------------------
    async def public_counters(self) -> dict[str, Any]:
        keys = await self.a_setting(
            "analytics", "public_counter_keys", ["students_active", "programmes", "faculty_count"]
        )
        allowed = {k for k, s in STAT_KEYS.items() if s.public}
        row = await self.row(None)
        out: dict[str, Any] = {}
        for k in keys if isinstance(keys, list) else []:
            stat = STAT_KEYS.get(k)
            col = stat.column if stat else (k if k in KPI_COLUMNS else None)
            if (k in allowed or k in KPI_COLUMNS) and col:
                out[k] = int(row.get(col) or 0) if not col.endswith("_pct") else row.get(col)
        return {"counters": out, "as_of": row.get("day")}


def _is_uuid(v: str) -> bool:
    try:
        uuid.UUID(v)
        return True
    except ValueError:
        return False
