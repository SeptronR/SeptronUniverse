"""Pure result arithmetic — Prompts/15 §15.6 ``result_service`` rule 2 (no database access; unit-testable).

* ``grade_for(pct, ranges)``: absolute grade from ``[{grade, min_pct, max_pct, points, is_fail?}]``; returns the letter,
  the grade point and whether the percentage sits within 0.5 below the next higher band (``GRADE_BOUNDARY``);
* ``relative_bands(values, config)``: z-score bands ``config.bands = [{grade, min_z}]`` (highest first) over a cohort;
* ``sgpa`` / ``cgpa``: Σ(C × GP) / ΣC with the regulation's denominator / attempt policy;
* ``row_hash`` / ``checksum``: sha256 over the canonical fields (the immutability trigger keeps them fixed).
"""

import hashlib
import statistics
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

TWO = Decimal("0.01")
ONE = Decimal("0.1")

DEFAULT_RANGES: list[dict[str, Any]] = [
    {"grade": "O", "min_pct": 90, "max_pct": 100, "points": 10},
    {"grade": "A+", "min_pct": 80, "max_pct": 89.99, "points": 9},
    {"grade": "A", "min_pct": 70, "max_pct": 79.99, "points": 8},
    {"grade": "B+", "min_pct": 60, "max_pct": 69.99, "points": 7},
    {"grade": "B", "min_pct": 55, "max_pct": 59.99, "points": 6},
    {"grade": "C", "min_pct": 50, "max_pct": 54.99, "points": 5},
    {"grade": "P", "min_pct": 45, "max_pct": 49.99, "points": 4},
    {"grade": "F", "min_pct": 0, "max_pct": 44.99, "points": 0, "is_fail": True},
]
DEFAULT_BANDS = [
    {"grade": "O", "min_z": 1.5},
    {"grade": "A+", "min_z": 1.0},
    {"grade": "A", "min_z": 0.5},
    {"grade": "B+", "min_z": 0.0},
    {"grade": "B", "min_z": -0.5},
    {"grade": "C", "min_z": -1.0},
    {"grade": "P", "min_z": -99},
]


def d2(v: Any) -> Decimal:
    return Decimal(str(v)).quantize(TWO, rounding=ROUND_HALF_UP)


def d1(v: Any) -> Decimal:
    return Decimal(str(v)).quantize(ONE, rounding=ROUND_HALF_UP)


def passes(
    ese: Decimal | None,
    total: Decimal,
    cia: Decimal | None,
    cia_max: Decimal,
    ese_max: Decimal,
    total_max: Decimal,
    rules: dict[str, Any],
) -> bool:
    """ESE % ≥ ``ese_pass_min_pct`` and total % ≥ ``total_pass_min_pct`` (and CIA % ≥ ``cia_pass_min_pct`` when set)."""
    ese_ok = ese_max == 0 or (ese or Decimal(0)) / ese_max * 100 >= Decimal(str(rules.get("ese_pass_min_pct", 45)))
    tot_ok = total_max == 0 or total / total_max * 100 >= Decimal(str(rules.get("total_pass_min_pct", 50)))
    cmin = rules.get("cia_pass_min_pct")
    cia_ok = cmin is None or cia_max == 0 or (cia or Decimal(0)) / cia_max * 100 >= Decimal(str(cmin))
    return bool(ese_ok and tot_ok and cia_ok)


def fail_grade(ranges: list[dict[str, Any]]) -> tuple[str, Decimal]:
    for r in ranges:
        if r.get("is_fail"):
            return str(r["grade"]), d1(r.get("points", 0))
    low = min(ranges, key=lambda r: float(r.get("min_pct", 0)))
    return str(low["grade"]), d1(low.get("points", 0))


def grade_for(pct: Decimal, ranges: list[dict[str, Any]]) -> tuple[str, Decimal, bool]:
    ordered = sorted(ranges, key=lambda r: float(r.get("min_pct", 0)), reverse=True)
    p = float(pct)
    for i, r in enumerate(ordered):
        if p >= float(r.get("min_pct", 0)) - 1e-9:
            boundary = i > 0 and float(ordered[i - 1].get("min_pct", 0)) - p <= 0.5
            return str(r["grade"]), d1(r.get("points", 0)), boundary
    g, gp = fail_grade(ranges)
    return g, gp, False


def points_of(grade: str, ranges: list[dict[str, Any]]) -> Decimal | None:
    for r in ranges:
        if str(r.get("grade")) == grade:
            return d1(r.get("points", 0))
    return None


def relative_bands(values: list[float], config: dict[str, Any]) -> list[str]:
    bands = sorted(config.get("bands") or DEFAULT_BANDS, key=lambda b: float(b["min_z"]), reverse=True)
    mean = statistics.fmean(values)
    sd = statistics.pstdev(values) or 1.0
    out = []
    for v in values:
        z = (v - mean) / sd
        out.append(next((str(b["grade"]) for b in bands if z >= float(b["min_z"])), str(bands[-1]["grade"])))
    return out


def sgpa(rows: list[tuple[Decimal, Decimal | None, bool]], include_failed: bool) -> Decimal | None:
    """rows: (credits, grade_point, passed) of the credit-bearing, CGPA-counting results of one term."""
    num = Decimal(0)
    den = Decimal(0)
    for credits, gp, passed in rows:
        if not passed and not include_failed:
            continue
        num += credits * (gp or Decimal(0))
        den += credits
    return d2(num / den) if den > 0 else None


def cgpa(
    attempts: dict[Any, list[tuple[int, int, Decimal, Decimal | None, bool]]], policy: str, include_failed: bool
) -> tuple[Decimal | None, Decimal]:
    """attempts: course → [(attempt_number, version, credits, gp, passed)]; returns (CGPA, credits earned)."""
    num = Decimal(0)
    den = Decimal(0)
    earned = Decimal(0)
    for rows in attempts.values():
        if not rows:
            continue
        if policy == "best":
            pick = max(rows, key=lambda r: (r[3] or Decimal(0), r[0], r[1]))
        else:
            pick = max(rows, key=lambda r: (r[0], r[1]))
        _, _, credits, gp, passed = pick
        if passed:
            earned += credits
        if not passed and not include_failed:
            continue
        num += credits * (gp or Decimal(0))
        den += credits
    return (d2(num / den) if den > 0 else None), earned


def result_class(cg: Decimal | None, rules: list[dict[str, Any]], first_attempt: bool) -> str | None:
    if cg is None:
        return None
    for r in rules:
        if r.get("first_attempt_only") and not first_attempt:
            continue
        if float(cg) >= float(r.get("min_cgpa", 0)):
            return str(r.get("name"))
    return None


def row_hash(fields: dict[str, Any]) -> str:
    canon = "|".join(f"{k}={'' if fields[k] is None else fields[k]}" for k in sorted(fields))
    return hashlib.sha256(canon.encode()).hexdigest()


def checksum(hashes: list[str]) -> str:
    return hashlib.sha256("".join(sorted(hashes)).encode()).hexdigest()
