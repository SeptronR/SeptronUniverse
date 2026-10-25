"""Template builder — Prompts/26 §26.6 ``template_service`` ({documents.templates}, {documents.bilingual_templates}).

Platform defaults (``institution_id`` NULL, read-only to tenants) → institution override: clone → edit (draft) →
preview → publish (``version`` + 1 on the family; older versions stay for re-render fidelity). A family is the set of
rows sharing ``layout._meta.family`` (the first version's id); ``_meta`` also carries ``status`` (draft | published),
``change_note``, ``published_by`` and ``college_id`` (college overrides, only while
``documents.college_overrides`` is on). Editing a published version creates the next draft version.

Lint: unknown ``{{ variables }}`` (not in the type's catalogue, the overrides or the renderer's own keys), missing
key variables of the type, unsupported CSS (``position:sticky``, ``@import``, scripts) — errors block publish (422).
Role limits: the controller of examinations edits exam templates, the HR officer staff templates.
"""

import re
import uuid
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.enums.documents import TEMPLATE_TYPES
from app.models.documents import DocumentTemplate, IssuedDocument
from app.schemas.documents import (
    DocLintIssue,
    DocTemplateIn,
    DocTemplateLint,
    DocTemplateOut,
    DocTemplatePreview,
    DocTemplateUpdate,
    DocTemplateUsage,
    DocVariable,
    DocVariablesCatalogue,
)
from app.services.documents.common import DocumentsBase, forbidden, not_found, now_utc
from app.services.documents.defaults import BLOCK_TYPES, compile_layout, default_template, variables_for
from app.services.documents.render_service import RenderService, pdf_bytes
from app.services.facilities.common import scope_ids

VAR_RE = re.compile(r"{{\s*([a-zA-Z_][\w.]*)")
RENDERER_KEYS = {"css", "watermark", "photo", "today", "purpose", "body", "document", "institution", "signatories"}
BAD_CSS = ("@import", "<script", "position:sticky", "position: sticky", "javascript:")
FLOWS: dict[str, list[str]] = {
    "id_card": ["Phase 07 ID cards", "Bulk generation"],
    "undertaking": ["Phase 07 undertakings"],
    "offer_letter": ["Phase 08 admission offers"],
    "hall_ticket": ["Phase 14 hall tickets"],
    "grade_card": ["Phase 15 grade cards"],
    "transcript": ["Phase 16 transcripts", "Certificate requests"],
    "degree": ["Phase 18 degrees"],
    "provisional": ["Phase 18 provisional certificates", "Certificate requests"],
    "hostel_allotment": ["Phase 20 allotment letters"],
    "event_certificate": ["Phase 25 event certificates"],
    "medical_certificate": ["Phase 25 health centre"],
    "receipt": ["Phase 12 receipts"],
}


def _meta(t: DocumentTemplate) -> dict[str, Any]:
    return dict((t.layout or {}).get("_meta") or {})


class TemplateService(DocumentsBase):
    def _view(self) -> None:
        if not (self.can("templates", "view") or self.can("templates", "manage") or self.office()):
            raise forbidden("templates:view required")

    def _manage(self, template_type: str) -> None:
        if not self.can("templates", "manage"):
            raise forbidden("templates:manage required")
        self.require_writer()
        self.require_type(template_type)

    def out(self, t: DocumentTemplate) -> DocTemplateOut:
        m = _meta(t)
        return DocTemplateOut(
            id=t.id,
            institution_id=t.institution_id,
            template_type=t.template_type,
            name=t.name,
            layout=t.layout,
            html_template=t.html_template,
            css=t.css,
            page_size=t.page_size,
            is_bilingual=t.is_bilingual,
            secondary_language=t.secondary_language,
            variables=t.variables,
            is_default=t.is_default,
            is_active=t.is_active,
            version=t.version,
            source="platform" if t.institution_id is None else "institution",
            status=m.get("status", "published"),
            college_id=m.get("college_id"),
            change_note=m.get("change_note"),
            created_at=t.created_at,
            updated_at=t.updated_at,
        )

    async def row(self, tid: uuid.UUID, *, for_update: bool = False) -> DocumentTemplate:
        stmt = select(DocumentTemplate).where(
            DocumentTemplate.id == tid,
            DocumentTemplate.deleted_at.is_(None),
            (DocumentTemplate.institution_id == self.inst) | DocumentTemplate.institution_id.is_(None),
        )
        if for_update:
            stmt = stmt.with_for_update()
        t = (await self.db.execute(stmt)).scalar_one_or_none()
        if t is None:
            raise not_found("Template")
        return t

    async def list_templates(self, template_type: str | None, source: str | None) -> list[DocTemplateOut]:
        await self.require_feature("documents.templates")
        self._view()
        stmt = select(DocumentTemplate).where(
            DocumentTemplate.deleted_at.is_(None),
            (DocumentTemplate.institution_id == self.inst) | DocumentTemplate.institution_id.is_(None),
        )
        if template_type:
            stmt = stmt.where(DocumentTemplate.template_type == template_type)
        if source == "platform":
            stmt = stmt.where(DocumentTemplate.institution_id.is_(None))
        elif source == "institution":
            stmt = stmt.where(DocumentTemplate.institution_id == self.inst)
        limit = self.type_limit()
        if limit is not None:
            stmt = stmt.where(DocumentTemplate.template_type.in_(limit))
        rows = (await self.db.execute(stmt.order_by(DocumentTemplate.template_type, DocumentTemplate.name))).scalars()
        # latest version of each family only (versions tab lists the rest)
        best: dict[str, DocumentTemplate] = {}
        for t in rows:
            fam = _meta(t).get("family") or str(t.id)
            if fam not in best or t.version > best[fam].version:
                best[fam] = t
        return [
            self.out(t)
            for t in sorted(best.values(), key=lambda t: (t.template_type, t.institution_id is not None, t.name))
        ]

    async def get(self, tid: uuid.UUID) -> DocTemplateOut:
        self._view()
        return self.out(await self.row(tid))

    async def _college_check(self, college_id: uuid.UUID | None) -> None:
        if college_id is None:
            if scope_ids(self.principal, "college") and not self.can("certificates", "view_all"):
                raise forbidden("College administrators create college overrides")
            return
        if not await self.doc_setting("college_overrides", False):
            raise forbidden("College template overrides are not permitted by the institution")
        colleges = scope_ids(self.principal, "college")
        if colleges and college_id not in colleges:
            raise forbidden("Not your college")

    async def create(self, body: DocTemplateIn) -> DocTemplateOut:
        await self.require_feature("documents.templates")
        if body.template_type not in TEMPLATE_TYPES:
            raise APIError(422, ErrorCode.VALIDATION, f"Unknown template type {body.template_type}")
        self._manage(body.template_type)
        if body.is_bilingual:
            await self.require_feature("documents.bilingual_templates")
        await self._college_check(body.college_id)
        src: dict[str, Any]
        if body.from_template_id:
            base = await self.row(body.from_template_id)
            if base.template_type != body.template_type:
                raise APIError(422, ErrorCode.VALIDATION, "Clone must keep the template type")
            src = {
                "layout": {k: v for k, v in (base.layout or {}).items() if k != "_meta"},
                "html_template": base.html_template,
                "css": base.css,
                "page_size": base.page_size,
                "variables": base.variables,
                "secondary_language": base.secondary_language,
            }
        else:
            src = default_template(body.template_type, bilingual=body.is_bilingual)
        layout = dict(body.layout or src.get("layout") or {})
        layout["_meta"] = {
            "status": "draft",
            "college_id": str(body.college_id) if body.college_id else None,
            "cloned_from": str(body.from_template_id) if body.from_template_id else None,
        }
        t = DocumentTemplate(
            institution_id=self.inst,
            template_type=body.template_type,
            name=body.name,
            layout=layout,
            html_template=body.html_template or src.get("html_template") or compile_layout(layout),
            css=body.css if body.css is not None else src.get("css"),
            page_size=body.page_size or src.get("page_size") or "A4",
            is_bilingual=body.is_bilingual,
            secondary_language=body.secondary_language
            or (src.get("secondary_language") if body.is_bilingual else None),
            variables=body.variables or src.get("variables") or variables_for(body.template_type),
            is_default=body.is_default,
            version=1,
            is_active=True,
            created_by=self.actor_id,
        )
        self.db.add(t)
        await self.db.flush()
        layout = dict(t.layout or {})
        layout["_meta"] = {**layout["_meta"], "family": str(t.id)}
        t.layout = layout
        await self.db.flush()
        await self._audit("create", "document_template", t.id, None, {"type": t.template_type, "name": t.name})
        return self.out(t)

    async def update(self, tid: uuid.UUID, body: DocTemplateUpdate) -> DocTemplateOut:
        t = await self.row(tid, for_update=True)
        if t.institution_id is None:
            raise forbidden("Platform templates are read-only — clone to override")
        self._manage(t.template_type)
        if body.is_bilingual:
            await self.require_feature("documents.bilingual_templates")
        m = _meta(t)
        if m.get("college_id"):
            await self._college_check(uuid.UUID(m["college_id"]))
        if m.get("status", "published") == "published":
            # editing a published version starts the next draft of the family
            fam = m.get("family") or str(t.id)
            top = (
                await self.db.execute(
                    select(func.max(DocumentTemplate.version)).where(
                        DocumentTemplate.institution_id == self.inst,
                        DocumentTemplate.layout["_meta"]["family"].astext == fam,
                    )
                )
            ).scalar_one() or t.version
            new = DocumentTemplate(
                institution_id=self.inst,
                template_type=t.template_type,
                name=t.name,
                layout={**(t.layout or {}), "_meta": {**m, "status": "draft", "family": fam, "change_note": None}},
                html_template=t.html_template,
                css=t.css,
                page_size=t.page_size,
                is_bilingual=t.is_bilingual,
                secondary_language=t.secondary_language,
                variables=t.variables,
                is_default=t.is_default,
                version=int(top) + 1,
                is_active=True,
                created_by=self.actor_id,
            )
            self.db.add(new)
            await self.db.flush()
            t, m = new, _meta(new)
        data = body.model_dump(exclude_unset=True)
        if "layout" in data and data["layout"] is not None:
            layout = {k: v for k, v in data.pop("layout").items() if k != "_meta"}
            layout["_meta"] = m
            t.layout = layout
            if layout.get("mode") != "html" and "html_template" not in data:
                t.html_template = compile_layout(layout)
        for k, v in data.items():
            setattr(t, k, v)
        await self.db.flush()
        return self.out(t)

    async def publish(self, tid: uuid.UUID, change_note: str) -> DocTemplateOut:
        t = await self.row(tid, for_update=True)
        if t.institution_id is None:
            raise forbidden("Platform templates are read-only")
        self._manage(t.template_type)
        if t.is_bilingual and not await self.feature("documents.bilingual_templates"):
            raise APIError(403, ErrorCode.FEATURE_DISABLED, "Feature documents.bilingual_templates is not enabled")
        lint = self.lint(t)
        if not lint.ok:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "Template has lint errors",
                {"issues": [i.model_dump() for i in lint.issues if i.level == "error"]},
            )
        m = _meta(t)
        m.update(
            status="published",
            change_note=change_note,
            published_by=str(self.actor_id),
            published_at=now_utc().isoformat(),
        )
        t.layout = {**(t.layout or {}), "_meta": m}
        if t.is_default:
            for other in (
                await self.db.execute(
                    select(DocumentTemplate).where(
                        DocumentTemplate.institution_id == self.inst,
                        DocumentTemplate.template_type == t.template_type,
                        DocumentTemplate.id != t.id,
                        DocumentTemplate.is_default.is_(True),
                    )
                )
            ).scalars():
                if (_meta(other).get("family") or str(other.id)) != m.get("family"):
                    other.is_default = False
        await self.db.flush()
        await self._audit("publish", "document_template", t.id, None, {"version": t.version, "note": change_note})
        await self._emit(
            "documents.template_published",
            {"template_id": str(t.id), "template_type": t.template_type, "version": t.version},
            "document_template",
            t.id,
        )
        return self.out(t)

    async def versions(self, tid: uuid.UUID) -> list[DocTemplateOut]:
        self._view()
        t = await self.row(tid)
        fam = _meta(t).get("family") or str(t.id)
        rows = (
            await self.db.execute(
                select(DocumentTemplate)
                .where(
                    (DocumentTemplate.institution_id == t.institution_id)
                    if t.institution_id
                    else DocumentTemplate.institution_id.is_(None),
                    (DocumentTemplate.layout["_meta"]["family"].astext == fam) | (DocumentTemplate.id == t.id),
                )
                .order_by(DocumentTemplate.version.desc())
            )
        ).scalars()
        return [self.out(r) for r in rows]

    def catalogue(self, template_type: str) -> DocVariablesCatalogue:
        self._view()
        if template_type not in TEMPLATE_TYPES:
            raise APIError(422, ErrorCode.VALIDATION, f"Unknown template type {template_type}")
        return DocVariablesCatalogue(
            template_type=template_type, variables=[DocVariable(**v) for v in variables_for(template_type)]
        )

    def lint(self, t: DocumentTemplate | dict[str, Any]) -> DocTemplateLint:
        get = (lambda k: t.get(k)) if isinstance(t, dict) else (lambda k: getattr(t, k))
        layout = get("layout") or {}
        source = (
            (get("html_template") or "")
            if layout.get("mode") == "html" or not layout.get("blocks")
            else compile_layout(layout)
        )
        known = {v["key"] for v in variables_for(str(get("template_type")))}
        issues: list[DocLintIssue] = []
        for var in sorted(set(VAR_RE.findall(source))):
            if var in known or var in RENDERER_KEYS or var.split(".")[0] in RENDERER_KEYS:
                continue
            issues.append(DocLintIssue(level="error", message=f"Unknown variable {var}", variable=var))
        try:
            from jinja2.sandbox import SandboxedEnvironment

            SandboxedEnvironment().parse(source)
        except Exception as exc:  # noqa: BLE001
            issues.append(DocLintIssue(level="error", message=f"Template syntax: {exc}"[:200]))
        css = (get("css") or "").lower()
        for bad in BAD_CSS:
            if bad in css or bad in source.lower():
                issues.append(DocLintIssue(level="error", message=f"Unsupported construct {bad}"))
        for b in layout.get("blocks") or []:
            if isinstance(b, dict) and b.get("type") not in BLOCK_TYPES:
                issues.append(DocLintIssue(level="warning", message=f"Unknown block {b.get('type')}"))
        return DocTemplateLint(ok=not any(i.level == "error" for i in issues), issues=issues)

    async def lint_template(self, tid: uuid.UUID) -> DocTemplateLint:
        self._view()
        return self.lint(await self.row(tid))

    async def preview(self, tid: uuid.UUID, body: DocTemplatePreview) -> tuple[bytes, str]:
        """PDF (or HTML) with a ``PREVIEW`` watermark — no register entry, nothing stored."""
        await self.require_feature("documents.templates")
        self._view()
        t = await self.row(tid)
        draft = body.draft.model_dump(exclude_unset=True) if body.draft else {}
        if draft.get("is_bilingual"):
            await self.require_feature("documents.bilingual_templates")
        src = {
            "template_type": t.template_type,
            "name": t.name,
            "layout": draft.get("layout", t.layout),
            "html_template": draft.get("html_template", t.html_template),
            "css": draft.get("css", t.css),
        }
        r = RenderService(self.db, self.principal, self.request, self.inst)
        if body.sample_entity_type and body.sample_entity_id:
            ctx, _, _ = await r.context(t.template_type, body.sample_entity_type, body.sample_entity_id, body.variables)
        else:
            ctx = await r.base_context()
            for v in variables_for(t.template_type):
                cur = ctx
                parts = v["key"].split(".")
                for p in parts[:-1]:
                    cur = cur.setdefault(p, {}) if isinstance(cur.get(p, {}), dict) else {}
                cur.setdefault(parts[-1], v.get("example") or "")
            for k, val in (body.variables or {}).items():
                ctx[k] = val
        ctx["document"] = {**(ctx.get("document") or {}), "number": "PREVIEW", "issued_on": ctx.get("today", "")}
        ctx["watermark"] = "PREVIEW"
        markup = r.render_html(src, ctx)
        if body.format == "html":
            return markup.encode(), "text/html"
        return pdf_bytes(markup, f"Preview — {t.name}", "PREVIEW"), "application/pdf"

    async def usage(self, tid: uuid.UUID) -> DocTemplateUsage:
        self._view()
        t = await self.row(tid)
        fam = _meta(t).get("family") or str(t.id)
        ids = [
            i
            for (i,) in (
                await self.db.execute(
                    select(DocumentTemplate.id).where(
                        (DocumentTemplate.id == t.id) | (DocumentTemplate.layout["_meta"]["family"].astext == fam)
                    )
                )
            ).all()
        ]
        rows = (
            await self.db.execute(
                select(IssuedDocument.entity_type, func.count(), func.max(IssuedDocument.issued_at))
                .where(IssuedDocument.institution_id == self.inst, IssuedDocument.template_id.in_(ids))
                .group_by(IssuedDocument.entity_type)
            )
        ).all()
        last = max((r[2] for r in rows if r[2]), default=None)
        return DocTemplateUsage(
            template_id=t.id,
            issued_count=sum(int(r[1]) for r in rows),
            by_entity_type={str(r[0] or "—"): int(r[1]) for r in rows},
            flows=FLOWS.get(t.template_type, ["Certificate requests", "Render API"]),
            last_issued_at=last,
        )
