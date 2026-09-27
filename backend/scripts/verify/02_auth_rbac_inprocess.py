"""In-process API verification for Phase 02 — the Redis-less counterpart of ``02_auth_rbac.ps1``.

    python scripts/verify/02_auth_rbac_inprocess.py

Drives the ASGI app through ``httpx.ASGITransport`` (no uvicorn, no lifespan) against the local PostgreSQL, with
``fakeredis`` standing in for Redis and Celery's broker switched to ``memory://``. It walks the sixteen checks of
Prompts/02 §02.11 — login/lockout/refresh-rotation/MFA/sessions, ``/auth/me`` per role, roles and the permission
matrix, scoped assignments, feature toggles with dependency rules, the institution switch, time-boxed accounts,
impersonation, PII masking, seat limits and ``/install`` — the only step it cannot prove without a worker is that the
``feature_flag.changed`` consumer drops the cache in *another* process (the API's own invalidation is asserted).

Pre-requisites (RUN_AFTER_PHASE.md §2-3):
    alembic upgrade head
    python scripts/seed_platform.py
    python scripts/seed_demo_institution.py --type university --only base
"""

import asyncio
import re
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyotp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # scripts/ holds _bootstrap
import _bootstrap  # noqa: E402,F401

CHECKS = 0
CREDENTIALS = _bootstrap.REPO_ROOT / "LOCAL_TEST_CREDENTIALS.md"


def check(cond: Any, msg: str) -> None:
    global CHECKS
    if not cond:
        raise SystemExit(f"ASSERT FAILED: {msg}")
    CHECKS += 1
    print(f"  ok: {msg}")


def password_of(role: str) -> str:
    """Read a demo password from LOCAL_TEST_CREDENTIALS.md (``| role | identifier | password |``)."""
    if not CREDENTIALS.exists():
        raise SystemExit("LOCAL_TEST_CREDENTIALS.md not found - run scripts/seed_demo_institution.py --only base")
    rows = [
        line for line in CREDENTIALS.read_text(encoding="utf-8").splitlines() if re.match(rf"^\|\s*{role}\s*\|", line)
    ]
    if not rows:
        raise SystemExit(f"no credentials for role {role!r} in LOCAL_TEST_CREDENTIALS.md")
    return rows[-1].split("|")[3].strip().strip("`")


def install_fake_redis() -> Any:
    import fakeredis
    import fakeredis.aioredis

    fake = fakeredis.aioredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)
    import app.core.authz.dependencies as dependencies
    import app.core.features as features
    import app.core.idempotency as idempotency
    import app.core.rate_limit as rate_limit
    import app.core.ws as ws
    import app.db.session as session
    import app.services.auth_service as auth_service

    for mod in (session, features, idempotency, rate_limit, ws, dependencies, auth_service):
        mod.redis_client = fake  # type: ignore[attr-defined]
    import main as main_module

    main_module.redis_client = fake  # type: ignore[attr-defined]
    return fake


async def run() -> int:  # noqa: C901 - one linear walk through §02.11
    fake = install_fake_redis()
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text

    from app.core.rbac.registry import PERMISSIONS
    from app.db.session import PlatformSessionLocal
    from app.tasks.celery_app import celery
    from main import app

    celery.conf.broker_url = "memory://"
    celery.conf.result_backend = "cache+memory://"

    async def login(identifier: str, password: str, **extra: Any) -> Any:
        return await client.post("/api/v1/auth/login", json={"identifier": identifier, "password": password, **extra})

    def bearer(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    # base_url must be a PLATFORM_HOST: any other host is read as a tenant sub-domain by InstitutionContextMiddleware
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
        print("0. reset the fixtures of a previous run")
        async with PlatformSessionLocal() as db:
            await db.execute(
                text(
                    "DELETE FROM mfa_secrets WHERE user_id IN (SELECT id FROM users WHERE username IN ('coe','superadmin'))"
                )
            )
            await db.execute(text("UPDATE users SET mfa_enabled = FALSE WHERE username IN ('coe','superadmin')"))
            probes = "SELECT id FROM users WHERE username IN ('verify.temp','support.verify')"
            await db.execute(
                text(
                    f"DELETE FROM impersonation_logs WHERE impersonator_id IN ({probes}) OR target_user_id IN ({probes})"
                )
            )
            await db.execute(text(f"DELETE FROM audit_logs WHERE user_id IN ({probes})"))
            await db.execute(text("DELETE FROM users WHERE username IN ('verify.temp','support.verify')"))
            await db.execute(text("DELETE FROM roles WHERE slug IN ('imp_probe','nope_role')"))
            await db.execute(
                text(
                    "UPDATE subscription_plans SET student_limit = 200000, staff_limit = 20000 WHERE code = 'university'"
                )
            )
            await db.execute(
                text("UPDATE users SET valid_to = NOW() + INTERVAL '7 days' WHERE username = 'auditor.tmp'")
            )
            # step 18 changes student.1's password (and the history refuses to set the old one back)
            from app.core.security import hash_password

            await db.execute(
                text(
                    "UPDATE users SET password_hash = :h, must_change_password = FALSE, "
                    "preferences = COALESCE(preferences, '{}'::jsonb) - 'password_history' WHERE username = 'student.1'"
                ),
                {"h": hash_password(password_of("student"))},
            )
            touched_keys = "feature_key LIKE 'hostel.%' OR feature_key IN ('comms.whatsapp','security.sso','fees.core')"
            await db.execute(text(f"DELETE FROM institution_feature_flags WHERE {touched_keys}"))
            await db.execute(text(f"DELETE FROM feature_flag_changes WHERE {touched_keys}"))
            await db.commit()
        check(True, "MFA enrolments, probe users/roles, feature flags, passwords and plan limits reset")

        print("0b. seed state")
        async with PlatformSessionLocal() as db:
            perms = (await db.execute(text("SELECT count(*) FROM permissions"))).scalar_one()
            templates = (await db.execute(text("SELECT count(*) FROM roles WHERE institution_id IS NULL"))).scalar_one()
            inst_id = (await db.execute(text("SELECT id FROM institutions WHERE slug = 'demo-uni'"))).scalar_one()
            inst_roles = (
                await db.execute(text("SELECT count(*) FROM roles WHERE institution_id = :i"), {"i": inst_id})
            ).scalar_one()
        check(perms == len(PERMISSIONS) == 916, f"permission catalogue seeded ({perms} = registry)")
        check(templates == 51, f"{templates} platform role templates")
        check(inst_roles == 49, f"demo institution holds {inst_roles} roles (51 templates minus the 2 platform roles)")

        print("1. student login")
        r = await login("student.1", password_of("student"))
        body = r.json()
        check(r.status_code == 200 and body["data"]["access_token"], "POST /auth/login -> 200 with access_token")
        student = body["data"]["access_token"]
        check("students:self" in body["data"]["permissions"], "permissions contain students:self")
        check("core.auth" in body["data"]["features"], "features contain core.auth")
        cookie = r.headers.get("set-cookie", "")
        check(
            "refresh_token=" in cookie
            and "HttpOnly" in cookie
            and "SameSite=strict" in cookie.replace("Strict", "strict"),
            "refresh_token cookie is HttpOnly + SameSite=Strict",
        )
        check(body["data"]["user"]["role_slugs"] == ["student"], "role_slugs = [student]")
        check(body["data"]["institution"]["slug"] == "demo-uni", "login resolved the institution")

        print("2. lockout after 5 failures")
        for i in range(5):
            r = await login("student.1", "WrongPassword!1")
            check(r.status_code == 401, f"wrong password attempt {i + 1} -> 401")
        r = await login("student.1", "WrongPassword!1")
        check(
            r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED",
            "6th attempt inside the window -> 429 RATE_LIMITED",
        )
        r = await login("student.1", password_of("student"))
        check(r.status_code == 429, "the lockout also blocks the correct password")
        await fake.delete(f"login_fail:{inst_id}:student.1")
        r = await login("student.1", password_of("student"))
        check(r.status_code == 200, "after the window is cleared the correct password works again")
        student = r.json()["data"]["access_token"]
        old_cookie = _cookie(r)

        print("3. refresh rotation + reuse detection")
        r = await client.post("/api/v1/auth/refresh", headers={"Cookie": f"refresh_token={old_cookie}"})
        check(r.status_code == 200 and r.json()["data"]["access_token"], "refresh -> new access token")
        new_cookie = _cookie(r)
        check(new_cookie and new_cookie != old_cookie, "the refresh cookie rotated")
        r = await client.post("/api/v1/auth/refresh", headers={"Cookie": f"refresh_token={old_cookie}"})
        check(
            r.status_code == 401 and "reuse" in r.json()["error"]["message"].lower(),
            "replaying the old cookie -> 401 (reuse detected)",
        )
        r = await client.post("/api/v1/auth/refresh", headers={"Cookie": f"refresh_token={new_cookie}"})
        check(r.status_code == 401, "the whole family was revoked: the new cookie is dead too")

        print("4. MFA for a privileged role (coe)")
        coe_password = password_of("controller_of_examinations")
        r = await login("coe", coe_password)
        err = r.json()["error"]
        check(
            r.status_code == 403 and err["code"] == "MFA_REQUIRED" and err["details"]["mfa_setup_required"] is True,
            "coe without enrolment -> 403 MFA_REQUIRED + mfa_setup_required",
        )
        setup_token = err["details"]["mfa_setup_token"]
        r = await client.post("/api/v1/auth/mfa/setup", headers=bearer(setup_token))
        setup = r.json()["data"]
        check(
            r.status_code == 200 and setup["secret"] and setup["qr_png_base64"],
            "mfa/setup -> secret + QR (limited token)",
        )
        totp = pyotp.TOTP(setup["secret"])
        r = await client.post("/api/v1/auth/mfa/confirm", json={"code": totp.now()}, headers=bearer(setup_token))
        confirm = r.json()["data"]
        check(r.status_code == 200 and len(confirm["recovery_codes"]) == 10, "mfa/confirm -> 10 recovery codes")
        check(confirm["access_token"], "confirming with the limited token opens a session")
        r = await login("coe", coe_password)
        check(
            r.status_code == 403 and r.json()["error"]["code"] == "MFA_REQUIRED", "enrolled: login still needs a code"
        )
        r = await login("coe", coe_password, mfa_code="000000")
        check(r.status_code == 401, "wrong code -> 401")
        r = await login("coe", coe_password, mfa_code=totp.now())
        check(r.status_code == 200 and r.json()["data"]["access_token"], "login with a valid TOTP code -> 200")
        r = await login("coe", coe_password, mfa_code=confirm["recovery_codes"][0])
        check(r.status_code == 200, "a recovery code also works")
        r = await login("coe", coe_password, mfa_code=confirm["recovery_codes"][0])
        check(r.status_code == 401, "recovery codes are single-use")

        print("5. /auth/me as accountant")
        r = await login("accountant", password_of("accountant"))
        accountant = r.json()["data"]["access_token"]
        r = await client.get("/api/v1/auth/me", headers=bearer(accountant))
        me = r.json()["data"]
        perms = set(me["permissions"])
        for needed in ("hr:view_all", "leaves:view_all", "leaves:self", "attendance:staff_view_all", "payroll:manage"):
            check(needed in perms, f"accountant holds {needed}")
        check([s["scope_type"] for s in me["scopes"]] == ["institution"], "accountant scope = [institution]")
        check(me["visibility_defaults"]["users"]["scopes"] == [], "accountant has no users:view_all scope tab")

        print("6. roles list")
        r = await client.get("/api/v1/roles", headers=bearer(student))
        check(
            r.status_code == 403 and r.json()["error"]["code"] == "PERMISSION_DENIED",
            "GET /roles as student -> 403 PERMISSION_DENIED",
        )
        r = await login("inst.admin", password_of("institution_admin"))
        admin = r.json()["data"]["access_token"]
        r = await client.get("/api/v1/roles?page_size=200", headers=bearer(admin))
        check(
            r.status_code == 200 and r.json()["meta"]["pagination"]["total"] == 49,
            "inst.admin sees the 49 institution roles",
        )

        print("7. permission matrix")
        roles = {row["slug"]: row for row in r.json()["data"]}
        accountant_role = roles["accountant"]["id"]
        r = await client.get(f"/api/v1/roles/{accountant_role}/permissions", headers=bearer(admin))
        matrix = r.json()["data"]
        check(
            r.status_code == 200 and any(m["module"] == "leaves" for m in matrix["modules"]), "matrix has module rows"
        )
        payload = {"modules": [{"module": "leaves", "actions": [{"action": "view_all", "granted": False}]}]}
        r = await client.put(f"/api/v1/roles/{accountant_role}/permissions", json=payload, headers=bearer(admin))
        check(r.status_code == 200, "PUT matrix removing leaves:view_all -> 200")
        r = await login("accountant", password_of("accountant"))
        check(
            "leaves:view_all" not in r.json()["data"]["permissions"],
            "after re-login the accountant lost leaves:view_all",
        )
        payload["modules"][0]["actions"][0]["granted"] = True
        r = await client.put(f"/api/v1/roles/{accountant_role}/permissions", json=payload, headers=bearer(admin))
        r = await login("accountant", password_of("accountant"))
        accountant = r.json()["data"]["access_token"]
        check("leaves:view_all" in r.json()["data"]["permissions"], "restoring the cell brings it back")
        async with PlatformSessionLocal() as db:
            audited = (
                await db.execute(text("SELECT count(*) FROM audit_logs WHERE module='roles' AND action='permissions'"))
            ).scalar_one()
        check(audited >= 2, f"matrix changes are audited ({audited} rows)")

        print("8. scoped assignment")
        async with PlatformSessionLocal() as db:
            faculty_user = (
                await db.execute(
                    text("SELECT id FROM users WHERE username='faculty.1' AND institution_id=:i"), {"i": inst_id}
                )
            ).scalar_one()
            cse = (
                await db.execute(
                    text("SELECT id FROM departments WHERE code='CSE' AND institution_id=:i"), {"i": inst_id}
                )
            ).scalar_one()
            other_dept = uuid.uuid4()
        hod_role = roles["hod"]["id"]
        r = await client.post(
            f"/api/v1/users/{faculty_user}/roles",
            json={"role_id": hod_role, "scope_type": "department", "scope_id": str(cse)},
            headers=bearer(admin),
        )
        check(r.status_code == 201 and r.json()["data"]["scope_label"], "assign hod @department CSE -> 201 with label")
        assignment_id = r.json()["data"]["id"]
        r = await login("faculty.1", password_of("faculty"))
        scopes = {(s["scope_type"], s["scope_id"]) for s in r.json()["data"]["scopes"]}
        check(("department", str(cse)) in scopes, "/auth/me shows the department scope")
        r = await client.post(
            f"/api/v1/users/{faculty_user}/roles",
            json={"role_id": hod_role, "scope_type": "department", "scope_id": str(other_dept)},
            headers=bearer(admin),
        )
        check(
            r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION",
            "a department of another institution -> 422 VALIDATION",
        )
        r = await client.post(
            f"/api/v1/users/{faculty_user}/roles",
            json={"role_id": roles["dean"]["id"], "scope_type": "institution"},
            headers=bearer(admin),
        )
        check(r.status_code == 422, "dean must be faculty-scoped -> 422")
        r = await client.delete(f"/api/v1/users/{faculty_user}/roles/{assignment_id}", headers=bearer(admin))
        check(r.status_code == 200, "revoking the assignment -> 200")

        print("9. feature toggles (super admin — MFA is mandatory for the platform account)")
        sa_password = password_of("super_admin")
        r = await login("superadmin", sa_password)
        check(
            r.status_code == 403 and r.json()["error"]["code"] == "MFA_REQUIRED",
            "the super admin cannot sign in without MFA",
        )
        sa_setup_token = r.json()["error"]["details"]["mfa_setup_token"]
        r = await client.post("/api/v1/auth/mfa/setup", headers=bearer(sa_setup_token))
        sa_totp = pyotp.TOTP(r.json()["data"]["secret"])
        r = await client.post("/api/v1/auth/mfa/confirm", json={"code": sa_totp.now()}, headers=bearer(sa_setup_token))
        check(r.status_code == 200, "super admin enrolled MFA")
        r = await login("superadmin", sa_password, mfa_code=sa_totp.now())
        check(
            r.status_code == 200 and r.json()["data"]["user"]["is_super_admin"] is True, "super admin login with TOTP"
        )
        sa = r.json()["data"]["access_token"]
        sa_headers = {**bearer(sa), "X-Institution-Id": str(inst_id)}
        r = await client.get(f"/api/v1/institutions/{inst_id}/features", headers=sa_headers)
        flags = {f["key"]: f for f in r.json()["data"]["flags"]}
        check(r.status_code == 200 and len(flags) == 356, f"{len(flags)} feature rows for the tenant")
        check(
            flags["hostel.core"]["effective"] is False and flags["hostel.core"]["source"] == "default",
            "hostel.core is off by default (opt-in module, docs/Feature_Flags.md §2.12)",
        )
        r = await client.get("/api/v1/hostels", headers=bearer(admin))
        check(
            r.status_code == 403 and r.json()["error"]["code"] == "FEATURE_DISABLED",
            "GET /hostels (stub) is gated while the key is off",
        )
        r = await client.put(
            f"/api/v1/institutions/{inst_id}/features/hostel.core",
            json={"enabled": True, "reason": "demo tenant bought hostel management"},
            headers=sa_headers,
        )
        check(r.status_code == 200 and r.json()["data"]["effective"] is True, "super admin enabled hostel.core")
        r = await login("student.1", password_of("student"))
        check("hostel.core" in r.json()["data"]["features"], "the student's features now list hostel.core")
        r = await client.get("/api/v1/hostels", headers=bearer(admin))
        check(r.status_code == 200, f"GET /hostels reachable while the feature is on ({r.status_code} {r.text[:200]})")
        r = await client.put(
            f"/api/v1/institutions/{inst_id}/features/hostel.core",
            json={"enabled": False, "reason": "verify 02"},
            headers=sa_headers,
        )
        check(r.status_code == 200 and r.json()["data"]["effective"] is False, "super admin disabled hostel.core")
        r = await client.get("/api/v1/hostels", headers=bearer(admin))
        check(
            r.status_code == 403 and r.json()["error"]["code"] == "FEATURE_DISABLED",
            "GET /hostels -> 403 FEATURE_DISABLED",
        )
        r = await login("student.1", password_of("student"))
        check("hostel.core" not in r.json()["data"]["features"], "the student's features no longer list hostel.core")
        r = await client.put(
            f"/api/v1/institutions/{inst_id}/features/fees.core", json={"enabled": False}, headers=sa_headers
        )
        err = r.json()["error"]
        check(
            r.status_code == 409
            and err["code"] == "RULE_VIOLATION"
            and "fees.scholarships" in err["details"]["dependants"],
            "disabling fees.core lists its dependants -> 409",
        )
        r = await client.put(
            f"/api/v1/institutions/{inst_id}/features/hostel.gate_qr", json={"enabled": True}, headers=sa_headers
        )
        err = r.json()["error"]
        check(
            r.status_code == 409 and "hostel.leave_outpass" in err["details"]["missing_dependencies"],
            "enabling hostel.gate_qr without its dependencies -> 409 listing them",
        )
        r = await client.put(
            f"/api/v1/institutions/{inst_id}/features/hostel.gate_qr",
            json={"enabled": True, "confirm_dependencies": True},
            headers=sa_headers,
        )
        check(
            r.status_code == 200 and r.json()["data"]["effective"] is True,
            "confirm_dependencies=true enables the chain",
        )
        r = await client.get(f"/api/v1/institutions/{inst_id}/features", headers=sa_headers)
        flags = {f["key"]: f for f in r.json()["data"]["flags"]}
        check(
            flags["hostel.core"]["effective"] and flags["hostel.leave_outpass"]["effective"],
            "the dependencies were enabled transitively",
        )
        changes = r.json()["data"]["changes"]
        check(len(changes) >= 4, f"change log records every toggle ({len(changes)} entries)")

        print("10. institution toggle")
        r = await client.put(
            f"/api/v1/institutions/{inst_id}/features/hostel.mess",
            json={"enabled": True, "confirm_dependencies": True},
            headers=sa_headers,
        )
        check(r.status_code == 200 and r.json()["data"]["effective"] is True, "platform enabled hostel.mess")
        r = await client.put(
            "/api/v1/features/hostel.mess/institution-toggle", json={"enabled": False}, headers=bearer(admin)
        )
        check(r.status_code == 200 and r.json()["data"]["effective"] is False, "inst.admin switched hostel.mess off")
        r = await client.put(
            f"/api/v1/institutions/{inst_id}/features/comms.whatsapp", json={"enabled": False}, headers=sa_headers
        )
        r = await client.put(
            "/api/v1/features/comms.whatsapp/institution-toggle", json={"enabled": True}, headers=bearer(admin)
        )
        check(
            r.status_code == 409 and r.json()["error"]["code"] == "RULE_VIOLATION",
            "enabling what the platform disabled -> 409",
        )
        r = await client.put(
            "/api/v1/features/core.auth/institution-toggle", json={"enabled": False}, headers=bearer(admin)
        )
        check(r.status_code == 409, "core keys cannot be toggled")
        r = await client.put(
            "/api/v1/features/hostel.mess/institution-toggle", json={"enabled": True}, headers=bearer(admin)
        )
        check(r.status_code == 200 and r.json()["data"]["effective"] is True, "and back on")

        print("11. time-boxed account")
        r = await login("auditor.tmp", password_of("auditor"))
        check(r.status_code == 200, "auditor.tmp (valid 7 days) can sign in")
        async with PlatformSessionLocal() as db:
            auditor_id = (
                await db.execute(
                    text("SELECT id FROM users WHERE username='auditor.tmp' AND institution_id=:i"), {"i": inst_id}
                )
            ).scalar_one()
        r = await client.put(
            f"/api/v1/_dev/users/{auditor_id}/validity",
            json={"valid_to": (datetime.now(UTC) - timedelta(days=1)).isoformat()},
            headers=bearer(sa),
        )
        check(r.status_code == 200, "dev route set valid_to in the past")
        r = await login("auditor.tmp", password_of("auditor"))
        check(
            r.status_code == 401
            and r.json()["error"]["code"] == "UNAUTHENTICATED"
            and "expired" in r.json()["error"]["message"].lower(),
            "expired account -> 401 'account expired'",
        )
        r = await client.put(
            f"/api/v1/_dev/users/{auditor_id}/validity",
            json={"valid_to": (datetime.now(UTC) + timedelta(days=7)).isoformat()},
            headers=bearer(sa),
        )

        print("12. impersonation")
        async with PlatformSessionLocal() as db:
            admin_id = (
                await db.execute(
                    text("SELECT id FROM users WHERE username='inst.admin' AND institution_id=:i"), {"i": inst_id}
                )
            ).scalar_one()
        r = await client.post(
            f"/api/v1/users/{admin_id}/impersonate", json={"reason": "phase 02 verification"}, headers=bearer(sa)
        )
        imp = r.json()["data"]
        check(r.status_code == 200 and imp["access_token"], "super admin impersonates inst.admin")
        imp_token = imp["access_token"]
        r = await client.get("/api/v1/auth/me", headers=bearer(imp_token))
        me = r.json()["data"]["user"]
        check(me["username"] == "inst.admin" and me["impersonator_id"], "/auth/me shows the impersonator")
        r = await client.post(
            "/api/v1/roles",
            json={"name": "Impersonation Probe", "slug": "imp_probe", "permissions": ["dashboard:view"]},
            headers=bearer(imp_token),
        )
        check(r.status_code == 201, "a write during impersonation succeeds")
        probe_role = r.json()["data"]["id"]
        async with PlatformSessionLocal() as db:
            impersonated_audit = (
                await db.execute(
                    text("SELECT count(*) FROM audit_logs WHERE impersonator_id IS NOT NULL AND record_id = :r"),
                    {"r": probe_role},
                )
            ).scalar_one()
        check(impersonated_audit == 1, "audit_logs carries impersonator_id")
        r = await client.post("/api/v1/auth/impersonation/stop", headers=bearer(imp_token))
        check(r.status_code == 200, "impersonation stopped")
        r = await client.get("/api/v1/auth/me", headers=bearer(imp_token))
        check(r.status_code == 401, "the impersonation token is blacklisted afterwards")
        await client.delete(f"/api/v1/roles/{probe_role}", headers=bearer(admin))
        # support agent: read-only impersonation
        async with PlatformSessionLocal() as db:
            support_id = uuid.uuid4()
            await db.execute(
                text(
                    "INSERT INTO users (id, institution_id, username, email, password_hash, display_name, user_type, "
                    "is_super_admin, is_verified) VALUES (:id, NULL, 'support.verify', 'support.verify@universe.local', "
                    "'x', 'Support Agent', 'platform', FALSE, TRUE)"
                ),
                {"id": support_id},
            )
            support_role = (
                await db.execute(text("SELECT id FROM roles WHERE institution_id IS NULL AND slug='support_agent'"))
            ).scalar_one()
            await db.execute(
                text("INSERT INTO user_roles (user_id, role_id, scope_type) VALUES (:u, :r, 'institution')"),
                {"u": support_id, "r": support_role},
            )
            await db.commit()
        from app.core.security import create_access_token

        support_token = create_access_token(support_id, None, False)
        r = await client.post(
            f"/api/v1/users/{admin_id}/impersonate", json={"reason": "support check"}, headers=bearer(support_token)
        )
        check(
            r.status_code == 200 and r.json()["data"]["read_only"] is True, "support agent impersonation is read-only"
        )
        ro_token = r.json()["data"]["access_token"]
        r = await client.get("/api/v1/roles", headers=bearer(ro_token))
        check(r.status_code == 200, "read-only impersonation may read")
        r = await client.post("/api/v1/roles", json={"name": "Nope", "slug": "nope_role"}, headers=bearer(ro_token))
        check(
            r.status_code == 403 and r.json()["error"]["details"].get("reason") == "impersonation",
            "a write under read-only impersonation -> 403",
        )

        print("13. PII masking")
        async with PlatformSessionLocal() as db:
            hr_id = (
                await db.execute(text("SELECT id FROM users WHERE username='hr' AND institution_id=:i"), {"i": inst_id})
            ).scalar_one()
        r = await client.get(f"/api/v1/users/{hr_id}", headers=bearer(admin))
        masked = r.json()["data"]
        check(
            r.status_code == 200 and masked["phone"].startswith("*"),
            f"inst.admin sees a masked phone ({masked['phone']})",
        )
        check("*" in masked["email"], f"email masked ({masked['email']})")
        r = await login("hr", password_of("hr_officer"))
        hr_token = r.json()["data"]["access_token"]
        r = await client.get(f"/api/v1/users/{hr_id}", headers=bearer(hr_token))
        full = r.json()["data"]
        check(full["phone"] and not full["phone"].startswith("*"), "hr (hr:view_pii) sees the full phone")

        print("14. entitlements and the seat limit")
        r = await client.get("/api/v1/entitlements", headers=bearer(admin))
        ent = r.json()["data"]
        check(
            r.status_code == 200 and ent["plan"] == "university" and ent["status"] == "active",
            "entitlements -> plan/status",
        )
        check(ent["limits"]["students"] == 200000, "limits come from the plan")
        r = await client.put("/api/v1/_dev/plans/university", json={"student_limit": 1}, headers=bearer(sa))
        check(r.status_code == 200, "dev route lowered the plan's student limit")
        r = await client.post(
            "/api/v1/students", json={"first_name": "Seat", "last_name": "Limit"}, headers=bearer(admin)
        )
        err = r.json()["error"]
        check(
            r.status_code == 403 and err["code"] == "RULE_VIOLATION" and err["details"]["code"] == "SEAT_LIMIT",
            "POST /students beyond the limit -> 403 RULE_VIOLATION / SEAT_LIMIT",
        )
        r = await client.put(
            "/api/v1/_dev/plans/university", json={"student_limit": 200000, "staff_limit": 20000}, headers=bearer(sa)
        )
        r = await client.post("/api/v1/students", json={"first_name": "Seat", "last_name": "Ok"}, headers=bearer(admin))
        check(r.status_code == 201, "with the limit restored the create passes")

        print("15. sessions")
        r = await login("student.1", password_of("student"), platform="web", device_label="Chrome on Windows")
        first = r.json()["data"]["access_token"]
        first_cookie = _cookie(r)
        r = await login("student.1", password_of("student"), platform="android", device_label="Pixel 8")
        second = r.json()["data"]["access_token"]
        r = await client.get("/api/v1/auth/sessions", headers=bearer(second))
        sessions = r.json()["data"]
        check(r.status_code == 200 and len(sessions) >= 2, f"session list shows {len(sessions)} devices")
        check(any(s["current"] for s in sessions), "the current session is flagged")
        check(all(s["ip_masked"] != s.get("ip") for s in sessions), "IPs are masked in the list")
        other = next(s for s in sessions if not s["current"])
        r = await client.delete(f"/api/v1/auth/sessions/{other['id']}", headers=bearer(second))
        check(r.status_code == 200, "revoking the other session -> 200")
        r = await client.post("/api/v1/auth/refresh", headers={"Cookie": f"refresh_token={first_cookie}"})
        check(r.status_code == 401, "the revoked session's refresh cookie -> 401")
        r = await client.get("/api/v1/auth/login-history", headers=bearer(second))
        check(r.status_code == 200 and len(r.json()["data"]) >= 5, "login history lists the attempts")
        r = await client.post("/api/v1/auth/logout", headers=bearer(second))
        check(r.status_code == 200, "logout -> 200")
        r = await client.get("/api/v1/auth/me", headers=bearer(second))
        check(r.status_code == 401, "the access token is blacklisted after logout")
        check(first is not None, "first session token issued")

        print("16. install")
        from app.core.config import settings

        payload = {
            "install_key": settings.INSTALL_SECRET_KEY,
            # an existing super admin is never overwritten (install_service rule 1), so this only matters on a fresh DB
            "super_admin_email": "platform.admin@septronuniverse.in",
            "super_admin_password": "Install@2026Setup",
        }
        r = await client.post("/api/v1/install", json=payload)
        check(r.status_code in (200, 409), f"POST /install -> {r.status_code} (200 first run, 409 afterwards)")
        r = await client.post("/api/v1/install", json=payload)
        check(
            r.status_code == 409 and r.json()["error"]["code"] == "CONFLICT", "a second POST /install -> 409 CONFLICT"
        )
        r = await client.post("/api/v1/install", json={**payload, "install_key": "wrong"})
        check(r.status_code in (403, 409), "a wrong install key never installs")

        print("17. consents, DSRs and the SSO hook")
        r = await client.post(
            "/api/v1/consents", json={"purpose": "communication", "granted": True}, headers=bearer(student)
        )
        check(r.status_code == 201 and r.json()["data"]["granted"] is True, "POST /consents -> 201")
        r = await client.post(
            "/api/v1/consents", json={"purpose": "communication", "granted": False}, headers=bearer(student)
        )
        check(r.status_code == 201, "withdrawing is a new record")
        r = await client.get("/api/v1/consents/me", headers=bearer(student))
        latest = {c["purpose"]: c for c in r.json()["data"]}
        check(latest["communication"]["granted"] is False, "GET /consents/me returns the latest decision")
        r = await client.post(
            "/api/v1/data-subject-requests",
            json={"request_type": "export", "details": "verify"},
            headers=bearer(student),
        )
        check(r.status_code == 201 and r.json()["data"]["status"] == "received", "DSR created with a 30-day SLA")
        r = await client.get("/api/v1/data-subject-requests/me", headers=bearer(student))
        check(r.status_code == 200 and len(r.json()["data"]) >= 1, "GET /data-subject-requests/me")
        sso_hint = "inst.admin@demo-uni.septronuniverse.in"
        r = await client.get(f"/api/v1/auth/sso/mock/start?institution_slug=demo-uni&login_hint={sso_hint}")
        check(
            r.status_code == 403 and r.json()["error"]["code"] == "FEATURE_DISABLED",
            "SSO start while security.sso is off -> 403 FEATURE_DISABLED",
        )
        await client.put(
            f"/api/v1/institutions/{inst_id}/features/security.sso",
            json={"enabled": True, "confirm_dependencies": True},
            headers=sa_headers,
        )
        r = await client.get(f"/api/v1/auth/sso/mock/start?institution_slug=demo-uni&login_hint={sso_hint}")
        start = r.json()["data"]
        check(r.status_code == 200 and start["authorize_url"], "SSO start -> authorize_url + state")
        code = start["authorize_url"].split("code=")[1].split("&")[0]
        r = await client.get(f"/api/v1/auth/sso/mock/callback?code={code}&state={start['state']}")
        check(
            r.status_code == 200 and r.json()["data"]["user"]["username"] == "inst.admin",
            "SSO callback signs the user in",
        )
        r = await client.get(f"/api/v1/auth/sso/mock/callback?code={code}&state=forged.signature")
        check(r.status_code == 400, "a forged state -> 400")
        await client.put(
            f"/api/v1/institutions/{inst_id}/features/security.sso", json={"enabled": False}, headers=sa_headers
        )

        print("18. password flows")
        r = await client.post(
            "/api/v1/auth/forgot-password", json={"identifier": "student.1", "institution_slug": "demo-uni"}
        )
        check(r.status_code == 200, "POST /auth/forgot-password -> 200 (never reveals whether the account exists)")
        r = await client.post("/api/v1/auth/forgot-password", json={"identifier": "nobody@example.com"})
        check(r.status_code == 200, "an unknown identifier answers 200 as well")
        r = await login("student.1", password_of("student"))
        student = r.json()["data"]["access_token"]
        r = await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": password_of("student"), "new_password": "short"},
            headers=bearer(student),
        )
        check(r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION", "a weak password -> 422 VALIDATION")
        new_password = "Student@Verify02"
        r = await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": password_of("student"), "new_password": new_password},
            headers=bearer(student),
        )
        check(r.status_code == 200, "change-password -> 200")
        r = await login("student.1", new_password)
        check(r.status_code == 200, "the new password works")
        student = r.json()["data"]["access_token"]
        r = await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": new_password, "new_password": password_of("student")},
            headers=bearer(student),
        )
        check(r.status_code == 422, "reusing a password from the history -> 422")

        print("19. OTP login")
        r = await client.post(
            "/api/v1/auth/send-otp", json={"phone": _phone("student.1"), "institution_slug": "demo-uni"}
        )
        check(r.status_code == 200 and r.json()["data"]["sent"] is True, "POST /auth/send-otp -> 200")
        code = await fake.get(f"otp:{_phone('student.1').lower()}")
        check(code and len(code) == 6, "the code is stored in Redis for the destination")
        r = await client.post("/api/v1/auth/send-otp", json={"phone": _phone("student.1")})
        check(r.status_code == 429, "a resend inside the cool-down -> 429")
        r = await client.post("/api/v1/auth/verify-otp", json={"phone": _phone("student.1"), "code": "000000"})
        check(r.status_code == 401, "a wrong code -> 401")
        r = await client.post("/api/v1/auth/verify-otp", json={"phone": _phone("student.1"), "code": code})
        check(r.status_code == 200 and r.json()["data"]["access_token"], "verify-otp signs the user in")
        r = await client.post("/api/v1/auth/verify-otp", json={"phone": _phone("student.1"), "code": code})
        check(r.status_code == 401, "the code is single-use")

        print("20. credential sheets + must_change_password gate")
        r = await client.post(
            "/api/v1/users",
            json={
                "username": "verify.temp",
                "display_name": "Verification Temp",
                "user_type": "staff",
                "roles": [{"role_id": roles["receptionist"]["id"]}],
            },
            headers=bearer(admin),
        )
        created = r.json()["data"]
        check(r.status_code == 201 and created["temporary_password"], "POST /users generates a temporary password")
        check(created["must_change_password"] is True, "the new user must change the password")
        r = await login("verify.temp", created["temporary_password"])
        temp_token = r.json()["data"]["access_token"]
        check(r.status_code == 200, "the new user can sign in")
        r = await client.get("/api/v1/roles", headers=bearer(temp_token))
        check(
            r.status_code == 403 and r.json()["error"]["details"].get("reason") == "must_change_password",
            "every non-auth route is blocked until the password is changed",
        )
        r = await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": created["temporary_password"], "new_password": "Verify@Temp2026"},
            headers=bearer(temp_token),
        )
        check(r.status_code == 200, "change-password lifts the gate")
        r = await client.post(
            "/api/v1/users/credential-sheets",
            json={"audience": "staff", "ids": [created["id"]], "batch_label": "verify"},
            headers=bearer(admin),
        )
        sheet = r.json()["data"]
        check(r.status_code == 202 and sheet["job_id"], "POST /users/credential-sheets -> 202 with a job")
        import app.tasks.auth  # noqa: F401  (registers jobs.users.credential_sheet in this process)
        from app.core import jobs as jobs_core

        body_fn = celery.tasks["jobs.users.credential_sheet"].run.__wrapped__
        await jobs_core._run(body_fn, uuid.UUID(sheet["job_id"]))  # noqa: SLF001
        r = await client.get(f"/api/v1/jobs/{sheet['job_id']}", headers=bearer(admin))
        job_row = r.json()["data"]
        check(job_row["status"] == "succeeded" and job_row["result_url"], "the credential-sheet job produced a file")
        async with PlatformSessionLocal() as db:
            file_url = (
                await db.execute(text("SELECT file_url FROM credential_sheets WHERE id = :s"), {"s": sheet["sheet_id"]})
            ).scalar_one()
        check(file_url, "credential_sheets.file_url recorded")
        r = await client.post(f"/api/v1/users/{created['id']}/deactivate", headers=bearer(admin))
        check(r.status_code == 200 and r.json()["data"]["is_active"] is False, "deactivate -> is_active false")
        r = await login("verify.temp", "Verify@Temp2026")
        check(r.status_code == 401, "a deactivated user cannot sign in")

    print("")
    print(f"PHASE 02 auth/rbac (in-process): PASS ({CHECKS} checks)")
    return 0


def _cookie(response: Any) -> str:
    for name, value in response.headers.multi_items():
        if name.lower() == "set-cookie" and value.startswith("refresh_token="):
            return value.split(";")[0].split("=", 1)[1]
    return ""


def _phone(username: str) -> str:
    import hashlib

    digits = int(hashlib.sha256(username.encode()).hexdigest()[:8], 16) % 10**8
    return f"+9190{digits:08d}"


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
