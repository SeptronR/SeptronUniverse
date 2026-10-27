"""Shared plumbing of the Phase 37 services — the ``audit_repository`` / ``security_event_repository`` helpers of
Prompts/37 §37.5, on the Phase 36 :class:`~app.services.reports.common.ReportsBase` (permissions, scope resolution,
people lookups, the ``institution_settings`` side store — here category ``audit_meta``).

* **Visibility** (``audit_logs``): ``self`` = rows the caller wrote (``user_id``); ``view_all`` widens by the caller's
  scope — institution scope → all; college scope → rows whose *record* belongs to the caller's colleges; department /
  faculty scope → rows whose record belongs to the caller's departments (``RECORD_SCOPE_SQL`` resolvers by
  ``record_type``) plus rows written by staff of those departments; the COE (``exams:manage`` / ``results:manage``)
  sees every ``exams`` / ``results`` row; IQAC (aggregates-only) reads counts, never rows.
* **Masking**: ``old_values`` / ``new_values`` keys in ``PII_VALUE_KEYS`` are masked unless the caller holds
  ``view_pii`` on the record's module (``RECORD_PII_MODULE`` by record type, else the row's module).
* **Decode events** (``exams:decode`` rows) are visible to COE (``exams:decode``), institution admins and auditors only.
* **Date bounds** are mandatory: default last 30 days, at most 366 days per query (exports beyond via the job).
* IPs are masked to the /24 (IPv4) or /48 (IPv6) network.
"""

import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import and_, false, or_, select, text, true
from sqlalchemy.sql.elements import ColumnElement

from app.core.authz.masking import mask_value
from app.core.errors import APIError, ErrorCode
from app.enums.audit import (
    DECODE_ACTIONS,
    DEFAULT_QUERY_DAYS,
    MAX_QUERY_DAYS,
    PII_VALUE_KEYS,
    RECORD_PII_MODULE,
    RECORD_SCOPE_SQL,
    SUMMARY_TEMPLATES,
)
from app.models.audit import META, AuditLog
from app.services.reports.common import ReportsBase, forbidden, is_auditor, not_found, now_utc, rule, scope_ids

__all__ = [
    "AuditBase",
    "content_hash",
    "forbidden",
    "is_auditor",
    "mask_ip24",
    "not_found",
    "now_utc",
    "rule",
    "scope_ids",
]


def mask_ip24(ip: Any) -> str | None:
    if not ip:
        return None
    s = str(ip).split("/")[0]
    if ":" in s:
        return ":".join(s.split(":")[:3]) + "::/48"
    parts = s.split(".")
    return ".".join(parts[:3]) + ".0/24" if len(parts) == 4 else None


def content_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, default=str, sort_keys=True).encode()).hexdigest()


class _Fmt(dict):  # type: ignore[type-arg]
    def __missing__(self, key: str) -> str:
        return ""


class AuditBase(ReportsBase):
    audit_module = "audit_logs"
    module = "audit_logs"
    meta_category = META

    # ---- permissions ------------------------------------------------------------------------------------------------
    def institution_wide(self) -> bool:
        p = self.principal
        return p is None or getattr(p, "is_super_admin", False) or any(t == "institution" for t, _ in p.scopes)

    def is_inst_admin(self) -> bool:
        p = self.principal
        return p is None or getattr(p, "is_super_admin", False) or "institution_admin" in (p.roles or [])

    def views_all(self) -> bool:
        return self.can("audit_logs", "view_all")

    def require(self, *specs: str) -> None:
        for spec in specs:
            module, _, action = spec.partition(":")
            if self.can(module, action):
                return
        raise forbidden(f"{' | '.join(specs)} required")

    def require_writer(self) -> None:
        if is_auditor(self.principal) and not self.is_inst_admin():
            raise forbidden("The auditor role is read-only")

    def sees_decode(self) -> bool:
        return self.can("exams", "decode") or self.is_inst_admin() or is_auditor(self.principal)

    def coe_wide(self) -> bool:
        return self.institution_wide() and (self.can("exams", "manage") or self.can("results", "manage"))

    # ---- date bounds ------------------------------------------------------------------------------------------------
    @staticmethod
    def bounds(
        date_from: datetime | None, date_to: datetime | None, max_days: int = MAX_QUERY_DAYS
    ) -> tuple[datetime, datetime]:
        hi = date_to or now_utc()
        lo = date_from or hi - timedelta(days=DEFAULT_QUERY_DAYS)
        if lo.tzinfo is None:
            lo = lo.replace(tzinfo=hi.tzinfo or now_utc().tzinfo)
        if hi.tzinfo is None:
            hi = hi.replace(tzinfo=lo.tzinfo)
        if lo > hi:
            raise APIError(422, ErrorCode.VALIDATION, "'from' must be before 'to'", {"field": "from"})
        if (hi - lo).days > max_days:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"A query may span at most {max_days} days — export longer ranges as a job",
                {"field": "from", "max_days": max_days},
            )
        return lo, hi

    # ---- visibility -------------------------------------------------------------------------------------------------
    def levels(self) -> list[str]:
        p = self.principal
        out = ["self"]
        if p is None or getattr(p, "is_super_admin", False):
            return ["self", "all"]
        if self.views_all() and not self.aggregates_only("audit_logs"):
            if scope_ids(p, "department") or scope_ids(p, "faculty"):
                out.append("department")
            if scope_ids(p, "college"):
                out.append("college")
            if self.institution_wide():
                out.append("all")
        return out

    @staticmethod
    def _record_in(col_idx: int, ids: list[uuid.UUID]) -> ColumnElement[bool]:
        """Rows whose record (by ``record_type``) resolves to one of ``ids`` (college col 1 / department col 2)."""
        if not ids:
            return false()
        col = "c1" if col_idx == 0 else "c2"
        branches = [
            f"(audit_logs.record_type = '{rtype}' AND EXISTS (SELECT 1 FROM ({sql.format(rid='audit_logs.record_id')}) "
            f"_s(c1, c2) WHERE _s.{col} = ANY(:_scope_ids)))"
            for rtype, sql in RECORD_SCOPE_SQL.items()
        ]
        return cast(ColumnElement[bool], text("(" + " OR ".join(branches) + ")").bindparams(_scope_ids=ids))

    async def scope_predicate(self, scope: str | None) -> tuple[ColumnElement[bool], str]:
        """→ (predicate, effective level); a requested scope outside ``levels()`` narrows silently."""
        p = self.principal
        levels = self.levels()
        level = scope if scope in levels else levels[-1]
        if scope in ("mine", "own"):
            level = "self"
        me = getattr(p, "id", None)
        own: ColumnElement[bool] = AuditLog.user_id == me if me else false()
        decode_ok = self.sees_decode()
        hide_decode: ColumnElement[bool] = true() if decode_ok else AuditLog.action.notin_(DECODE_ACTIONS)
        if level == "all":
            return hide_decode, level
        parts: list[ColumnElement[bool]] = [own]
        if self.coe_wide():
            parts.append(AuditLog.module.in_(("exams", "results")))
        if level == "college":
            parts.append(self._record_in(0, scope_ids(p, "college")))
        elif level == "department":
            depts = await self.department_ids()
            parts.append(self._record_in(1, depts))
            parts.append(
                cast(
                    ColumnElement[bool],
                    text(
                        "audit_logs.user_id IN (SELECT user_id FROM staff WHERE department_id = ANY(:_dep_ids))"
                    ).bindparams(_dep_ids=depts),
                )
            )
        return and_(or_(*parts), hide_decode), level

    def scope_meta(self, level: str) -> dict[str, Any]:
        scopes = [lv for lv in self.levels() if lv != "self"]
        if scopes:
            return {"self": False, "scopes": ["own", *scopes], "default": level if level != "self" else "own"}
        return {"self": True}

    # ---- masking / rendering ----------------------------------------------------------------------------------------
    def pii_module(self, row: AuditLog) -> str:
        return RECORD_PII_MODULE.get(row.record_type or "", row.module)

    def may_unmask(self, row: AuditLog) -> bool:
        p = self.principal
        if p is None or getattr(p, "is_super_admin", False):
            return True
        return bool(p.has(self.pii_module(row), "view_pii")) or row.user_id == getattr(p, "id", None)

    def mask_values(self, row: AuditLog, values: dict[str, Any] | None) -> tuple[dict[str, Any] | None, list[str]]:
        if not values or self.may_unmask(row):
            return values, []
        masked: list[str] = []

        def walk(v: Any, path: str) -> Any:
            if isinstance(v, dict):
                out = {}
                for k, x in v.items():
                    kind = PII_VALUE_KEYS.get(str(k).split("@")[0].split(".")[-1])
                    if kind and x not in (None, "", [], {}):
                        masked.append(f"{path}{k}")
                        out[k] = mask_value(x if not isinstance(x, dict | list) else json.dumps(x), kind)
                    else:
                        out[k] = walk(x, f"{path}{k}.")
                return out
            if isinstance(v, list):
                return [walk(x, path) for x in v]
            return v

        return walk(values, ""), sorted(set(masked))

    @staticmethod
    def summary_line(row: AuditLog) -> str:
        nv = dict(row.new_values or {})
        tpl = SUMMARY_TEMPLATES.get(f"{row.module}:{row.action}")
        if tpl:
            fmt = _Fmt({k: (", ".join(map(str, v)) if isinstance(v, list) else v) for k, v in nv.items()})
            if "amount" not in nv and "amount_paise" in nv:
                fmt["amount"] = f"{(nv.get('amount_paise') or 0) / 100:,.2f}"
            if "keys" not in nv and nv:
                fmt["keys"] = ", ".join(sorted(nv)[:5])
            return tpl.format_map(fmt).strip()
        what = (row.record_type or "record").replace("_", " ")
        return f"{row.action.replace('_', ' ').capitalize()} {what}"

    @staticmethod
    def record_label(row: AuditLog) -> str | None:
        nv = dict(row.new_values or {}) or dict(row.old_values or {})
        for k in ("label", "number", "code", "name", "registration_number", "title", "key", "receipt_number"):
            v = nv.get(k)
            if isinstance(v, str | int) and v != "":
                return str(v)[:120]
        return None

    async def user_refs(self, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, str]:
        return await self.user_display([i for i in ids if i])

    # ---- side store helpers -----------------------------------------------------------------------------------------
    async def meta_list(self, kind: str) -> list[tuple[str, dict[str, Any]]]:
        rows = await self.metas(kind)
        return sorted(
            rows.items(),
            key=lambda kv: str(kv[1].get("created_at") or kv[1].get("set_at") or kv[1].get("first_seen") or ""),
            reverse=True,
        )

    async def require_record_visible(self, row: AuditLog) -> None:
        pred, _ = await self.scope_predicate(None)
        found = (
            await self.db.execute(
                select(AuditLog.id).where(AuditLog.id == row.id, AuditLog.occurred_at == row.occurred_at, pred)
            )
        ).first()
        if found is None:
            raise not_found("Audit row")
