"""Security posture, MFA enforcement, scans, JWT keys, VAPT / ISO trackers — Prompts/43 §43.6
``security_hardening_service`` items 2 / 5 / 6, ``vapt_service`` and ``iso_readiness_service``.

Posture controls (``pass | warn | fail``; score = pass + ½ warn over the controls): ``csp`` (enforced vs report-only),
``tls`` (https origins in production), ``jwt`` (RS256 + key published), ``mfa`` (users in MFA-required roles without a
confirmed secret), ``sessions`` (live sessions older than ``security.session_max_days``), ``ip_allowlist_exam_ops``
(no active ``exam_decode`` / ``results_publish`` CIDR), ``api_keys`` (no expiry / unused for
``security.api_key_unused_days``), ``scans`` (``platform_settings['security.scans']`` high findings), ``backups``
(``platform_settings['ops.backups']`` last run ≤ 26 h, Phase 44), ``audit_chain`` (Phase 37 last verification),
``vapt`` (open high / critical findings in ``docs/Security/VAPT_Findings.csv``). Results are stored in
``security_meta posture:latest``; the platform view (super admin) aggregates every tenant's latest result.
"""

from __future__ import annotations

import builtins
import csv
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.core import events
from app.core.audit import log_audit
from app.core.config import settings
from app.core.notifications.notify import notify_event
from app.core.security import jwks, signing_algorithm
from app.services.hardening.common import HardeningBase

DOCS = Path(__file__).resolve().parents[4] / "docs" / "Security"
SECURITY_META = "security_meta"
MFA_DEFAULT = (
    "super_admin",
    "institution_admin",
    "registrar",
    "controller_of_examinations",
    "exam_cell",
    "accountant",
    "privacy_officer",
    "integration_admin",
)


def _item(control: str, status: str, detail: str, evidence: str | None = None) -> dict[str, Any]:
    return {
        "control": control,
        "status": status,
        "detail": detail,
        "evidence_url": evidence,
        "last_checked": datetime.now(UTC).isoformat(),
    }


def vapt_findings() -> builtins.list[dict[str, str]]:
    path = DOCS / "VAPT_Findings.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def vapt_status() -> dict[str, Any]:
    rows = vapt_findings()
    open_rows = [r for r in rows if (r.get("status") or "").lower() not in ("fixed", "closed", "accepted")]
    by: dict[str, int] = {}
    for r in open_rows:
        sev = (r.get("severity") or "unknown").lower()
        by[sev] = by.get(sev, 0) + 1
    retest = sum(
        1 for r in rows if (r.get("status") or "").lower() == "fixed" and (r.get("retest") or "").lower() != "pass"
    )
    blocked = by.get("critical", 0) + by.get("high", 0) > 0 or retest > 0
    return {
        "findings": rows,
        "open_by_severity": by,
        "retest_pending": retest,
        "gate": "blocked" if blocked else "pass",
    }


def iso_readiness() -> dict[str, Any]:
    path = DOCS / "ISO27001_Readiness.md"
    counts = {"implemented": 0, "partial": 0, "missing": 0}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\|\s*A\.\d+\.\d+.*\|\s*(implemented|partial|missing)\s*\|", line, re.I)
            if m:
                counts[m.group(1).lower()] += 1
    return {"controls_total": sum(counts.values()), **counts, "checklist_url": "docs/Security/ISO27001_Readiness.md"}


class PostureService(HardeningBase):
    def require_read(self) -> None:
        self.require("security:view", "security:view_all", "security:manage", "privacy:manage")

    def require_manage(self) -> None:
        self.require("security:manage")

    async def _required_roles(self) -> builtins.list[str]:
        configured = await self.setting("security", "mfa_required_roles", None)
        return list(configured) if isinstance(configured, list) and configured else list(MFA_DEFAULT)

    async def mfa_missing(self) -> builtins.list[dict[str, Any]]:
        roles = await self._required_roles()
        rows = (
            await self.db.execute(
                text(
                    "SELECT u.id, u.display_name, array_agg(DISTINCT r.slug) FROM users u JOIN user_roles ur ON ur.user_id = u.id "
                    "JOIN roles r ON r.id = ur.role_id LEFT JOIN mfa_secrets m ON m.user_id = u.id AND m.confirmed_at IS NOT NULL "
                    "WHERE u.institution_id = :i AND u.deleted_at IS NULL AND u.is_active AND r.slug = ANY(:r) AND m.id IS NULL "
                    "GROUP BY u.id, u.display_name ORDER BY u.display_name LIMIT 500"
                ),
                {"i": self.inst, "r": roles},
            )
        ).all()
        return [{"user_id": str(u), "user": name, "roles": list(rs or [])} for u, name, rs in rows]

    async def check(self) -> dict[str, Any]:  # noqa: C901, PLR0912, PLR0915 - one list of controls
        self.require_read()
        items: list[dict[str, Any]] = []
        items.append(
            _item(
                "csp",
                "pass" if settings.CSP_ENFORCE else "warn",
                "CSP enforced" if settings.CSP_ENFORCE else "CSP in report-only mode",
            )
        )
        https = all(o.startswith("https://") for o in settings.ALLOWED_ORIGINS)
        items.append(
            _item(
                "tls",
                "pass" if https else ("fail" if settings.is_production else "warn"),
                "all allowed origins are https" if https else "non-https origins configured",
            )
        )
        alg = signing_algorithm()
        items.append(
            _item(
                "jwt",
                "pass" if alg == "RS256" and jwks()["keys"] else "warn",
                f"tokens signed with {alg}",
                "/.well-known/jwks.json",
            )
        )
        missing = await self.mfa_missing()
        items.append(
            _item("mfa", "pass" if not missing else "fail", f"{len(missing)} user(s) in MFA-required roles without MFA")
        )
        max_days = int(await self.setting("security", "session_max_days", 7) or 7)
        old = (
            await self.db.execute(
                text(
                    "SELECT count(*) FROM user_sessions WHERE institution_id = :i AND revoked_at IS NULL AND expires_at > NOW() "
                    "AND created_at < NOW() - make_interval(days => :d)"
                ),
                {"i": self.inst, "d": max_days},
            )
        ).scalar_one()
        items.append(
            _item("sessions", "pass" if not old else "warn", f"{old} live session(s) older than {max_days} days")
        )
        allow = (
            await self.db.execute(
                text(
                    "SELECT count(*) FROM ip_allowlists WHERE institution_id = :i AND is_active "
                    "AND purpose IN ('exam_decode', 'results_publish')"
                ),
                {"i": self.inst},
            )
        ).scalar_one()
        items.append(
            _item(
                "ip_allowlist_exam_ops",
                "pass" if allow else "warn",
                "exam decode / result publish restricted by IP" if allow else "no IP allow-list for exam operations",
            )
        )
        unused = int(await self.setting("security", "api_key_unused_days", 90) or 90)
        keys = (
            await self.db.execute(
                text(
                    "SELECT count(*) FILTER (WHERE expires_at IS NULL), count(*) FILTER (WHERE coalesce(last_used_at, created_at) "
                    "< NOW() - make_interval(days => :d)) FROM api_keys WHERE institution_id = :i AND is_active"
                ),
                {"i": self.inst, "d": unused},
            )
        ).one()
        items.append(
            _item(
                "api_keys",
                "pass" if not (keys[0] or keys[1]) else "warn",
                f"{keys[0]} key(s) without expiry, {keys[1]} unused for {unused} days",
            )
        )
        scans = await self.platform_value("security.scans", None) or {}
        high = sum(int((s or {}).get("high", 0)) for s in (scans.values() if isinstance(scans, dict) else []))
        items.append(
            _item(
                "scans",
                "warn" if not scans else ("fail" if high else "pass"),
                "no scan summary pushed yet" if not scans else f"{high} high finding(s) across {len(scans)} tool(s)",
            )
        )
        backups = await self.platform_value("ops.backups", None) or {}
        last = backups.get("last_success_at") if isinstance(backups, dict) else None
        fresh = bool(last) and datetime.fromisoformat(str(last)) > datetime.now(UTC) - timedelta(hours=26)
        items.append(_item("backups", "pass" if fresh else "warn", f"last successful backup {last or 'unknown'}"))
        chain = (
            await self.db.execute(
                text(
                    "SELECT value FROM institution_settings WHERE institution_id = :i AND category = 'audit_meta' "
                    "AND key LIKE 'verify:%' ORDER BY updated_at DESC LIMIT 1"
                ),
                {"i": self.inst},
            )
        ).scalar_one_or_none()
        chain_ok = isinstance(chain, dict) and bool(chain.get("ok"))
        items.append(
            _item(
                "audit_chain",
                "pass" if chain_ok else ("fail" if isinstance(chain, dict) else "warn"),
                "hash chain verified"
                if chain_ok
                else ("chain broken" if isinstance(chain, dict) else "no chain verification yet"),
            )
        )
        v = vapt_status()
        items.append(
            _item(
                "vapt",
                "pass" if v["gate"] == "pass" else "fail",
                f"open: {v['open_by_severity']}",
                "docs/Security/VAPT_Findings.csv",
            )
        )
        score = round(
            100 * sum(1 if i["status"] == "pass" else 0.5 if i["status"] == "warn" else 0 for i in items) / len(items),
            1,
        )
        result = {"items": items, "score": score, "checked_at": datetime.now(UTC).isoformat()}
        await self.put_meta("posture:latest", result, SECURITY_META)
        await events.emit(
            self.db,
            institution_id=self.inst,
            event_type="security.posture_checked",
            payload={"score": score, "fail": [i["control"] for i in items if i["status"] == "fail"]},
            aggregate_type="institution",
            aggregate_id=self.inst,
            actor_user_id=getattr(self.principal, "id", None),
        )
        return result

    async def latest(self) -> dict[str, Any]:
        self.require_read()
        return dict(await self.meta("posture:latest", SECURITY_META) or {"items": [], "score": None})

    async def mfa_enforcement(self) -> dict[str, Any]:
        self.require_read()
        return {
            "required_roles": await self._required_roles(),
            "users_missing": await self.mfa_missing(),
            "grace_until": await self.setting("security", "mfa_grace_until", None),
        }

    async def enforce_mfa(self, grace_days: int) -> dict[str, Any]:
        self.require_manage()
        until = (datetime.now(UTC) + timedelta(days=grace_days)).isoformat()
        await self.put_meta("mfa_grace_until", until, "security")
        missing = await self.mfa_missing()
        if missing:
            await notify_event(
                self.db,
                self.inst,
                "security.mfa_enforcement_reminder",
                audience={"user_ids": [m["user_id"] for m in missing]},
                context={"grace_until": until},
            )
        await events.emit(
            self.db,
            institution_id=self.inst,
            event_type="security.mfa_enforced",
            payload={"grace_until": until, "users": len(missing)},
            aggregate_type="institution",
            aggregate_id=self.inst,
            actor_user_id=self.principal.id,
        )
        await log_audit(
            self.db,
            principal=self.principal,
            module="security",
            action="mfa_enforce",
            record_type="institution",
            record_id=self.inst,
            new={"grace_until": until, "users": len(missing)},
            request=self.request,
        )
        return {"grace_until": until, "reminded": len(missing)}

    async def scans(self) -> builtins.list[dict[str, Any]]:
        self.require_read()
        raw = await self.platform_value("security.scans", None) or {}
        return [{"tool": k, **(v or {})} for k, v in sorted(raw.items())] if isinstance(raw, dict) else []

    async def jwt_status(self) -> dict[str, Any]:
        return {
            "algorithm": signing_algorithm(),
            "current_kid": settings.JWT_KID,
            "published_keys": [k["kid"] for k in jwks()["keys"]],
            "previous_kids": sorted({*settings.JWT_PREVIOUS_KEYS, *settings.JWT_RSA_PREVIOUS_PUBLIC_KEYS}),
            "rotation_runbook": "docs/Runbooks/jwt_key_rotation.md",
        }

    async def platform_posture(self) -> dict[str, Any]:
        rows = (
            await self.db.execute(
                text(
                    "SELECT s.institution_id, i.name, s.value FROM institution_settings s JOIN institutions i ON i.id = s.institution_id "
                    "WHERE s.category = :c AND s.key = 'posture:latest'"
                ),
                {"c": SECURITY_META},
            )
        ).all()
        tenants = [
            {
                "institution_id": str(i),
                "name": n,
                "score": (v or {}).get("score"),
                "fail": [x["control"] for x in (v or {}).get("items", []) if x.get("status") == "fail"],
            }
            for i, n, v in rows
        ]
        return {
            "tenants": tenants,
            "scans": await self.scans_platform(),
            "vapt": vapt_status(),
            "iso": iso_readiness(),
            "jwt": await self.jwt_status(),
        }

    async def scans_platform(self) -> builtins.list[dict[str, Any]]:
        raw = await self.platform_value("security.scans", None) or {}
        return [{"tool": k, **(v or {})} for k, v in sorted(raw.items())] if isinstance(raw, dict) else []
