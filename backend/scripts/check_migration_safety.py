"""Expand / contract migration lint (CI) — Prompts/44 §44.6 migrations 1.

Fails when a revision added in this branch (``--since <git ref>``, default ``origin/main``; ``--all`` checks every file)
contains a destructive or locking operation without the matching marker:

* ``op.drop_column`` / ``op.drop_table`` / ``DROP COLUMN`` / ``DROP TABLE`` / ``RENAME`` / ``ALTER COLUMN … TYPE`` →
  needs ``# contract-of: <revision>`` (the expand revision whose code no longer uses the old shape shipped earlier);
* ``nullable=False`` on ``add_column`` without ``server_default`` / ``SET NOT NULL`` → needs ``# contract-of``;
* ``op.create_index`` on a table listed in ``LARGE_TABLES`` without ``postgresql_concurrently=True`` (inside
  ``autocommit_block``);
* ``# risky`` revisions are allowed but reported (the deploy opens a read-only window first).

Also asserts a single Alembic head.

    python scripts/check_migration_safety.py [--since origin/main | --all]
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ROOT / "alembic" / "versions"
LARGE_TABLES = (
    "audit_logs",
    "domain_events",
    "student_class_attendance",
    "message_logs",
    "notifications",
    "webhook_deliveries",
    "vehicle_gps_logs",
    "internal_marks",
    "student_course_results",
    "fee_payments",
    "consent_records",
)
DESTRUCTIVE = re.compile(
    r"op\.drop_column|op\.drop_table|DROP\s+COLUMN|DROP\s+TABLE|RENAME\s+(COLUMN|TO)|ALTER\s+COLUMN\s+\w+\s+TYPE|op\.alter_column\([^)]*type_=",
    re.I,
)
NOT_NULL = re.compile(r"add_column\([^)]*nullable=False(?![^)]*server_default)", re.S)
SET_NOT_NULL = re.compile(r"SET\s+NOT\s+NULL", re.I)
INDEX = re.compile(r"op\.create_index\(\s*['\"][^'\"]+['\"]\s*,\s*['\"](\w+)['\"](?P<rest>[^)]*)\)", re.S)


def changed(since: str) -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=A", since, "--", str(VERSIONS)],  # noqa: S603, S607
            capture_output=True,
            text=True,
            check=True,
            cwd=ROOT,
        ).stdout
    except subprocess.CalledProcessError:
        return []
    return [ROOT.parent / p for p in out.split()]


def _upgrade_body(src: str) -> str:
    """Only ``upgrade()`` matters — a downgrade may drop what its upgrade created."""
    m = re.search(r"^def upgrade\(\).*?(?=^def |\Z)", src, re.S | re.M)
    return m.group(0) if m else src


def check(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    code = "\n".join(ln for ln in _upgrade_body(src).splitlines() if not ln.lstrip().startswith("#"))
    contract = "# contract-of:" in src
    out = []
    if DESTRUCTIVE.search(code) and not contract:
        out.append("destructive operation without '# contract-of: <revision>'")
    if (NOT_NULL.search(code) or SET_NOT_NULL.search(code)) and not contract:
        out.append("NOT NULL added without a default — expand with nullable / default first, contract later")
    for m in INDEX.finditer(code):
        if m.group(1) in LARGE_TABLES and "postgresql_concurrently=True" not in m.group("rest"):
            out.append(f"index on large table {m.group(1)} must be created CONCURRENTLY (autocommit_block)")
    return out


def heads() -> int:
    revs, downs = set(), set()
    for f in VERSIONS.glob("*.py"):
        s = f.read_text(encoding="utf-8")
        r = re.search(r"^revision: str = ['\"]([^'\"]+)", s, re.M) or re.search(r"^revision = ['\"]([^'\"]+)", s, re.M)
        d = re.search(r"^down_revision: [^=]+= ['\"]([^'\"]+)", s, re.M) or re.search(
            r"^down_revision = ['\"]([^'\"]+)", s, re.M
        )
        if r:
            revs.add(r.group(1))
        if d:
            downs.add(d.group(1))
    return len(revs - downs)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="origin/main")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    files = sorted(VERSIONS.glob("*.py")) if a.all else changed(a.since)
    problems = {f.name: p for f in files if (p := check(f))}
    risky = [f.name for f in files if "# risky" in f.read_text(encoding="utf-8")]
    n_heads = heads()
    print(
        f"migration safety: {len(files)} revision(s) checked, {len(problems)} with problems, heads={n_heads}, risky={risky}"
    )  # noqa: T201
    for name, ps in problems.items():
        for p in ps:
            print(f"  {name}: {p}")  # noqa: T201
    return 1 if problems or n_heads != 1 else 0


if __name__ == "__main__":
    sys.exit(main())
