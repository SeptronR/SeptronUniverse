"""PII masking guard (CI) — Prompts/43 §43.6 privacy 3 / §43.11 step 13.

Every response schema field whose name classifies as *identifier* or *financial* (``app/core/pii_inventory.py``
rules) must be declared through a ``Masked*`` type, unless reviewed into ``scripts/pii_mask_exempt.txt``.
Also probes the log redaction processor with an Aadhaar-bearing event.

    python scripts/check_pii_masking.py
    python scripts/check_pii_masking.py --write-exempt   # snapshot current offenders (review before committing)
"""

import argparse
import sys

import _bootstrap  # noqa: F401


def main() -> int:
    from app.core.pii_inventory import EXEMPT_FILE, masking_audit

    ap = argparse.ArgumentParser()
    ap.add_argument("--write-exempt", action="store_true")
    args = ap.parse_args()
    result = masking_audit()
    if args.write_exempt:
        lines = sorted({".".join(i["schema_field"].split(".")[-2:]) for i in result["issues"]})
        old = EXEMPT_FILE.read_text(encoding="utf-8").splitlines() if EXEMPT_FILE.exists() else []
        keep = [ln for ln in old if ln.startswith("#")] or [
            "# Response-schema PII fields reviewed as returned unmasked (self views / masked in service) — Phase 43"
        ]
        body = sorted({*(ln for ln in old if ln and not ln.startswith("#")), *lines})
        EXEMPT_FILE.write_text("\n".join(keep + body) + "\n", encoding="utf-8")
        print(f"wrote {len(body)} exempt fields")  # noqa: T201
        return 0
    from app.core.logging import redact_pii

    probe = redact_pii(None, "info", {"event": "probe", "aadhaar": "123412341234", "body": {"pan": "ABCDE1234F"}})
    log_ok = "123412341234" not in str(probe) and "ABCDE1234F" not in str(probe)
    print(f"pii masking: {result['checked']} identifier / financial fields checked, {len(result['issues'])} unmasked")  # noqa: T201
    for i in result["issues"]:
        print(f"  UNMASKED {i['schema_field']} ({i['cls']})")  # noqa: T201
    print(f"log redaction probe: {'OK' if log_ok else 'LEAK'}")  # noqa: T201
    return 0 if result["ok"] and log_ok else 1


if __name__ == "__main__":
    sys.exit(main())
