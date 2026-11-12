"""Course catalogue — Prompts/40 §40.6 ``catalogue_service`` (``website.course_catalog`` + ``academics.public_catalog``).

Builds on the Phase 05 projection (``CatalogService``: active programmes, their current regulation, public courses,
syllabus) and adds the website settings (``website_meta catalogue``: per-programme visibility / show-fees /
highlight, hidden course codes, electives / outcomes flags), the intake (Phase 34 ``affiliation_program_approvals``
of the current year for affiliated colleges, else ``programs.sanctioned_intake``), the indicative fee summary
(Phase 12 structure totals, only with ``website.catalog_show_fees`` **and** the programme's ``show_fees``), the
admission CTA (an open Phase 08 cycle listing the programme → ``/apply/{slug}``), term grouping, search and JSON-LD.
"""

import uuid
from typing import Any

from sqlalchemy import text

from app.core.errors import APIError, ErrorCode
from app.schemas.website import CatalogueSettingsIO
from app.services.website.common import WebsiteBase, invalidate


class CatalogueService(WebsiteBase):
    async def settings_io(self) -> CatalogueSettingsIO:
        return CatalogueSettingsIO.model_validate(await self.meta("catalogue", {}) or {})

    async def save_settings(self, body: CatalogueSettingsIO) -> CatalogueSettingsIO:
        if not (self.can("manage") or (self.principal and self.principal.has("academics", "manage"))):
            from app.core.errors import APIError as _E

            raise _E(403, ErrorCode.PERMISSION_DENIED, "Insufficient permissions")
        await self.put_meta("catalogue", body.model_dump(mode="json"))
        await invalidate(self.inst)
        await self.audit("catalogue_updated", "website_catalogue", None, {"hidden": len(body.courses_hidden)})
        await self.emit("website.catalogue_updated", {"programmes": len(body.programmes)})
        return body

    async def _phase05(self) -> Any:
        from app.models.platform import Institution
        from app.services.catalog_service import CatalogService

        inst = await self.db.get(Institution, self.inst)
        assert inst is not None
        return CatalogService(self.db, inst)

    async def _context(self) -> dict[str, Any]:
        cfg = await self.settings_io()
        by_code: dict[str, dict[str, Any]] = {}
        ids = {str(p.program_id): p for p in cfg.programmes}
        rows = (
            (
                await self.db.execute(
                    text(
                        "SELECT p.id, p.code, p.sanctioned_intake, c.college_type AS institution_type FROM programs p "
                        "JOIN colleges c ON c.id = p.college_id WHERE p.institution_id = :i AND p.deleted_at IS NULL"
                    ),
                    {"i": self.inst},
                )
            )
            .mappings()
            .all()
        )
        approvals = {
            str(r[0]): int(r[1])
            for r in (
                await self.db.execute(
                    text(
                        "SELECT program_id, sum(sanctioned_intake) FROM affiliation_program_approvals "
                        "WHERE institution_id = :i AND approval_status = 'approved' "
                        "AND (valid_to IS NULL OR valid_to >= CURRENT_DATE) GROUP BY 1"
                    ),
                    {"i": self.inst},
                )
            ).all()
        }
        cycles = (
            await self.db.execute(
                text(
                    "SELECT acp.program_id, ac.slug FROM admission_cycle_programs acp JOIN admission_cycles ac "
                    "ON ac.id = acp.cycle_id WHERE acp.institution_id = :i AND ac.status = 'open' "
                    "AND (ac.closes_at IS NULL OR ac.closes_at > NOW())"
                ),
                {"i": self.inst},
            )
        ).all()
        apply = {str(r[0]): r[1] for r in cycles}
        show_fees_global = bool(await self.setting("catalog_show_fees"))
        for r in rows:
            s = ids.get(str(r["id"]))
            by_code[r["code"]] = {
                "id": r["id"],
                "visible": s.visible if s else True,
                "highlight": bool(s and s.highlight),
                "show_fees": show_fees_global and bool(s and s.show_fees),
                "intake": approvals.get(str(r["id"])) or r["sanctioned_intake"],
                "apply_slug": apply.get(str(r["id"])),
            }
        return {"cfg": cfg, "programmes": by_code}

    async def _fees(self, program_id: uuid.UUID) -> dict[str, Any] | None:
        rows = (
            await self.db.execute(
                text(
                    "SELECT coalesce(term_number, 0) AS term, sum(total_paise) AS total FROM fee_structures "
                    "WHERE institution_id = :i AND program_id = :p AND status IN ('active', 'approved', 'published') "
                    "AND deleted_at IS NULL GROUP BY 1 ORDER BY 1"
                ),
                {"i": self.inst, "p": program_id},
            )
        ).all()
        if not rows:
            return None
        return {"indicative": True, "by_term_paise": {int(t): int(v or 0) for t, v in rows}, "currency": "INR"}

    async def list_programmes(
        self, level: str | None, mode: str | None, department: str | None, q: str | None
    ) -> list[dict[str, Any]]:
        ctx = await self._context()
        data = await (await self._phase05()).catalog(None, level, None)
        out = []
        for p in data.get("programs") or []:
            meta = ctx["programmes"].get(p["code"], {})
            if not meta.get("visible", True):
                continue
            if mode and p.get("mode") != mode:
                continue
            if department and p.get("department") != department.upper():
                continue
            hay = f"{p.get('code')} {p.get('name')} {p.get('specialization') or ''}".lower()
            courses = " ".join(f"{c.get('code')} {c.get('title')}" for c in p.get("courses") or []).lower()
            if q and q.lower() not in hay and q.lower() not in courses:
                continue
            item = {k: v for k, v in p.items() if k != "courses"}
            item.update(
                intake=meta.get("intake") or p.get("sanctioned_intake"),
                highlight=meta.get("highlight", False),
                apply_url=f"/apply/{meta['apply_slug']}" if meta.get("apply_slug") else None,
            )
            if meta.get("show_fees") and meta.get("id"):
                item["fees_summary"] = await self._fees(meta["id"])
            out.append(item)
        return out

    async def programme(self, code: str) -> dict[str, Any]:
        ctx = await self._context()
        meta = ctx["programmes"].get(code.upper())
        if meta is None or not meta.get("visible", True):
            raise APIError(404, ErrorCode.NOT_FOUND, "Programme not found")
        p = await (await self._phase05()).program_detail(code, None)
        cfg: CatalogueSettingsIO = ctx["cfg"]
        hidden = {c.upper() for c in cfg.courses_hidden}
        terms: dict[int, list[dict[str, Any]]] = {}
        for c in p.get("courses") or []:
            if c.get("code", "").upper() in hidden:
                continue
            terms.setdefault(int(c.get("term") or c.get("term_number") or 0), []).append(c)
        out = {k: v for k, v in p.items() if k != "courses"}
        out["terms"] = [{"number": n, "courses": cs} for n, cs in sorted(terms.items())]
        out["intake"] = meta.get("intake")
        out["apply_url"] = f"/apply/{meta['apply_slug']}" if meta.get("apply_slug") else None
        if meta.get("show_fees"):
            out["fees_summary"] = await self._fees(meta["id"])
        if cfg.show_outcomes:
            out["outcomes"] = [
                dict(r)
                for r in (
                    await self.db.execute(
                        text(
                            "SELECT code, statement, outcome_type FROM outcome_definitions WHERE institution_id = :i "
                            "AND scope_id = :p AND is_active AND upper(outcome_type) IN ('PO', 'PSO', 'PEO') "
                            "ORDER BY outcome_type, sequence, code"
                        ),
                        {"i": self.inst, "p": meta["id"]},
                    )
                )
                .mappings()
                .all()
            ]
        out["json_ld"] = {
            "@context": "https://schema.org",
            "@type": "EducationalOccupationalProgram",
            "name": p.get("name"),
            "programCode": p.get("code"),
            "timeToComplete": f"P{p.get('duration_years') or 0}Y",
            "occupationalCredentialAwarded": p.get("degree_name"),
        }
        return out

    async def course(self, code: str) -> dict[str, Any]:
        cfg = await self.settings_io()
        if code.upper() in {c.upper() for c in cfg.courses_hidden}:
            raise APIError(404, ErrorCode.NOT_FOUND, "Course not found")
        reg = (
            await self.db.execute(
                text(
                    "SELECT r.code FROM courses c JOIN regulations r ON r.id = c.regulation_id WHERE c.institution_id = :i "
                    "AND c.code = :c AND c.is_public_catalog AND c.deleted_at IS NULL "
                    "ORDER BY r.effective_from_admission_year DESC LIMIT 1"
                ),
                {"i": self.inst, "c": code.upper()},
            )
        ).first()
        if reg is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Course not found")
        out = await (await self._phase05()).course_detail(reg[0], code)
        out["json_ld"] = {
            "@context": "https://schema.org",
            "@type": "Course",
            "courseCode": out.get("code"),
            "name": out.get("title"),
        }
        return dict(out)
