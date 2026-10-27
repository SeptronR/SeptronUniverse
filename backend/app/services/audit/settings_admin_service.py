"""Settings catalogue, effective values, history and import / export — Prompts/37 §37.6 ``settings_service``
({core.settings}; extends the Phase 03 :class:`~app.services.settings_service.SettingsService`).

1. ``catalogue(category, q, scope)`` — every key of the typed template with the Phase 37 metadata
   (:mod:`app.core.settings_catalogue`) and the number of colleges overriding it.
2. ``effective(college_id)`` — value per key resolved ``college → institution → platform default → template
   default`` with its source badge. Writes go through ``SettingsService.bulk_update(strict=True)`` (locks → 409,
   type / range / dependency → 422, reason for sensitive categories, college scope rules, ``settings.changed`` and
   ``settings.changed_sensitive``).
3. ``history`` reads ``audit_logs`` (``module='settings'``) per key; ``changes_since(date)`` diffs the value at that
   date (from the history) with the current one; ``reset`` deletes the institution row (template default applies),
   ``clear_override`` the college row; ``export`` / ``import`` (dry run first; locked and invalid keys are skipped and
   reported; an applied import is one audited batch sharing the request id).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select

from app.core import events
from app.core.errors import APIError, ErrorCode
from app.core.settings_catalogue import CATALOGUE
from app.core.settings_template import BY_KEY
from app.models.audit import AuditLog
from app.models.platform import InstitutionSetting
from app.schemas.settings import (
    EffectiveSettingOut,
    SettingDefOut,
    SettingItem,
    SettingsDiffOut,
    SettingsExportOut,
    SettingsHistoryOut,
    SettingsImportReport,
)
from app.services.audit.common import AuditBase, forbidden, not_found, now_utc
from app.services.settings_service import SettingsService, coerce, invalidate_settings_cache


class SettingsAdminService(AuditBase):
    audit_module = "settings"

    def require_view(self) -> None:
        self.require("settings:view", "settings:manage")

    def require_manage(self) -> None:
        self.require("settings:manage")
        self.require_writer()

    # ---- catalogue --------------------------------------------------------------------------------------------------
    async def _platform_defaults(self) -> dict[str, Any]:
        v = await self.platform_setting("settings_platform_defaults")
        return dict(v or {}) if isinstance(v, dict) else {}

    async def _rows(self) -> list[InstitutionSetting]:
        return list(
            (
                await self.db.execute(
                    select(InstitutionSetting).where(
                        InstitutionSetting.institution_id == self.inst,
                        InstitutionSetting.category.notlike("%\\_meta"),
                    )
                )
            ).scalars()
        )

    async def catalogue(self, category: str | None, q: str | None, scope: str | None) -> list[SettingDefOut]:
        self.require_view()
        rows = await self._rows()
        overrides: dict[str, int] = {}
        for r in rows:
            if r.college_id is not None:
                overrides[f"{r.category}.{r.key}"] = overrides.get(f"{r.category}.{r.key}", 0) + 1
        needle = (q or "").lower().strip()
        out = []
        for k, e in CATALOGUE.items():
            d = e.as_dict()
            if category and d["category"] != category:
                continue
            if scope and d["scope"] != scope:
                continue
            if needle and needle not in k.lower() and needle not in str(d["label"]).lower():
                continue
            out.append(SettingDefOut(**d, overridden_in_colleges=overrides.get(k, 0)))
        return out

    async def effective(self, college_id: uuid.UUID | None, category: str | None = None) -> list[EffectiveSettingOut]:
        self.require_view()
        rows = await self._rows()
        inst_rows = {(r.category, r.key): r for r in rows if r.college_id is None}
        col_rows = {(r.category, r.key): r for r in rows if college_id and r.college_id == college_id}
        platform = await self._platform_defaults()
        out = []
        for k, e in CATALOGUE.items():
            d = e.defn
            if category and d.category != category:
                continue
            ck = (d.category, d.key)
            if ck in col_rows:
                v, src, at = col_rows[ck].value, "college", col_rows[ck].updated_at
            elif ck in inst_rows:
                v, src, at = inst_rows[ck].value, "institution", inst_rows[ck].updated_at
            elif k in platform:
                v, src, at = platform[k], "platform", None
            else:
                v, src, at = d.default, "default", None
            out.append(
                EffectiveSettingOut(
                    key=k,
                    category=d.category,
                    value=v,
                    source=src,
                    locked_by=e.locked_by,  # type: ignore[arg-type]
                    overridden_at_college=ck in col_rows,
                    updated_at=at,
                )
            )
        return out

    # ---- history ----------------------------------------------------------------------------------------------------
    async def history(
        self, key: str | None, category: str | None, date_from: datetime | None, date_to: datetime | None
    ) -> list[SettingsHistoryOut]:
        self.require_view()
        lo, hi = self.bounds(date_from, date_to)
        rows = list(
            (
                await self.db.execute(
                    select(AuditLog)
                    .where(
                        AuditLog.institution_id == self.inst,
                        AuditLog.module == "settings",
                        AuditLog.occurred_at >= lo,
                        AuditLog.occurred_at <= hi,
                    )
                    .order_by(AuditLog.occurred_at.desc())
                    .limit(2000)
                )
            ).scalars()
        )
        names = await self.user_refs([r.user_id for r in rows])
        out: list[SettingsHistoryOut] = []
        for r in rows:
            nv, ov = dict(r.new_values or {}), dict(r.old_values or {})
            reason = nv.get("_reason")
            for label in sorted(set(nv) | set(ov)):
                if label.startswith("_"):
                    continue
                full, _, col = label.partition("@")
                if key and full != key:
                    continue
                if category and not full.startswith(f"{category}."):
                    continue
                if full not in CATALOGUE:
                    continue
                out.append(
                    SettingsHistoryOut(
                        audit_id=r.id,
                        at=r.occurred_at,
                        key=full,
                        college_id=_uuid(col),
                        old=ov.get(label),
                        new=nv.get(label),
                        actor_id=r.user_id,
                        actor_name=names.get(r.user_id) if r.user_id else None,
                        reason=reason,
                        request_id=r.request_id,
                    )
                )
        return out

    async def changes_since(self, since: datetime) -> list[SettingsDiffOut]:
        """Keys whose institution value changed since ``since`` (value then → now)."""
        self.require_view()
        hist = await self.history(None, None, since, now_utc())
        first: dict[str, SettingsHistoryOut] = {}
        for h in sorted(hist, key=lambda x: x.at):
            if h.college_id is None:
                first.setdefault(h.key, h)
        current = {e.key: e.value for e in await self.effective(None)}
        return [
            SettingsDiffOut(key=k, before=h.old, after=current.get(k), changed_at=h.at, actor_id=h.actor_id)
            for k, h in sorted(first.items())
            if h.old != current.get(k)
        ]

    # ---- reset / overrides ------------------------------------------------------------------------------------------
    async def _delete(self, full_key: str, college_id: uuid.UUID | None, action: str, reason: str | None) -> None:
        from app.services.institution.context import check_college_writable

        self.require_manage()
        cat, _, key = full_key.partition(".")
        meta = CATALOGUE.get(full_key)
        if meta is None:
            raise not_found("Setting")
        if meta.locked_by != "none" or meta.scope == "platform":
            raise APIError(
                409, ErrorCode.RULE_VIOLATION, f"{full_key} is locked", {"code": "SETTING_LOCKED", "key": full_key}
            )
        if meta.sensitive and not (reason or "").strip():
            raise APIError(
                422, ErrorCode.VALIDATION, "A reason is required for changes to sensitive settings", {"field": "reason"}
            )
        check_college_writable(self.principal, college_id)
        stmt = select(InstitutionSetting).where(
            InstitutionSetting.institution_id == self.inst,
            InstitutionSetting.category == cat,
            InstitutionSetting.key == key,
            InstitutionSetting.college_id.is_(None)
            if college_id is None
            else InstitutionSetting.college_id == college_id,
        )
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise not_found("Setting value" if college_id is None else "College override")
        label = full_key + (f"@{college_id}" if college_id else "")
        old = row.value
        await self.db.execute(delete(InstitutionSetting).where(InstitutionSetting.id == row.id))
        await invalidate_settings_cache(self.inst, [cat])
        await self._audit(
            action,
            "institution_settings",
            self.inst,
            {label: old},
            {
                label: BY_KEY[(cat, key)].default if college_id is None else None,
                "key": full_key,
                **({"_reason": reason} if reason else {}),
            },
        )
        await events.emit(
            self.db,
            institution_id=self.inst,
            event_type="settings.changed",
            payload={"institution_id": str(self.inst), "categories": [cat], "keys": [label]},
            aggregate_type="institution",
            aggregate_id=self.inst,
            actor_user_id=self.actor_id,
        )

    async def reset(self, full_key: str, reason: str | None) -> list[EffectiveSettingOut]:
        await self._delete(full_key, None, "reset", reason)
        return [e for e in await self.effective(None) if e.key == full_key]

    async def clear_override(
        self, full_key: str, college_id: uuid.UUID, reason: str | None
    ) -> list[EffectiveSettingOut]:
        await self._delete(full_key, college_id, "override_clear", reason)
        return [e for e in await self.effective(college_id) if e.key == full_key]

    # ---- export / import --------------------------------------------------------------------------------------------
    async def export(self) -> SettingsExportOut:
        self.require_manage()
        rows = await self._rows()
        values: dict[str, Any] = {}
        colleges: dict[str, dict[str, Any]] = {}
        for r in rows:
            full = f"{r.category}.{r.key}"
            if full not in CATALOGUE:
                continue
            if r.college_id is None:
                values[full] = r.value
            else:
                colleges.setdefault(str(r.college_id), {})[full] = r.value
        await self._audit("export", "institution_settings", self.inst, None, {"keys": len(values)})
        return SettingsExportOut(
            institution_id=self.inst, exported_at=now_utc(), values=values, college_overrides=colleges
        )

    async def import_(self, doc: dict[str, Any], dry_run: bool, reason: str | None) -> SettingsImportReport:
        self.require_manage()
        values = doc.get("values") if isinstance(doc.get("values"), dict) else doc
        current = {e.key: e.value for e in await self.effective(None)}
        report = SettingsImportReport(dry_run=dry_run)
        items: list[SettingItem] = []
        for full, value in sorted((values or {}).items()):
            meta = CATALOGUE.get(str(full))
            if meta is None:
                report.invalid.append({"key": full, "reason": "unknown setting"})
                continue
            if meta.locked_by != "none" or meta.scope == "platform":
                report.skipped_locked.append(full)
                continue
            try:
                v = coerce(meta.defn, value)
            except ValueError as exc:
                report.invalid.append({"key": full, "reason": str(exc)})
                continue
            if v == current.get(full):
                report.unchanged.append(full)
                continue
            report.applied.append(full)
            items.append(SettingItem(category=meta.defn.category, key=meta.defn.key, value=v))
        report.request_id = getattr(getattr(self.request, "state", None), "request_id", None)
        if dry_run or not items:
            return report
        if any(CATALOGUE[f"{i.category}.{i.key}"].sensitive for i in items) and not (reason or "").strip():
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "A reason is required: the import changes sensitive settings",
                {"field": "reason"},
            )
        await SettingsService(self.db, self.principal).bulk_update(
            items, self.request, reason=reason or "settings import", strict=True, action="import"
        )
        await self._emit("settings.imported", {"applied": report.applied}, "institution", self.inst)
        return report

    # ---- feature changes / platform actions -------------------------------------------------------------------------
    def require_feature_log(self) -> None:
        if not (self.can("features", "view") or self.views_all()):
            raise forbidden("features:view or audit_logs:view_all required")


def _uuid(v: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(v)) if v else None
    except ValueError:
        return None
