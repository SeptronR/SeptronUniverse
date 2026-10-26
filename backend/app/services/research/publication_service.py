"""Publications — Prompts/30 §30.6 ``publication_service`` ({research.publications}).

1. Records by faculty / scholars with authors tagged to staff / scholars: co-authors inside the institution share one
   row (``authors[].staff_id``) and every tagged author sees it as their own. DOIs are normalised (``10.x/…``
   lower-case) and unique per institution under ``research.duplicate_doi_policy``: ``block`` → 409 ``DUPLICATE_DOI``
   with the existing row and a ``claim-coauthor`` hint; ``warn`` → saved with the duplicate ids listed.
2. Imports: Crossref by DOI / ORCID, Scopus by author id (``BibliographicProvider`` mocks until Phase 41), BibTeX / CSV
   text → preview (matches = same DOI or ≥ 0.85 title similarity to an existing row the caller is not tagged on,
   duplicates = already the caller's, new) kept 1 hour in the side store → apply (new rows unverified, matches
   claimed). Nightly / weekly sync for faculty with ORCID / Scopus ids; citations refresh.
3. Verification: HOD first level (``research:verify`` at department scope → ``department``), research cell final
   (``is_verified`` + ``verified_by`` = the cell member's staff id); rejection with remarks; verified rows are locked
   for authors (403 ``LOCKED`` — change requests go through the research cell); a verifier outside the row's units gets
   404. Verified counts by indexing feed NAAC 3.3.x and NIRF PU / QP (``stats_service``).
"""

import difflib
import secrets
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, or_, select

from app.integrations.bibliographic import parse_bibtex, parse_csv
from app.integrations.registry import get_adapter
from app.models.hr import FacultyProfile, Staff
from app.models.research import Publication
from app.schemas.research import (
    ClaimCoauthor,
    ImportApply,
    ImportCandidate,
    ImportPreview,
    ImportResult,
    PublicationImport,
    PublicationIn,
    PublicationOut,
    PublicationUpdate,
    RschVerifyRequest,
    RschVerifyResult,
)
from app.services.research.common import (
    ResearchBase,
    forbidden,
    normalise_doi,
    not_found,
    now_utc,
    rule,
    staff_name,
)

KEYS = ("title", "doi", "indexing", "year", "is_verified")


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


class PublicationService(ResearchBase):
    # ---- reads ----------------------------------------------------------------------------------------------------------
    async def predicate(self, scope: str | None = None) -> Any:
        return await self.owned_predicate(Publication.staff_id, scope=scope, json_col=Publication.authors)

    async def row(self, pid: uuid.UUID, *, lock: bool = False, visible: bool = True) -> Publication:
        stmt = select(Publication).where(Publication.id == pid, Publication.institution_id == self.inst)
        if visible:
            stmt = stmt.where(await self.predicate())
        if lock:
            stmt = stmt.with_for_update()
        p = (await self.db.execute(stmt)).scalar_one_or_none()
        if p is None:
            raise not_found("Publication")
        return p

    async def outs(self, rows: list[Publication]) -> list[PublicationOut]:
        staff = await self.staff_map([r.staff_id for r in rows])
        metas = await self.metas("pub", [r.id for r in rows]) if rows else {}
        mine = await self.my_staff_id()
        dois = [r.doi for r in rows if r.doi]
        dup: dict[str, list[uuid.UUID]] = {}
        if dois:
            for pid, d in (
                await self.db.execute(
                    select(Publication.id, Publication.doi).where(
                        Publication.institution_id == self.inst, Publication.doi.in_(dois)
                    )
                )
            ).all():
                dup.setdefault(d, []).append(pid)
        out = []
        for r in rows:
            m = metas.get(str(r.id), {})
            s = staff.get(r.staff_id) if r.staff_id else None
            is_mine = mine is not None and (
                r.staff_id == mine or any(str(a.get("staff_id")) == str(mine) for a in (r.authors or []))
            )
            level = "final" if r.is_verified else m.get("level", "none")
            out.append(
                PublicationOut(
                    id=r.id,
                    staff_id=r.staff_id,
                    staff_name=staff_name(s),
                    department_id=s.department_id if s else None,
                    scholar_id=r.scholar_id,
                    pub_type=r.pub_type,
                    title=r.title,
                    venue=r.venue,
                    year=r.year,
                    doi=r.doi,
                    issn_isbn=r.issn_isbn,
                    indexing=r.indexing,
                    impact_factor=r.impact_factor,
                    authors=list(r.authors or []),
                    author_position=r.author_position,
                    citations=r.citations,
                    evidence_url=r.evidence_url,
                    is_verified=r.is_verified,
                    verification_level=level if level in ("none", "department", "final", "rejected") else "none",
                    remarks=m.get("remarks"),
                    source=m.get("source"),
                    is_mine=is_mine,
                    can_edit=self.cell() or (is_mine and not r.is_verified),
                    duplicates=[d for d in dup.get(r.doi or "", []) if d != r.id],
                    created_at=r.created_at,
                )
            )
        return out

    async def query(
        self,
        *,
        staff_id: uuid.UUID | None = None,
        department_id: uuid.UUID | None = None,
        indexing: str | None = None,
        year: int | None = None,
        verified: bool | None = None,
        q: str | None = None,
        scope: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[PublicationOut], int]:
        stmt = select(Publication).where(Publication.institution_id == self.inst, await self.predicate(scope))
        if staff_id is not None:
            stmt = stmt.where(
                or_(Publication.staff_id == staff_id, Publication.authors.contains([{"staff_id": str(staff_id)}]))
            )
        if department_id is not None:
            stmt = stmt.where(Publication.staff_id.in_(select(Staff.id).where(Staff.department_id == department_id)))
        if indexing:
            stmt = stmt.where(Publication.indexing == indexing)
        if year:
            stmt = stmt.where(Publication.year == year)
        if verified is not None:
            stmt = stmt.where(Publication.is_verified.is_(verified))
        if q:
            stmt = stmt.where(or_(Publication.title.ilike(f"%{q}%"), Publication.doi.ilike(f"%{q}%")))
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = list(
            (
                await self.db.execute(
                    stmt.order_by(Publication.year.desc().nullslast(), Publication.created_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).scalars()
        )
        return await self.outs(rows), total

    async def get(self, pid: uuid.UUID) -> PublicationOut:
        return (await self.outs([await self.row(pid)]))[0]

    # ---- writes ---------------------------------------------------------------------------------------------------------
    async def _owner(self, staff_id: uuid.UUID | None) -> uuid.UUID:
        if staff_id is not None and self.cell():
            return (await self.staff_row(staff_id)).id
        return (await self.require_my_staff()).id

    async def _duplicates(self, doi: str | None, exclude: uuid.UUID | None = None) -> list[Publication]:
        if not doi:
            return []
        stmt = select(Publication).where(Publication.institution_id == self.inst, Publication.doi == doi)
        if exclude is not None:
            stmt = stmt.where(Publication.id != exclude)
        return list((await self.db.execute(stmt)).scalars())

    async def _doi_check(self, doi: str | None, exclude: uuid.UUID | None = None) -> list[uuid.UUID]:
        dups = await self._duplicates(doi, exclude)
        if not dups:
            return []
        if (await self.json_setting("duplicate_doi_policy", "block")) == "block":
            raise rule(
                "A publication with this DOI is already recorded — claim co-authorship instead",
                "DUPLICATE_DOI",
                existing_id=str(dups[0].id),
                existing_title=dups[0].title,
                action=f"/research/publications/{dups[0].id}/claim-coauthor",
            )
        return [d.id for d in dups]

    @staticmethod
    def _authors(body_authors: list[Any], owner: uuid.UUID, owner_name: str | None, position: int | None) -> list[Any]:
        authors = [a.model_dump(mode="json") if hasattr(a, "model_dump") else dict(a) for a in body_authors]
        if not any(str(a.get("staff_id")) == str(owner) for a in authors):
            entry = {
                "name": owner_name or "Author",
                "staff_id": str(owner),
                "scholar_id": None,
                "is_corresponding": False,
            }
            idx = (position - 1) if position and position - 1 <= len(authors) else len(authors)
            authors.insert(idx, entry)
        return authors

    async def create(self, body: PublicationIn, *, source: str | None = None) -> PublicationOut:
        self.require_writer()
        owner = await self._owner(body.staff_id)
        s = await self.staff_row(owner)
        doi = normalise_doi(body.doi)
        dups = await self._doi_check(doi)
        authors = self._authors(body.authors, owner, staff_name(s), body.author_position)
        position = body.author_position or next(
            (i + 1 for i, a in enumerate(authors) if str(a.get("staff_id")) == str(owner)), None
        )
        p = Publication(
            institution_id=self.inst,
            staff_id=owner,
            scholar_id=body.scholar_id,
            pub_type=body.pub_type.value,
            title=body.title,
            venue=body.venue,
            year=body.year,
            doi=doi,
            issn_isbn=body.issn_isbn,
            indexing=body.indexing.value,
            impact_factor=body.impact_factor,
            authors=authors,
            author_position=position,
            citations=body.citations,
            evidence_url=body.evidence_url,
            is_verified=False,
        )
        self.db.add(p)
        await self.db.flush()
        await self.put_meta(
            "pub", p.id, {"level": "none", "source": source or "manual", "duplicates": [str(d) for d in dups]}
        )
        await self._audit("create", "publication", p.id, None, {"title": p.title, "doi": doi, "source": source})
        await self._emit(
            "research.publication_imported" if source and source != "manual" else "research.publication_created",
            {"publication_id": str(p.id), "staff_id": str(owner), "doi": doi, "indexing": p.indexing},
            "publication",
            p.id,
        )
        return (await self.outs([p]))[0]

    async def update(self, pid: uuid.UUID, body: PublicationUpdate) -> PublicationOut:
        self.require_writer()
        p = await self.row(pid, lock=True)
        mine = await self.is_mine(p.staff_id, p.authors)
        if not self.cell():
            if not mine:
                raise forbidden("Only a tagged author or the research cell edits a publication")
            if p.is_verified:
                raise rule("A verified publication is locked — ask the research cell for a change", "LOCKED", 403)
        data = body.model_dump(exclude_unset=True, mode="json")
        if "doi" in data:
            data["doi"] = normalise_doi(data["doi"])
            if data["doi"] != p.doi:
                await self._doi_check(data["doi"], exclude=p.id)
        if "authors" in data and data["authors"] is not None and p.staff_id:
            s = await self.staff_row(p.staff_id)
            data["authors"] = self._authors(data["authors"], p.staff_id, staff_name(s), p.author_position)
        old = {k: getattr(p, k) for k in data}
        for k, v in data.items():
            setattr(p, k, v)
        m = await self.meta("pub", p.id)
        if m.get("level") == "rejected":
            m["level"] = "none"
            await self.put_meta("pub", p.id, m)
        await self.db.flush()
        await self._audit("update", "publication", p.id, {k: str(v) for k, v in old.items()}, data)
        return (await self.outs([p]))[0]

    async def delete(self, pid: uuid.UUID) -> None:
        self.require_writer()
        p = await self.row(pid, lock=True)
        if not self.cell():
            if p.staff_id != await self.my_staff_id():
                raise forbidden("Only the recording author or the research cell deletes a publication")
            if p.is_verified:
                raise rule("A verified publication is locked", "LOCKED", 403)
        await self._audit("delete", "publication", p.id, {"title": p.title, "doi": p.doi}, None)
        await self.db.delete(p)
        await self.db.flush()

    async def claim(self, pid: uuid.UUID, body: ClaimCoauthor) -> PublicationOut:
        """Tag the caller as a co-author of an existing row (the duplicate-DOI path)."""
        self.require_writer()
        me = await self.require_my_staff()
        p = (
            await self.db.execute(
                select(Publication)
                .where(Publication.id == pid, Publication.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if p is None:
            raise not_found("Publication")
        authors = [dict(a) for a in (p.authors or [])]
        if p.staff_id == me.id or any(str(a.get("staff_id")) == str(me.id) for a in authors):
            raise rule("You are already an author of this publication", "ALREADY_AUTHOR")
        name = staff_name(me)
        entry = {"name": name, "staff_id": str(me.id), "scholar_id": None, "is_corresponding": body.is_corresponding}
        # an untagged author with the same name is the caller (imports carry names only)
        same = next(
            (
                i
                for i, a in enumerate(authors)
                if not a.get("staff_id") and name and _similar(a.get("name", ""), name) > 0.8
            ),
            None,
        )
        if same is not None:
            authors[same] = {**authors[same], **entry}
        elif body.author_position and body.author_position - 1 <= len(authors):
            authors.insert(body.author_position - 1, entry)
        else:
            authors.append(entry)
        p.authors = authors
        await self.db.flush()
        await self.timeline("pub", p.id, "claimed", staff_id=str(me.id))
        await self._audit("claim_coauthor", "publication", p.id, None, {"staff_id": str(me.id)})
        return (await self.outs([p]))[0]

    # ---- verification ---------------------------------------------------------------------------------------------------
    async def verify(self, body: RschVerifyRequest) -> RschVerifyResult:
        self.require_writer()
        if not self.verifier():
            raise forbidden("research:verify required")
        final = self.cell("verify")
        rows = list(
            (
                await self.db.execute(
                    select(Publication)
                    .where(
                        Publication.institution_id == self.inst,
                        Publication.id.in_(body.ids),
                        await self.owned_predicate(Publication.staff_id, scope=None if final else "department"),
                    )
                    .order_by(Publication.id)
                    .with_for_update()
                )
            ).scalars()
        )
        if len(rows) != len(set(body.ids)):
            raise not_found("Publication")
        me = await self.my_staff_id()
        out = RschVerifyResult()
        for p in rows:
            m = await self.meta("pub", p.id)
            hist = list(m.get("history") or [])
            hist.append(
                {
                    "at": now_utc().isoformat(),
                    "by": str(self.actor_id),
                    "approve": body.approve,
                    "level": "final" if final else "department",
                    "remarks": body.remarks,
                }
            )
            if p.is_verified and body.approve:
                out.skipped.append({"id": str(p.id), "reason": "already verified"})
                continue
            if not body.approve:
                p.is_verified, p.verified_by = False, None
                m.update(level="rejected", remarks=body.remarks, history=hist)
                out.rejected += 1
                event = "research.publication_rejected"
            elif final:
                p.is_verified, p.verified_by = True, me
                m.update(level="final", remarks=body.remarks, history=hist)
                out.verified += 1
                event = "research.publication_verified"
            else:
                m.update(level="department", remarks=body.remarks, history=hist)
                out.department_level += 1
                event = ""
            await self.put_meta("pub", p.id, m)
            if event:
                await self._emit(event, {"publication_id": str(p.id), "staff_id": str(p.staff_id)}, "publication", p.id)
                if p.staff_id:
                    await self._notify(
                        event,
                        [await self.staff_user(p.staff_id)],
                        {"title": p.title[:120], "level": m.get("level"), "remarks": body.remarks or ""},
                    )
        await self.db.flush()
        await self._audit("verify", "publication", None, None, body.model_dump(mode="json") | {"final": final})
        return out

    # ---- imports --------------------------------------------------------------------------------------------------------
    async def _fetch(self, body: PublicationImport) -> list[dict[str, Any]]:
        if body.source in ("bibtex", "csv"):
            text = body.content
            if not text and body.file_url:
                from app.core.files import get_storage

                try:
                    text = (await get_storage().get(body.file_url)).decode("utf-8", "replace")
                except Exception as exc:  # noqa: BLE001 - storage backends raise their own errors
                    raise rule("The import file could not be read", "IMPORT_FILE", 422) from exc
            if not text:
                raise rule("content or file_url is required", "IMPORT_EMPTY", 422)
            return parse_bibtex(text) if body.source == "bibtex" else parse_csv(text)
        allowed = await self.json_setting("import_sources", ["crossref", "scopus", "orcid"])
        if body.source not in allowed:
            raise rule(f"Import source {body.source} is not enabled", "SOURCE_DISABLED", 422)
        ident = body.identifier
        if not ident:
            prof = None
            owner = await self._owner(body.staff_id)
            prof = (
                await self.db.execute(select(FacultyProfile).where(FacultyProfile.staff_id == owner))
            ).scalar_one_or_none()
            ident = (prof.scopus_id if body.source == "scopus" else prof.orcid) if prof else None
        if not ident:
            raise rule("An identifier (DOI / ORCID iD / Scopus id) is required", "IDENTIFIER_REQUIRED", 422)
        provider = "live" if await self.feature("integrations.scopus_crossref_orcid") else "mock"
        return list(await get_adapter(body.source, provider).works(ident))

    async def preview(self, body: PublicationImport) -> ImportPreview:
        self.require_writer()
        owner = await self._owner(body.staff_id)
        works = await self._fetch(body)
        existing = list(
            (
                await self.db.execute(
                    select(Publication).where(Publication.institution_id == self.inst).order_by(Publication.created_at)
                )
            ).scalars()
        )
        by_doi = {p.doi: p for p in existing if p.doi}
        out = ImportPreview(token=secrets.token_hex(12), source=body.source)
        for i, w in enumerate(works):
            doi = normalise_doi(w.get("doi"))
            hit = by_doi.get(doi) if doi else None
            sim = 1.0 if hit else None
            if hit is None:
                best = max(existing, key=lambda p: _similar(p.title, w["title"]), default=None)
                if best is not None:
                    s = _similar(best.title, w["title"])
                    if s >= 0.85:
                        hit, sim = best, round(s, 3)
            cand = ImportCandidate(
                key=f"w{i}",
                title=str(w["title"])[:500],
                venue=w.get("venue"),
                year=w.get("year"),
                doi=doi,
                indexing=w.get("indexing"),
                impact_factor=w.get("impact_factor"),
                pub_type=w.get("pub_type") or "journal",
                authors=w.get("authors") or [],
                citations=w.get("citations"),
                existing_id=hit.id if hit else None,
                similarity=sim,
            )
            if hit is None:
                out.new.append(cand)
            elif hit.staff_id == owner or any(str(a.get("staff_id")) == str(owner) for a in (hit.authors or [])):
                out.duplicates.append(cand)
            else:
                out.matches.append(cand)
        await self.put_meta(
            "import",
            out.token,
            {
                "staff_id": str(owner),
                "source": body.source,
                "expires": (now_utc() + timedelta(hours=1)).isoformat(),
                "preview": out.model_dump(mode="json"),
            },
        )
        return out

    async def apply(self, body: ImportApply) -> ImportResult:
        self.require_writer()
        m = await self.meta("import", body.token)
        if not m or m.get("expires", "") < now_utc().isoformat():
            raise rule("The import preview expired — preview again", "PREVIEW_EXPIRED", 410)
        owner = uuid.UUID(m["staff_id"])
        if owner != await self.my_staff_id() and not self.cell():
            raise forbidden("Only the importing faculty member applies the preview")
        prev = ImportPreview.model_validate(m["preview"])
        keys = set(body.keys) if body.keys else None
        res = ImportResult(skipped=len(prev.duplicates))
        for c in prev.new:
            if keys is not None and c.key not in keys:
                res.skipped += 1
                continue
            try:
                await self.create(
                    PublicationIn(
                        pub_type=c.pub_type
                        if c.pub_type in ("journal", "conference", "book", "chapter")
                        else "journal",
                        title=c.title,
                        venue=c.venue,
                        year=c.year,
                        doi=c.doi,
                        indexing=c.indexing
                        if c.indexing in ("sci", "scie", "scopus", "wos", "ugc_care", "other")
                        else "none",
                        impact_factor=c.impact_factor,
                        authors=[],
                        citations=c.citations,
                        staff_id=owner,
                    ),
                    source=prev.source,
                )
                res.created += 1
            except Exception:  # noqa: BLE001 - a duplicate created meanwhile is skipped
                res.skipped += 1
        if body.claim_matches:
            for c in prev.matches:
                if keys is not None and c.key not in keys or c.existing_id is None:
                    continue
                try:
                    await self.claim(c.existing_id, ClaimCoauthor())
                    res.claimed += 1
                except Exception:  # noqa: BLE001 - already an author
                    res.skipped += 1
        m["applied"] = res.model_dump()
        await self.put_meta("import", body.token, m)
        return res

    # ---- sync -----------------------------------------------------------------------------------------------------------
    async def sync_citations(self, staff_id: uuid.UUID | None = None) -> int:
        provider = "live" if await self.feature("integrations.scopus_crossref_orcid") else "mock"
        adapter = get_adapter("scopus", provider)
        stmt = select(Publication).where(Publication.institution_id == self.inst, Publication.doi.is_not(None))
        if staff_id is not None:
            stmt = stmt.where(Publication.staff_id == staff_id)
        n = 0
        for p in (await self.db.execute(stmt)).scalars():
            c = await adapter.citations(p.doi)
            if c is not None and c != p.citations:
                p.citations, n = max(int(p.citations or 0), int(c)), n + 1
        await self.db.flush()
        return n

    async def weekly_sync(self) -> int:
        """Opted-in faculty (ORCID or Scopus id on the profile, ``research_sync`` not false) → new works imported."""
        n = 0
        profiles = (
            await self.db.execute(
                select(FacultyProfile).where(
                    FacultyProfile.institution_id == self.inst,
                    or_(FacultyProfile.orcid.is_not(None), FacultyProfile.scopus_id.is_not(None)),
                )
            )
        ).scalars()
        for prof in profiles:
            src, ident = ("orcid", prof.orcid) if prof.orcid else ("scopus", prof.scopus_id)
            try:
                prev = await self.preview(PublicationImport(source=src, identifier=ident, staff_id=prof.staff_id))
                n += (await self.apply(ImportApply(token=prev.token, claim_matches=False))).created
            except Exception:  # noqa: BLE001 - one faculty's failure never stops the sync
                continue
        return n + await self.sync_citations()
