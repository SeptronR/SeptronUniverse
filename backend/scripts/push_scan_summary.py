"""Summarise CI security scan reports into ``platform_settings['security.scans']`` — Prompts/43 §43.6 item 5.

    python scripts/push_scan_summary.py --dir scan-reports [--report-base https://ci.example/run/123] [--dry-run]
    python scripts/push_scan_summary.py --dir scan-reports --post-url $SCAN_SUMMARY_URL   # CI: X-Ops-Token from env

Understands: ``pip-audit.json`` (pip-audit -f json), ``npm-audit.json`` (npm audit --json), ``bandit.json``,
``semgrep.json``, ``trivy.json``, ``gitleaks.json``, ``osv.json``. Unknown files are ignored. ``high`` counts
high + critical; the release gate blocks while any tool reports ``high > 0``.
"""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401


def _counts(tool: str, data: Any) -> dict[str, int]:  # noqa: C901, PLR0912 - one parser per tool
    c = {"high": 0, "medium": 0, "low": 0}

    def add(sev: str) -> None:
        s = (sev or "").lower()
        c[
            "high"
            if s in ("high", "critical", "error")
            else "medium"
            if s in ("medium", "moderate", "warning")
            else "low"
        ] += 1

    if tool == "pip-audit":
        for dep in data.get("dependencies", data if isinstance(data, list) else []):
            for _ in dep.get("vulns", []):
                add("high")
    elif tool == "npm-audit":
        for sev, n in (data.get("metadata", {}).get("vulnerabilities", {}) or {}).items():
            if sev != "total" and sev != "info":
                for _ in range(int(n)):
                    add(sev)
    elif tool == "bandit":
        for r in data.get("results", []):
            add(r.get("issue_severity", "low"))
    elif tool == "semgrep":
        for r in data.get("results", []):
            add(r.get("extra", {}).get("severity", "low"))
    elif tool == "trivy":
        for res in data.get("Results", []) or []:
            for v in res.get("Vulnerabilities", []) or []:
                add(v.get("Severity", "low"))
    elif tool == "gitleaks":
        for _ in data if isinstance(data, list) else []:
            add("high")
    elif tool == "osv":
        for res in data.get("results", []):
            for pkg in res.get("packages", []):
                for _ in pkg.get("vulnerabilities", []):
                    add("high")
    return c


async def push(summary: dict[str, Any]) -> None:
    from sqlalchemy import text

    from app.db.session import platform_engine

    async with platform_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO platform_settings (key, value) VALUES ('security.scans', CAST(:v AS jsonb)) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()"
            ),
            {"v": json.dumps(summary)},
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--report-base", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--post-url", default=None, help="POST to /api/v1/internal/security/scans instead of the database")
    args = ap.parse_args()
    summary: dict[str, Any] = {}
    now = datetime.now(UTC).isoformat()
    for f in sorted(Path(args.dir).glob("*.json")):
        tool = f.stem
        try:
            data = json.loads(f.read_text(encoding="utf-8") or "{}")
        except ValueError:
            continue
        summary[tool] = {
            **_counts(tool, data),
            "run_at": now,
            "report_url": f"{args.report_base}/{f.name}" if args.report_base else None,
        }
    print(json.dumps(summary, indent=1))  # noqa: T201
    if not args.dry_run and summary and args.post_url:
        import os

        import httpx

        r = httpx.post(args.post_url, json=summary, headers={"X-Ops-Token": os.environ.get("INTERNAL_OPS_TOKEN", "")}, timeout=30)
        print(f"posted: {r.status_code}")  # noqa: T201
    elif not args.dry_run and summary:
        asyncio.run(push(summary))
    return 1 if any(v["high"] for v in summary.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
