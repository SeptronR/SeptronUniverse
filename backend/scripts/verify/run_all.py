"""Verification runner — Prompts/43 §43.6 ``verification_runner_service`` / §43.11 step 1.

Runs the per-phase API scripts (``scripts/verify/NN_*.ps1``, PowerShell 7) in phase order against a running, seeded
API and the database-level suites in-process, and writes a JUnit XML + Markdown report:

    python scripts/verify/run_all.py --suite api_all [--base-url http://localhost:8000/api/v1] [--reset]
    python scripts/verify/run_all.py --suite api_round_2          # phases of one round (ROUNDS below)
    python scripts/verify/run_all.py --suite golden|visibility|immutability|static|smoke
    python scripts/verify/run_all.py --suite all                   # static + golden + visibility + immutability + api_all

``--reset`` re-seeds the demo tenant first (``seed_demo_institution.py --type <type> --all``). A failing phase is
recorded and the runner continues with the next one; the exit code is 1 when anything failed. Never point it at
production (refused when ``APP_ENV=production``). Reports land in ``backend/reports/qa/<suite>-<timestamp>/``.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
sys.path.insert(0, str(BACKEND / "scripts"))
PY = sys.executable

ROUNDS: dict[str, tuple[int, int]] = {
    "0": (0, 4),  # platform, auth, institution, comms / workflow
    "1": (5, 13),  # academics → assessment (student lifecycle)
    "2": (14, 18),  # exams, results, post-result, attainment, degrees
    "3": (19, 27),  # campus: library … student support
    "4": (28, 34),  # engagement: placement … affiliation
    "5": (35, 44),  # platform: analytics … deployment
}
STATIC = [
    "check_schema_drift.py",
    "check_authz_coverage.py",
    "check_feature_registry.py",
    "check_metric_registry.py",
    "check_report_registry.py",
    "check_audit_coverage.py",
    "check_adapter_registry.py",
    "check_pii_masking.py",
    "check_access_matrix.py",
    "check_tokens_sync.py",
]


class Case:
    def __init__(self, suite: str, name: str, ok: bool, seconds: float, output: str, skipped: bool = False):
        self.suite, self.name, self.ok, self.seconds, self.output, self.skipped = (
            suite,
            name,
            ok,
            seconds,
            output,
            skipped,
        )


def _run(cmd: list[str], timeout: int = 1800) -> tuple[bool, str, float]:
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, cwd=BACKEND, capture_output=True, text=True, timeout=timeout, check=False)  # noqa: S603
        return p.returncode == 0, (p.stdout + p.stderr)[-8000:], time.monotonic() - t0
    except subprocess.TimeoutExpired as e:
        return False, f"timeout after {timeout}s\n{(e.stdout or '')[-4000:]}", time.monotonic() - t0


def api_phases(lo: int, hi: int, base_url: str) -> list[Case]:
    pwsh = shutil.which("pwsh")
    out: list[Case] = []
    for script in sorted(HERE.glob("[0-9][0-9]_*.ps1")):
        n = int(script.name[:2])
        if not (lo <= n <= hi):
            continue
        if pwsh is None:
            twin = next(iter(sorted(HERE.glob(f"{script.name[:2]}_*_inprocess.py"))), None)
            if twin is None:
                out.append(Case("api", script.stem, True, 0, "pwsh not installed and no in-process twin", skipped=True))
                continue
            ok, text, secs = _run([PY, str(twin)])
            out.append(Case("api", twin.stem, ok, secs, text))
            continue
        ok, text, secs = _run([pwsh, "-NoProfile", "-File", str(script), "-BaseUrl", base_url])
        out.append(Case("api", script.stem, ok, secs, text))
    return out


def static_checks() -> list[Case]:
    out = []
    for s in STATIC:
        path = BACKEND / "scripts" / s
        if not path.exists():
            out.append(Case("static", s, True, 0, "not present", skipped=True))
            continue
        ok, text, secs = _run([PY, str(path)], timeout=900)
        out.append(Case("static", s, ok, secs, text))
    return out


def smoke(base_url: str) -> list[Case]:
    """Post-deploy smoke: liveness, readiness, public status, OpenAPI — no credentials needed."""
    import urllib.request

    root = base_url.removesuffix("/api/v1")
    out = []
    for name, url in (
        ("health", f"{root}/health"),
        ("ready", f"{root}/ready"),
        ("status", f"{base_url}/public/status"),
        ("openapi", f"{base_url}/openapi.json"),
    ):
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(url, timeout=15) as r:  # noqa: S310 - operator-supplied base URL
                ok, text = r.status == 200, f"{r.status}"
        except Exception as e:  # noqa: BLE001
            ok, text = False, str(e)
        out.append(Case("smoke", name, ok, time.monotonic() - t0, text))
    return out


def load_scenarios(base_url: str) -> list[Case]:
    """Weekly k6 scenarios (``load/*.js``); thresholds inside each script decide the exit code. Needs ``k6`` and the
    ``--load`` fixtures / tokens (staging)."""
    k6 = shutil.which("k6")
    out = []
    for script in sorted((BACKEND.parent / "load").glob("*.js")):
        if script.name == "lib.js":
            continue
        if k6 is None:
            out.append(Case("load", script.stem, True, 0, "k6 not installed", skipped=True))
            continue
        ok, text, secs = _run([k6, "run", "-e", f"BASE={base_url}", str(script)], timeout=3600)
        out.append(Case("load", script.stem, ok, secs, text))
    return out


def inprocess(name: str, script: str) -> list[Case]:
    ok, text, secs = _run([PY, str(HERE / script)], timeout=900)
    return [Case(name, script, ok, secs, text)]


def write_reports(suite: str, cases: list[Case]) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = BACKEND / "reports" / "qa" / f"{suite}-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    failed = [c for c in cases if not c.ok and not c.skipped]
    skipped = [c for c in cases if c.skipped]
    xml = [
        f'<?xml version="1.0" encoding="UTF-8"?>\n<testsuites name="{suite}" tests="{len(cases)}" failures="{len(failed)}">'
    ]
    for group in sorted({c.suite for c in cases}):
        cs = [c for c in cases if c.suite == group]
        xml.append(
            f'  <testsuite name="{group}" tests="{len(cs)}" failures="{sum(1 for c in cs if not c.ok and not c.skipped)}">'
        )
        for c in cs:
            xml.append(f'    <testcase classname="{group}" name="{escape(c.name)}" time="{c.seconds:.1f}">')
            if c.skipped:
                xml.append(f'      <skipped message="{escape(c.output[:200])}"/>')
            elif not c.ok:
                xml.append(f"      <failure><![CDATA[{c.output}]]></failure>")
            xml.append("    </testcase>")
        xml.append("  </testsuite>")
    xml.append("</testsuites>\n")
    (out / "junit.xml").write_text("\n".join(xml), encoding="utf-8")
    md = [
        f"# Verification — {suite}",
        "",
        f"{len(cases)} checks · {len(failed)} failed · {len(skipped)} skipped · {stamp}",
        "",
        "| Suite | Check | Result | Seconds |",
        "|---|---|---|---|",
    ]
    md += [
        f"| {c.suite} | {c.name} | {'skipped' if c.skipped else ('pass' if c.ok else '**FAIL**')} | {c.seconds:.1f} |"
        for c in cases
    ]
    for c in failed:
        md += ["", f"## {c.name}", "```", c.output[-3000:], "```"]
    (out / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (out / "summary.json").write_text(
        json.dumps(
            {
                "suite": suite,
                "total": len(cases),
                "failed": len(failed),
                "skipped": len(skipped),
                "cases": [{"suite": c.suite, "name": c.name, "ok": c.ok, "skipped": c.skipped} for c in cases],
            },
            indent=1,
        )
    )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", default="api_all")
    ap.add_argument("--base-url", default=os.environ.get("VERIFY_BASE_URL", "http://localhost:8000/api/v1"))
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--type", default="university")
    ap.add_argument("--env", default="dev", help="label only (dev | ci | staging); production is always refused")
    ap.add_argument("--report-dir", default=None, help="also copy the report files here (CI artefacts)")
    args = ap.parse_args()
    if os.environ.get("APP_ENV") == "production":
        print("refusing to run verification suites against production")  # noqa: T201
        return 2
    cases: list[Case] = []
    if args.reset:
        ok, text, secs = _run(
            [PY, str(BACKEND / "scripts" / "seed_demo_institution.py"), "--type", args.type, "--all"], timeout=3600
        )
        cases.append(Case("seed", f"reset {args.type}", ok, secs, text))
    suite = args.suite
    if suite == "smoke":
        cases += smoke(args.base_url)
    if suite in ("static", "all"):
        cases += static_checks()
    if suite in ("golden", "all"):
        cases += inprocess("golden", "golden_check.py")
    if suite in ("visibility", "all"):
        cases += inprocess("visibility", "visibility_check.py")
    if suite in ("immutability", "all"):
        cases += inprocess("immutability", "immutability_check.py")
    if suite in ("api_all", "all"):
        cases += api_phases(0, 99, args.base_url)
    elif suite.startswith("api_round_"):
        lo, hi = ROUNDS[suite.removeprefix("api_round_")]
        cases += api_phases(lo, hi, args.base_url)
    if suite == "load":
        cases += load_scenarios(args.base_url)
    report = write_reports(suite, cases)
    if args.report_dir:
        dest = Path(args.report_dir)
        dest.mkdir(parents=True, exist_ok=True)
        for f in report.iterdir():
            shutil.copy(f, dest / f"{suite}-{f.name}")
    failed = [c for c in cases if not c.ok and not c.skipped]
    print(f"{suite}: {len(cases)} checks, {len(failed)} failed → {report.relative_to(BACKEND)}")  # noqa: T201
    for c in failed:
        print(f"  FAIL {c.suite}/{c.name}")  # noqa: T201
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
