"""Per-institution fee defaults (Prompts/12 §12.2) — synchronous SQL so revision ``0012`` and
``seed_institution_defaults`` (new tenants) share it. Idempotent (``ON CONFLICT DO NOTHING`` / existence checks).

* minimal ``ledger_accounts`` chart: Fees receivable, Cash, Bank, Fee income (+ one child per head type), Refunds,
  Scholarship credits (Phase 23 extends it);
* the IN pack fee-head template (tuition, admission, exam, hostel, mess, transport, library, lab, caution deposit,
  fine, certificate, reval, condonation, convocation, affiliation) with GST flags (mess / transport / certificate
  taxable 5 % / 18 % — applied only when ``fees.gst_invoicing`` is on) mapped to their income ledgers;
* fine defaults: late fee ₹50 / day after 7 grace days capped at ₹5,000; library ₹2 / day;
* discounts ``SIBLING`` (10 %, approval) and ``STAFFWARD`` (25 % tuition, automatic when the feature is on).
"""

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

LEDGER = (
    ("1100", "Fees receivable", "asset", None),
    ("1200", "Cash", "asset", None),
    ("1300", "Bank", "asset", None),
    ("4000", "Fee income", "income", None),
    ("2100", "Refunds payable", "liability", None),
    ("5100", "Scholarship credits", "expense", None),
    ("2200", "Caution deposits", "liability", None),
)
# code, name, head_type, refundable, taxable, gst_rate, ledger code
HEADS: tuple[tuple[str, str, str, bool, bool, float | None, str], ...] = (
    ("TUITION", "Tuition fee", "tuition", False, False, None, "4010"),
    ("ADMISSION", "Admission fee", "admission", False, False, None, "4020"),
    ("EXAM", "Examination fee", "exam", False, False, None, "4030"),
    ("HOSTEL", "Hostel fee", "hostel", False, False, None, "4040"),
    ("MESS", "Mess fee", "mess", False, True, 5.0, "4050"),
    ("TRANSPORT", "Transport fee", "transport", False, True, 5.0, "4060"),
    ("LIBRARY", "Library fee", "library", False, False, None, "4070"),
    ("LAB", "Laboratory fee", "lab", False, False, None, "4080"),
    ("CAUTION", "Caution deposit", "caution_deposit", True, False, None, "2200"),
    ("FINE", "Fines & late fees", "fine", False, False, None, "4090"),
    ("CERT", "Certificate fee", "certificate", False, True, 18.0, "4100"),
    ("REVAL", "Revaluation fee", "reval", False, False, None, "4110"),
    ("CONDONE", "Condonation fee", "condonation", False, False, None, "4120"),
    ("CONVOC", "Convocation fee", "convocation", False, False, None, "4130"),
    ("AFFIL", "Affiliation fee", "affiliation", False, False, None, "4140"),
    ("OTHER", "Other fees", "other", False, False, None, "4190"),
)


def seed_fee_defaults(conn: Connection, institution_id: uuid.UUID | str) -> dict[str, int]:
    iid = str(institution_id)
    out = {"ledger_accounts": 0, "fee_heads": 0, "fine_configurations": 0, "fee_discounts": 0}

    def ledger(code: str, name: str, kind: str, parent: str | None) -> Any:
        res = conn.execute(
            text(
                "INSERT INTO ledger_accounts (institution_id, code, name, account_type, parent_id) "
                "VALUES (CAST(:i AS uuid), :c, :n, :t, (SELECT id FROM ledger_accounts WHERE institution_id = "
                "CAST(:i AS uuid) AND code = :p)) ON CONFLICT (institution_id, code) DO NOTHING"
            ),
            {"i": iid, "c": code, "n": name, "t": kind, "p": parent},
        )
        out["ledger_accounts"] += res.rowcount or 0

    for code, name, kind, parent in LEDGER:
        ledger(code, name, kind, parent)
    for _code, name, _, _, _, _, lcode in HEADS:
        if lcode.startswith("4"):
            ledger(lcode, f"Fee income — {name}", "income", "4000")
    for code, name, head_type, refundable, taxable, gst, lcode in HEADS:
        res = conn.execute(
            text(
                "INSERT INTO fee_heads (institution_id, code, name, head_type, is_refundable, is_taxable, gst_rate, "
                "ledger_account_id) VALUES (CAST(:i AS uuid), :c, :n, :h, :r, :t, :g, (SELECT id FROM ledger_accounts "
                "WHERE institution_id = CAST(:i AS uuid) AND code = :l)) ON CONFLICT (institution_id, code) DO NOTHING"
            ),
            {"i": iid, "c": code, "n": name, "h": head_type, "r": refundable, "t": taxable, "g": gst, "l": lcode},
        )
        out["fee_heads"] += res.rowcount or 0
    for applies_to, calc, amount, grace, cap in (
        ("late_fee", "per_day", 5000, 7, 500000),
        ("library_overdue", "per_day", 200, 0, 50000),
    ):
        exists = conn.execute(
            text("SELECT 1 FROM fine_configurations WHERE institution_id = CAST(:i AS uuid) AND applies_to = :a"),
            {"i": iid, "a": applies_to},
        ).first()
        if exists is None:
            conn.execute(
                text(
                    "INSERT INTO fine_configurations (institution_id, applies_to, calc_type, amount_paise, grace_days, "
                    "max_paise) VALUES (CAST(:i AS uuid), :a, :c, :m, :g, :x)"
                ),
                {"i": iid, "a": applies_to, "c": calc, "m": amount, "g": grace, "x": cap},
            )
            out["fine_configurations"] += 1
    for code, name, value, heads, approval in (
        ("SIBLING", "Sibling concession", 10, ["TUITION"], True),
        ("STAFFWARD", "Staff ward concession", 25, ["TUITION"], False),
    ):
        res = conn.execute(
            text(
                "INSERT INTO fee_discounts (institution_id, code, name, discount_type, value, applies_to_heads, "
                "requires_approval) VALUES (CAST(:i AS uuid), :c, :n, 'percentage', :v, CAST(:h AS jsonb), :a) "
                "ON CONFLICT (institution_id, code) DO NOTHING"
            ),
            {"i": iid, "c": code, "n": name, "v": value, "h": __import__("json").dumps(heads), "a": approval},
        )
        out["fee_discounts"] += res.rowcount or 0
    return out
