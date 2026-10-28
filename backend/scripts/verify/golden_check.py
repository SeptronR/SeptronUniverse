"""Golden datasets through the production calculators — Prompts/43 §43.11 step 5 (in-process, no server needed)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: E402, F401


def main() -> int:
    from app.services.hardening.golden import run_all

    r = run_all()
    print(f"golden: {r['passed']}/{r['total']} cases pass")  # noqa: T201
    for f in r["failed"]:
        print(f"  DIFF {f['file']} · {f['kind']} · {f['name']}: {f['diffs']}")  # noqa: T201
    return 0 if not r["failed"] else 1


if __name__ == "__main__":
    sys.exit(main())
