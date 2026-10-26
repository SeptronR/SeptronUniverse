"""Bibliographic providers (Prompts/30 §30.6 publications 2) — ``BibliographicProvider`` for Crossref (DOI / ORCID
works), Scopus (author id, citations) and ORCID (works). Phase 41 supplies the live adapters; until then the ``mock``
provider of each capability returns deterministic fixtures (the same identifier always yields the same works, so a
verify run can expect "3 matches / 1 duplicate / 4 new" against the demo seed). BibTeX / CSV parsing is local.
"""

import csv
import hashlib
import io
import re
from typing import Any, Protocol

from app.integrations.registry import register_adapter

FIXTURE_VENUES = (
    ("IEEE Access", "scie", 3.9),
    ("Expert Systems with Applications", "sci", 8.5),
    ("Journal of Physics: Conference Series", "scopus", None),
    ("Materials Today: Proceedings", "scopus", None),
    ("International Journal of Engineering Research", "ugc_care", None),
)


class BibliographicProvider(Protocol):
    capability: str
    provider: str

    async def works(self, identifier: str) -> list[dict[str, Any]]: ...

    async def citations(self, doi: str) -> int | None: ...


class MockBibliographic:
    """Fixture works: 8 per author identifier, 1 per DOI; citations derive from the DOI hash."""

    provider = "mock"

    def __init__(self, capability: str, **config: Any):
        self.capability = capability
        self.config = config

    async def health(self) -> tuple[bool, str]:
        return True, "mock"

    def _seed(self, identifier: str) -> int:
        return int(hashlib.sha256(identifier.encode()).hexdigest()[:8], 16)

    def _work(self, identifier: str, i: int) -> dict[str, Any]:
        n = self._seed(f"{identifier}:{i}")
        venue, indexing, impact = FIXTURE_VENUES[n % len(FIXTURE_VENUES)]
        return {
            "title": f"Study {n % 9973} on adaptive learning systems ({self.capability} {i + 1})",
            "venue": venue,
            "year": 2018 + n % 8,
            "doi": f"10.5555/mock.{n % 1_000_000:06d}",
            "indexing": indexing,
            "impact_factor": impact,
            "pub_type": "journal",
            "authors": [{"name": "A. Author"}, {"name": "B. Author"}],
            "citations": n % 60,
        }

    async def works(self, identifier: str) -> list[dict[str, Any]]:
        if identifier.startswith("10."):
            return [self._work(identifier, 0) | {"doi": identifier.lower()}]
        return [self._work(identifier, i) for i in range(8)]

    async def citations(self, doi: str) -> int | None:
        return self._seed(doi) % 80


for _cap in ("crossref", "scopus", "orcid"):
    register_adapter(_cap, "mock")((lambda cap: (lambda **cfg: MockBibliographic(cap, **cfg)))(_cap))


_BIB_ENTRY = re.compile(r"@(\w+)\s*\{\s*[^,]*,(.*?)\n\}", re.S)
_BIB_FIELD = re.compile(r"(\w+)\s*=\s*[{\"](.*?)[}\"]\s*,?\s*$", re.M)


def parse_bibtex(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for kind, body in _BIB_ENTRY.findall(text or ""):
        f = {k.lower(): v.strip() for k, v in _BIB_FIELD.findall(body)}
        if not f.get("title"):
            continue
        year = f.get("year", "")
        out.append(
            {
                "title": f["title"][:500],
                "venue": (f.get("journal") or f.get("booktitle") or f.get("publisher") or "")[:300] or None,
                "year": int(year) if year.isdigit() else None,
                "doi": f.get("doi"),
                "pub_type": {"inproceedings": "conference", "book": "book", "incollection": "chapter"}.get(
                    kind.lower(), "journal"
                ),
                "authors": [{"name": a.strip()} for a in f.get("author", "").split(" and ") if a.strip()],
                "indexing": None,
            }
        )
    return out


def parse_csv(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in csv.DictReader(io.StringIO(text or "")):
        r = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        if not r.get("title"):
            continue
        out.append(
            {
                "title": r["title"][:500],
                "venue": r.get("venue") or r.get("journal") or None,
                "year": int(r["year"]) if r.get("year", "").isdigit() else None,
                "doi": r.get("doi") or None,
                "pub_type": r.get("pub_type") or "journal",
                "indexing": r.get("indexing") or None,
                "impact_factor": float(r["impact_factor"]) if r.get("impact_factor") else None,
                "authors": [{"name": a.strip()} for a in (r.get("authors") or "").split(";") if a.strip()],
            }
        )
    return out
