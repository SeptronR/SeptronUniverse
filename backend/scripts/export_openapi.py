"""Export the OpenAPI document to ``backend/openapi.json`` (input for ``npm run gen:api`` and Dart generation).

Deterministic output (sorted keys, 2-space indent, trailing newline) so CI can ``git diff --exit-code`` it
(RUN_AFTER_PHASE.md §8, guards.yml).
"""

import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401


def main() -> int:
    from main import app

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else _bootstrap.BACKEND_DIR / "openapi.json"
    spec = app.openapi()
    out.write_text(json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    paths = len(spec.get("paths", {}))
    print(f"wrote {out} ({paths} paths, {len(spec.get('components', {}).get('schemas', {}))} schemas)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
