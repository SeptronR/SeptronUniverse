"""Statutory payroll calculator — Prompts/06 §06.6 payroll rule 1 (``pf``, ``esi``, ``pt``, ``tds``, ``lwf``).

Pure functions over the pack's ``hr.statutory`` block merged with the institution's ``payroll.*`` settings
(``statutory_overrides`` deep-merged, ``pt_state``, ``tds_regime``, ``pf_wage_ceiling_applies``). Amounts are paise;
statutory amounts round to whole rupees the way the returns are filed (ESI rounds *up*).

The safe formula evaluator (``calc_type = formula``) only accepts numbers, component codes, ``+ - * /``, unary minus,
parentheses and ``min`` / ``max`` / ``round`` — anything else is rejected (422 at save time, 0 at run time).
"""

import ast
import copy
import math
from typing import Any

from app.core.errors import APIError, ErrorCode

ALLOWED_FUNCS = {"min": min, "max": max, "round": round}


def merged_config(pack_statutory: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    cfg = copy.deepcopy(pack_statutory or {})
    for kind, override in (settings.get("statutory_overrides") or {}).items():
        if isinstance(override, dict):
            cfg.setdefault(kind, {}).update(override)
    if settings.get("pt_state"):
        cfg.setdefault("pt", {})["state"] = settings["pt_state"]
    if settings.get("tds_regime"):
        cfg.setdefault("tds", {})["regime"] = settings["tds_regime"]
    if settings.get("pf_wage_ceiling_applies") is not None:
        cfg.setdefault("pf", {})["apply_ceiling"] = bool(settings["pf_wage_ceiling_applies"])
    return cfg


def _rupee(paise: float) -> int:
    return int(round(paise / 100.0)) * 100


def pf(wage_paise: int, cfg: dict[str, Any]) -> dict[str, int]:
    """Employee 12 % and employer 12 % (EPS 8.33 % of the capped wage, EPF the rest) of the PF wage."""
    c = cfg.get("pf") or {}
    if not c or wage_paise <= 0:
        return {"wage": 0, "employee": 0, "employer": 0, "eps": 0, "epf": 0}
    ceiling = int(c.get("wage_ceiling_paise") or 0)
    wage = min(wage_paise, ceiling) if c.get("apply_ceiling", True) and ceiling else wage_paise
    employee = _rupee(wage * float(c.get("employee_pct", 12)) / 100)
    employer = _rupee(wage * float(c.get("employer_pct", 12)) / 100)
    eps_wage = min(wage, ceiling) if ceiling else wage
    eps = min(employer, _rupee(eps_wage * float(c.get("eps_pct", 8.33)) / 100))
    return {"wage": wage, "employee": employee, "employer": employer, "eps": eps, "epf": employer - eps}


def esi(gross_paise: int, cfg: dict[str, Any]) -> dict[str, int]:
    """0.75 % / 3.25 % of gross when the gross is within the threshold (rounded up to the next rupee)."""
    c = cfg.get("esi") or {}
    if not c or gross_paise <= 0 or gross_paise > int(c.get("threshold_paise") or 0):
        return {"employee": 0, "employer": 0, "wage": 0}
    ee = math.ceil(gross_paise * float(c.get("employee_pct", 0.75)) / 100 / 100) * 100
    er = math.ceil(gross_paise * float(c.get("employer_pct", 3.25)) / 100 / 100) * 100
    return {"employee": ee, "employer": er, "wage": gross_paise}


def professional_tax(gross_paise: int, month: int, cfg: dict[str, Any]) -> int:
    c = cfg.get("pt") or {}
    state = c.get("state") or c.get("default_state")
    slabs = (c.get("states") or {}).get(state or "", [])
    amount = 0
    for slab in sorted(slabs, key=lambda s: int(s["min_paise"])):
        if gross_paise >= int(slab["min_paise"]):
            amount = int(slab.get("feb_amount_paise", slab["amount_paise"]) if month == 2 else slab["amount_paise"])
    return amount


def annual_tax(taxable_paise: int, cfg: dict[str, Any]) -> int:
    """Income tax on annual taxable income (after the standard deduction) incl. 87A rebate and cess."""
    c = cfg.get("tds") or {}
    regime = (c.get("regimes") or {}).get(c.get("regime") or c.get("default_regime") or "new")
    if not regime or taxable_paise <= 0:
        return 0
    tax = 0.0
    lower = 0
    for slab in regime["slabs"]:
        upper = slab["upto_paise"]
        top = taxable_paise if upper is None else min(taxable_paise, int(upper))
        if top > lower:
            tax += (top - lower) * float(slab["pct"]) / 100
        if upper is None or taxable_paise <= int(upper):
            break
        lower = int(upper)
    if taxable_paise <= int(regime.get("rebate_limit_paise") or 0):
        tax = 0
    tax *= 1 + float(c.get("cess_pct", 4)) / 100
    return _rupee(tax)


def tds_monthly(monthly_taxable_paise: int, cfg: dict[str, Any], pf_employee_paise: int = 0) -> dict[str, int]:
    """Projected annual tax ÷ 12 (the old regime also deducts employee PF under 80C, capped at ₹1.5 L)."""
    c = cfg.get("tds") or {}
    name = c.get("regime") or c.get("default_regime") or "new"
    regime = (c.get("regimes") or {}).get(name)
    if not regime:
        return {"monthly": 0, "annual_taxable": 0, "annual_tax": 0}
    annual = monthly_taxable_paise * 12 - int(regime.get("standard_deduction_paise") or 0)
    if name == "old":
        annual -= min(pf_employee_paise * 12, 15_000_000)
    annual = max(annual, 0)
    tax = annual_tax(annual, cfg)
    return {"monthly": _rupee(tax / 12), "annual_taxable": annual, "annual_tax": tax}


def lwf(month: int, cfg: dict[str, Any]) -> dict[str, int]:
    c = cfg.get("lwf") or {}
    if not c or month not in (c.get("months") or []):
        return {"employee": 0, "employer": 0}
    return {"employee": int(c.get("employee_paise") or 0), "employer": int(c.get("employer_paise") or 0)}


# ---- safe formula evaluator ---------------------------------------------------------------------------------------
def _check(node: ast.AST, names: set[str]) -> None:
    if isinstance(node, ast.Expression):
        _check(node.body, names)
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add | ast.Sub | ast.Mult | ast.Div):
        _check(node.left, names)
        _check(node.right, names)
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
        _check(node.operand, names)
    elif isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return
    elif isinstance(node, ast.Name):
        if node.id not in names and node.id not in ALLOWED_FUNCS:
            raise ValueError(f"unknown component code {node.id!r}")
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ALLOWED_FUNCS:
        if node.keywords:
            raise ValueError("keyword arguments are not allowed")
        for a in node.args:
            _check(a, names)
    else:
        raise ValueError(f"unsupported expression element {type(node).__name__}")


def validate_formula(expr: str, codes: set[str]) -> None:
    try:
        _check(ast.parse(expr, mode="eval"), codes)
    except (SyntaxError, ValueError) as exc:
        raise APIError(422, ErrorCode.VALIDATION, f"Invalid formula: {exc}", {"field": "formula.expr"}) from exc


def eval_formula(expr: str, values: dict[str, int]) -> int:
    """Evaluate over component amounts in **rupees** (``BASIC * 0.1``) and return paise; errors yield 0."""
    try:
        tree = ast.parse(expr, mode="eval")
        _check(tree, set(values))
        scope: dict[str, Any] = {k: v / 100 for k, v in values.items()}
        scope.update(ALLOWED_FUNCS)
        result = eval(compile(tree, "<formula>", "eval"), {"__builtins__": {}}, scope)  # noqa: S307 - AST-validated
        return int(round(float(result) * 100))
    except Exception:  # noqa: BLE001 - a broken formula contributes nothing rather than failing the whole run
        return 0
