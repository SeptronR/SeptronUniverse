"""Regenerate the PII inventory from ``Database_Schema.sql`` — Prompts/43 §43.2 / §43.6 privacy 3.

python scripts/gen_pii_inventory.py           # writes app/core/pii_inventory.json
python scripts/gen_pii_inventory.py --check   # exit 1 when the committed inventory is stale
"""

import argparse
import json
import sys

from _bootstrap import BACKEND_DIR


def main() -> int:
    from app.core.pii_inventory import INVENTORY_FILE, build_from_schema

    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    sql = (BACKEND_DIR.parent / "Database_Schema.sql").read_text(encoding="utf-8")
    inv = build_from_schema(sql)
    data = json.dumps(inv, indent=1, sort_keys=True) + "\n"
    if args.check:
        ok = INVENTORY_FILE.exists() and INVENTORY_FILE.read_text(encoding="utf-8") == data
        print("pii inventory up to date" if ok else "pii inventory stale — run scripts/gen_pii_inventory.py")  # noqa: T201
        return 0 if ok else 1
    INVENTORY_FILE.write_text(data, encoding="utf-8")
    by: dict[str, int] = {}
    for f in inv:
        by[f["cls"]] = by.get(f["cls"], 0) + 1
    print(f"wrote {INVENTORY_FILE.name}: {len(inv)} fields {by}")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
