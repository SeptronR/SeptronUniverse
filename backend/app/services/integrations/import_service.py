"""Data migration toolkit — Prompts/41 §41.6 ``import_service`` (``data.migration_toolkit``) and ``export_service``.

Business rules
1. Templates from :mod:`import_hooks` (columns, types, required, lookups, unique keys, example) with a sample xlsx.
   Upload: the file (stored key / file-service URL, csv or xlsx, ≤ ``imports.max_rows`` = 200 000 → 413) is parsed
   into ``data_import_rows(status='pending')``; headers are auto-mapped by label / key similarity, or by a saved
   profile (``integrations_meta imports.profiles``).
2. Permissions: ``integrations:import`` imports every entity; otherwise the entity's ``<module>:bulk_import``;
   college-scoped callers have ``college_id`` forced (a different college → 422).
3. ``validate`` (job ``imports.validate``): normalise + hook validation per row → ``valid`` / ``invalid`` with
   errors; report ``{summary, by_error}``; ``status='validated'``.
4. ``apply`` (job ``imports.apply``): needs ``confirm_valid_rows`` equal to the current valid count (409 otherwise);
   chunks of ``imports.chunk_size`` (500) each in a SAVEPOINT; a row failing inside a chunk becomes ``invalid`` with
   the error, the rest keep going; ``created_entity_id`` stored; ``status='applied'``; ``imports.applied`` emitted.
5. ``rollback`` (job): within 30 days; per row the hook undoes it or reports why not (row ``skipped``);
   ``status='rolled_back'``. Unapplied imports older than 7 days expire (Beat).
6. Workbook: the cut-over steps (``WORKBOOK_STEPS``) in ``integrations_meta imports.workbook``; attaching an import to
   a step whose dependencies are not done → 409; progress = done steps / all.
7. User export (DSR / portability): rows about a user across modules (profile, roles, own student / staff record,
   notifications, consents, audit trail of own actions) → JSON in the file store; third-party PII masked.
"""

from __future__ import annotations

import builtins
import csv
import difflib
import io
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.audit import log_audit
from app.core.errors import APIError, ErrorCode
from app.models.platform import DataImport, DataImportRow
from app.schemas.integrations import (
    ImportColumn,
    ImportCreate,
    ImportOut,
    ImportRowOut,
    ImportTemplateOut,
    WorkbookOut,
    WorkbookStepOut,
)
from app.services.integrations.import_hooks import HOOKS, WORKBOOK_STEPS

META = "integrations_meta"
MAX_ROWS = 200_000
CHUNK = 500
ROLLBACK_DAYS = 30


async def read_rows(file_url: str) -> builtins.list[dict[str, Any]]:
    from app.core.files import storage

    key = file_url.split("?")[0].split("/files/")[-1]
    data = await storage.get(key)
    if key.lower().endswith((".xlsx", ".xlsm")):
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        it = ws.iter_rows(values_only=True)  # type: ignore[union-attr]
        header = [str(h or "").strip() for h in next(it, [])]
        return [
            {header[i]: v for i, v in enumerate(r) if i < len(header) and header[i]}
            for r in it
            if any(c not in (None, "") for c in r)
        ]
    return [dict(r) for r in csv.DictReader(io.StringIO(data.decode("utf-8-sig", errors="ignore")))]


def auto_map(headers: builtins.list[str], entity: str) -> dict[str, str]:
    cols = HOOKS[entity].columns
    out: dict[str, str] = {}
    for h in headers:
        norm = h.strip().lower().replace(" ", "_")
        names = {c["key"]: c["key"] for c in cols} | {c["label"].lower().replace(" ", "_"): c["key"] for c in cols}
        hit = names.get(norm) or (difflib.get_close_matches(norm, list(names), n=1, cutoff=0.75) or [None])[0]
        if hit:
            out[h] = names[hit]
    return out


class ImportService:
    def __init__(self, db: AsyncSession, principal: Any, request: Request | None = None):
        self.db, self.principal, self.request = db, principal, request
        self.inst: uuid.UUID = principal.institution_id

    # ---- rule 1 / 2 -----------------------------------------------------------------------------------------------
    def _may(self, entity: str) -> None:
        hook = HOOKS.get(entity)
        if hook is None:
            raise APIError(422, ErrorCode.VALIDATION, f"Unknown entity {entity!r}", {"field": "entity"})
        if not (self.principal.has("integrations", "import") or self.principal.has(hook.module, "bulk_import")):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, f"You may not import {hook.label.lower()}")

    def templates(self) -> builtins.list[ImportTemplateOut]:
        return [
            ImportTemplateOut(
                entity=h.entity,
                label=h.label,
                module=h.module,
                permission=h.permission,
                columns=[ImportColumn(**c) for c in h.columns],
                notes=h.notes,
            )
            for h in HOOKS.values()
            if self.principal.has("integrations", "import") or self.principal.has(h.module, "bulk_import")
        ]

    def sample_xlsx(self, entity: str) -> bytes:
        self._may(entity)
        from app.services.reports.render_service import xlsx_sheets

        cols = HOOKS[entity].columns
        return xlsx_sheets({entity: [{c["label"]: c.get("example") or "" for c in cols}]})

    async def _profiles(self) -> dict[str, Any]:
        r = (
            await self.db.execute(
                text(
                    "SELECT value FROM institution_settings WHERE institution_id = :i AND category = :c AND key = 'imports.profiles' AND college_id IS NULL"
                ),
                {"i": self.inst, "c": META},
            )
        ).first()
        return dict(r[0]) if r and isinstance(r[0], dict) else {}

    async def _put(self, key: str, value: Any) -> None:
        await self.db.execute(
            text(
                "INSERT INTO institution_settings (id, institution_id, college_id, category, key, value, value_type, is_public, created_at, updated_at) "
                "VALUES (:id, :i, NULL, :c, :k, CAST(:v AS jsonb), 'json', FALSE, NOW(), NOW()) "
                "ON CONFLICT (institution_id, college_id, category, key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()"
            ),
            {"id": uuid.uuid4(), "i": self.inst, "c": META, "k": key, "v": json.dumps(value, default=str)},
        )

    async def profiles(self) -> dict[str, Any]:
        return await self._profiles()

    async def save_profile(self, name: str, entity: str, mapping: dict[str, str]) -> dict[str, Any]:
        self._may(entity)
        p = await self._profiles()
        p[name] = {"entity": entity, "mapping": mapping}
        await self._put("imports.profiles", p)
        return p

    async def delete_profile(self, name: str) -> None:
        p = await self._profiles()
        p.pop(name, None)
        await self._put("imports.profiles", p)

    async def _college_forced(self, college_id: uuid.UUID | None) -> uuid.UUID | None:
        mine = [sid for st, sid in self.principal.scopes if st == "college" and sid]
        if self.principal.has("integrations", "import") and not mine:
            return college_id
        if mine and college_id and college_id not in mine:
            raise APIError(
                422, ErrorCode.VALIDATION, "You may import only into your own college", {"field": "college_id"}
            )
        return college_id or (mine[0] if mine else None)

    async def create(self, body: ImportCreate) -> ImportOut:
        self._may(body.entity)
        college = await self._college_forced(body.college_id)
        rows = await read_rows(body.file_url)
        if len(rows) > MAX_ROWS:
            raise APIError(413, ErrorCode.VALIDATION, f"At most {MAX_ROWS} rows per import")
        mapping = body.mapping
        if not mapping and body.profile_name:
            mapping = ((await self._profiles()).get(body.profile_name) or {}).get("mapping")
        mapping = mapping or auto_map(list(rows[0].keys()) if rows else [], body.entity)
        imp = DataImport(
            institution_id=self.inst,
            entity=body.entity,
            file_url=body.file_url,
            mapping={"columns": mapping, "options": body.options, "college_id": str(college) if college else None},
            mode="dry_run",
            status="uploaded",
            total_rows=len(rows),
            requested_by=self.principal.id,
        )
        self.db.add(imp)
        await self.db.flush()
        for n, r in enumerate(rows, 1):
            self.db.add(
                DataImportRow(
                    institution_id=self.inst,
                    import_id=imp.id,
                    row_no=n,
                    raw={
                        k: (v if isinstance(v, (str, int, float, bool)) or v is None else str(v)) for k, v in r.items()
                    },
                    status="pending",
                )
            )
        await self.db.flush()
        if body.profile_name and body.mapping:
            await self.save_profile(body.profile_name, body.entity, body.mapping)
        await log_audit(
            self.db,
            principal=self.principal,
            module="integrations",
            action="import_upload",
            record_type="data_import",
            record_id=imp.id,
            new={"entity": body.entity, "rows": len(rows)},
            request=self.request,
        )
        await self._emit("imports.uploaded", imp)
        return self._out(imp)

    def _out(self, imp: DataImport) -> ImportOut:
        can = (
            imp.status == "applied"
            and imp.applied_at is not None
            and imp.applied_at > datetime.now(UTC) - timedelta(days=ROLLBACK_DAYS)
        )
        return ImportOut(
            id=imp.id,
            entity=imp.entity,
            status=imp.status,
            mode=imp.mode,
            file_url=imp.file_url,
            total_rows=imp.total_rows,
            valid_rows=imp.valid_rows,
            error_rows=imp.error_rows,
            report=imp.report,
            mapping=imp.mapping,
            job_id=imp.job_id,
            applied_at=imp.applied_at,
            rolled_back_at=imp.rolled_back_at,
            created_at=imp.created_at,
            can_rollback=can,
        )

    async def _get(self, iid: uuid.UUID) -> DataImport:
        imp = await self.db.get(DataImport, iid)
        if imp is None or imp.institution_id != self.inst:
            raise APIError(404, ErrorCode.NOT_FOUND, "Import not found")
        self._may(imp.entity)
        return imp

    async def list(self, mine: bool) -> builtins.list[ImportOut]:
        q = select(DataImport).where(DataImport.institution_id == self.inst)
        if mine or not self.principal.has("integrations", "import"):
            q = q.where(DataImport.requested_by == self.principal.id)
        return [
            self._out(i) for i in (await self.db.execute(q.order_by(DataImport.created_at.desc()).limit(200))).scalars()
        ]

    async def get(self, iid: uuid.UUID) -> ImportOut:
        return self._out(await self._get(iid))

    async def set_mapping(self, iid: uuid.UUID, mapping: dict[str, str], profile: str | None) -> ImportOut:
        imp = await self._get(iid)
        if imp.status not in ("uploaded", "validated"):
            raise APIError(409, ErrorCode.RULE_VIOLATION, f"Import is {imp.status}")
        imp.mapping = {**(imp.mapping or {}), "columns": mapping}
        imp.status = "uploaded"
        if profile:
            await self.save_profile(profile, imp.entity, mapping)
        await self.db.flush()
        return self._out(imp)

    async def rows(
        self, iid: uuid.UUID, status: str | None, error_code: str | None, page: int
    ) -> builtins.list[ImportRowOut]:
        await self._get(iid)
        q = select(DataImportRow).where(DataImportRow.import_id == iid)
        if status:
            q = q.where(DataImportRow.status == status)
        rows = (await self.db.execute(q.order_by(DataImportRow.row_no).offset((page - 1) * 100).limit(100))).scalars()
        out = [
            ImportRowOut(
                row_no=r.row_no,
                raw=r.raw,
                normalized=r.normalized,
                errors=r.errors,
                status=r.status,
                created_entity_id=r.created_entity_id,
            )
            for r in rows
        ]
        if error_code:
            out = [r for r in out if any(e.get("code") == error_code for e in r.errors or [])]
        if self.principal.has("audit_logs", "verify_chain") and not self.principal.has("integrations", "import"):
            out = [r.model_copy(update={"raw": dict.fromkeys(r.raw, "•••"), "normalized": None}) for r in out]
        return out

    async def enqueue(self, iid: uuid.UUID, kind: str, params: dict[str, Any] | None = None) -> ImportOut:
        imp = await self._get(iid)
        from app.core.jobs import enqueue

        job = await enqueue(
            self.db, self.principal, f"imports.{kind}", {"import_id": str(iid), **(params or {})}, queue="reports"
        )
        imp.job_id = job.id
        await self.db.flush()
        return self._out(imp)

    # ---- rule 3 -----------------------------------------------------------------------------------------------------
    def _ctx(self, imp: DataImport) -> dict[str, Any]:
        return {
            "db": self.db,
            "inst": self.inst,
            "principal": self.principal,
            "request": self.request,
            "options": (imp.mapping or {}).get("options") or {},
            "college_id": (imp.mapping or {}).get("college_id"),
        }

    async def validate(self, iid: uuid.UUID) -> ImportOut:
        imp = await self._get(iid)
        hook = HOOKS[imp.entity]
        mapping = (imp.mapping or {}).get("columns") or {}
        ctx = self._ctx(imp)
        by_error: dict[str, int] = {}
        valid = invalid = 0
        for r in (
            await self.db.execute(
                select(DataImportRow).where(DataImportRow.import_id == iid).order_by(DataImportRow.row_no)
            )
        ).scalars():
            mapped = {mapping.get(k, k): v for k, v in (r.raw or {}).items()}
            if ctx.get("college_id"):
                mapped["college_id"] = ctx["college_id"]
            normalized, errors = await hook.validate(mapped, ctx)
            r.normalized = json.loads(json.dumps(normalized, default=str))
            r.errors = errors or None
            r.status = "invalid" if errors else "valid"
            valid += 0 if errors else 1
            invalid += 1 if errors else 0
            for e in errors:
                by_error[e["code"]] = by_error.get(e["code"], 0) + 1
        imp.valid_rows, imp.error_rows, imp.status = valid, invalid, "validated"
        imp.report = {
            "summary": {"total": imp.total_rows, "valid": valid, "invalid": invalid},
            "by_error": [{"code": k, "count": v} for k, v in sorted(by_error.items(), key=lambda x: -x[1])],
        }
        await self.db.flush()
        await self._emit("imports.validated", imp)
        return self._out(imp)

    # ---- rule 4 -----------------------------------------------------------------------------------------------------
    async def check_apply(self, iid: uuid.UUID, confirm: int) -> None:
        imp = await self._get(iid)
        if imp.status != "validated":
            raise APIError(409, ErrorCode.RULE_VIOLATION, "Validate the import first")
        if confirm != (imp.valid_rows or 0):
            raise APIError(
                409, ErrorCode.RULE_VIOLATION, f"Confirm {imp.valid_rows} valid rows", {"valid_rows": imp.valid_rows}
            )

    async def apply(self, iid: uuid.UUID, on_conflict: str = "skip") -> ImportOut:
        imp = await self._get(iid)
        hook = HOOKS[imp.entity]
        ctx = self._ctx(imp)
        ctx["on_conflict"] = on_conflict
        imp.status, imp.mode = "applying", "apply"
        await self.db.flush()
        rows = list(
            (
                await self.db.execute(
                    select(DataImportRow)
                    .where(DataImportRow.import_id == iid, DataImportRow.status == "valid")
                    .order_by(DataImportRow.row_no)
                )
            ).scalars()
        )
        applied = failed = 0
        for start in range(0, len(rows), CHUNK):
            for r in rows[start : start + CHUNK]:
                try:
                    async with self.db.begin_nested():
                        r.created_entity_id = await hook.apply(dict(r.normalized or {}), ctx)
                    r.status = "applied"
                    applied += 1
                except Exception as exc:  # noqa: BLE001 - a row's failure is recorded on the row
                    r.status = "invalid"
                    r.errors = [
                        *(r.errors or []),
                        {"column": "*", "code": "APPLY_FAILED", "message": str(getattr(exc, "message", exc))[:300]},
                    ]
                    failed += 1
            await self.db.flush()
        imp.status, imp.applied_at = "applied", datetime.now(UTC)
        imp.report = {**(imp.report or {}), "applied": applied, "apply_failed": failed}
        await self.db.flush()
        await log_audit(
            self.db,
            principal=self.principal,
            module="integrations",
            action="import_apply",
            record_type="data_import",
            record_id=imp.id,
            new={"applied": applied, "failed": failed},
            request=self.request,
        )
        await self._emit("imports.applied", imp, {"applied": applied, "failed": failed})
        from app.core.notifications.notify import notify_event

        await notify_event(
            self.db,
            self.inst,
            "imports.applied",
            audience={"user_ids": [str(self.principal.id)]},
            context={"entity": hook.label, "applied": applied, "failed": failed, "route": f"/admin/imports/{imp.id}"},
        )
        return self._out(imp)

    # ---- rule 5 -----------------------------------------------------------------------------------------------------
    async def rollback(self, iid: uuid.UUID, reason: str) -> ImportOut:
        imp = await self._get(iid)
        if not self._out(imp).can_rollback:
            raise APIError(
                409, ErrorCode.RULE_VIOLATION, f"Imports can be rolled back within {ROLLBACK_DAYS} days of applying"
            )
        hook = HOOKS[imp.entity]
        if hook.rollback is None:
            raise APIError(409, ErrorCode.RULE_VIOLATION, f"{hook.label} imports cannot be rolled back")
        ctx = self._ctx(imp)
        undone = skipped = 0
        for r in (
            await self.db.execute(
                select(DataImportRow).where(DataImportRow.import_id == iid, DataImportRow.status == "applied")
            )
        ).scalars():
            if r.created_entity_id is None:
                continue
            async with self.db.begin_nested():
                why = await hook.rollback(r.created_entity_id, ctx)
            if why:
                r.status, r.errors = (
                    "skipped",
                    [*(r.errors or []), {"column": "*", "code": "ROLLBACK_SKIPPED", "message": why}],
                )
                skipped += 1
            else:
                r.status = "rolled_back"
                undone += 1
        imp.status, imp.rolled_back_at = "rolled_back", datetime.now(UTC)
        imp.report = {
            **(imp.report or {}),
            "rolled_back": undone,
            "rollback_skipped": skipped,
            "rollback_reason": reason,
        }
        await self.db.flush()
        await log_audit(
            self.db,
            principal=self.principal,
            module="integrations",
            action="import_rollback",
            record_type="data_import",
            record_id=imp.id,
            new={"undone": undone, "skipped": skipped, "reason": reason},
            request=self.request,
        )
        await self._emit("imports.rolled_back", imp)
        return self._out(imp)

    async def delete(self, iid: uuid.UUID) -> None:
        imp = await self._get(iid)
        if imp.status in ("applying", "applied"):
            raise APIError(409, ErrorCode.RULE_VIOLATION, "Roll back an applied import instead")
        await self.db.delete(imp)

    async def error_file(self, iid: uuid.UUID) -> bytes:
        await self._get(iid)
        from app.services.reports.render_service import xlsx_sheets

        rows = (
            await self.db.execute(
                select(DataImportRow)
                .where(DataImportRow.import_id == iid, DataImportRow.status == "invalid")
                .order_by(DataImportRow.row_no)
            )
        ).scalars()
        return xlsx_sheets(
            {
                "errors": [
                    {
                        "row": r.row_no,
                        **{k: str(v) for k, v in (r.raw or {}).items()},
                        "errors": "; ".join(f"{e['column']}: {e['message']}" for e in r.errors or []),
                    }
                    for r in rows
                ]
            }
        )

    # ---- rule 6 -----------------------------------------------------------------------------------------------------
    async def workbook(self) -> WorkbookOut:
        r = (
            await self.db.execute(
                text(
                    "SELECT value FROM institution_settings WHERE institution_id = :i AND category = :c AND key = 'imports.workbook' AND college_id IS NULL"
                ),
                {"i": self.inst, "c": META},
            )
        ).first()
        state: dict[str, Any] = dict(r[0]) if r and isinstance(r[0], dict) else {}
        steps = []
        done = 0
        for order, entity, label, deps in WORKBOOK_STEPS:
            s = (state.get("steps") or {}).get(str(order)) or {}
            status = s.get("status", "pending")
            if s.get("import_id"):
                imp = await self.db.get(DataImport, uuid.UUID(s["import_id"]))
                status = "done" if imp and imp.status == "applied" else (imp.status if imp else "pending")
            done += status == "done"
            steps.append(
                WorkbookStepOut(
                    order=order,
                    entity=entity,
                    label=label,
                    status=status,
                    import_id=s.get("import_id"),
                    depends_on=list(deps),
                )
            )
        return WorkbookOut(
            started_at=state.get("started_at"), progress_pct=int(done * 100 / len(WORKBOOK_STEPS)), steps=steps
        )

    async def workbook_start(self) -> WorkbookOut:
        if not self.principal.has("integrations", "import"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Insufficient permissions")
        await self._put("imports.workbook", {"started_at": datetime.now(UTC).isoformat(), "steps": {}})
        return await self.workbook()

    async def workbook_attach(self, order: int, import_id: uuid.UUID | None, mark_done: bool) -> WorkbookOut:
        wb = await self.workbook()
        step = next((s for s in wb.steps if s.order == order), None)
        if step is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Unknown step")
        pending = [d for d in step.depends_on if next(s for s in wb.steps if s.order == d).status != "done"]
        if pending:
            raise APIError(409, ErrorCode.RULE_VIOLATION, f"Complete step(s) {pending} first", {"depends_on": pending})
        r = (
            await self.db.execute(
                text(
                    "SELECT value FROM institution_settings WHERE institution_id = :i AND category = :c AND key = 'imports.workbook' AND college_id IS NULL"
                ),
                {"i": self.inst, "c": META},
            )
        ).first()
        state: dict[str, Any] = dict(r[0]) if r and isinstance(r[0], dict) else {"steps": {}}
        state.setdefault("steps", {})[str(order)] = {
            "import_id": str(import_id) if import_id else None,
            "status": "done" if mark_done else "in_progress",
        }
        await self._put("imports.workbook", state)
        await events.emit(
            self.db,
            institution_id=self.inst,
            event_type="imports.workbook_step_done",
            payload={"order": order},
            aggregate_type="data_import",
        )
        return await self.workbook()

    async def _emit(self, event_type: str, imp: DataImport, extra: dict[str, Any] | None = None) -> None:
        await events.emit(
            self.db,
            institution_id=self.inst,
            event_type=event_type,
            payload={"import_id": str(imp.id), "entity": imp.entity, **(extra or {})},
            aggregate_type="data_import",
            aggregate_id=imp.id,
            actor_user_id=self.principal.id,
        )


# ---- rule 7 -------------------------------------------------------------------------------------------------------------
async def export_user(db: Any, institution_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
    async def rows(sql: str) -> builtins.list[dict[str, Any]]:
        return [
            {k: (str(v) if isinstance(v, (uuid.UUID, datetime)) else v) for k, v in dict(r).items()}
            for r in (await db.execute(text(sql), {"u": user_id, "i": institution_id})).mappings().all()
        ]

    data = {
        "generated_at": datetime.now(UTC).isoformat(),
        "user": await rows(
            "SELECT id, username, display_name, email, phone, locale, created_at, last_login_at FROM users WHERE id = :u"
        ),
        "roles": await rows(
            "SELECT r.slug, ur.scope_type, ur.assigned_at FROM user_roles ur JOIN roles r ON r.id = ur.role_id WHERE ur.user_id = :u"
        ),
        "student": await rows(
            "SELECT id, registration_number, first_name, last_name, dob, gender, category, status, admission_date FROM students WHERE user_id = :u AND institution_id = :i"
        ),
        "guardians": [
            {**g, "phone": "masked (third party)", "email": "masked (third party)"}
            for g in await rows(
                "SELECT g.relation, g.name FROM student_guardians g JOIN students s ON s.id = g.student_id WHERE s.user_id = :u"
            )
        ],
        "staff": await rows(
            "SELECT id, employee_id, first_name, last_name, joining_date, status FROM staff WHERE user_id = :u AND institution_id = :i"
        ),
        "notifications": await rows(
            "SELECT title, category, created_at, is_read FROM notifications WHERE user_id = :u ORDER BY created_at DESC LIMIT 2000"
        ),
        "consents": await rows(
            "SELECT purpose, granted, text_version, recorded_at, withdrawn_at FROM consent_records WHERE user_id = :u"
        ),
        "activity": await rows(
            "SELECT created_at, module, action, record_type FROM audit_logs WHERE user_id = :u AND institution_id = :i ORDER BY created_at DESC LIMIT 5000"
        ),
    }
    return data
