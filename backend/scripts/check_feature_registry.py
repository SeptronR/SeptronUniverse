"""Feature-registry guard — Prompts/00_PREREQUISITE_Project_Setup.md §2 tree; docs/Feature_Flags.md §4.

Diffs the code registry (``FEATURE_REGISTRY``) against ``docs/Feature_Flags.md`` and, when reachable, the DB seed
(``platform_features``):

  * every registered key exists in the doc with the same default / tier / core-ness and a compatible ``depends_on``;
  * every ``feature_required(key)`` cited by a route and every ``feature:`` in ``frontend/src/nav.ts`` is registered;
  * ``--strict``: every doc key is registered (switched on by Phase 43/44 when all modules exist);
  * ``--db``: every doc key has a ``platform_features`` row with matching default/tier (needs a database).
"""

import argparse
import asyncio
import re
import sys

import _bootstrap  # noqa: F401
from feature_doc import load_doc_features


def nav_feature_keys() -> set[str]:
    nav = _bootstrap.FRONTEND_DIR / "src" / "nav.ts"
    if not nav.exists():
        return set()
    return set(re.findall(r"feature:\s*['\"]([a-z0-9_.]+)['\"]", nav.read_text(encoding="utf-8")))


def route_feature_keys() -> set[str]:
    from check_authz_coverage import route_feature
    from fastapi.routing import APIRoute

    from main import app

    keys: set[str] = set()
    for route in app.routes:
        if isinstance(route, APIRoute):
            key = route_feature(route)
            if key:
                keys.add(key)
    return keys


async def db_rows() -> dict[str, tuple[bool, str]]:
    from sqlalchemy import text

    from app.db.session import engine

    async with engine.connect() as conn:
        rows = (await conn.execute(text("SELECT key, default_enabled, min_plan_tier FROM platform_features"))).all()
    return {r[0]: (bool(r[1]), r[2]) for r in rows}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strict", action="store_true", help="every documented key must be registered in code")
    ap.add_argument("--db", action="store_true", help="also compare with the platform_features table")
    args = ap.parse_args()

    import app.features  # noqa: F401
    from app.core.features import FEATURE_REGISTRY

    doc = load_doc_features()
    errors: list[str] = []

    for key, f in sorted(FEATURE_REGISTRY.items()):
        d = doc.get(key)
        if d is None:
            errors.append(f"registered but not documented: {key}")
            continue
        if f.default_enabled != d.default_enabled:
            errors.append(
                f"default mismatch: {key} code={'on' if f.default_enabled else 'off'} doc={'on' if d.default_enabled else 'off'}"
            )
        if f.min_plan_tier != d.min_plan_tier:
            errors.append(f"tier mismatch: {key} code={f.min_plan_tier} doc={d.min_plan_tier}")
        if f.is_core != key.startswith("core."):
            errors.append(f"is_core mismatch: {key} (only core.* keys are non-toggleable)")
        if set(f.depends_on) != set(d.depends_on):
            errors.append(f"depends_on mismatch: {key} code={sorted(f.depends_on)} doc={sorted(d.depends_on)}")
        for dep in f.depends_on:
            if dep not in doc:
                errors.append(f"unknown dependency: {key} -> {dep}")

    for key in sorted(route_feature_keys()):
        if key not in FEATURE_REGISTRY:
            errors.append(f"route cites unregistered feature: {key}")
    for key in sorted(nav_feature_keys()):
        if key not in doc:
            errors.append(f"nav.ts cites undocumented feature: {key}")

    if args.strict:
        for key in sorted(set(doc) - set(FEATURE_REGISTRY)):
            errors.append(f"documented but not registered: {key}")

    if args.db:
        rows: dict[str, tuple[bool, str]] | None
        try:
            rows = asyncio.run(db_rows())
        except Exception as exc:  # noqa: BLE001
            errors.append(f"database not reachable for --db comparison: {exc}")
            rows = None
        if rows is not None:
            for key, d in sorted(doc.items()):
                if key not in rows:
                    errors.append(f"doc key missing in platform_features: {key} (run scripts/seed_platform.py)")
                elif rows[key] != (d.default_enabled, d.min_plan_tier):
                    errors.append(f"platform_features row differs from doc: {key} db={rows[key]}")
            for key in sorted(set(rows) - set(doc)):
                errors.append(f"platform_features row not in doc: {key}")

    print(
        f"feature registry: {len(FEATURE_REGISTRY)} registered, {len(doc)} documented, "
        f"{len(set(doc) - set(FEATURE_REGISTRY))} documented-but-not-yet-registered"
    )
    if errors:
        print("FEATURE REGISTRY DRIFT:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
