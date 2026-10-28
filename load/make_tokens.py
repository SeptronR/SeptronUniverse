"""Sign in the seeded load-test users and write tokens.json for the k6 scenarios (staging only).

    python load/make_tokens.py --base https://staging-api.example/api/v1 --institution demo-uni --students 500 --staff 50
Reads usernames / passwords from LOCAL_TEST_CREDENTIALS.md (never committed). Tokens are short-lived access tokens.
"""

import argparse
import json
import re
from pathlib import Path

import httpx


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--institution", default="demo-uni")
    ap.add_argument("--students", type=int, default=500)
    ap.add_argument("--staff", type=int, default=50)
    args = ap.parse_args()
    creds = Path(__file__).resolve().parents[1] / "LOCAL_TEST_CREDENTIALS.md"
    rows = re.findall(r"\|\s*([a-z_]+)\s*\|\s*([\w.\-]+)\s*\|\s*`?([^|`\s]+)`?\s*\|", creds.read_text(encoding="utf-8"))
    out: dict[str, list[str] | str] = {"students": [], "staff": []}
    with httpx.Client(base_url=args.base, timeout=20) as c:
        for role, user, pwd in rows:
            bucket = "students" if role == "student" else "staff"
            limit = args.students if bucket == "students" else args.staff
            if len(out[bucket]) >= limit:
                continue
            r = c.post("/auth/login", json={"identifier": user, "password": pwd, "institution": args.institution})
            if r.status_code == 200 and r.json().get("data", {}).get("access_token"):
                out[bucket].append(r.json()["data"]["access_token"])  # type: ignore[union-attr]
                if role == "controller_of_examinations":
                    out["coe"] = r.json()["data"]["access_token"]
    Path(__file__).with_name("tokens.json").write_text(json.dumps(out))
    print({k: len(v) if isinstance(v, list) else 1 for k, v in out.items()})


if __name__ == "__main__":
    main()
