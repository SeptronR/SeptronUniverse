"""Cycle / submission exports — Prompts/32 §32.6 ``cycle_service`` step 3 (job ``accreditation.cycle_export``).

Formats: NAAC SSR / AQAR and NBA SAR (docx — WordprocessingML written directly — with QnM tables carrying numerator /
denominator, QlM narratives and an evidence index with links; ``pdf`` through the Phase 26 ``documents.render``),
NIRF DCF / AISHE DCF / AICTE / UGC annual / xlsx (openpyxl workbooks, one sheet per section). Every export is
registered as an ``issued_documents`` row (``documents.render('custom', 'accreditation_cycle', cycle_id)``, skipped
while ``documents.templates`` is off) for traceability and recorded in the cycle side store (``cycle:<id>.exports``).
This is the data provider for the Phase 36 statutory renderers; the workbook / docx writers are the shared Phase 36
``services/reports/render_service`` (re-exported here for existing imports)."""

import uuid
from typing import Any

from sqlalchemy import select

from app.models.accreditation import AccreditationCycle, EvidenceDocument, MetricValue
from app.services.accreditation.common import AccreditationBase, forbidden, now_utc
from app.services.accreditation.cycle_service import CycleService, cycle_period_label
from app.services.documents.render_service import register_resolver
from app.services.reports.render_service import docx_bytes, xlsx_sheets  # shared renderers (Phase 36)

ENTITY = "accreditation_cycle"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ExportService(AccreditationBase):
    def require_exporter(self) -> None:
        self.require_writer()
        if not self.iqac("submit"):
            raise forbidden("accreditation:submit required")

    async def _metric_rows(self, label: str | None, keys: set[str] | None = None) -> list[dict[str, Any]]:
        if not label:
            return []
        stmt = select(MetricValue).where(MetricValue.institution_id == self.inst, MetricValue.period_label == label)
        if keys is not None:
            stmt = stmt.where(MetricValue.metric_key.in_(keys or {"-"}))
        defs = await self.definitions_by_key()
        return [
            {
                "metric": r.metric_key,
                "name": defs[r.metric_key].name if r.metric_key in defs else r.metric_key,
                "period": r.period_label,
                "college_id": str(r.college_id) if r.college_id else None,
                "program_id": str(r.program_id) if r.program_id else None,
                "value": float(r.value) if r.value is not None else None,
                "numerator": float(r.numerator) if r.numerator is not None else None,
                "denominator": float(r.denominator) if r.denominator is not None else None,
                "source": r.source,
                "verified": r.verified_at is not None,
            }
            for r in (await self.db.execute(stmt.order_by(MetricValue.metric_key))).scalars()
        ]

    async def cycle_export(
        self, cycle_id: uuid.UUID, fmt: str, period_label: str | None = None
    ) -> tuple[bytes, str, str, int]:
        """→ (content, filename, mime, rows)."""
        svc = CycleService(self.db, self.principal, self.request, self.inst)
        c = await svc.cycle(cycle_id)
        fw = await self.framework(c.framework_id)
        label = period_label or cycle_period_label(c)
        responses = await svc.responses(c.id)
        crits = {cr.code: cr for cr in await self.criteria(fw.id)}
        keys = {cr.metric_key for cr in crits.values() if cr.metric_key}
        metrics = await self._metric_rows(label, keys)
        by_key: dict[str, list[dict[str, Any]]] = {}
        for m in metrics:
            by_key.setdefault(m["metric"], []).append(m)
        ev_ids = [uuid.UUID(e) for r in responses for e in r.evidence_ids]
        evidence = (
            list(
                (await self.db.execute(select(EvidenceDocument).where(EvidenceDocument.id.in_(ev_ids)))).scalars().all()
            )
            if ev_ids
            else []
        )
        stem = f"{fw.code}-{fmt}-{label or 'cycle'}".replace("/", "-")
        if fmt in ("naac_ssr", "naac_aqar", "nba_sar", "docx", "pdf"):
            blocks: list[tuple[str, Any]] = [("p", f"{c.name} · {fw.name} · period {label or '—'} · status {c.status}")]
            for r in responses:
                blocks.append(("h2", f"{r.code} {r.title}"))
                cr = crits.get(r.code)
                if cr is not None and cr.metric_key and by_key.get(cr.metric_key):
                    rows = [["Metric", "Value", "Numerator", "Denominator", "Source", "Verified"]]
                    rows += [
                        [
                            m["name"],
                            str(m["value"]),
                            str(m["numerator"]),
                            str(m["denominator"]),
                            m["source"],
                            "yes" if m["verified"] else "no",
                        ]
                        for m in by_key[cr.metric_key]
                    ]
                    blocks.append(("table", rows))
                if r.narrative:
                    import re

                    blocks.append(("p", re.sub(r"<[^>]+>", "\n", r.narrative).strip()))
                if r.evidence_ids:
                    blocks.append(("p", "Evidence: " + ", ".join(r.evidence_ids)))
            blocks.append(("h1", "Evidence index"))
            blocks.append(
                (
                    "table",
                    [["#", "Title", "Type", "Period", "Link"]]
                    + [
                        [str(i), e.title, e.doc_type or "", e.period_label or "", e.file_url]
                        for i, e in enumerate(evidence, 1)
                    ],
                )
            )
            if fmt == "pdf":
                # the PDF is the Phase 26 rendition registered by the job (``register_document``); no file body here
                return b"", f"{stem}.pdf", "application/pdf", len(responses)
            return docx_bytes(f"{fw.name} — {c.name}", blocks), f"{stem}.docx", DOCX, len(responses)
        sheets: dict[str, list[dict[str, Any]]] = {}
        if fmt == "nirf_dcf":
            for prefix in ("TLR", "RP", "GO", "OI", "PR"):
                ks = {cr.metric_key for code, cr in crits.items() if code.startswith(prefix) and cr.metric_key}
                sheets[prefix] = [m for m in metrics if m["metric"] in ks]
        elif fmt == "aishe_dcf":
            for code, cr in sorted(crits.items()):
                sheets[f"{code} {cr.title}"[:30]] = (
                    [m for m in metrics if m["metric"] == cr.metric_key] if cr.metric_key else []
                )
        else:
            sheets["metrics"] = metrics
            sheets["responses"] = [
                {"code": r.code, "title": r.title, "status": r.status, "owner": r.owner_name, "words": r.word_count}
                for r in responses
            ]
        sheets["evidence"] = [
            {"title": e.title, "type": e.doc_type, "period": e.period_label, "link": e.file_url} for e in evidence
        ]
        return xlsx_sheets(sheets), f"{stem}.xlsx", XLSX, len(metrics)

    async def register_document(self, c: AccreditationCycle, fmt: str, body: str) -> Any:
        """``documents.render('custom', 'accreditation_cycle')`` → ``DocRenderResult`` (None while templates are off)."""
        if not await self.feature("documents.templates"):
            return None
        from app.core.errors import APIError
        from app.services.documents.render_service import render

        try:
            res = await render(
                self.db,
                self.principal,
                "custom",
                ENTITY,
                c.id,
                institution_id=self.inst,
                variables_override={"title": f"{c.name} — {fmt.upper()} export", "body": body},
                allow_multiple=True,
            )
        except APIError:
            return None
        return res

    async def record_export(
        self, cycle_id: uuid.UUID, fmt: str, url: str | None, rows: int, doc_id: uuid.UUID | None
    ) -> dict[str, Any]:
        m = await self.meta("cycle", cycle_id)
        entry = {
            "id": uuid.uuid4().hex[:12],
            "format": fmt,
            "status": "ready",
            "file_url": url,
            "issued_document_id": str(doc_id) if doc_id else None,
            "created_at": now_utc().isoformat(),
            "rows": rows,
        }
        m.setdefault("exports", []).append(entry)
        m["exports"] = m["exports"][-30:]
        await self.put_meta("cycle", cycle_id, m)
        await self._emit(
            "accreditation.export_ready", {"cycle_id": str(cycle_id), "format": fmt, "url": url}, ENTITY, cycle_id
        )
        return entry

    async def exports(self, cycle_id: uuid.UUID) -> list[dict[str, Any]]:
        await CycleService(self.db, self.principal, self.request, self.inst).cycle(cycle_id)
        return list(reversed((await self.meta("cycle", cycle_id)).get("exports") or []))


@register_resolver(ENTITY)
async def _cycle_ctx(svc: Any, cid: uuid.UUID) -> tuple[dict[str, Any], str | None, uuid.UUID | None]:
    c = (await svc.db.execute(select(AccreditationCycle).where(AccreditationCycle.id == cid))).scalar_one()
    return (
        {
            "cycle": {
                "name": c.name,
                "status": c.status,
                "period": cycle_period_label(c) or "",
                "grade": c.grade or "",
            }
        },
        None,
        None,
    )
