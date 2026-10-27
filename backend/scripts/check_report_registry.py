"""Report registry guard — Prompts/36 §36.11 step 1 / §36.13.

* every Round 3–4 ``/<module>/reports/{kind}`` route resolves to registered keys (``legacy.LEGACY_ROUTES`` covers the
  route and every kind is a ``REPORT_REGISTRY`` key);
* every register of ``RegisterRequest.register`` has a registered ledger report;
* every report / builder-model permission is a ``module:action`` of the permission catalogue, every feature is
  registered, every ``chart_key`` is a Phase 35 chart, every statutory code has section providers.

    python scripts/check_report_registry.py      # exit 1 listing problems
"""

import re
import sys

import _bootstrap  # noqa: F401


def main() -> int:  # noqa: C901 - one linear guard
    from fastapi.routing import APIRoute

    import app.features  # noqa: F401
    from app.core.charts import CHART_REGISTRY
    from app.core.features import FEATURE_REGISTRY
    from app.core.rbac.registry import PERMISSIONS
    from app.core.reports import MODEL_REGISTRY, REGISTER_KEYS, REPORT_REGISTRY
    from app.enums.reports import REGISTERS, STATUTORY_DEFS
    from app.services.reports.common import ensure_registry
    from app.services.reports.legacy import LEGACY_ROUTES
    from app.services.reports.statutory_sections import SECTIONS
    from main import app as fastapi_app

    ensure_registry()
    perms = set(PERMISSIONS)
    problems: list[str] = []

    routes = {
        r.path.removeprefix("/api/v1")
        for r in fastapi_app.routes
        if isinstance(r, APIRoute) and re.search(r"/reports/\{(kind|report)\}$", r.path)
    }
    for path in sorted(routes):
        if path not in LEGACY_ROUTES:
            problems.append(f"route {path} is not retro-registered (services/reports/legacy.py LEGACY_ROUTES)")
    for path, (module, kinds) in LEGACY_ROUTES.items():
        if path not in routes:
            problems.append(f"LEGACY_ROUTES lists {path} but no such route exists")
        problems += [f"{path}: {module}.{k} not registered" for k in kinds if f"{module}.{k}" not in REPORT_REGISTRY]
    problems += [f"register {r} has no report" for r in REGISTERS if r not in REGISTER_KEYS]
    for d in REPORT_REGISTRY.values():
        problems += [f"report {d.key}: unknown permission {p}" for p in d.permission if p not in perms]
        if d.feature and d.feature not in FEATURE_REGISTRY:
            problems.append(f"report {d.key}: unknown feature {d.feature}")
        if d.chart_key and d.chart_key not in CHART_REGISTRY:
            problems.append(f"report {d.key}: unknown chart {d.chart_key}")
        if d.register and d.layout != "ledger":
            problems.append(f"register report {d.key} must use the ledger layout")
    for m in MODEL_REGISTRY.values():
        problems += [f"model {m.key}: unknown permission {p}" for p in m.permission if p not in perms]
        if m.feature and m.feature not in FEATURE_REGISTRY:
            problems.append(f"model {m.key}: unknown feature {m.feature}")
        if len(m.joins) > 6:
            problems.append(f"model {m.key}: too many joins offered")
    for code, sdef in STATUTORY_DEFS.items():
        problems += [f"statutory {code}: no section provider {s}" for s in sdef["sections"] if s not in SECTIONS]
    catalogue = sum(1 for d in REPORT_REGISTRY.values() if not d.registry_only)
    print(  # noqa: T201
        f"reports: {len(REPORT_REGISTRY)} registered ({catalogue} in the catalogue), registers: {len(REGISTER_KEYS)}, "
        f"builder models: {len(MODEL_REGISTRY)}, legacy routes: {len(LEGACY_ROUTES)}, statutory codes: {len(STATUTORY_DEFS)}"
    )
    for p in problems:
        print(f"  MISSING {p}")  # noqa: T201
    if problems:
        return 1
    print("0 missing")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
