"""Authz coverage guard — Prompts/00_PREREQUISITE_Project_Setup.md §3.24.

Walks ``app.routes``; every route under ``/api/v1`` must carry ``permission_required`` / ``any_permission_required``
**and** ``feature_required`` (module-level include counts) somewhere in its dependency chain, unless it is listed in
``app/api/v1/public.py:PUBLIC_ROUTES``. Exit 1 listing offenders. Also flags PUBLIC_ROUTES entries that no longer exist.
"""

import sys
from typing import Any

import _bootstrap  # noqa: F401
from fastapi.routing import APIRoute


def walk(dependant: Any, seen: set[int] | None = None) -> list[Any]:
    seen = seen if seen is not None else set()
    calls: list[Any] = []
    for sub in getattr(dependant, "dependencies", []):
        if id(sub) in seen:
            continue
        seen.add(id(sub))
        if sub.call is not None:
            calls.append(sub.call)
        calls.extend(walk(sub, seen))
    return calls


def route_permissions(route: APIRoute) -> list[tuple[str, str]]:
    perms: list[tuple[str, str]] = []
    for call in walk(route.dependant):
        perms.extend(getattr(call, "__permissions__", []) or [])
    return perms


def route_feature(route: APIRoute) -> str | None:
    for call in walk(route.dependant):
        key = getattr(call, "__feature_key__", None)
        if key:
            return str(key)
    return None


def main() -> int:
    from app.api.v1.public import PUBLIC_ROUTES
    from main import app

    offenders: list[str] = []
    seen_public: set[str] = set()
    checked = 0
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/v1"):
            continue
        for method in sorted(route.methods or []):
            if method in {"HEAD", "OPTIONS"}:
                continue
            checked += 1
            sig = f"{method} {route.path}"
            if sig in PUBLIC_ROUTES:
                seen_public.add(sig)
                continue
            problems = []
            if not route_permissions(route):
                problems.append("no permission_required")
            if not route_feature(route):
                problems.append("no feature_required")
            if problems:
                offenders.append(f"{sig}: {', '.join(problems)}")
    stale = sorted(PUBLIC_ROUTES - seen_public)
    print(f"authz coverage: {checked} routes checked, {len(seen_public)} public, {len(offenders)} offenders")
    if offenders:
        print("UNPROTECTED ROUTES (add permission_required + feature_required, or list in PUBLIC_ROUTES):")
        for o in offenders:
            print(f"  - {o}")
    if stale:
        print("STALE PUBLIC_ROUTES entries (route no longer exists):")
        for s in stale:
            print(f"  - {s}")
    if offenders or stale:
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
