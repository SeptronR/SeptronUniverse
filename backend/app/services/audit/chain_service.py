"""Audit hash-chain verification and signed daily digests — Prompts/37 §37.6 ``audit_service`` step 2.

* ``verify(from, to)`` walks ``audit_logs`` of the institution in ``(occurred_at, id)`` order in SQL batches of
  10 000. Each row's hash is recomputed **in SQL** with the trigger's own expression
  (``sha256(prev_hash || module || action || record_id || new_values || occurred_at)`` — Database_Schema.sql
  ``trigger_audit_hash_chain``), and ``prev_hash`` must name a row already seen — or, failing that, an existing row of
  the institution (the trigger links rows in insertion order; rows written in one transaction share ``occurred_at``
  and back-dated rows point at later ones). The first row failing either check is reported.
  With ``compare_digests`` the stored daily digests of the range are recomputed and compared, and the archived digest
  files are compared with the stored ones (a tampered file or row → mismatch). A failure emits
  ``audit.chain_broken`` and notifies ``audit.alert_recipients`` (Phase 38 raises the platform alert from the event).
* ``sign_day(date)`` (Beat ``audit.digest_daily`` 00:15) computes the day's digest (row count + last hash), signs it
  with HMAC-SHA256 under ``audit.digest_signing_key_id`` (derived from the platform secret — the key id is recorded),
  stores ``audit_meta digest:<date>`` and writes ``{institution}/audit-digests/{date}.json`` to the file store (cold
  storage), independent of the database.
* ``dev_corrupt_copy`` (development only) copies the last 7 days into ``audit_logs_dev_copy``, flips one row's
  ``new_values`` and verifies the copy — the live chain is never touched.
"""

import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import text

from app.core.config import settings as app_settings
from app.schemas.audit import BrokenLink, ChainDigestOut, ChainVerifyOut
from app.services.audit.common import AuditBase, forbidden, now_utc

RECOMPUTE = (
    "encode(digest(COALESCE(prev_hash,'') || module || action || COALESCE(record_id::text,'') || "
    "COALESCE(new_values::text,'') || occurred_at::text, 'sha256'), 'hex')"
)
BATCH = 10_000
LIVE = "audit_logs"
DEV_COPY = "audit_logs_dev_copy"


def _sign(key_id: str, payload: str) -> str:
    key = hashlib.sha256(f"{app_settings.SECRET_KEY}:audit-digest:{key_id}".encode()).digest()
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()


class ChainService(AuditBase):
    def require_verifier(self) -> None:
        self.require("audit_logs:verify_chain", "audit_logs:manage")

    # ---- walk -------------------------------------------------------------------------------------------------------
    async def _walk(self, table: str, lo: datetime, hi: datetime) -> tuple[int, BrokenLink | None, str]:
        prev = (
            await self.db.execute(
                text(
                    f"SELECT hash FROM {table} WHERE institution_id = :i AND occurred_at < :lo "
                    "ORDER BY occurred_at DESC, id DESC LIMIT 1"
                ),
                {"i": self.inst, "lo": lo},
            )
        ).first()
        seen: set[str] = {prev[0]} if prev else set()
        rows, last_hash = 0, prev[0] if prev else ""
        cursor_at, cursor_id = lo - timedelta(microseconds=1), uuid.UUID(int=0)
        first_row = prev is None
        while True:
            batch = (
                await self.db.execute(
                    text(
                        f"SELECT id, occurred_at, prev_hash, hash, {RECOMPUTE} AS recomputed FROM {table} "
                        "WHERE institution_id = :i AND occurred_at <= :hi AND (occurred_at, id) > (:ca, :cid) "
                        "ORDER BY occurred_at, id LIMIT :n"
                    ),
                    {"i": self.inst, "hi": hi, "ca": cursor_at, "cid": cursor_id, "n": BATCH},
                )
            ).all()
            if not batch:
                break
            for rid, at, prev_hash, h, recomputed in batch:
                rows += 1
                if h != recomputed:
                    return rows, BrokenLink(id=rid, occurred_at=at, reason="hash_mismatch"), last_hash
                if prev_hash is None:
                    if not first_row:
                        return rows, BrokenLink(id=rid, occurred_at=at, reason="missing_prev_hash"), last_hash
                elif seen and prev_hash not in seen and not await self._hash_exists(table, prev_hash):
                    # the trigger links rows in insertion order: a back-dated row may point at a later row
                    return rows, BrokenLink(id=rid, occurred_at=at, reason="prev_hash_unknown"), last_hash
                first_row = False
                seen.add(h)
                last_hash = h
            cursor_at, cursor_id = batch[-1][1], batch[-1][0]
            if len(batch) < BATCH:
                break
        return rows, None, last_hash

    async def _hash_exists(self, table: str, h: str) -> bool:
        found = (
            await self.db.execute(
                text(f"SELECT 1 FROM {table} WHERE institution_id = :i AND hash = :h LIMIT 1"), {"i": self.inst, "h": h}
            )
        ).first()
        return found is not None

    async def verify(
        self, date_from: datetime | None, date_to: datetime | None, compare_digests: bool = True, table: str = LIVE
    ) -> ChainVerifyOut:
        self.require_verifier()
        hi = date_to or now_utc()
        lo = date_from or hi - timedelta(days=7)
        started = time.monotonic()
        rows, broken, last_hash = await self._walk(table, lo, hi)
        digest = hashlib.sha256(
            f"{self.inst}|{lo.isoformat()}|{hi.isoformat()}|{rows}|{last_hash}".encode()
        ).hexdigest()
        mismatches = (
            await self._compare_digests(lo.date(), hi.date(), table) if compare_digests and table == LIVE else []
        )
        ok = broken is None and not mismatches
        vid = uuid.uuid4().hex[:12]
        result = ChainVerifyOut(
            ok=ok,
            rows=rows,
            first_broken=broken,
            digest=digest,
            duration_ms=int((time.monotonic() - started) * 1000),
            date_from=lo,
            date_to=hi,
            digest_mismatches=mismatches,
            verification_id=vid,
        )
        await self.put_meta(
            "verify",
            vid,
            {
                **result.model_dump(mode="json"),
                "table": table,
                "created_at": now_utc().isoformat(),
                "by": str(self.actor_id) if self.actor_id else None,
            },
        )
        await self._audit(
            "verify_chain",
            "audit_logs",
            None,
            None,
            {"rows": rows, "ok": ok, "table": table, "from": lo.isoformat(), "to": hi.isoformat()},
        )
        if table == LIVE:
            await self._emit(
                "audit.chain_verified" if ok else "audit.chain_broken",
                {"ok": ok, "rows": rows, "first_broken": str(broken.id) if broken else None, "mismatches": mismatches},
                "institution",
                self.inst,
            )
            if not ok:
                await self.alert_broken(lo, hi, broken, mismatches)
        return result

    async def alert_broken(self, lo: datetime, hi: datetime, broken: BrokenLink | None, mismatches: list[str]) -> None:
        roles = await self.a_setting("audit", "alert_recipients", ["institution_admin", "security_officer"])
        inst = await self.institution()
        await self._notify(
            "audit.chain_broken",
            [],
            {
                "institution": inst.name,
                "range": f"{lo.date()} – {hi.date()}",
                "first_broken": str(broken.id) if broken else ", ".join(mismatches[:5]),
            },
            audience={"roles": list(roles or [])},
        )

    # ---- digests ----------------------------------------------------------------------------------------------------
    async def _day(self, d: date, table: str = LIVE) -> tuple[int, str | None]:
        lo = datetime(d.year, d.month, d.day, tzinfo=UTC)
        row = (
            await self.db.execute(
                text(
                    f"SELECT COUNT(*), (SELECT hash FROM {table} WHERE institution_id = :i AND occurred_at >= :lo AND "
                    f"occurred_at < :hi ORDER BY occurred_at DESC, id DESC LIMIT 1) FROM {table} "
                    "WHERE institution_id = :i AND occurred_at >= :lo AND occurred_at < :hi"
                ),
                {"i": self.inst, "lo": lo, "hi": lo + timedelta(days=1)},
            )
        ).one()
        return int(row[0]), row[1]

    def _digest(self, d: date, rows: int, last_hash: str | None) -> str:
        return hashlib.sha256(f"{self.inst}|{d.isoformat()}|{rows}|{last_hash or ''}".encode()).hexdigest()

    async def sign_day(self, d: date) -> ChainDigestOut:
        from app.core.files import build_key, get_storage

        rows, last_hash = await self._day(d)
        key_id = str(await self.a_setting("audit", "digest_signing_key_id", "platform-default") or "platform-default")
        digest = self._digest(d, rows, last_hash)
        signature = _sign(key_id, digest)
        doc = {
            "institution_id": str(self.inst),
            "date": d.isoformat(),
            "rows": rows,
            "last_hash": last_hash,
            "digest": digest,
            "signature": signature,
            "key_id": key_id,
            "signed_at": now_utc().isoformat(),
        }
        key = build_key(self.inst, "audit-digests", f"{d.isoformat()}.json")
        archived = None
        try:
            await get_storage().put(key, json.dumps(doc, sort_keys=True).encode(), "application/json")
            archived = key
        except Exception:  # noqa: BLE001 - the stored digest still counts; the next run re-archives
            archived = None
        await self.put_meta("digest", d.isoformat(), {**doc, "archived_key": archived})
        await self._audit(
            "digest_sign", "audit_logs", None, None, {"date": d.isoformat(), "rows": rows, "digest": digest}
        )
        await self._emit("audit.digest_signed", {"date": d.isoformat(), "rows": rows}, "institution", self.inst)
        return self._digest_out(d, {**doc, "archived_key": archived})

    def _digest_out(self, d: date, m: dict[str, Any], verified: bool | None = None) -> ChainDigestOut:
        from app.core.files import get_storage

        key = m.get("archived_key")
        return ChainDigestOut(
            date=d,
            rows=int(m.get("rows") or 0),
            last_hash=m.get("last_hash"),
            digest=str(m.get("digest") or ""),
            signed=bool(m.get("signature"))
            and m.get("signature") == _sign(str(m.get("key_id") or ""), str(m.get("digest") or "")),
            key_id=m.get("key_id"),
            archived_url=get_storage().signed_url(str(key), 3600) if key else None,
            verified=verified,
        )

    async def digests(self, date_from: date | None, date_to: date | None) -> list[ChainDigestOut]:
        self.require_verifier()
        hi = date_to or now_utc().date()
        lo = date_from or hi - timedelta(days=30)
        out = []
        for k, m in (await self.metas("digest")).items():
            try:
                d = date.fromisoformat(k)
            except ValueError:
                continue
            if lo <= d <= hi:
                out.append(self._digest_out(d, m))
        return sorted(out, key=lambda x: x.date, reverse=True)

    async def _compare_digests(self, lo: date, hi: date, table: str) -> list[str]:
        from app.core.files import get_storage

        storage = get_storage()
        bad: list[str] = []
        for k, m in (await self.metas("digest")).items():
            try:
                d = date.fromisoformat(k)
            except ValueError:
                continue
            if not lo <= d <= hi:
                continue
            rows, last_hash = await self._day(d, table)
            if self._digest(d, rows, last_hash) != m.get("digest"):
                bad.append(f"{k}:recomputed")
                continue
            if m.get("signature") != _sign(str(m.get("key_id") or ""), str(m.get("digest") or "")):
                bad.append(f"{k}:signature")
                continue
            if m.get("archived_key"):
                try:
                    archived = json.loads(await storage.get(str(m["archived_key"])))
                except Exception:  # noqa: BLE001 - a missing / unreadable archive is a mismatch
                    bad.append(f"{k}:archive_missing")
                    continue
                if archived.get("digest") != m.get("digest") or archived.get("signature") != m.get("signature"):
                    bad.append(f"{k}:archive_tampered")
        return sorted(bad)

    async def daily_digest(self, today: date) -> int:
        """Beat ``audit.digest_daily``: sign yesterday's digest."""
        await self.sign_day(today - timedelta(days=1))
        return 1

    async def daily_verify(self, today: date) -> int:
        """Beat ``audit.chain_verify_daily``: the last 24 h (and the whole previous month on the 1st)."""
        if not await self.a_setting("audit", "chain_verify_daily", True):
            return 0
        hi = now_utc()
        lo = hi - timedelta(days=1)
        if today.day == 1:
            first = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
            lo = datetime(first.year, first.month, 1, tzinfo=UTC)
        out = await self.verify(lo, hi)
        return int(out.rows)

    # ---- development fixture ----------------------------------------------------------------------------------------
    async def dev_corrupt_copy(self) -> ChainVerifyOut:
        if app_settings.APP_ENV != "development":
            raise forbidden("Development only")
        self.require_verifier()
        hi = now_utc()
        lo = hi - timedelta(days=7)
        await self.db.execute(text(f"DROP TABLE IF EXISTS {DEV_COPY}"))
        await self.db.execute(
            text(
                f"CREATE TEMP TABLE {DEV_COPY} AS SELECT * FROM audit_logs WHERE institution_id = :i AND occurred_at >= :lo"
            ),
            {"i": self.inst, "lo": lo - timedelta(days=1)},
        )
        await self.db.execute(
            text(
                f"UPDATE {DEV_COPY} SET new_values = COALESCE(new_values, '{{}}'::jsonb) || '{{\"tampered\": true}}'::jsonb "
                f"WHERE id = (SELECT id FROM {DEV_COPY} WHERE occurred_at >= :lo ORDER BY occurred_at OFFSET "
                f"(SELECT COUNT(*) / 2 FROM {DEV_COPY} WHERE occurred_at >= :lo) LIMIT 1)"
            ),
            {"lo": lo},
        )
        return await self.verify(lo, hi, compare_digests=False, table=DEV_COPY)

    async def dev_tamper_digest(self, d: date) -> None:
        """Development only: rewrite the archived digest file of ``d`` (the next verify reports the mismatch)."""
        from app.core.files import get_storage

        if app_settings.APP_ENV != "development":
            raise forbidden("Development only")
        m = await self.meta("digest", d.isoformat())
        if m.get("archived_key"):
            doc = {**m, "digest": "0" * 64}
            await get_storage().put(str(m["archived_key"]), json.dumps(doc).encode(), "application/json")
