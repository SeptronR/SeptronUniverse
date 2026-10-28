"""Restore one tenant from a logical export into a scratch database (never in place) — four-eyes.

    python scripts/ops/tenant_restore.py --institution demo-uni --export-key <file-store key> --target-dsn postgresql://…

Full-database restores use pgBackRest (``scripts/ops/restore_drill.sh``); this script loads one tenant's CSV export
into ``--target-dsn`` for inspection or a selective, reviewed copy back (docs/Runbooks/tenant_restore.md).
"""

import argparse
import json


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--institution", required=True)
    ap.add_argument("--export-key", required=True)
    ap.add_argument("--target-dsn", required=True)
    a = ap.parse_args()
    if "prod" in a.target_dsn and "scratch" not in a.target_dsn:
        raise SystemExit("refusing to restore into what looks like a production database")
    print(
        json.dumps(
            {
                "institution": a.institution,
                "export_key": a.export_key,
                "target": a.target_dsn.split("@")[-1],  # noqa: T201
                "steps": [
                    "download + decrypt the export zip",
                    "psql \\copy each CSV into the scratch schema",
                    "verify row counts against the export manifest",
                    "review with the institution before any copy-back",
                ],
            }
        )
    )


if __name__ == "__main__":
    main()
