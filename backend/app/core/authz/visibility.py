"""Row-level visibility: predicate = self ∪ ownership ∪ (scope if module:view_all).

See docs/Authorization_and_Visibility.md §3 and Prompts/00_PREREQUISITE_Project_Setup.md §3.12 (ADR 0004).
Each phase registers its module (``register_module``) and ownership links (``register_link``) in
``app/services/<module>/visibility.py``; the resolver is applied by ``BaseRepository.visible()`` and ``get()``.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, false, or_

from app.utils.response import VisibilityMeta

Predicate = Callable[[Any, type], ColumnElement[bool]]


@dataclass
class OwnershipLink:
    module: str
    name: str
    predicate: Predicate  # predicate(principal, model) -> SQLAlchemy expression


@dataclass
class ModuleVisibility:
    module: str
    model: Any
    self_predicate: Predicate | None = None  # (principal, model) -> expr
    # {"institution": "institution_id", "college": "college_id", "department": "department_id"}
    scope_columns: dict[str, str] | None = None


MODULES: dict[str, ModuleVisibility] = {}
LINKS: dict[str, list[OwnershipLink]] = {}

SCOPE_ORDER = ["self", "own", "department", "faculty", "college", "all"]


def register_module(mv: ModuleVisibility) -> None:
    MODULES[mv.module] = mv


def register_link(link: OwnershipLink) -> None:
    LINKS.setdefault(link.module, []).append(link)


class VisibilityResolver:
    def __init__(self, principal: Any):
        self.p = principal

    def scopes_for(self, module: str) -> list[str]:
        """Scope tab names the principal may see for the module (empty without ``view_all``); institution → all."""
        if not self.p.has(module, "view_all"):
            return []
        names = {"all" if st == "institution" else st for st, _ in self.p.scopes}
        return sorted(names, key=lambda n: SCOPE_ORDER.index(n) if n in SCOPE_ORDER else 99)

    def predicate(self, module: str) -> ColumnElement[bool] | None:
        mv = MODULES[module]
        parts: list[ColumnElement[bool]] = []
        if self.p.is_super_admin:
            return None  # RLS + platform role still apply
        if mv.self_predicate:
            parts.append(mv.self_predicate(self.p, mv.model))
        for link in LINKS.get(module, []):
            parts.append(link.predicate(self.p, mv.model))
        if self.p.has(module, "view_all"):
            for scope_type, scope_id in self.p.scopes:
                col = (mv.scope_columns or {}).get(scope_type)
                if scope_type == "institution":
                    parts.append(mv.model.institution_id == self.p.institution_id)
                elif col and scope_id is not None:
                    parts.append(getattr(mv.model, col) == scope_id)
        return or_(*parts) if parts else false()

    def meta(self, module: str) -> VisibilityMeta:
        mv = MODULES[module]
        return VisibilityMeta(
            self=bool(mv.self_predicate) or bool(LINKS.get(module)),
            scopes=self.scopes_for(module),
            pii=self.p.has(module, "view_pii"),
        )
