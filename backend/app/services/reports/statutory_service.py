"""Statutory reports (``reports.statutory``) — Prompts/36 §36.6 ``statutory_service`` / §36.5 ``statutory_repository``.

1. Definitions: ``app/enums/reports.py:STATUTORY_DEFS`` (the pack's statutory list) — period type, sections
   (``statutory_sections.py`` providers; aggregates only), Phase 32 submission type, due date, default sign-off roles
   (``reports.statutory_signoff_roles`` overrides per institution).
2. ``generate(code, period)`` (job ``report.statutory_generate``): build payload → validate (section totals equal the
   Phase 32 metric named by the section, mandatory fields present, the Phase 32 consistency check of the period) →
   render the code's formats (xlsx / csv / pdf with a sign-off block / docx narrative) → register each file in
   ``issued_documents`` (``template_type='statutory_report'``, ``entity_type='compliance_submission'``) → create /
   update the Phase 32 ``compliance_submissions`` row (``status='generated'``, payload summary, file URL) → status
   ``generated``. Regenerating after sign-off creates a new version and revokes the previous documents; a
   submitted period (Phase 32 ``submitted`` / ``acknowledged``) is immutable.
3. Review: ``request_review`` (notifies the sign-off role holders) → ``sign_off`` by each required role (order-free)
   → ``signed_off`` (files locked); ``reopen`` with reason before submission. Diff vs a previous period per section,
   export pack (zip of every file + validation report), due calendar → reminders.

State lives in ``institution_settings`` (category ``reports_meta``) under ``statutory:<code>:<period>[:<discipline>]``.
"""

import json
import secrets
import uuid
from datetime import date
from typing import Any

from sqlalchemy import select, text, update

from app.core.errors import APIError, ErrorCode
from app.core.jobs import enqueue
from app.core.reports import ReportColumn
from app.enums.reports import STATUTORY_DEFS
from app.models.accreditation import ComplianceSubmission
from app.models.documents import IssuedDocument
from app.schemas.reports import (
    ReportRunOut,
    StatutoryDiffOut,
    StatutoryGenerateRequest,
    StatutoryListItem,
    StatutoryOut,
    StatutoryReviewAction,
)
from app.services.reports import render_service as R
from app.services.reports.common import ReportsBase, forbidden, not_found, now_utc, rule
from app.services.reports.statutory_sections import SECTIONS, Period, parse_period

__all__ = ["StatutoryService"]

MANAGERS = ("institution_admin", "registrar", "iqac_coordinator", "vice_chancellor")
SUBMITTED = ("submitted", "acknowledged")


def _cols(section: dict[str, Any]) -> list[ReportColumn]:
    return [c if isinstance(c, ReportColumn) else ReportColumn(**c) for c in section.get("columns") or []]


def _json_safe(v: Any) -> Any:
    return json.loads(json.dumps(v, default=str))


class StatutoryService(ReportsBase):
    # ---- access ---------------------------------------------------------------------------------------------------------
    async def require_on(self) -> None:
        if not await self.feature_on("reports.statutory"):
            raise APIError(
                403,
                ErrorCode.FEATURE_DISABLED,
                "Feature reports.statutory is not enabled",
                {"feature": "reports.statutory"},
            )

    def defn(self, code: str) -> dict[str, Any]:
        d = STATUTORY_DEFS.get(code)
        if d is None:
            raise not_found("Statutory report")
        return d

    async def signoff_roles(self, code: str) -> list[str]:
        roles = await self.r_setting("statutory_signoff_roles", {}) or {}
        return list(roles.get(code) or self.defn(code)["signoff"])

    def is_reader(self) -> bool:
        return (
            self.can("reports", "statutory")
            or self.is_admin()
            or (self.can("reports", "view_all") and "auditor" in self.roles())
        )

    async def require_reader(self) -> None:
        await self.require_on()
        if not self.is_reader():
            raise forbidden("reports:statutory required")

    async def require_generator(self, code: str) -> None:
        """``reports:statutory`` + (registrar / IQAC / principal / admin, or a sign-off role of this code)."""
        await self.require_reader()
        self.require_writer()
        if self.is_admin() or any(r in self.roles() for r in MANAGERS):
            return
        if any(self.holds_role(r) for r in await self.signoff_roles(code)):
            return
        raise forbidden(f"Only {', '.join(await self.signoff_roles(code))} or the registrar / IQAC can generate {code}")

    # ---- state -------------------------------------------------------------------------------------------------------------
    @staticmethod
    def state_key(code: str, period: str, discipline: str | None) -> str:
        return f"{code}:{period}" + (f":{discipline}" if discipline else "")

    async def state(self, code: str, period: str, discipline: str | None = None) -> dict[str, Any]:
        return await self.meta("statutory", self.state_key(code, period, discipline))

    async def put_state(self, code: str, period: str, discipline: str | None, value: dict[str, Any]) -> None:
        await self.put_meta("statutory", self.state_key(code, period, discipline), _json_safe(value))

    async def _submission(self, sid: str | None) -> ComplianceSubmission | None:
        if not sid:
            return None
        return (
            await self.db.execute(select(ComplianceSubmission).where(ComplianceSubmission.id == uuid.UUID(sid)))
        ).scalar_one_or_none()

    async def out(self, code: str, st: dict[str, Any], *, full: bool = True) -> StatutoryOut:
        d = self.defn(code)
        status = st.get("status") or "generated"
        sub = await self._submission(st.get("compliance_submission_id"))
        if sub is not None and sub.status in SUBMITTED:
            status = "submitted"
        names = await self.user_display([uuid.UUID(s["user"]) for s in st.get("signoffs") or [] if s.get("user")])
        return StatutoryOut(
            code=code,
            name=d["name"],
            period_label=st.get("period_label") or "",
            discipline=st.get("discipline"),
            college_id=uuid.UUID(st["college_id"]) if st.get("college_id") else None,
            version=int(st.get("version") or 1),
            status=status,
            payload_summary=dict(st.get("summary") or {}),
            sections=dict(st.get("sections") or {}) if full else {},
            validation=list(st.get("validation") or []),
            validation_status=st.get("validation_status") or "pass",
            files=list(st.get("files") or []),
            compliance_submission_id=uuid.UUID(st["compliance_submission_id"])
            if st.get("compliance_submission_id")
            else None,
            signoffs=[
                {**s, "user_name": names.get(uuid.UUID(s["user"])) if s.get("user") else None}
                for s in st.get("signoffs") or []
            ],
            signoff_roles=await self.signoff_roles(code),
            job_id=uuid.UUID(st["job_id"]) if st.get("job_id") else None,
            generated_at=self.utc(st.get("generated_at")),
            reopened=list(st.get("reopened") or []),
            history=list(st.get("history") or [])[-30:],
        )

    # ---- list / due calendar -------------------------------------------------------------------------------------------------
    def due_on(self, code: str, period: Period) -> date:
        m, dd = self.defn(code)["due"]
        y = period.end.year if (m, dd) > (period.end.month, period.end.day) else period.end.year + 1
        return date(y, m, dd)

    def current_period(self, code: str, today: date) -> Period:
        pt = self.defn(code)["period_type"]
        if pt == "calendar_year":
            return parse_period(str(today.year - 1), pt)
        start = today.year if today.month >= (4 if pt == "financial_year" else 7) else today.year - 1
        return parse_period(str(start - 1), pt)

    async def codes(self) -> list[StatutoryListItem]:
        await self.require_reader()
        states = await self.metas("statutory")
        today = await self.today()
        out = []
        for code, d in STATUTORY_DEFS.items():
            mine = sorted(
                (v for k, v in states.items() if k.split(":")[0] == code), key=lambda v: str(v.get("period_label"))
            )
            last = mine[-1] if mine else None
            per = self.current_period(code, today)
            out.append(
                StatutoryListItem(
                    code=code,
                    name=d["name"],
                    period_type=d["period_type"],
                    last_period=last.get("period_label") if last else None,
                    status=(await self.out(code, last, full=False)).status if last else None,
                    signoff_roles=await self.signoff_roles(code),
                    formats=list(d["formats"]),
                    due_on=self.due_on(code, per),
                    submission_type=d.get("submission_type"),
                    disciplines=list(d.get("disciplines") or []),
                )
            )
        return out

    async def get(self, code: str, period: str, discipline: str | None = None) -> StatutoryOut:
        await self.require_reader()
        label = self._label(code, period)
        st = await self.state(code, label, discipline)
        if not st:
            raise not_found(f"{code} {label}")
        return await self.out(code, st)

    def _label(self, code: str, period: str) -> str:
        try:
            return parse_period(period, self.defn(code)["period_type"]).label
        except ValueError as exc:
            raise rule(str(exc), "INVALID_PERIOD", 422) from exc

    # ---- generate ------------------------------------------------------------------------------------------------------------
    async def request_generate(self, code: str, body: StatutoryGenerateRequest) -> ReportRunOut:
        await self.require_generator(code)
        d = self.defn(code)
        label = self._label(code, body.period_label)
        if body.discipline and d.get("disciplines") and body.discipline not in d["disciplines"]:
            raise rule(f"discipline must be one of {d['disciplines']}", "INVALID_DISCIPLINE", 422)
        st = await self.state(code, label, body.discipline)
        sub = await self._submission(st.get("compliance_submission_id"))
        if sub is not None and sub.status in SUBMITTED:
            raise rule("The period was submitted — create a correction in Phase 32", "IMMUTABLE")
        job = await enqueue(
            self.db,
            self.principal,
            "report.statutory_generate",
            {
                "key": f"statutory.{code}",
                "code": code,
                "period_label": label,
                "discipline": body.discipline,
                "college_id": str(body.college_id) if body.college_id else None,
                "params": body.params,
                "format": "+".join(d["formats"]),
            },
            task_name="jobs.report.statutory_generate",
        )
        return ReportRunOut(job_id=job.id, key=f"statutory.{code}", status="queued", params={"period_label": label})

    async def build(
        self, code: str, period: Period, college_id: uuid.UUID | None, discipline: str | None
    ) -> list[dict[str, Any]]:
        sections: list[dict[str, Any]] = []
        for key in self.defn(code)["sections"]:
            sections += await SECTIONS[key](self, period, college_id, discipline)
        return sections

    async def validate(self, sections: list[dict[str, Any]], period: Period) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for s in sections:
            rows = list(s.get("rows") or [])
            if s.get("mandatory_rows") and not rows:
                out.append({"section": s["key"], "check": "rows present", "status": "fail", "detail": "no rows"})
            for f in s.get("mandatory") or []:
                missing = [str(r.get("code") or i) for i, r in enumerate(rows) if r.get(f) in (None, "")]
                out.append(
                    {
                        "section": s["key"],
                        "check": f"{f} present",
                        "status": "fail" if missing else "pass",
                        "detail": ("missing for " + ", ".join(missing[:10])) if missing else None,
                    }
                )
            if s.get("metric_check"):
                total = float((s.get("totals") or {}).get("total") or 0)
                mv = (
                    await self.db.execute(
                        text(
                            "SELECT value FROM metric_values WHERE institution_id = :i AND metric_key = :k AND period_label = :p "
                            "AND college_id IS NULL AND program_id IS NULL"
                        ),
                        {"i": self.inst, "k": s["metric_check"], "p": period.label},
                    )
                ).scalar_one_or_none()
                if mv is None:
                    out.append(
                        {
                            "section": s["key"],
                            "check": f"total = {s['metric_check']}",
                            "status": "warn",
                            "detail": "metric not computed for the period",
                        }
                    )
                else:
                    ok_ = abs(float(mv) - total) < 0.5
                    out.append(
                        {
                            "section": s["key"],
                            "check": f"total = {s['metric_check']}",
                            "status": "pass" if ok_ else "fail",
                            "detail": None if ok_ else f"section {total:g} vs metric {float(mv):g}",
                        }
                    )
            if s.get("note"):
                out.append({"section": s["key"], "check": "source available", "status": "warn", "detail": s["note"]})
        cons = (
            await self.db.execute(
                text(
                    "SELECT value FROM institution_settings WHERE institution_id = :i AND category = 'accreditation_meta' "
                    "AND key = :k AND college_id IS NULL"
                ),
                {"i": self.inst, "k": f"consistency:{period.label}"},
            )
        ).scalar_one_or_none()
        if isinstance(cons, dict):
            failed = [c.get("name") for c in cons.get("checks") or [] if c.get("status") == "fail"]
            out.append(
                {
                    "section": "consistency",
                    "check": "Phase 32 consistency",
                    "status": "warn" if failed else "pass",
                    "detail": ", ".join(str(f) for f in failed) or None,
                }
            )
        return out

    async def generate_now(
        self,
        job_id: uuid.UUID | None,
        code: str,
        period_label: str,
        discipline: str | None = None,
        college_id: str | None = None,
        job: Any = None,
    ) -> dict[str, Any]:
        """Body of ``report.statutory_generate``."""
        await self.require_generator(code)
        d = self.defn(code)
        period = parse_period(period_label, d["period_type"])
        cid = uuid.UUID(college_id) if college_id else None
        st = await self.state(code, period.label, discipline)
        sub = await self._submission(st.get("compliance_submission_id"))
        if sub is not None and sub.status in SUBMITTED:
            raise rule("The period was submitted — create a correction in Phase 32", "IMMUTABLE")
        version = int(st.get("version") or 0)
        if st and (st.get("status") == "signed_off" or st.get("files")):
            await self._revoke(st, f"Superseded by version {version + 1}")
        version += 1
        sections = await self.build(code, period, cid, discipline)
        if job is not None:
            await job.progress(self.db, 40, f"{len(sections)} sections built")
        validation = await self.validate(sections, period)
        vstatus = (
            "fail"
            if any(v["status"] == "fail" for v in validation)
            else ("warn" if any(v["status"] == "warn" for v in validation) else "pass")
        )
        title = f"{d['name']} — {period.label}" + (f" ({discipline})" if discipline else "")
        header = await self.header(title, None, {})
        header["scope"] = f"Version {version}"
        files: list[dict[str, Any]] = []
        rendered: dict[str, bytes] = {}
        for fmt in d["formats"]:
            content, ext = self._render(fmt, title, sections, header, st.get("signoffs") or [])
            stem = f"{code}-{period.label}" + (f"-{discipline}" if discipline else "") + f"-v{version}"
            storage_key, url = await self.upload(f"statutory/{code}", f"{stem}.{ext}", content, R.CONTENT_TYPES[ext])
            checksum = R.sha256(content)
            doc_id = await self._register(code, period.label, discipline, version, fmt, url, checksum, job_id)
            files.append(
                {
                    "format": fmt,
                    "url": url,
                    "checksum": checksum,
                    "issued_document_id": str(doc_id),
                    "storage_key": storage_key,
                }
            )
            rendered[f"{stem}.{ext}"] = content
        if job is not None:
            await job.progress(self.db, 85, f"{len(files)} files registered")
        summary = {
            s["key"]: {"title": s["title"], "rows": len(s.get("rows") or []), "totals": s.get("totals") or {}}
            for s in sections
        }
        submission_id = await self._link_submission(
            code, period.label, summary, files, job_id, st.get("compliance_submission_id")
        )
        now = now_utc().isoformat()
        history = list(st.get("history") or []) + [
            {"at": now, "by": str(self.actor_id), "action": "generated", "version": version}
        ]
        new = {
            "code": code,
            "period_label": period.label,
            "discipline": discipline,
            "college_id": college_id,
            "version": version,
            "status": "generated",
            "summary": summary,
            "sections": {
                s["key"]: {
                    "title": s["title"],
                    "columns": [c.as_dict() for c in _cols(s)],
                    "rows": s.get("rows") or [],
                    "totals": s.get("totals") or {},
                }
                for s in sections
            },
            "validation": validation,
            "validation_status": vstatus,
            "files": files,
            "compliance_submission_id": submission_id,
            "signoffs": [],
            "job_id": str(job_id) if job_id else None,
            "generated_at": now,
            "reopened": list(st.get("reopened") or []),
            "history": history[-50:],
        }
        await self.put_state(code, period.label, discipline, new)
        await self._audit(
            "statutory_generated",
            "statutory_report",
            job_id,
            None,
            {"code": code, "period": period.label, "version": version},
        )
        await self._emit(
            "reports.statutory_generated",
            {"code": code, "period_label": period.label, "version": version, "compliance_submission_id": submission_id},
            "statutory_report",
            job_id,
        )
        xlsx = next((f for f in files if f["format"] == "xlsx"), files[0] if files else None)
        return {
            "result_url": xlsx["url"] if xlsx else None,
            "rows": sum(len(s.get("rows") or []) for s in sections),
            "checksum": xlsx["checksum"] if xlsx else None,
            "code": code,
            "period_label": period.label,
            "version": version,
            "validation": vstatus,
            "files": [{k: v for k, v in f.items() if k != "storage_key"} for f in files],
        }

    def _render(
        self,
        fmt: str,
        title: str,
        sections: list[dict[str, Any]],
        header: dict[str, Any],
        signoffs: list[dict[str, Any]],
    ) -> tuple[bytes, str]:
        blocks = [
            {"title": s["title"], "columns": _cols(s), "rows": s.get("rows") or [], "totals": s.get("totals") or {}}
            for s in sections
        ]
        if fmt == "xlsx":
            return R.render_xlsx(blocks, header), "xlsx"
        if fmt == "csv":
            rows: list[dict[str, Any]] = []
            for s in sections:
                for r in s.get("rows") or []:
                    rows.append({"section": s["key"], **r})
            keys: list[str] = ["section"]
            for r in rows:
                keys += [k for k in r if k not in keys]
            return R.render_csv([ReportColumn(k) for k in keys], rows), "csv"
        if fmt == "docx":
            return R.render_docx(title, blocks, [header.get("institution") or "", header.get("scope") or ""]), "docx"
        return (
            R.render_pdf(title, [], [], layout="landscape", header=header, sections=blocks, signoff=signoffs),
            "pdf",
        )

    async def _register(
        self,
        code: str,
        period: str,
        discipline: str | None,
        version: int,
        fmt: str,
        url: str,
        checksum: str,
        job_id: uuid.UUID | None,
    ) -> uuid.UUID:
        number = f"ST-{code[:10].upper()}-{period}-{(discipline or '')[:4].upper()}V{version}-{fmt.upper()}"[:40]
        doc = IssuedDocument(
            institution_id=self.inst,
            template_type="statutory_report",
            entity_type="compliance_submission",
            document_number=number,
            serial_no=f"V{version}",
            pdf_url=url,
            verification_token=secrets.token_hex(24),
            content_hash=checksum,
            watermark_text=None,
            issued_by=self.actor_id,
            job_id=job_id,
        )
        self.db.add(doc)
        await self.db.flush()
        return doc.id

    async def _revoke(self, st: dict[str, Any], reason: str) -> None:
        ids = [uuid.UUID(f["issued_document_id"]) for f in st.get("files") or [] if f.get("issued_document_id")]
        if ids:
            await self.db.execute(
                update(IssuedDocument)
                .where(IssuedDocument.id.in_(ids), IssuedDocument.revoked_at.is_(None))
                .values(revoked_at=now_utc(), revoke_reason=reason)
            )
        for f in st.get("files") or []:
            f["revoked"] = True

    async def _link_submission(
        self,
        code: str,
        period: str,
        summary: dict[str, Any],
        files: list[dict[str, Any]],
        job_id: uuid.UUID | None,
        existing: str | None,
    ) -> str | None:
        """Create / update the Phase 32 ``compliance_submissions`` row (only for codes the pack maps to a type)."""
        stype = self.defn(code).get("submission_type")
        if not stype:
            return None
        s = await self._submission(existing)
        if s is None:
            s = (
                await self.db.execute(
                    select(ComplianceSubmission)
                    .where(
                        ComplianceSubmission.institution_id == self.inst,
                        ComplianceSubmission.submission_type == stype,
                        ComplianceSubmission.period_label == period,
                        ComplianceSubmission.status.in_(("draft", "generated")),
                    )
                    .order_by(ComplianceSubmission.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        if s is None:
            from app.enums.accreditation import SUBMISSION_FRAMEWORK

            fw = (
                await self.db.execute(
                    text("SELECT id FROM accreditation_frameworks WHERE code = :c"),
                    {"c": SUBMISSION_FRAMEWORK.get(stype, ("",))[0]},
                )
            ).scalar_one_or_none()
            s = ComplianceSubmission(
                institution_id=self.inst, framework_id=fw, period_label=period, submission_type=stype
            )
            self.db.add(s)
            await self.db.flush()
        payload = dict(s.payload or {})
        payload["statutory"] = {
            "code": code,
            "summary": summary,
            "files": [{k: v for k, v in f.items() if k != "storage_key"} for f in files],
        }
        s.payload = _json_safe(payload)
        xlsx = next((f for f in files if f["format"] == "xlsx"), files[0] if files else None)
        s.file_url = xlsx["url"] if xlsx else s.file_url
        s.status, s.job_id = "generated", job_id
        await self.db.flush()
        return str(s.id)

    # ---- review / sign-off --------------------------------------------------------------------------------------------------
    async def review(
        self, code: str, period: str, body: StatutoryReviewAction, discipline: str | None = None
    ) -> StatutoryOut:
        await self.require_reader()
        self.require_writer()
        label = self._label(code, period)
        st = await self.state(code, label, discipline)
        if not st:
            raise not_found(f"{code} {label}")
        current = (await self.out(code, st, full=False)).status
        roles = await self.signoff_roles(code)
        now = now_utc().isoformat()
        hist = list(st.get("history") or [])
        if body.action == "request_review":
            await self.require_generator(code)
            if current not in ("generated", "in_review"):
                raise rule(f"Cannot request review while {current}", "INVALID_STATE")
            st["status"] = "in_review"
            users: list[uuid.UUID] = []
            for r in roles:
                users += [u for u in await self.role_holders(r) if u not in users]
            await self._notify(
                "reports.statutory_review_requested",
                users,
                {"code": code, "name": self.defn(code)["name"], "period": label, "roles": ", ".join(roles)},
            )
            await self._emit(
                "reports.statutory_review_requested", {"code": code, "period_label": label}, "statutory_report", None
            )
        elif body.action == "sign_off":
            if current != "in_review":
                raise rule(f"Sign-off needs status in_review (is {current})", "INVALID_STATE")
            signed = {s["role"] for s in st.get("signoffs") or []}
            mine = [r for r in roles if self.holds_role(r) and r not in signed]
            if body.role:
                mine = [r for r in mine if r == body.role]
            if not mine:
                raise forbidden(
                    f"You hold none of the outstanding sign-off roles ({', '.join(r for r in roles if r not in signed)})"
                )
            st.setdefault("signoffs", []).append(
                {"role": mine[0], "user": str(self.actor_id), "at": now, "remarks": body.remarks}
            )
            if {s["role"] for s in st["signoffs"]} >= set(roles):
                st["status"] = "signed_off"
                await self._notify(
                    "reports.statutory_signed_off",
                    [
                        uuid.UUID(h["by"])
                        for h in hist
                        if h.get("action") == "generated" and h.get("by") not in (None, "None")
                    ][-1:],
                    {"code": code, "name": self.defn(code)["name"], "period": label},
                )
                await self._emit(
                    "reports.statutory_signed_off", {"code": code, "period_label": label}, "statutory_report", None
                )
        else:
            if current == "submitted":
                raise rule("Submitted periods cannot be reopened", "IMMUTABLE")
            if not body.remarks:
                raise rule("A reason is required to reopen", "REASON_REQUIRED", 422)
            await self.require_generator(code)
            st["status"], st["signoffs"] = "generated", []
            st.setdefault("reopened", []).append({"at": now, "by": str(self.actor_id), "reason": body.remarks})
            await self._emit(
                "reports.statutory_reopened", {"code": code, "period_label": label}, "statutory_report", None
            )
        hist.append(
            {"at": now, "by": str(self.actor_id), "action": body.action, "role": body.role, "remarks": body.remarks}
        )
        st["history"] = hist[-50:]
        await self.put_state(code, label, discipline, st)
        await self._audit(f"statutory_{body.action}", "statutory_report", None, None, {"code": code, "period": label})
        return await self.out(code, st)

    # ---- diff / pack ----------------------------------------------------------------------------------------------------------
    async def diff(self, code: str, period: str, vs: str | None, discipline: str | None = None) -> StatutoryDiffOut:
        await self.require_reader()
        label = self._label(code, period)
        cur = await self.state(code, label, discipline)
        if not cur:
            raise not_found(f"{code} {label}")
        if vs:
            vs_label = self._label(code, vs)
        else:
            p = parse_period(label, self.defn(code)["period_type"])
            vs_label = parse_period(str(p.year - 1), self.defn(code)["period_type"]).label
        prev = await self.state(code, vs_label, discipline)
        rows = []
        for key in sorted(set(cur.get("summary") or {}) | set(prev.get("summary") or {})):
            a = (prev.get("summary") or {}).get(key) or {}
            b = (cur.get("summary") or {}).get(key) or {}
            deltas = {}
            for k in sorted(set(a.get("totals") or {}) | set(b.get("totals") or {})):
                x, y = (a.get("totals") or {}).get(k), (b.get("totals") or {}).get(k)
                deltas[k] = {
                    "previous": x,
                    "current": y,
                    "delta": (y or 0) - (x or 0) if x is not None or y is not None else None,
                }
            rows.append(
                {
                    "section": key,
                    "title": b.get("title") or a.get("title"),
                    "rows_previous": a.get("rows"),
                    "rows_current": b.get("rows"),
                    "totals": deltas,
                }
            )
        return StatutoryDiffOut(code=code, period_label=label, vs=vs_label if prev else None, sections=rows)

    async def request_pack(self, code: str, period: str, discipline: str | None = None) -> ReportRunOut:
        await self.require_reader()
        label = self._label(code, period)
        if not await self.state(code, label, discipline):
            raise not_found(f"{code} {label}")
        job = await enqueue(
            self.db,
            self.principal,
            "report.statutory_pack",
            {
                "key": f"statutory.{code}",
                "code": code,
                "period_label": label,
                "discipline": discipline,
                "format": "zip",
            },
            task_name="jobs.report.statutory_pack",
        )
        return ReportRunOut(job_id=job.id, key=f"statutory.{code}", status="queued", format="zip")

    async def pack_now(
        self, job_id: uuid.UUID, code: str, period_label: str, discipline: str | None = None
    ) -> dict[str, Any]:
        from app.core.files import get_storage

        await self.require_reader()
        st = await self.state(code, period_label, discipline)
        storage = get_storage()
        files: dict[str, bytes] = {}
        for f in st.get("files") or []:
            if f.get("storage_key") and not f.get("revoked"):
                try:
                    files[str(f["storage_key"]).rsplit("/", 1)[-1]] = await storage.get(str(f["storage_key"]))
                except Exception:  # noqa: BLE001 - a purged file is listed in the validation report instead
                    files[f"MISSING-{f['format']}.txt"] = b"file no longer available"
        report = [ReportColumn("section"), ReportColumn("check"), ReportColumn("status"), ReportColumn("detail")]
        files["validation-report.csv"] = R.render_csv(report, list(st.get("validation") or []))
        files["manifest.json"] = json.dumps(
            {k: st.get(k) for k in ("code", "period_label", "discipline", "version", "status", "summary", "signoffs")},
            default=str,
            indent=2,
        ).encode()
        content = R.zip_bytes(files)
        storage_key, url = await self.upload(
            f"statutory/{code}", f"{code}-{period_label}-pack.zip", content, R.CONTENT_TYPES["zip"]
        )
        await self._audit("statutory_pack", "statutory_report", job_id, None, {"code": code, "period": period_label})
        return {
            "result_url": url,
            "storage_key": storage_key,
            "rows": len(files),
            "checksum": R.sha256(content),
            "key": f"statutory.{code}",
        }

    async def due_reminders(self) -> int:
        """Weekly: codes whose current period is due within 30 days and not signed off → remind the sign-off roles."""
        today = await self.today()
        sent = 0
        for code in STATUTORY_DEFS:
            per = self.current_period(code, today)
            due = self.due_on(code, per)
            if not (0 <= (due - today).days <= 30):
                continue
            st = await self.state(code, per.label)
            if st and st.get("status") == "signed_off":
                continue
            users: list[uuid.UUID] = []
            for r in await self.signoff_roles(code):
                users += [u for u in await self.role_holders(r) if u not in users]
            await self._notify(
                "reports.statutory_due",
                users,
                {"code": code, "name": STATUTORY_DEFS[code]["name"], "period": per.label, "due_on": due.isoformat()},
            )
            sent += 1
        return sent
