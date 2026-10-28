"""Theme token sync guard — Prompts/42 §42.11 step 7.

``frontend/src/styles/tokens.json`` (web) and ``flutter/assets/theme/tokens.json`` (app) must be byte-identical;
``npm run tokens:export`` copies the web file into the Flutter bundle.
"""

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    web = ROOT / "frontend" / "src" / "styles" / "tokens.json"
    app = ROOT / "flutter" / "assets" / "theme" / "tokens.json"
    if not app.exists():
        print(f"MISSING {app.relative_to(ROOT)} — run `npm run tokens:export`")  # noqa: T201
        return 1
    hw, ha = (hashlib.sha256(p.read_bytes()).hexdigest() for p in (web, app))
    print(f"tokens web={hw[:12]} app={ha[:12]}")  # noqa: T201
    if hw != ha:
        print("tokens out of sync — run `npm run tokens:export`")  # noqa: T201
        return 1
    print("OK")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
