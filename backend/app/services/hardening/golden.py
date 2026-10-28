"""Golden datasets — Prompts/43 §43.6 ``golden_service``.

Each case in ``scripts/verify/golden/*.json`` (``{"kind", "name", "input", "expected", "version"}``) runs through the
**production calculators** (no re-implementation): results ``compute.sgpa`` / ``cgpa`` / ``grade_for`` /
``relative_bands``, attendance ``pct_of`` / ``band`` / ``sessions_needed`` / ``attended_counted``, library
``compute_fine``, fees ``invoice_service.pct_of`` (discount / GST / late fee composition). Comparison is field by field
with tolerance 0 (numbers compared as decimals rounded to the engine's own precision). ``/_dev/compute/{kind}`` exposes
the same calculators to the verification scripts outside production.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

GOLDEN_DIR = Path(__file__).resolve().parents[3] / "scripts" / "verify" / "golden"


def _dec(v: Any) -> Decimal | None:
    return None if v is None else Decimal(str(v))


def c_sgpa(i: dict[str, Any]) -> dict[str, Any]:
    from app.services.results.compute import sgpa

    rows = [(Decimal(str(c)), _dec(gp), bool(p)) for c, gp, p in i["rows"]]
    return {"sgpa": sgpa(rows, bool(i.get("include_failed", False)))}


def c_cgpa(i: dict[str, Any]) -> dict[str, Any]:
    from app.services.results.compute import cgpa

    attempts = {
        course: [(int(a), int(v), Decimal(str(c)), _dec(gp), bool(p)) for a, v, c, gp, p in rows]
        for course, rows in i["attempts"].items()
    }
    cg, earned = cgpa(attempts, i.get("policy", "latest"), bool(i.get("include_failed", False)))
    return {"cgpa": cg, "credits_earned": earned}


def c_grade(i: dict[str, Any]) -> dict[str, Any]:
    from app.services.results.compute import grade_for

    g, gp, boundary = grade_for(Decimal(str(i["pct"])), i["ranges"])
    return {"grade": g, "points": gp, "boundary": boundary}


def c_relative(i: dict[str, Any]) -> dict[str, Any]:
    from app.services.results.compute import relative_bands

    return {"grades": relative_bands([float(v) for v in i["values"]], i.get("config") or {})}


def c_eligibility(i: dict[str, Any]) -> dict[str, Any]:
    from app.services.attendance.common import attended_counted, band, pct_of, sessions_needed, totals_of

    attended, counted = attended_counted(totals_of(i["counters"]))
    pct = pct_of(attended, counted)
    status = band(pct, float(i["min_pct"]), float(i["floor_pct"]))
    if status == "condonable" and i.get("condoned"):
        status = "eligible_condoned"
    return {"pct": pct, "band": status, "sessions_needed": sessions_needed(attended, counted, float(i["min_pct"]))}


def c_fines(i: dict[str, Any]) -> dict[str, Any]:
    from app.services.library.circulation_service import compute_fine

    cfg = SimpleNamespace(
        **{"grace_days": 0, "calc_type": "per_day", "amount_paise": 0, "slabs": None, "max_paise": None, **i["config"]}
    )
    return {"fine_paise": compute_fine(cfg, int(i["days_overdue"]))}  # type: ignore[arg-type]


def c_fees(i: dict[str, Any]) -> dict[str, Any]:
    from app.services.fees.invoice_service import pct_of

    net = gst = 0
    for h in i["heads"]:
        amount = int(h["amount_paise"])
        amount -= pct_of(amount, h.get("discount_pct", 0))
        net += amount
        gst += pct_of(amount, h.get("gst_pct", 0))
    late = int(i.get("late_days", 0)) * int(i.get("late_fee_per_day_paise", 0))
    late = min(late, int(i["late_fee_cap_paise"])) if i.get("late_fee_cap_paise") else late
    return {"net_paise": net, "gst_paise": gst, "late_fee_paise": late, "total_paise": net + gst + late}


COMPUTE = {
    "sgpa": c_sgpa,
    "cgpa": c_cgpa,
    "grade": c_grade,
    "relative": c_relative,
    "eligibility": c_eligibility,
    "fines": c_fines,
    "fees": c_fees,
}


def _num(v: Any) -> str:
    d = Decimal(str(v)).normalize()
    return format(d, "f") if d != d.to_integral() else str(d.quantize(Decimal(1)))


def _norm(v: Any) -> Any:
    if isinstance(v, Decimal | float | int) and not isinstance(v, bool):
        return _num(v)
    if isinstance(v, str):
        try:
            return _num(v)
        except ArithmeticError:
            return v
    if isinstance(v, list):
        return [_norm(x) for x in v]
    if isinstance(v, dict):
        return {k: _norm(x) for k, x in v.items()}
    return v


def run_case(case: dict[str, Any]) -> dict[str, Any]:
    fn = COMPUTE.get(case["kind"])
    if fn is None:
        return {
            "name": case.get("name"),
            "kind": case["kind"],
            "ok": False,
            "diffs": [{"field": "kind", "error": "unknown"}],
        }
    try:
        actual = fn(case["input"])
    except Exception as e:  # noqa: BLE001 - a broken case is reported, never aborts the run
        return {"name": case.get("name"), "kind": case["kind"], "ok": False, "diffs": [{"field": "*", "error": str(e)}]}
    diffs = [
        {"field": k, "expected": exp, "actual": _norm(actual.get(k))}
        for k, exp in case["expected"].items()
        if _norm(exp) != _norm(actual.get(k))
    ]
    return {
        "name": case.get("name"),
        "kind": case["kind"],
        "version": case.get("version"),
        "ok": not diffs,
        "diffs": diffs,
    }


def load_cases(directory: Path = GOLDEN_DIR) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for f in sorted(directory.glob("*.json")):
        for c in json.loads(f.read_text(encoding="utf-8")):
            cases.append({**c, "file": f.name})
    return cases


def run_all(directory: Path = GOLDEN_DIR) -> dict[str, Any]:
    results = [{**run_case(c), "file": c["file"]} for c in load_cases(directory)]
    return {
        "total": len(results),
        "passed": sum(1 for r in results if r["ok"]),
        "failed": [r for r in results if not r["ok"]],
        "results": results,
    }
