"""Evidence repository — Prompts/32 §32.6 ``evidence_service`` ({accreditation.evidence_repo}).

Documents tagged to a criterion / metric / period with a doc type (policy, minutes, certificate, report, photo, MoU…),
verification, versioning (previous file URLs in ``evidence:<id>``), the upload size cap
``accreditation.evidence_max_mb`` (→ 413), **auto-suggestions** from module events (``event.completed`` with a
``naac_criterion``, ``research.publication_verified``, ``research.mou_signed``, ``phd.thesis_awarded``,
``placement.stats_published``, ``governance.minutes_approved``, ``accounting.period_closed``) into an inbox
(``suggestion:<id>``) — accepting creates the evidence row linking the module entity —, evidence packs (zip per
criterion with an index; criterion 3 also embeds the Phase 30 NAAC research pack) and the 7-year retention sweep.

Visibility: IQAC / institution readers all; HOD the uploads of their department's staff; everyone else their own
uploads (``uploaded_by``)."""

import csv
import io
import uuid
import zipfile
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select

from app.core.errors import APIError, ErrorCode
from app.models.accreditation import EvidenceDocument, FrameworkCriterion
from app.schemas.accreditation import EvidenceIn, EvidenceOut, EvidenceSuggestion, EvidenceUpdate, EvidenceVerify
from app.services.accreditation.common import AccreditationBase, forbidden, not_found, now_utc, rule

RETENTION_YEARS = 7


class EvidenceService(AccreditationBase):
    def can_upload(self) -> bool:
        return self.iqac("evidence") or self.can(self.module, "evidence")

    async def _predicate(self, scope: str | None = None) -> Any:
        from sqlalchemy import false, or_, true

        if self.reader_all() and scope in (None, "all"):
            return true()
        parts = []
        if self.actor_id and scope in (None, "own"):
            parts.append(EvidenceDocument.uploaded_by == self.actor_id)
        depts = await self.resolved_dept_ids() if scope in (None, "department") else None
        if depts:
            parts.append(EvidenceDocument.uploaded_by.in_(await self.dept_user_ids(depts) or [uuid.uuid4()]))
        colleges = self.college_ids()
        if colleges and scope in (None, "college"):
            from app.models.hr import Staff

            parts.append(
                EvidenceDocument.uploaded_by.in_(
                    select(Staff.user_id).where(Staff.institution_id == self.inst, Staff.college_id.in_(colleges))
                )
            )
        return or_(*parts) if parts else false()

    async def _criterion_id(self, body: EvidenceIn) -> uuid.UUID | None:
        if body.framework_criterion_id:
            return body.framework_criterion_id
        if body.criterion_code:
            fw = await self.framework(body.framework_code or "NAAC_2024")
            return (await self.criterion_by_code(fw.id, body.criterion_code)).id
        return None

    async def outs(self, rows: list[EvidenceDocument]) -> list[EvidenceOut]:
        wanted = [r.framework_criterion_id for r in rows if r.framework_criterion_id] or [uuid.uuid4()]
        codes: dict[uuid.UUID, str] = {
            cid: str(code)
            for cid, code in (
                await self.db.execute(
                    select(FrameworkCriterion.id, FrameworkCriterion.code).where(FrameworkCriterion.id.in_(wanted))
                )
            ).all()
        }
        names = await self.user_names([r.uploaded_by for r in rows])
        metas = await self.metas("evidence", [r.id for r in rows])
        return [
            EvidenceOut(
                id=r.id,
                framework_criterion_id=r.framework_criterion_id,
                criterion_code=codes.get(r.framework_criterion_id) if r.framework_criterion_id else None,
                metric_key=r.metric_key,
                period_label=r.period_label,
                title=r.title,
                doc_type=r.doc_type,
                file_url=r.file_url,
                uploaded_by=r.uploaded_by,
                uploaded_by_name=names.get(r.uploaded_by) if r.uploaded_by else None,
                verified=r.verified_at is not None,
                verified_at=r.verified_at,
                tags=[str(t) for t in r.tags or []],
                version=len(metas.get(str(r.id), {}).get("versions") or []) + 1,
                source=metas.get(str(r.id), {}).get("source"),
                created_at=r.created_at,
            )
            for r in rows
        ]

    async def query(
        self,
        *,
        criterion: str | None = None,
        framework: str | None = None,
        period: str | None = None,
        metric_key: str | None = None,
        doc_type: str | None = None,
        verified: bool | None = None,
        q: str | None = None,
        scope: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[EvidenceOut], int]:
        stmt = select(EvidenceDocument).where(
            EvidenceDocument.institution_id == self.inst, await self._predicate(scope)
        )
        if criterion:
            fw = await self.framework(framework or "NAAC_2024")
            ids = [
                c.id for c in await self.criteria(fw.id) if c.code == criterion or c.code.startswith(criterion + ".")
            ]
            stmt = stmt.where(EvidenceDocument.framework_criterion_id.in_(ids or [uuid.uuid4()]))
        if period:
            stmt = stmt.where(EvidenceDocument.period_label == period)
        if metric_key:
            stmt = stmt.where(EvidenceDocument.metric_key == metric_key)
        if doc_type:
            stmt = stmt.where(EvidenceDocument.doc_type == doc_type)
        if verified is not None:
            stmt = stmt.where(
                EvidenceDocument.verified_at.is_not(None) if verified else EvidenceDocument.verified_at.is_(None)
            )
        if q:
            stmt = stmt.where(EvidenceDocument.title.ilike(f"%{q}%"))
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = list(
            (await self.db.execute(stmt.order_by(EvidenceDocument.created_at.desc()).limit(limit).offset(offset)))
            .scalars()
            .all()
        )
        return await self.outs(rows), total

    async def row(self, eid: uuid.UUID) -> EvidenceDocument:
        r = (
            await self.db.execute(
                select(EvidenceDocument).where(
                    EvidenceDocument.id == eid, EvidenceDocument.institution_id == self.inst, await self._predicate()
                )
            )
        ).scalar_one_or_none()
        if r is None:
            raise not_found("Evidence")
        return r

    async def get(self, eid: uuid.UUID) -> EvidenceOut:
        return (await self.outs([await self.row(eid)]))[0]

    async def create(self, body: EvidenceIn, *, source: dict[str, Any] | None = None) -> EvidenceOut:
        self.require_writer()
        if not self.can_upload():
            raise forbidden("accreditation:evidence required")
        max_mb = int(await self.acc_setting("evidence_max_mb") or 25)
        if body.size_bytes is not None and body.size_bytes > max_mb * 1024 * 1024:
            raise APIError(413, ErrorCode.VALIDATION, f"Evidence larger than {max_mb} MB", {"code": "TOO_LARGE"})
        row = EvidenceDocument(
            institution_id=self.inst,
            framework_criterion_id=await self._criterion_id(body),
            metric_key=body.metric_key,
            period_label=body.period_label,
            title=body.title,
            doc_type=body.doc_type,
            file_url=body.file_url,
            uploaded_by=self.actor_id,
            tags=body.tags,
        )
        self.db.add(row)
        await self.db.flush()
        if source or body.size_bytes:
            await self.put_meta("evidence", row.id, {"source": source, "size_bytes": body.size_bytes, "versions": []})
        await self._audit("evidence_uploaded", "evidence_document", row.id, None, {"title": row.title})
        await self._emit("accreditation.evidence_uploaded", {"evidence_id": str(row.id)}, "evidence_document", row.id)
        return (await self.outs([row]))[0]

    def _may_edit(self, r: EvidenceDocument) -> bool:
        return self.iqac("evidence") or (r.uploaded_by is not None and r.uploaded_by == self.actor_id)

    async def update(self, eid: uuid.UUID, body: EvidenceUpdate) -> EvidenceOut:
        self.require_writer()
        r = await self.row(eid)
        if not self._may_edit(r):
            raise forbidden("Only the uploader or IQAC edits evidence")
        if r.verified_at is not None and not self.iqac("evidence"):
            raise rule("Verified evidence is locked", "LOCKED")
        m = await self.meta("evidence", r.id)
        if body.file_url and body.file_url != r.file_url:
            m.setdefault("versions", []).append(
                {"file_url": r.file_url, "at": now_utc().isoformat(), "by": str(self.actor_id)}
            )
            r.verified_by = r.verified_at = None
        for f in ("title", "doc_type", "period_label", "metric_key", "file_url", "tags"):
            v = getattr(body, f)
            if v is not None:
                setattr(r, f, v)
        await self.put_meta("evidence", r.id, m)
        await self.db.flush()
        return (await self.outs([r]))[0]

    async def delete(self, eid: uuid.UUID) -> None:
        self.require_writer()
        r = await self.row(eid)
        if not self._may_edit(r) or (r.verified_at is not None and not self.iqac("evidence")):
            raise forbidden("Only IQAC deletes verified evidence")
        await self.db.delete(r)
        await self._audit("evidence_deleted", "evidence_document", eid, {"title": r.title}, None)

    async def verify(self, eid: uuid.UUID, body: EvidenceVerify) -> EvidenceOut:
        self.require_iqac("evidence")
        r = await self.row(eid)
        if body.action == "verify":
            r.verified_by, r.verified_at = self.actor_id, now_utc()
            await self._emit("accreditation.evidence_verified", {"evidence_id": str(r.id)}, "evidence_document", r.id)
        else:
            r.verified_by = r.verified_at = None
        await self.db.flush()
        return (await self.outs([r]))[0]

    # ---- suggestions ---------------------------------------------------------------------------------------------------
    async def suggest(
        self,
        module: str,
        entity: str,
        entity_id: Any,
        title: str,
        criterion_code: str | None,
        period_label: str | None = None,
        file_url: str | None = None,
    ) -> str | None:
        if not await self.feature("accreditation.evidence_repo"):
            return None
        sid = f"{module}-{entity}-{entity_id}" if entity_id else f"{module}-{entity}-{uuid.uuid4().hex[:8]}"
        if await self.meta("suggestion", sid):
            return sid
        await self.put_meta(
            "suggestion",
            sid,
            {
                "module": module,
                "entity": entity,
                "entity_id": str(entity_id) if entity_id else None,
                "title": title[:200],
                "criterion_code": criterion_code,
                "period_label": period_label,
                "file_url": file_url,
                "status": "pending",
                "created_at": now_utc().isoformat(),
            },
        )
        await self._emit(
            "accreditation.evidence_suggested", {"suggestion_id": sid, "module": module}, "evidence_document", None
        )
        return sid

    async def suggestions(self, status: str = "pending") -> list[EvidenceSuggestion]:
        if not (self.can_upload() or self.reader_all()):
            raise forbidden("accreditation:evidence required")
        out = [
            EvidenceSuggestion(id=k, **{f: v.get(f) for f in EvidenceSuggestion.model_fields if f != "id" and f in v})
            for k, v in (await self.metas("suggestion")).items()
            if v.get("status", "pending") == status
        ]
        return sorted(out, key=lambda s: s.created_at or "", reverse=True)

    async def decide_suggestion(self, sid: str, accept: bool) -> EvidenceSuggestion:
        self.require_iqac("evidence")
        m = await self.meta("suggestion", sid)
        if not m:
            raise not_found("Suggestion")
        if m.get("status") != "pending":
            raise rule("Suggestion already decided", "ALREADY_DECIDED")
        if accept:
            ev = await self.create(
                EvidenceIn(
                    criterion_code=m.get("criterion_code"),
                    period_label=m.get("period_label"),
                    title=m.get("title") or "Evidence",
                    doc_type="report",
                    file_url=m.get("file_url") or f"entity://{m.get('module')}/{m.get('entity')}/{m.get('entity_id')}",
                    tags=[str(m.get("module"))],
                ),
                source={k: m.get(k) for k in ("module", "entity", "entity_id")},
            )
            m["evidence_id"] = str(ev.id)
        m["status"] = "accepted" if accept else "dismissed"
        await self.put_meta("suggestion", sid, m)
        return EvidenceSuggestion(
            id=sid, **{f: m.get(f) for f in EvidenceSuggestion.model_fields if f != "id" and f in m}
        )

    # ---- packs / retention ----------------------------------------------------------------------------------------------
    async def build_pack(self, criterion: str, period: str | None = None, framework: str = "NAAC_2024") -> bytes:
        if not (self.can_upload() or self.reader_all()):
            raise forbidden("accreditation:evidence required")
        items, _ = await self.query(criterion=criterion, framework=framework, period=period, limit=100000)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            s = io.StringIO()
            w = csv.writer(s)
            w.writerow(["#", "criterion", "metric", "period", "title", "type", "verified", "file_url"])
            for i, e in enumerate(items, 1):
                w.writerow(
                    [i, e.criterion_code, e.metric_key, e.period_label, e.title, e.doc_type, e.verified, e.file_url]
                )
            z.writestr(f"{framework}_{criterion}_evidence_index.csv", s.getvalue())
            if criterion.split(".")[0] == "3" and await self.feature("research.publications"):
                from app.services.research.score_service import ScoreService

                year = int(period[:4]) if period and period[:4].isdigit() else None
                z.writestr(
                    f"NAAC_{criterion}_research_pack.zip",
                    await ScoreService(self.db, self.principal, self.request, self.inst).evidence_pack(criterion, year),
                )
            z.writestr(
                "README.txt",
                f"{framework} criterion {criterion} evidence pack — {len(items)} document(s)"
                f"{f' for {period}' if period else ''}. The index lists every document with its link.\n",
            )
        return buf.getvalue()

    async def retention_sweep(self) -> int:
        cutoff = now_utc() - timedelta(days=365 * RETENTION_YEARS)
        res = await self.db.execute(
            delete(EvidenceDocument).where(
                EvidenceDocument.institution_id == self.inst, EvidenceDocument.created_at < cutoff
            )
        )
        return int(res.rowcount or 0)  # type: ignore[attr-defined]
