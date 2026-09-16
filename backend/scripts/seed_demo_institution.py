"""Demo institution seeder — Prompts/00_PREREQUISITE_Project_Setup.md §3 tree; RUN_AFTER_PHASE.md §3.

    python scripts/seed_demo_institution.py --type university --only <module>
    python scripts/seed_demo_institution.py --type autonomous --all       # every registered module (Phase 43+)
    python scripts/seed_demo_institution.py --list

Every phase registers a seeder with ``@seeder("<module>", after=["base"])``; ``base`` (Phase 02) creates the demo
institution ``demo-uni``, its colleges, roles and one demo user per role and writes the credentials to
``LOCAL_TEST_CREDENTIALS.md`` (git-ignored). Seeders are idempotent (``get_or_create`` helpers) and run in dependency order.
"""

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import _bootstrap  # noqa: F401
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

INSTITUTION_TYPES = {
    "university": {
        "slug": "demo-uni",
        "name": "Septron Demo University",
        "institution_type": "university",
        "colleges": 3,
    },
    "autonomous": {
        "slug": "demo-auto",
        "name": "Septron Demo Autonomous College",
        "institution_type": "autonomous_college",
        "colleges": 1,
    },
    "affiliated": {
        "slug": "demo-aff",
        "name": "Septron Demo Affiliated College",
        "institution_type": "affiliated_college",
        "colleges": 1,
    },
}


@dataclass
class SeedContext:
    db: AsyncSession
    institution_type: str
    profile: dict[str, Any]
    created: dict[str, int] = field(default_factory=dict)
    credentials: list[tuple[str, str, str]] = field(default_factory=list)  # (role, identifier, password)

    def count(self, entity: str, n: int = 1) -> None:
        self.created[entity] = self.created.get(entity, 0) + n

    async def get_or_create(
        self, model: type, defaults: dict[str, Any] | None = None, **lookup: Any
    ) -> tuple[Any, bool]:
        q = select(model)
        for k, v in lookup.items():
            q = q.where(getattr(model, k) == v)
        obj = (await self.db.execute(q)).scalar_one_or_none()
        if obj is not None:
            return obj, False
        obj = model(**lookup, **(defaults or {}))
        self.db.add(obj)
        await self.db.flush()
        self.count(getattr(model, "__tablename__", model.__name__))
        return obj, True


Seeder = Callable[[SeedContext], Awaitable[None]]
SEEDERS: dict[str, tuple[Seeder, list[str]]] = {}


def seeder(name: str, after: list[str] | None = None) -> Callable[[Seeder], Seeder]:
    def deco(fn: Seeder) -> Seeder:
        SEEDERS[name] = (fn, after or [])
        return fn

    return deco


def resolve_order(selected: list[str]) -> list[str]:
    order: list[str] = []

    def visit(name: str, stack: tuple[str, ...] = ()) -> None:
        if name in order:
            return
        if name not in SEEDERS:
            raise SystemExit(f"unknown module {name!r}; available: {', '.join(sorted(SEEDERS)) or '(none yet)'}")
        if name in stack:
            raise SystemExit(f"seeder dependency cycle: {' -> '.join(stack + (name,))}")
        for dep in SEEDERS[name][1]:
            visit(dep, stack + (name,))
        order.append(name)

    for s in selected:
        visit(s)
    return order


def write_credentials(ctx: SeedContext) -> str | None:
    if not ctx.credentials:
        return None
    path = _bootstrap.REPO_ROOT / "LOCAL_TEST_CREDENTIALS.md"
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    with path.open("a", encoding="utf-8") as f:
        f.write(f"\n## Demo institution `{ctx.profile['slug']}` ({ctx.institution_type}, seeded {stamp})\n\n")
        f.write("| role | identifier | password |\n|---|---|---|\n")
        for role, ident, pwd in ctx.credentials:
            f.write(f"| {role} | {ident} | `{pwd}` |\n")
    return str(path)


async def run(institution_type: str, modules: list[str]) -> int:
    from app.db.session import SessionLocal

    order = resolve_order(modules)
    profile = INSTITUTION_TYPES[institution_type]
    async with SessionLocal() as db:
        ctx = SeedContext(db=db, institution_type=institution_type, profile=profile)
        for name in order:
            fn, _ = SEEDERS[name]
            print(f"-> seeding {name}")
            await fn(ctx)
            await db.commit()
    summary = ", ".join(f"{k}={v}" for k, v in sorted(ctx.created.items())) or "nothing new (already seeded)"
    print(f"done ({institution_type}): {summary}")
    creds = write_credentials(ctx)
    if creds:
        print(f"credentials appended to {creds}")
    return 0


def load_phase_seeders() -> None:
    """Import the per-module seeder registrations (``scripts/seeders/<module>.py``) added by the phases."""
    import importlib
    import pkgutil

    # seeders import ``from seed_demo_institution import seeder``: alias this module (running as __main__) so their
    # registrations land in the same SEEDERS dict instead of a second copy of the module
    sys.modules.setdefault("seed_demo_institution", sys.modules[__name__])
    pkg_dir = _bootstrap.BACKEND_DIR / "scripts" / "seeders"
    if not pkg_dir.exists():
        return
    for mod in pkgutil.iter_modules([str(pkg_dir)]):
        importlib.import_module(f"seeders.{mod.name}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--type", choices=sorted(INSTITUTION_TYPES), default="university")
    ap.add_argument("--only", action="append", help="module seeder to run (repeatable); dependencies run first")
    ap.add_argument("--all", action="store_true", help="run every registered seeder")
    ap.add_argument("--list", action="store_true", help="list registered seeders")
    args = ap.parse_args()

    load_phase_seeders()
    if args.list:
        for name, (_, deps) in sorted(SEEDERS.items()):
            print(f"{name:20s} after: {', '.join(deps) or '-'}")
        if not SEEDERS:
            print("(no seeders registered yet - Phase 02 adds 'base')")
        return 0
    modules = sorted(SEEDERS) if args.all else (args.only or [])
    if not modules:
        ap.error("pass --only <module> (repeatable), --all, or --list")
    return asyncio.run(run(args.type, modules))


if __name__ == "__main__":
    sys.exit(main())
