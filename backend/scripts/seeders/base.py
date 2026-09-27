"""``base`` demo seeder (Prompts/02 §02.11) — ``seed_demo_institution.py --type university --only base``.

Creates the demo tenant and everything the Phase 02 verification needs:

* institution (``demo-uni`` / ``demo-auto`` / ``demo-aff``) with a ``university`` subscription (status ``active``);
* colleges A/B (+ C for the university profile), a faculty (Engineering) and departments (CSE, ECE, MBA);
* the institution's role set, cloned from the 51 platform templates with their default grants
  (``RbacService.seed_institution_roles``);
* one demo user per role with a scoped assignment — ``dean.eng`` @faculty, ``hod.cse`` @department,
  ``college.admin.b`` @college B, ``warden.h1``/``gate.h1``/``faculty.1``/``advisor.1``/``student.1``/``parent.1``/
  ``alumni.1`` @self, the office roles @institution — plus the time-boxed ``auditor.tmp`` (7 days) and
  ``examiner.ext`` (30 days);
* passwords are generated per run and appended to ``LOCAL_TEST_CREDENTIALS.md`` (git-ignored). Re-running the seeder
  keeps existing users (idempotent) and only reports what was created;
* ``institution_settings[security.mfa_required_roles]`` narrows MFA to the exam separation-of-duties roles for the
  demo tenant (see the comment below) and ``[security.sso_role_map]`` maps SSO groups for the mock provider.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import select

from app.core.security import hash_password
from app.models.platform import College, Department, Faculty, Institution, InstitutionSetting, Role, User, UserRole
from app.models.saas import InstitutionSubscription, SubscriptionPlan

# (username, display name, role slug, scope, user_type, valid_days)
DEMO_USERS: list[tuple[str, str, str, str, str, int | None]] = [
    ("inst.admin", "Institution Admin", "institution_admin", "institution", "staff", None),
    ("registrar", "Registrar", "registrar", "institution", "staff", None),
    ("coe", "Controller of Examinations", "controller_of_examinations", "institution", "staff", None),
    ("exam.cell", "Exam Cell Officer", "exam_cell", "institution", "staff", None),
    ("decoder", "Exam Decoder", "exam_decoder", "institution", "staff", None),
    ("dean.eng", "Dean (Engineering)", "dean", "faculty:ENG", "staff", None),
    ("hod.cse", "Head of Department (CSE)", "hod", "department:CSE", "staff", None),
    ("faculty.1", "Faculty Member One", "faculty", "self", "staff", None),
    ("advisor.1", "Class Advisor One", "class_advisor", "offering", "staff", None),
    ("accountant", "Accountant", "accountant", "institution", "staff", None),
    ("hr", "HR Officer", "hr_officer", "institution", "staff", None),
    ("admissions", "Admissions Officer", "admissions_officer", "institution", "staff", None),
    ("placement", "Placement Officer", "placement_officer", "institution", "staff", None),
    ("warden.h1", "Hostel Warden (H1)", "hostel_warden", "self", "staff", None),
    ("gate.h1", "Hostel Gate Staff (H1)", "hostel_gate_staff", "self", "staff", None),
    ("librarian", "Librarian", "librarian", "institution", "staff", None),
    ("iqac", "IQAC Coordinator", "iqac_coordinator", "institution", "staff", None),
    ("college.admin.b", "College Admin (B)", "college_admin", "college:B", "staff", None),
    ("student.1", "Student One", "student", "self", "student", None),
    ("parent.1", "Parent One", "parent", "self", "guardian", None),
    ("alumni.1", "Alumnus One", "alumni", "self", "alumni", None),
    ("auditor.tmp", "Visiting Auditor", "auditor", "institution", "external", 7),
    ("examiner.ext", "External Examiner", "external_examiner", "self", "external", 30),
]

COLLEGES: list[tuple[str, str, bool]] = [
    ("A", "College of Engineering", True),
    ("B", "College of Management", False),
    ("C", "College of Sciences", False),
]
DEPARTMENTS: list[tuple[str, str, str, str | None]] = [
    ("CSE", "Computer Science & Engineering", "A", "ENG"),
    ("ECE", "Electronics & Communication Engineering", "A", "ENG"),
    ("MBA", "Business Administration", "B", None),
]


@seeder("base")
async def seed_base(ctx: SeedContext) -> None:
    profile = ctx.profile
    institution, created = await ctx.get_or_create(
        Institution,
        {
            "name": profile["name"],
            "institution_type": profile["institution_type"],
            "regulatory_pack": "IN",
            "timezone": "Asia/Kolkata",
            "locale": "en-IN",
            "currency": "INR",
            "status": "active",
        },
        slug=profile["slug"],
    )
    # RLS: every later INSERT of this session must carry the tenant context
    from app.db.session import bind_tenant, set_tenant

    bind_tenant(ctx.db, institution.id)
    await set_tenant(ctx.db, institution.id)
    await ctx.db.flush()

    colleges: dict[str, College] = {}
    for code, name, is_main in COLLEGES[: int(profile["colleges"])]:
        college, _ = await ctx.get_or_create(
            College,
            {
                "name": name,
                "college_type": "constituent",
                "is_main": is_main,
                "slug": f"{profile['slug']}-{code.lower()}",
            },
            institution_id=institution.id,
            code=code,
        )
        colleges[code] = college

    faculty, _ = await ctx.get_or_create(
        Faculty,
        {"name": "Faculty of Engineering"},
        institution_id=institution.id,
        college_id=colleges["A"].id,
        code="ENG",
    )
    faculties = {"ENG": faculty}

    departments: dict[str, Department] = {}
    for code, name, college_code, faculty_code in DEPARTMENTS:
        if college_code not in colleges:
            continue
        dept, _ = await ctx.get_or_create(
            Department,
            {
                "name": name,
                "faculty_id": faculties[faculty_code].id if faculty_code else None,
                "department_type": "academic",
            },
            institution_id=institution.id,
            college_id=colleges[college_code].id,
            code=code,
        )
        departments[code] = dept

    # subscription: the university plan so entitlements/feature plan defaults have a source
    plan = (
        await ctx.db.execute(select(SubscriptionPlan).where(SubscriptionPlan.code == "university"))
    ).scalar_one_or_none()
    if plan is not None:
        existing = (
            await ctx.db.execute(
                select(InstitutionSubscription).where(InstitutionSubscription.institution_id == institution.id)
            )
        ).scalar_one_or_none()
        if existing is None:
            ctx.db.add(
                InstitutionSubscription(
                    institution_id=institution.id,
                    plan_id=plan.id,
                    starts_on=datetime.now(UTC).date(),
                    ends_on=(datetime.now(UTC) + timedelta(days=365)).date(),
                    status="active",
                    billing_cycle="yearly",
                )
            )
            ctx.count("institution_subscriptions")

    # institution settings the auth service reads
    await ctx.get_or_create(
        InstitutionSetting,
        {"value": {"default": "faculty"}, "value_type": "json"},
        institution_id=institution.id,
        college_id=None,
        category="security",
        key="sso_role_map",
    )
    # The demo tenant narrows MFA to the exam separation-of-duties roles (the platform default in
    # ``app/core/rbac/registry.py`` also covers registrar/institution_admin/accountant) so the office roles used by
    # the verification script and the UI walkthrough sign in with a password alone. Production keeps the default.
    await ctx.get_or_create(
        InstitutionSetting,
        {"value": ["controller_of_examinations", "exam_decoder", "registrar"], "value_type": "json"},
        institution_id=institution.id,
        college_id=None,
        category="security",
        key="mfa_required_roles",
    )

    # roles cloned from the platform templates (with their default grants)
    from app.services.rbac_service import RbacService

    created_roles = await RbacService(ctx.db).seed_institution_roles(institution.id)
    if created_roles:
        ctx.count("roles", created_roles)
    await ctx.db.flush()

    roles = {
        r.slug: r
        for r in (
            await ctx.db.execute(select(Role).where(Role.institution_id == institution.id, Role.deleted_at.is_(None)))
        ).scalars()
    }

    now = datetime.now(UTC)
    for username, display_name, role_slug, scope, user_type, valid_days in DEMO_USERS:
        role = roles.get(role_slug)
        if role is None:
            continue
        password = _password()
        user = (
            await ctx.db.execute(select(User).where(User.institution_id == institution.id, User.username == username))
        ).scalar_one_or_none()
        if user is None:
            user = User(
                institution_id=institution.id,
                username=username,
                # a syntactically deliverable (but unregistered) domain: ``.test``/``.local`` are special-use names
                # that pydantic's EmailStr refuses, and later phases validate contact emails
                email=f"{username}@{profile['slug']}.septronuniverse.in",
                phone=_phone(username),
                display_name=display_name,
                user_type=user_type,
                password_hash=hash_password(password),
                is_verified=True,
                must_change_password=False,
                locale="en-IN",
                timezone="Asia/Kolkata",
                valid_to=now + timedelta(days=valid_days) if valid_days else None,
            )
            ctx.db.add(user)
            await ctx.db.flush()
            ctx.count("users")
            ctx.credentials.append((role_slug, username, password))
        scope_type, scope_id = _scope(scope, colleges, faculties, departments)
        exists = (
            await ctx.db.execute(
                select(UserRole).where(
                    UserRole.user_id == user.id, UserRole.role_id == role.id, UserRole.scope_type == scope_type
                )
            )
        ).scalar_one_or_none()
        if exists is None:
            ctx.db.add(
                UserRole(
                    institution_id=institution.id,
                    user_id=user.id,
                    role_id=role.id,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    valid_to=now + timedelta(days=valid_days) if valid_days else None,
                )
            )
            ctx.count("user_roles")
    await ctx.db.flush()


def _scope(
    scope: str, colleges: dict[str, College], faculties: dict[str, Faculty], departments: dict[str, Department]
) -> tuple[str, Any]:
    if ":" not in scope:
        return scope, None
    kind, code = scope.split(":", 1)
    if kind == "college":
        college = colleges.get(code) or next(iter(colleges.values()))
        return "college", college.id
    if kind == "faculty":
        fac = faculties.get(code)
        return ("faculty", fac.id) if fac else ("institution", None)
    if kind == "department":
        dept = departments.get(code)
        return ("department", dept.id) if dept else ("institution", None)
    return "institution", None


def _password() -> str:
    """Readable demo password that still satisfies the policy (≥ 10 chars, 3 of 4 classes)."""
    return f"Demo@{secrets.randbelow(10**6):06d}"


def _phone(username: str) -> str:
    """Deterministic fake number (``hash()`` is salted per process, so use a stable digest)."""
    digits = int(hashlib.sha256(username.encode()).hexdigest()[:8], 16) % 10**8
    return f"+9190{digits:08d}"
