"""Scheduled dashboard digests — Prompts/35 §35.6 readmodel_service (``analytics.digest`` job) / §35.7 Beat.

A schedule (side store ``analytics_meta`` ``digest:<id>``) names a cadence (``daily`` | ``weekly``), role slugs and / or
user ids, channels (``in_app`` / ``email`` / ``whatsapp`` — delivered by the Phase 23/24 notification pipeline) and the
hour (institution time). Sending renders each recipient's **own** role dashboard under their own visibility (the
principal is loaded per recipient — a digest never shows more than the dashboard would), writes a one-page PDF summary
(stat cards + chart totals), uploads it and sends ``analytics.digest`` with the link. Beat ``analytics.digest_daily`` /
``analytics.digest_weekly`` (Monday) fire the schedules due at the current hour, once per day (``sent:<id>:<date>``).
"""

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import or_, select

from app.models.platform import Role, UserRole
from app.services.analytics.common import AnalyticsBase, forbidden, not_found, rule

__all__ = ["DigestService"]

CADENCES = ("daily", "weekly")
CHANNELS = ("in_app", "email", "whatsapp")


class DigestService(AnalyticsBase):
    def _require_admin(self) -> None:
        if not self.can("settings", "manage"):
            raise forbidden("settings:manage required")

    async def schedules(self) -> list[dict[str, Any]]:
        self._require_admin()
        metas = await self.metas("digest")
        return sorted(
            [{"id": k, **v} for k, v in metas.items() if not v.get("deleted")],
            key=lambda d: (d.get("cadence") or "", d.get("hour") or 0),
        )

    async def create(self, body: dict[str, Any]) -> dict[str, Any]:
        self._require_admin()
        if body.get("cadence") not in CADENCES:
            raise rule("cadence must be daily | weekly", "BAD_CADENCE", 422)
        channels = [c for c in body.get("channels") or ["in_app", "email"] if c in CHANNELS]
        if not (body.get("roles") or body.get("user_ids")):
            raise rule("Pick at least one role or user", "NO_RECIPIENTS", 422)
        did = str(uuid.uuid4())
        row = {
            "cadence": body["cadence"],
            "roles": list(body.get("roles") or []),
            "user_ids": [str(u) for u in body.get("user_ids") or []],
            "channels": channels or ["in_app"],
            "hour": int(body.get("hour") or 7) if body.get("hour") != 0 else 0,
            "created_by": str(self.actor_id) if self.actor_id else None,
            "created_at": datetime.now(UTC).isoformat(),
            "last_sent_at": None,
        }
        await self.put_meta("digest", did, row)
        return {"id": did, **row}

    async def delete(self, did: str) -> None:
        self._require_admin()
        m = await self.meta("digest", did)
        if not m or m.get("deleted"):
            raise not_found("Digest")
        await self.put_meta("digest", did, {**m, "deleted": True})

    async def get(self, did: str) -> dict[str, Any]:
        m = await self.meta("digest", did)
        if not m or m.get("deleted"):
            raise not_found("Digest")
        return {"id": did, **m}

    async def recipients(self, d: dict[str, Any]) -> list[tuple[uuid.UUID, str | None]]:
        out: dict[uuid.UUID, str | None] = {}
        if d.get("roles"):
            rows = (
                await self.db.execute(
                    select(UserRole.user_id, Role.slug)
                    .join(Role, Role.id == UserRole.role_id)
                    .where(
                        Role.slug.in_(d["roles"]),
                        or_(UserRole.institution_id == self.inst, UserRole.institution_id.is_(None)),
                    )
                )
            ).all()
            for uid, slug in rows:
                out.setdefault(uid, slug)
        for u in d.get("user_ids") or []:
            try:
                out.setdefault(uuid.UUID(str(u)), None)
            except ValueError:
                continue
        return list(out.items())

    async def send(self, did: str) -> dict[str, Any]:
        """Job ``analytics.digest``: one PDF per recipient under the recipient's own visibility."""
        from app.services.analytics.dashboard_service import DashboardService
        from app.services.auth_service import load_principal
        from app.utils.pdf import simple_pdf

        d = await self.get(did)
        inst_name = (await self.institution()).name
        sent = 0
        failed = 0
        for uid, role in await self.recipients(d):
            try:
                principal = await load_principal(self.db, uid)
                dash = await DashboardService(self.db, principal, None, self.inst).for_role(role)
            except Exception:  # noqa: BLE001 - an inactive user / missing role skips that recipient
                failed += 1
                continue
            lines, summary = self.summarise(dash)
            url = await self._upload(
                f"digest-{d['cadence']}-{uid}-{date.today().isoformat()}.pdf",
                simple_pdf(lines, title=f"{inst_name} — {d['cadence']} digest"),
            )
            await self._notify(
                "analytics.digest",
                [uid],
                {
                    "cadence": d["cadence"],
                    "institution": inst_name,
                    "role": dash["role"],
                    "summary": summary,
                    "url": url,
                },
            )
            sent += 1
        await self.put_meta(
            "digest", did, {**{k: v for k, v in d.items() if k != "id"}, "last_sent_at": datetime.now(UTC).isoformat()}
        )
        await self._emit(
            "analytics.digest_sent", {"digest_id": did, "sent": sent, "failed": failed}, "institution", self.inst
        )
        return {"digest_id": did, "sent": sent, "failed": failed}

    @staticmethod
    def summarise(dash: dict[str, Any]) -> tuple[list[str], str]:
        lines = [f"Role: {dash.get('role')}", f"Generated: {datetime.now(UTC):%Y-%m-%d %H:%M} UTC", ""]
        bits: list[str] = []
        for w in dash.get("widgets", []):
            if w.get("unavailable"):
                continue
            if w.get("stat"):
                s = w["stat"]
                tgt = f" (target {s['target']})" if s.get("target") is not None else ""
                lines.append(f"{w.get('title')}: {s.get('value')}{tgt}")
                if len(bits) < 4:
                    bits.append(f"{w.get('title')} {s.get('value')}")
            elif w.get("data"):
                total = w["data"].get("total")
                lines.append(f"{w.get('title')}: {total if total is not None else len(w['data'].get('series') or [])}")
            elif w.get("items") is not None:
                lines.append(f"{w.get('title')}: {len(w['items'])} item(s)")
        for a in dash.get("alerts", []):
            if a.get("kind") == "kpi":
                lines.append(f"ALERT {a.get('key')}: {a.get('value')} vs target {a.get('target')}")
        return lines, "; ".join(bits) or "see attachment"

    async def _upload(self, name: str, content: bytes) -> str:
        from app.core.files import build_key, get_storage

        key = build_key(self.inst, "analytics", name)
        storage = get_storage()
        await storage.put(key, content, "application/pdf")
        return storage.signed_url(key)

    async def due(self, cadence: str, hour: int) -> list[str]:
        today = date.today().isoformat()
        out = []
        for k, v in (await self.metas("digest")).items():
            if v.get("deleted") or v.get("cadence") != cadence or int(v.get("hour") or 7) != hour:
                continue
            if (v.get("last_sent_at") or "")[:10] == today:
                continue
            out.append(k)
        return out
