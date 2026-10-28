"""Extract the mobile screen contract from the ``NN.10 Mobile`` sections of ``Prompts/01–41`` — Prompts/42 §42.6.

Writes ``flutter/tool/expected_screens.json``: per phase, the ``features/<folder>`` names, the role shells and the ``/app/...``
routes the section names. ``flutter/tool/check_screen_registry.dart`` checks every folder exists, every role has a shell
and every route is registered.

    python scripts/extract_mobile_screens.py           # regenerate
    python scripts/extract_mobile_screens.py --check   # exit 1 when the committed file is stale
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "flutter" / "tool" / "expected_screens.json"
SECTION = re.compile(r"^## (\d\d)\.10 Mobile\s*$(.*?)(?=^## )", re.M | re.S)
FOLDER = re.compile(r"`?features/([a-z_]+)")
ROUTE = re.compile(r"(/app/[a-z0-9_/-]+)")
SHELL = re.compile(r"([A-Z][A-Za-z/ ]*?) shell")
# shell names used in the prompts → role slugs of ``flutter/lib/core/constants.dart`` ``Roles``
SHELL_ROLES = {
    "accountant": "accountant",
    "admissions officer": "admissions_officer",
    "alumni": "alumni",
    "coe": "controller_of_examinations",
    "coe/exam cell": "controller_of_examinations",
    "driver": "driver",
    "faculty": "faculty",
    "gate staff": "hostel_gate_staff",
    "hod": "hod",
    "hr officer": "hr_officer",
    "institution admin": "institution_admin",
    "iqac": "iqac_coordinator",
    "iqac coordinator": "iqac_coordinator",
    "librarian": "librarian",
    "parent": "parent",
    "placement officer": "placement_officer",
    "registrar": "registrar",
    "scholar": "research_scholar",
    "student": "student",
    "super admin": "super_admin",
    "support": "support_agent",
    "warden": "hostel_warden",
    "examiner": "external_examiner",
    "recruiter": "recruiter",
    "placement": "placement_officer",
    "staff": "faculty",
}


def extract() -> dict[str, dict[str, list[str]]]:
    out: dict[str, dict[str, list[str]]] = {}
    for prompt in sorted((ROOT / "Prompts").glob("[0-4][0-9]_*.md")):
        phase = prompt.name[:2]
        if not ("01" <= phase <= "41"):
            continue
        for m in SECTION.finditer(prompt.read_text(encoding="utf-8")):
            body = m.group(2)
            folders = sorted(set(FOLDER.findall(body)))
            routes = sorted({r.rstrip("/") for r in ROUTE.findall(body)})
            roles = sorted(
                {
                    SHELL_ROLES[n.strip().lower()]
                    for m2 in SHELL.findall(body)
                    for n in m2.split("/")
                    if n.strip().lower() in SHELL_ROLES
                }
            )
            if folders or routes or roles:
                out[phase] = {"features": folders, "roles": roles, "routes": routes}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    data = json.dumps(extract(), indent=2, sort_keys=True) + "\n"
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != data:
            print("expected_screens.json is stale — run scripts/extract_mobile_screens.py")  # noqa: T201
            return 1
        print("expected_screens.json up to date")  # noqa: T201
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(data, encoding="utf-8")
    phases = json.loads(data)
    print(
        f"wrote {OUT.relative_to(ROOT)}: {len(phases)} phases, {sum(len(v['features']) for v in phases.values())} folders, {sum(len(v['routes']) for v in phases.values())} routes, {len({r for v in phases.values() for r in v['roles']})} roles"
    )  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
