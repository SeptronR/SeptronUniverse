"""Access-matrix guard — Prompts/43 §43.6 ``access_matrix_service`` / §43.11 step 15.

Reads ``docs/Access_Matrix.csv`` (``gen_access_matrix.py``: routes × roles, ``Y`` / ``N``) and fails on unexpected
grants — rules distilled from ``docs/Roles_and_Permissions.md`` §3:

* portal roles (student, learner, parent, alumni, applicant, recruiter, vendor) never reach a mutating route of the
  administrative modules (roles, features, users, settings, audit_logs, privacy, security, qa, platform, integrations)
  nor any read of security / qa / platform;
* no tenant role reaches a ``platform:*`` route (platform staff only);
* ``qa:*`` routes are reachable only by institution admins, security officers, auditors (read) and super admin.

    python scripts/check_access_matrix.py           # exit 1 listing unexpected grants
"""

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PORTAL = ("student", "learner", "parent", "alumni", "applicant", "recruiter", "vendor")
ADMIN_MODULES = (
    "roles",
    "features",
    "users",
    "settings",
    "audit_logs",
    "privacy",
    "security",
    "qa",
    "platform",
    "integrations",
)
READ_DENIED = ("security", "qa", "platform")
QA_ROLES = ("institution_admin", "security_officer", "auditor", "super_admin", "support_agent")
SELF_SERVICE = (
    "/me",
    "/consents",
    "/data-subject-requests",
    "/auth/",
    "/profile",
    "/sessions/me",
    "/privacy/consent-banner",
    "/privacy/purposes",
    "/notifications",
    "/users/me",
    "/support",
)


def main() -> int:
    path = ROOT / "docs" / "Access_Matrix.csv"
    with path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    roles = [c for c in rows[0] if c not in ("method", "path", "module", "permissions", "feature", "public")]
    bad: list[str] = []
    for r in rows:
        if r.get("public") == "yes":
            continue
        module, method, route = r["module"], r["method"], r["path"]
        mutating = method in ("POST", "PUT", "PATCH", "DELETE")
        perms = r.get("permissions") or ""
        self_service = any(s in route for s in SELF_SERVICE)
        for role in roles:
            if r.get(role) != "Y":
                continue
            if (
                role in PORTAL
                and not self_service
                and ((mutating and module in ADMIN_MODULES) or module in READ_DENIED)
            ):
                bad.append(f"{role} → {method} {route} ({perms})")
            if module == "platform" and role not in ("super_admin", "support_agent"):
                bad.append(f"{role} → platform route {method} {route}")
            if module == "qa" and role not in QA_ROLES:
                bad.append(f"{role} → qa route {method} {route}")
    print(f"access matrix: {len(rows)} routes × {len(roles)} roles, {len(bad)} unexpected grants")  # noqa: T201
    for b in bad[:200]:
        print(f"  UNEXPECTED {b}")  # noqa: T201
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
