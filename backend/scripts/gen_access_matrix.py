"""Route × role access matrix → ``docs/Access_Matrix.csv`` (docs/Roles_and_Permissions.md §3/§5).

Columns: method, path, module, permissions (``module:action|...``), feature, public, then one column per role slug
with ``Y`` (the role template grants every required permission), ``N`` or ``public``. Role templates come from
``app/core/rbac/registry.py:ROLE_TEMPLATES`` once Phase 02 ships it; until then the seeded role slugs in
``Database_Schema.sql`` §36.2 are used with super_admin as the only grant, so the file is complete and deterministic.
"""

import csv
import re
import sys
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
from fastapi.routing import APIRoute

ROLE_SEED_RE = re.compile(r"\(NULL,\s*'[^']+',\s*'([a-z_]+)',\s*(?:TRUE|FALSE)")


def role_templates() -> dict[str, set[str]]:
    try:
        from app.core.rbac.registry import ROLE_TEMPLATES  # type: ignore[import-not-found]

        return {slug: set(perms) for slug, perms in ROLE_TEMPLATES.items()}
    except ImportError:
        sql = _bootstrap.SCHEMA_SQL.read_text(encoding="utf-8")
        slugs = ROLE_SEED_RE.findall(sql)
        templates = {slug: set() for slug in slugs}
        templates["super_admin"] = {"*:*"}
        return templates


def grants(template: set[str], module: str, action: str) -> bool:
    return any(p in template for p in ("*:*", f"{module}:*", f"*:{action}", f"{module}:{action}", f"{module}:manage"))


def main() -> int:
    from check_authz_coverage import route_feature, route_permissions

    from main import app

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else _bootstrap.DOCS_DIR / "Access_Matrix.csv"
    templates = role_templates()
    roles = sorted(templates)
    from app.api.v1.public import PUBLIC_ROUTES

    rows: list[list[Any]] = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/v1"):
            continue
        perms = route_permissions(route)
        feature = route_feature(route) or ""
        module = perms[0][0] if perms else (route.path.split("/")[3] if len(route.path.split("/")) > 3 else "")
        for method in sorted(route.methods or []):
            if method in {"HEAD", "OPTIONS"}:
                continue
            public = f"{method} {route.path}" in PUBLIC_ROUTES
            row: list[Any] = [
                method,
                route.path,
                module,
                "|".join(f"{m}:{a}" for m, a in perms),
                feature,
                "yes" if public else "no",
            ]
            for slug in roles:
                if public:
                    row.append("public")
                elif not perms:
                    row.append("N")
                else:
                    ok = any(grants(templates[slug], m, a) for m, a in perms)
                    row.append("Y" if ok else "N")
            rows.append(row)
    rows.sort(key=lambda r: (r[1], r[0]))
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["method", "path", "module", "permissions", "feature", "public", *roles])
        w.writerows(rows)
    print(f"wrote {out} ({len(rows)} routes x {len(roles)} roles)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
