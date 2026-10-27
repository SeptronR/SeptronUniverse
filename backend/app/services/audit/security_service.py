"""Security events console, anomaly rules and admin session management — Prompts/37 §37.6 ``security_service``.

1. **Events** (``audit_logs:security``; {security.session_management} for sessions / login history): one union over
   ``login_history`` (success / failures / lockouts / MFA failures), ``user_sessions`` revocations,
   ``impersonation_logs`` (start / stop with reason), ``ip_allowlists`` and ``api_keys`` (created / last used /
   revoked) and ``audit_logs`` rows of the security modules (auth, users, roles, features, integrations, reports
   exports / downloads, settings in the ``security`` category, PII unmasks). IPs are masked to /24; a college admin
   sees events of the college's users only.
2. **Anomaly rules** (``audit.anomaly_rules``) are evaluated by Beat ``security.anomaly_scan`` every 5 minutes:
   ``pii_unmask_burst`` (≥ threshold ``view_pii`` reads by one user in the window), ``export_off_hours`` (exports /
   downloads at institution-local hours inside ``hours``), ``login_failures_per_ip`` (≥ threshold failures from one IP
   in the window), ``impersonation_writes`` (writes made while impersonating). An alert is kept once per rule /
   subject / hour bucket (``audit_meta anomaly:<id>``) with an audit row and the ``audit.anomaly`` notification to
   ``audit.alert_recipients``; acknowledging records the note; recommended actions link to the session revoke / API
   key / lock endpoints.
3. **Sessions**: list across users (masked IP, device, last seen), revoke one / all for a user (refresh then answers
   401), optionally force MFA re-enrolment (the TOTP secret is unconfirmed); login history per user.
"""

import hashlib
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text

from app.core.errors import APIError, ErrorCode
from app.core.features import is_enabled
from app.enums.audit import SECURITY_MODULES
from app.repositories.session_repository import SessionRepository
from app.schemas.audit import (
    AdminSessionOut,
    AnomalyAlertOut,
    AuditUser,
    LoginHistoryAdminOut,
    SecurityEventOut,
    SessionRevokeOut,
    SessionRevokeRequest,
)
from app.services.audit.common import AuditBase, forbidden, mask_ip24, not_found, now_utc, scope_ids

FAIL_OUTCOMES = ("bad_password", "locked", "mfa_failed", "expired", "inactive")
SEVERITY = {
    "login_success": "info",
    "login_failed": "low",
    "locked": "medium",
    "mfa_failed": "medium",
    "session_revoked": "low",
    "impersonation": "high",
    "ip_allowlist_change": "medium",
    "api_key": "medium",
    "export": "low",
    "pii_unmask": "low",
    "feature_toggle": "medium",
    "settings_change": "medium",
    "mfa_change": "medium",
    "password_reset": "medium",
}


def _audit_type(module: str, action: str) -> str:
    if action == "view_pii":
        return "pii_unmask"
    if module == "features":
        return "feature_toggle"
    if module == "settings":
        return "settings_change"
    if "mfa" in action:
        return "mfa_change"
    if "password" in action:
        return "password_reset"
    if "session" in action:
        return "session_revoked"
    if "impersonat" in action:
        return "impersonation"
    if module == "integrations" and "key" in action:
        return "api_key"
    if action in ("export", "download", "run") or module in ("reports", "exports"):
        return "export"
    return f"{module}_{action}"[:40]


class SecurityService(AuditBase):
    def require_console(self) -> None:
        self.require("audit_logs:security", "audit_logs:manage")

    async def require_sessions_feature(self) -> None:
        if not await is_enabled(self.inst, "security.session_management"):
            raise APIError(
                403,
                ErrorCode.FEATURE_DISABLED,
                "Feature security.session_management is not enabled",
                {"feature": "security.session_management"},
            )

    def _user_scope_sql(self, col: str) -> tuple[str, dict[str, Any]]:
        if self.institution_wide():
            return "TRUE", {}
        colleges = scope_ids(self.principal, "college")
        if not colleges:
            return f"{col} = :_me", {"_me": self.actor_id}
        return (
            f"({col} IN (SELECT user_id FROM staff WHERE college_id = ANY(:_cols)) OR {col} IN (SELECT s.user_id FROM "
            "students s WHERE s.college_id = ANY(:_cols)))",
            {"_cols": colleges},
        )

    # ---- events -----------------------------------------------------------------------------------------------------
    async def events(
        self,
        type_: str | None,
        user_id: uuid.UUID | None,
        ip: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        severity: str | None = None,
        limit: int = 500,
    ) -> list[SecurityEventOut]:
        self.require_console()
        lo, hi = self.bounds(date_from, date_to)
        scope_lh, b1 = self._user_scope_sql("user_id")
        b = {"i": self.inst, "lo": lo, "hi": hi, "mods": list(SECURITY_MODULES), **b1}
        sql = f"""
        SELECT 'lh:' || id::text AS id, CASE WHEN outcome = 'success' THEN 'login_success'
               WHEN outcome = 'locked' THEN 'locked' WHEN outcome = 'mfa_failed' THEN 'mfa_failed'
               ELSE 'login_failed' END AS type, occurred_at AS at, user_id, identifier, host(ip) AS ip,
               jsonb_build_object('outcome', outcome, 'user_agent', left(user_agent, 120)) AS details
          FROM login_history WHERE institution_id = :i AND occurred_at BETWEEN :lo AND :hi AND {scope_lh}
        UNION ALL
        SELECT 'us:' || id::text, 'session_revoked', revoked_at, user_id, NULL, host(ip),
               jsonb_build_object('reason', revoked_reason, 'device', device_label)
          FROM user_sessions WHERE institution_id = :i AND revoked_at BETWEEN :lo AND :hi
               AND COALESCE(revoked_reason, '') <> 'expired' AND {scope_lh}
        UNION ALL
        SELECT 'im:' || id::text, 'impersonation', started_at, target_user_id, NULL, host(ip),
               jsonb_build_object('impersonator_id', impersonator_id, 'reason', reason, 'ended_at', ended_at)
          FROM impersonation_logs WHERE institution_id = :i AND started_at BETWEEN :lo AND :hi
        UNION ALL
        SELECT 'ip:' || id::text, 'ip_allowlist_change', created_at, created_by, NULL, NULL,
               jsonb_build_object('purpose', purpose, 'cidr', cidr::text, 'active', is_active, 'label', label)
          FROM ip_allowlists WHERE institution_id = :i AND created_at BETWEEN :lo AND :hi
        UNION ALL
        SELECT 'ak:' || id::text, 'api_key', COALESCE(revoked_at, last_used_at, created_at), created_by, NULL, NULL,
               jsonb_build_object('name', name, 'prefix', key_prefix, 'last_used_at', last_used_at,
                                  'revoked_at', revoked_at, 'active', is_active)
          FROM api_keys WHERE institution_id = :i AND COALESCE(revoked_at, last_used_at, created_at) BETWEEN :lo AND :hi
        UNION ALL
        SELECT 'al:' || id::text, module || ':' || action, occurred_at, user_id, NULL, host(ip),
               jsonb_build_object('record_type', record_type, 'impersonator_id', impersonator_id,
                                  'keys', (SELECT jsonb_agg(k) FROM jsonb_object_keys(COALESCE(new_values, '{{}}'::jsonb)) k))
          FROM audit_logs WHERE institution_id = :i AND occurred_at BETWEEN :lo AND :hi
               AND (module = ANY(:mods) OR action = 'view_pii') AND {scope_lh}
        """
        outer = []
        if user_id:
            outer.append("user_id = :uid")
            b["uid"] = user_id
        if ip:
            outer.append("ip LIKE :ipq")
            b["ipq"] = f"{ip.split('/')[0].rsplit('.', 1)[0] if '.' in ip else ip}%"
        stmt = f"SELECT * FROM ({sql}) e {'WHERE ' + ' AND '.join(outer) if outer else ''} ORDER BY at DESC LIMIT :lim"
        b["lim"] = min(limit, 2000) * 2
        rows = (await self.db.execute(text(stmt), b)).mappings().all()
        names = await self.user_refs([r["user_id"] for r in rows])
        out: list[SecurityEventOut] = []
        for r in rows:
            t = str(r["type"])
            if ":" in t:
                mod, _, act = t.partition(":")
                t = _audit_type(mod, act)
            sev = SEVERITY.get(t, "info")
            if type_ and t != type_:
                continue
            if severity and sev != severity:
                continue
            out.append(
                SecurityEventOut(
                    id=str(r["id"]),
                    type=t,
                    at=r["at"],
                    user=AuditUser(id=r["user_id"], name=names.get(r["user_id"])) if r["user_id"] else None,
                    identifier=r["identifier"],
                    ip_masked=mask_ip24(r["ip"]),
                    severity=sev,  # type: ignore[arg-type]
                    details=dict(r["details"] or {}),
                )
            )
            if len(out) >= limit:
                break
        return out

    # ---- anomalies --------------------------------------------------------------------------------------------------
    async def scan(self) -> int:
        """Beat ``security.anomaly_scan``: evaluate every rule; returns the number of new alerts."""
        rules = await self.a_setting("audit", "anomaly_rules", []) or []
        created = 0
        for r in rules:
            name = str(r.get("rule") or "")
            fn = getattr(self, f"_rule_{name}", None)
            if fn is None:
                continue
            for hit in await fn(r):
                created += int(await self._raise(name, r, hit))
        return created

    async def _rule_pii_unmask_burst(self, r: dict[str, Any]) -> list[dict[str, Any]]:
        win = int(r.get("window_minutes") or 10)
        rows = (
            await self.db.execute(
                text(
                    "SELECT user_id, COUNT(*) AS n, MIN(occurred_at) AS first FROM audit_logs WHERE institution_id = :i AND "
                    "action = 'view_pii' AND occurred_at >= :since GROUP BY user_id HAVING COUNT(*) >= :t"
                ),
                {"i": self.inst, "since": now_utc() - timedelta(minutes=win), "t": int(r.get("threshold") or 50)},
            )
        ).all()
        return [{"subject": str(u), "users": [u], "count": int(n), "first": f, "window": win} for u, n, f in rows]

    async def _rule_login_failures_per_ip(self, r: dict[str, Any]) -> list[dict[str, Any]]:
        win = int(r.get("window_minutes") or 15)
        rows = (
            await self.db.execute(
                text(
                    "SELECT host(ip) AS ip, COUNT(*) AS n, MIN(occurred_at), array_remove(array_agg(DISTINCT user_id), NULL) "
                    "FROM login_history WHERE institution_id = :i AND outcome = ANY(:o) AND occurred_at >= :since "
                    "AND ip IS NOT NULL GROUP BY 1 HAVING COUNT(*) >= :t"
                ),
                {
                    "i": self.inst,
                    "o": list(FAIL_OUTCOMES),
                    "since": now_utc() - timedelta(minutes=win),
                    "t": int(r.get("threshold") or 30),
                },
            )
        ).all()
        return [
            {"subject": ip, "ips": [ip], "users": list(us or []), "count": int(n), "first": f, "window": win}
            for ip, n, f, us in rows
        ]

    async def _rule_export_off_hours(self, r: dict[str, Any]) -> list[dict[str, Any]]:
        hours = list(r.get("hours") or [0, 6])
        win = int(r.get("window_minutes") or 60)
        tz = getattr(await self.institution(), "timezone", None) or "Asia/Kolkata"
        rows = (
            await self.db.execute(
                text(
                    "SELECT user_id, COUNT(*), MIN(occurred_at) FROM audit_logs WHERE institution_id = :i AND "
                    "occurred_at >= :since AND (action IN ('export', 'download') OR (module = 'reports' AND action = 'run')) "
                    "AND EXTRACT(HOUR FROM occurred_at AT TIME ZONE :tz) >= :h0 AND EXTRACT(HOUR FROM occurred_at AT TIME ZONE :tz) < :h1 "
                    "GROUP BY user_id"
                ),
                {
                    "i": self.inst,
                    "since": now_utc() - timedelta(minutes=win),
                    "tz": tz or "Asia/Kolkata",
                    "h0": int(hours[0]),
                    "h1": int(hours[1]),
                },
            )
        ).all()
        return [{"subject": str(u), "users": [u], "count": int(n), "first": f, "window": win} for u, n, f in rows]

    async def _rule_impersonation_writes(self, r: dict[str, Any]) -> list[dict[str, Any]]:
        win = int(r.get("window_minutes") or 60)
        rows = (
            await self.db.execute(
                text(
                    "SELECT impersonator_id, COUNT(*), MIN(occurred_at), array_agg(DISTINCT user_id) FROM audit_logs WHERE "
                    "institution_id = :i AND impersonator_id IS NOT NULL AND occurred_at >= :since AND action NOT IN "
                    "('view', 'view_pii', 'download', 'login') GROUP BY impersonator_id HAVING COUNT(*) >= :t"
                ),
                {"i": self.inst, "since": now_utc() - timedelta(minutes=win), "t": int(r.get("threshold") or 1)},
            )
        ).all()
        return [
            {
                "subject": str(imp),
                "users": list(us or []),
                "count": int(n),
                "first": f,
                "window": win,
                "impersonator_id": str(imp),
            }
            for imp, n, f, us in rows
        ]

    async def _raise(self, rule_name: str, r: dict[str, Any], hit: dict[str, Any]) -> bool:
        bucket = now_utc().strftime("%Y%m%d%H")
        aid = hashlib.sha256(f"{rule_name}|{hit['subject']}|{bucket}".encode()).hexdigest()[:16]
        existing = await self.meta("anomaly", aid)
        doc = {
            "id": aid,
            "rule": rule_name,
            "count": hit["count"],
            "window": hit.get("window"),
            "users": [str(u) for u in hit.get("users") or [] if u],
            "ips": hit.get("ips") or [],
            "subject": hit["subject"],
            "first_seen": existing.get("first_seen") or (hit.get("first") or now_utc()).isoformat(),
            "last_seen": now_utc().isoformat(),
            "acknowledged": bool(existing.get("acknowledged")),
            "note": existing.get("note"),
            "acknowledged_by": existing.get("acknowledged_by"),
            "created_at": existing.get("created_at") or now_utc().isoformat(),
        }
        await self.put_meta("anomaly", aid, doc)
        if existing:
            return False
        await self._audit(
            "anomaly_detected",
            "security_anomaly",
            None,
            None,
            {"rule": rule_name, "count": hit["count"], "subject": hit["subject"]},
            module="security",
        )
        await self._emit(
            "audit.anomaly_detected",
            {"rule": rule_name, "count": hit["count"], "alert_id": aid},
            "institution",
            self.inst,
        )
        roles = await self.a_setting("audit", "alert_recipients", ["institution_admin", "security_officer"])
        names = await self.user_refs([_uuid(u) for u in doc["users"]])
        await self._notify(
            "audit.anomaly",
            [],
            {
                "rule": rule_name,
                "count": hit["count"],
                "window": hit.get("window") or "",
                "users": ", ".join(names.values()) or ", ".join(doc["ips"]),
            },
            audience={"roles": list(roles or [])},
        )
        return True

    def _alert_out(self, m: dict[str, Any], names: dict[uuid.UUID, str]) -> AnomalyAlertOut:
        ids = [i for i in (_uuid(u) for u in m.get("users") or []) if i is not None]
        users = [AuditUser(id=i, name=names.get(i)) for i in ids]
        actions: list[dict[str, Any]] = []
        for u in users:
            actions.append(
                {
                    "action": "revoke_sessions",
                    "method": "POST",
                    "path": "/api/v1/security/sessions/revoke",
                    "body": {"user_id": str(u.id), "all": True},
                }
            )
            actions.append(
                {"action": "lock_user", "method": "PUT", "path": f"/api/v1/users/{u.id}", "body": {"is_active": False}}
            )
        if m.get("rule") == "login_failures_per_ip":
            actions.append({"action": "review_ip_allowlist", "path": "/admin/security"})
        return AnomalyAlertOut(
            id=str(m["id"]),
            rule=str(m["rule"]),
            count=int(m.get("count") or 0),
            window=m.get("window"),
            users=users,
            ips=list(m.get("ips") or []),
            first_seen=datetime.fromisoformat(str(m["first_seen"])),
            last_seen=datetime.fromisoformat(str(m["last_seen"])) if m.get("last_seen") else None,
            acknowledged=bool(m.get("acknowledged")),
            acknowledged_by=_uuid(m.get("acknowledged_by")),
            note=m.get("note"),
            recommended_actions=actions,
        )

    async def anomalies(self, active: bool | None) -> list[AnomalyAlertOut]:
        self.require_console()
        rows = [
            m for _, m in await self.meta_list("anomaly") if active is None or (not m.get("acknowledged")) == active
        ]
        names = await self.user_refs([_uuid(u) for m in rows for u in m.get("users") or []])
        return [self._alert_out(m, names) for m in rows[:500]]

    async def acknowledge(self, alert_id: str, note: str) -> AnomalyAlertOut:
        self.require_console()
        self.require_writer()
        m = await self.meta("anomaly", alert_id)
        if not m:
            raise not_found("Anomaly alert")
        m.update(
            {
                "acknowledged": True,
                "note": note,
                "acknowledged_by": str(self.actor_id) if self.actor_id else None,
                "acknowledged_at": now_utc().isoformat(),
            }
        )
        await self.put_meta("anomaly", alert_id, m)
        await self._audit(
            "anomaly_ack",
            "security_anomaly",
            None,
            None,
            {"rule": m.get("rule"), "id": alert_id, "note": note},
            module="security",
        )
        await self._emit(
            "audit.anomaly_acknowledged", {"alert_id": alert_id, "rule": m.get("rule")}, "institution", self.inst
        )
        names = await self.user_refs([_uuid(u) for u in m.get("users") or []])
        return self._alert_out(m, names)

    # ---- sessions ---------------------------------------------------------------------------------------------------
    def require_sessions(self) -> None:
        self.require("audit_logs:security", "audit_logs:manage", "users:view_all", "users:manage")

    async def sessions(self, user_id: uuid.UUID | None, include_revoked: bool = False) -> list[AdminSessionOut]:
        self.require_sessions()
        await self.require_sessions_feature()
        scope, b = self._user_scope_sql("s.user_id")
        where = ["s.institution_id = :i", scope]
        if not include_revoked:
            where += ["s.revoked_at IS NULL", "s.expires_at > now()"]
        if user_id:
            where.append("s.user_id = :u")
            b["u"] = user_id
        rows = (
            (
                await self.db.execute(
                    text(
                        "SELECT s.id, s.user_id, s.device_label, s.platform, host(s.ip) AS ip, s.created_at, s.last_seen_at, "
                        f"s.expires_at, s.revoked_at, s.revoked_reason FROM user_sessions s WHERE {' AND '.join(where)} "
                        "ORDER BY s.last_seen_at DESC LIMIT 1000"
                    ),
                    {"i": self.inst, **b},
                )
            )
            .mappings()
            .all()
        )
        names = await self.user_refs([r["user_id"] for r in rows])
        return [
            AdminSessionOut(
                id=r["id"],
                user=AuditUser(id=r["user_id"], name=names.get(r["user_id"])),
                device_label=r["device_label"],
                platform=r["platform"],
                ip_masked=mask_ip24(r["ip"]),
                created_at=r["created_at"],
                last_seen_at=r["last_seen_at"],
                expires_at=r["expires_at"],
                revoked_at=r["revoked_at"],
                revoked_reason=r["revoked_reason"],
            )
            for r in rows
        ]

    async def _target_visible(self, user_id: uuid.UUID) -> None:
        scope, b = self._user_scope_sql("u.id")
        found = (
            await self.db.execute(
                text(f"SELECT 1 FROM users u WHERE u.id = :u AND u.institution_id = :i AND {scope}"),
                {"u": user_id, "i": self.inst, **b},
            )
        ).first()
        if found is None:
            raise not_found("User")

    async def revoke(self, body: SessionRevokeRequest) -> SessionRevokeOut:
        self.require("audit_logs:security", "audit_logs:manage", "users:manage")
        await self.require_sessions_feature()
        self.require_writer()
        repo = SessionRepository(self.db)
        count, uid = 0, body.user_id
        if body.session_id:
            sess = await repo.get(body.session_id)
            if sess is None or sess.institution_id != self.inst:
                raise not_found("Session")
            await self._target_visible(sess.user_id)
            uid = sess.user_id
            if sess.revoked_at is None:
                await repo.revoke(sess, "revoked_by_admin")
                count = 1
        elif uid:
            await self._target_visible(uid)
            count = await repo.revoke_all(uid, "revoked_by_admin")
        else:
            raise APIError(422, ErrorCode.VALIDATION, "user_id or session_id is required", {"field": "user_id"})
        mfa = False
        if body.force_mfa_reenrol and uid:
            res: Any = await self.db.execute(
                text("UPDATE mfa_secrets SET confirmed_at = NULL WHERE user_id = :u"), {"u": uid}
            )
            mfa = bool(res.rowcount)
        await self._audit(
            "session_revoke",
            "user",
            uid,
            None,
            {
                "count": count,
                "session_id": str(body.session_id) if body.session_id else None,
                "mfa_reset": mfa,
                "reason": body.reason,
            },
            module="security",
        )
        await self._emit(
            "security.session_revoked_by_admin", {"user_id": str(uid), "count": count, "mfa_reset": mfa}, "user", uid
        )
        return SessionRevokeOut(revoked=count, user_id=uid, mfa_reset=mfa)

    async def login_history(
        self, user_id: uuid.UUID | None, date_from: datetime | None, date_to: datetime | None
    ) -> list[LoginHistoryAdminOut]:
        self.require_sessions()
        await self.require_sessions_feature()
        lo, hi = self.bounds(date_from, date_to)
        scope, b = self._user_scope_sql("user_id")
        where = ["institution_id = :i", "occurred_at BETWEEN :lo AND :hi", scope]
        if user_id:
            where.append("user_id = :u")
            b["u"] = user_id
        rows = (
            (
                await self.db.execute(
                    text(
                        "SELECT id, user_id, identifier, outcome, host(ip) AS ip, user_agent, occurred_at FROM login_history "
                        f"WHERE {' AND '.join(where)} ORDER BY occurred_at DESC LIMIT 1000"
                    ),
                    {"i": self.inst, "lo": lo, "hi": hi, **b},
                )
            )
            .mappings()
            .all()
        )
        names = await self.user_refs([r["user_id"] for r in rows])
        return [
            LoginHistoryAdminOut(
                id=r["id"],
                user=AuditUser(id=r["user_id"], name=names.get(r["user_id"])) if r["user_id"] else None,
                identifier=r["identifier"],
                outcome=r["outcome"],
                ip_masked=mask_ip24(r["ip"]),
                user_agent=(r["user_agent"] or "")[:120] or None,
                occurred_at=r["occurred_at"],
            )
            for r in rows
        ]


def _uuid(v: Any) -> uuid.UUID | None:
    if v in (None, ""):
        return None
    try:
        return v if isinstance(v, uuid.UUID) else uuid.UUID(str(v))
    except ValueError:
        return None


__all__ = ["SecurityService", "forbidden"]
