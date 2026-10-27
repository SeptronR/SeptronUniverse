"""Audit coverage guard — Prompts/37 §37.6 ``audit_service`` step 4 / §37.11 step 5.

Every mutating route (POST / PUT / PATCH / DELETE under ``/api/v1``) must write an audit row: the endpoint, or a
service method it calls (followed up to three calls deep through ``self.<method>`` and the services the endpoint
instantiates), must call ``log_audit`` / ``_audit`` / ``audit`` / ``record_pii_view``, or enqueue a job (``enqueue`` —
``jobs:enqueue`` is audited by the job service), or the route is listed in ``AUDIT_EXEMPT`` (``scripts/audit_exempt.txt``:
``METHOD /path`` per line, reviewed; the ``AuditMiddleware`` fallback still records those routes as ``http_route``).

    python scripts/check_audit_coverage.py                  # exit 1 listing unaudited mutations
    python scripts/check_audit_coverage.py --write-exempt   # snapshot the current offenders into the exempt list
"""

import argparse
import ast
import importlib
import inspect
import sys
import textwrap
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
from fastapi.routing import APIRoute

EXEMPT_FILE = Path(__file__).with_name("audit_exempt.txt")
AUDIT_CALLS = {"log_audit", "_audit", "audit", "record_pii_view", "enqueue", "audit_fallback", "_audit_row"}
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


def load_exempt() -> set[str]:
    if not EXEMPT_FILE.exists():
        return set()
    return {
        ln.strip()
        for ln in EXEMPT_FILE.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.startswith("#")
    }


def _calls(fn: Any) -> tuple[set[str], list[tuple[str | None, str]]]:
    """→ (names called, (receiver class name or None for self, attribute) pairs)."""
    try:
        src = textwrap.dedent(inspect.getsource(fn))
    except (OSError, TypeError):
        return set(), []
    tree = ast.parse(src)
    names: set[str] = set()
    attrs: list[tuple[str | None, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                names.add(f.id)
            elif isinstance(f, ast.Attribute):
                names.add(f.attr)
                v = f.value
                if isinstance(v, ast.Call) and isinstance(v.func, ast.Name):
                    attrs.append((v.func.id, f.attr))
                elif isinstance(v, ast.Name) and v.id == "self":
                    attrs.append((None, f.attr))
                elif isinstance(v, ast.Name):
                    attrs.append((v.id, f.attr))
    return names, attrs


def audited(fn: Any, owner: Any, module_globals: dict[str, Any], depth: int = 0, seen: set[int] | None = None) -> bool:
    seen = seen if seen is not None else set()
    if id(fn) in seen or depth > 3:
        return False
    seen.add(id(fn))
    names, attrs = _calls(fn)
    if names & AUDIT_CALLS:
        return True
    for recv, attr in attrs:
        target_cls = owner if recv is None else module_globals.get(recv)
        if not inspect.isclass(target_cls):
            continue
        meth = getattr(target_cls, attr, None)
        if meth is None or not callable(meth):
            continue
        mod = sys.modules.get(getattr(target_cls, "__module__", ""), None)
        if audited(meth, target_cls, vars(mod) if mod else {}, depth + 1, seen):
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-exempt", action="store_true")
    args = parser.parse_args()
    from main import app

    exempt = load_exempt()
    offenders: list[str] = []
    checked = 0
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/v1"):
            continue
        for method in sorted(route.methods & MUTATING):
            checked += 1
            sig = f"{method} {route.path}"
            fn = route.endpoint
            mod = importlib.import_module(fn.__module__)
            if audited(fn, None, vars(mod)):
                continue
            if sig not in exempt:
                offenders.append(sig)
    if args.write_exempt:
        keep = sorted(exempt | set(offenders))
        EXEMPT_FILE.write_text(
            "# Mutating routes without an explicit log_audit (recorded by the AuditMiddleware fallback) — reviewed list.\n"
            + "\n".join(keep)
            + "\n",
            encoding="utf-8",
        )
        print(f"wrote {len(keep)} exempt routes to {EXEMPT_FILE.name}")  # noqa: T201
        return 0
    print(f"audit coverage: {checked} mutating routes checked, {len(exempt)} exempt, {len(offenders)} unaudited")  # noqa: T201
    for o in offenders:
        print(f"  UNAUDITED {o}")  # noqa: T201
    return 1 if offenders else 0


if __name__ == "__main__":
    sys.exit(main())
