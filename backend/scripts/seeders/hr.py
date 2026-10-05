"""``hr`` demo seeder (Prompts/06 §06.2 / §06.11 step 1) — ``seed_demo_institution.py --type university --only hr``.

On top of ``academics`` (colleges, CSE/ECE/MBA, batches, the current academic year/term):

* the pack HR templates (``seed_hr_defaults``: designations, leave types, payroll components) and the HR settings;
* two more demo users for the verification — ``faculty.2`` (faculty @self, ECE) and ``hod.ece`` (hod @department
  ECE) — written to ``LOCAL_TEST_CREDENTIALS.md`` as roles ``faculty_2`` / ``hod_ece`` so ``Get-DemoPassword 'hod'``
  keeps resolving ``hod.cse``;
* **30 staff** across CSE / ECE / MBA and the offices: 10 linked to the demo users (dean.eng, hod.cse, faculty.1,
  advisor.1, hod.ece, faculty.2, registrar, accountant, hr, librarian — creating them back-fills
  ``departments.hod_staff_id``, ``faculties.dean_staff_id`` and the section's ``class_advisor_staff_id``), 20 without
  an account (teaching, lab, office, guest / visiting with an hourly rate). ``faculty.1`` joined 2018 (CAS-eligible)
  and carries PAN / bank details for the masking checks;
* a salary structure for everyone effective 1 April 2026 (basic by cadre; office assistants sit under the ESI
  threshold), a festival advance for ``faculty.1`` (EMI ₹2,500) and the demo geo-fence (200 m).

Idempotent: staff are keyed by employee id; structures / the loan are created once. Services run as ``inst.admin``.
"""

from datetime import date
from typing import Any

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import select

from app.core.security import hash_password
from app.models.hr import Designation, LoanAdvance, Staff, StaffSalaryStructure
from app.models.platform import Department, Institution, InstitutionSetting, Role, User, UserRole

BASIC_BY_CODE = {
    "PROF": 14_420_000,
    "ASSOC": 13_140_000,
    "ASST": 5_770_000,
    "LECT": 4_400_000,
    "REG": 14_420_000,
    "AO": 5_610_000,
    "HRO": 5_610_000,
    "LIB": 5_610_000,
    "LABT": 2_920_000,
    "OA": 1_000_000,  # gross ₹20,600 — under the ESI threshold
}
EFFECTIVE = date(2026, 4, 1)

# (employee id, first, last, username | None, department, designation code, employment, gender, joined, hourly paise)
STAFF: list[tuple[str, str, str, str | None, str | None, str, str, str, date, int | None]] = [
    ("E1001", "Dean", "Engineering", "dean.eng", "CSE", "PROF", "regular", "M", date(2008, 7, 1), None),
    ("E1002", "Head", "Computer Science", "hod.cse", "CSE", "PROF", "regular", "F", date(2010, 7, 1), None),
    ("E1003", "Faculty", "One", "faculty.1", "CSE", "ASST", "regular", "M", date(2018, 7, 2), None),
    ("E1004", "Advisor", "One", "advisor.1", "CSE", "ASST", "regular", "F", date(2020, 7, 1), None),
    ("E1005", "Head", "Electronics", "hod.ece", "ECE", "PROF", "regular", "M", date(2011, 7, 1), None),
    ("E1006", "Faculty", "Two", "faculty.2", "ECE", "ASST", "regular", "F", date(2019, 7, 1), None),
    ("E1007", "University", "Registrar", "registrar", None, "REG", "regular", "M", date(2012, 6, 1), None),
    ("E1008", "Accounts", "Officer", "accountant", None, "AO", "regular", "F", date(2015, 6, 1), None),
    ("E1009", "HR", "Officer", "hr", None, "HRO", "regular", "F", date(2016, 6, 1), None),
    ("E1010", "Chief", "Librarian", "librarian", None, "LIB", "regular", "M", date(2014, 6, 1), None),
    ("E1011", "Anita", "Rao", None, "CSE", "ASSOC", "regular", "F", date(2012, 7, 1), None),
    ("E1012", "Vikram", "Nair", None, "CSE", "ASSOC", "regular", "M", date(2013, 7, 1), None),
    ("E1013", "Priya", "Iyer", None, "CSE", "ASST", "regular", "F", date(2021, 7, 1), None),
    ("E1014", "Rahul", "Menon", None, "CSE", "ASST", "contract", "M", date(2023, 7, 1), None),
    ("E1015", "Suresh", "Kumar", None, "ECE", "ASSOC", "regular", "M", date(2012, 7, 1), None),
    ("E1016", "Lakshmi", "Pillai", None, "ECE", "ASST", "regular", "F", date(2020, 7, 1), None),
    ("E1017", "Arjun", "Reddy", None, "ECE", "ASST", "regular", "M", date(2022, 7, 1), None),
    ("E1018", "Meena", "Joshi", None, "ECE", "LECT", "contract", "F", date(2024, 7, 1), None),
    ("E1019", "Kavita", "Shah", None, "MBA", "PROF", "regular", "F", date(2009, 6, 1), None),
    ("E1020", "Rohit", "Gupta", None, "MBA", "ASSOC", "regular", "M", date(2014, 6, 1), None),
    ("E1021", "Neha", "Verma", None, "MBA", "ASST", "regular", "F", date(2021, 6, 1), None),
    ("E1022", "Imran", "Khan", None, "MBA", "ASST", "regular", "M", date(2022, 6, 1), None),
    ("E1023", "Ravi", "Das", None, "CSE", "LABT", "regular", "M", date(2017, 6, 1), None),
    ("E1024", "Sunita", "Bose", None, "ECE", "LABT", "regular", "F", date(2018, 6, 1), None),
    ("E1025", "Mohan", "Lal", None, "CSE", "LABT", "contract", "M", date(2024, 1, 2), None),
    ("E1026", "Geeta", "Sharma", None, None, "OA", "regular", "F", date(2019, 3, 1), None),
    ("E1027", "Ramesh", "Yadav", None, None, "OA", "outsourced", "M", date(2023, 3, 1), None),
    ("E1028", "Deepak", "Chopra", None, "CSE", "GUEST", "guest", "M", date(2025, 8, 1), 150_000),
    ("E1029", "Farah", "Ali", None, "ECE", "GUEST", "guest", "F", date(2025, 8, 1), 150_000),
    ("E1030", "Sanjay", "Mehta", None, "MBA", "VISIT", "visiting", "M", date(2025, 7, 1), 250_000),
]
EXTRA_USERS = [
    # (username, display, role slug, scope, credential label)
    ("faculty.2", "Faculty Member Two", "faculty", "self", "faculty_2"),
    ("hod.ece", "Head of Department (ECE)", "hod", "department:ECE", "hod_ece"),
]


@seeder("hr", after=["academics"])
async def seed_hr(ctx: SeedContext) -> None:
    from seeders.base import _password, _phone

    from app.db.session import bind_tenant, set_tenant
    from app.schemas.hr import BankDetails, StaffCreate
    from app.services.auth_service import load_principal
    from app.services.institution_defaults import seed_hr_defaults
    from app.services.staff_service import StaffService

    inst = (await ctx.db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(ctx.db, inst.id)
    await set_tenant(ctx.db, inst.id)
    conn = await ctx.db.connection()
    hr_defaults = await conn.run_sync(lambda c: seed_hr_defaults(c, inst.id, inst.regulatory_pack))
    for k, v in hr_defaults.items():
        if v:
            ctx.count(k, v)

    depts = {
        d.code: d
        for d in (
            await ctx.db.execute(
                select(Department).where(Department.institution_id == inst.id, Department.deleted_at.is_(None))
            )
        ).scalars()
    }
    roles = {
        r.slug: r
        for r in (
            await ctx.db.execute(select(Role).where(Role.institution_id == inst.id, Role.deleted_at.is_(None)))
        ).scalars()
    }

    # ---- extra demo users --------------------------------------------------------------------------------------
    for username, display, slug, scope, label in EXTRA_USERS:
        user = (
            await ctx.db.execute(select(User).where(User.institution_id == inst.id, User.username == username))
        ).scalar_one_or_none()
        if user is None:
            pwd = _password()
            user = User(
                institution_id=inst.id,
                username=username,
                email=f"{username}@{ctx.profile['slug']}.septronuniverse.in",
                phone=_phone(username),
                display_name=display,
                user_type="staff",
                password_hash=hash_password(pwd),
                is_verified=True,
                must_change_password=False,
                locale="en-IN",
                timezone="Asia/Kolkata",
            )
            ctx.db.add(user)
            await ctx.db.flush()
            ctx.count("users")
            ctx.credentials.append((label, username, pwd))
        scope_type, scope_id = ("self", None)
        if scope.startswith("department:"):
            scope_type, scope_id = "department", depts[scope.split(":", 1)[1]].id
        exists = (
            await ctx.db.execute(
                select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == roles[slug].id)
            )
        ).scalar_one_or_none()
        if exists is None:
            ctx.db.add(
                UserRole(
                    institution_id=inst.id,
                    user_id=user.id,
                    role_id=roles[slug].id,
                    scope_type=scope_type,
                    scope_id=scope_id,
                )
            )
            ctx.count("user_roles")
    await ctx.db.flush()

    admin = (
        await ctx.db.execute(select(User).where(User.institution_id == inst.id, User.username == "inst.admin"))
    ).scalar_one()
    principal = await load_principal(ctx.db, admin.id)
    service = StaffService(ctx.db, principal, None, inst.id)
    designations = {
        d.code: d
        for d in (await ctx.db.execute(select(Designation).where(Designation.institution_id == inst.id))).scalars()
    }
    users = {
        u.username: u for u in (await ctx.db.execute(select(User).where(User.institution_id == inst.id))).scalars()
    }

    for emp, first, last, username, dept, code, employment, gender, joined, hourly in STAFF:
        staff = (
            await ctx.db.execute(select(Staff).where(Staff.institution_id == inst.id, Staff.employee_id == emp))
        ).scalar_one_or_none()
        if staff is None:
            user = users.get(username) if username else None
            if username and user is None:
                continue
            if (
                user is not None
                and (await ctx.db.execute(select(Staff).where(Staff.user_id == user.id))).scalar_one_or_none()
            ):
                continue
            designation = designations.get(code)
            body: dict[str, Any] = {
                "first_name": first,
                "last_name": last,
                "department_id": depts[dept].id if dept and dept in depts else None,
                "college_id": None if dept else next((d.college_id for d in depts.values() if d.code == "CSE"), None),
                "designation_id": designation.id if designation else None,
                "employment_type": employment,
                "gender": gender,
                "joining_date": joined,
                "employee_id": emp,
                "email": f"{emp.lower()}@{ctx.profile['slug']}.septronuniverse.in" if user is None else user.email,
                "phone": user.phone if user is not None else f"+9198{int(emp[1:]):08d}",
                "hourly_rate_paise": hourly,
                "pf_number": f"KN/BLR/12345/{emp[1:]}",
                "uan": f"1009{int(emp[1:]):08d}",
                "user_id": user.id if user is not None else None,
                "create_user": False,
            }
            if username == "faculty.1":
                body |= {
                    "pan": "ABCDE1234F",
                    "aadhaar": "234567890124",
                    "dob": date(1988, 5, 14),
                    "bank_details": BankDetails(
                        account_no="1234567890", ifsc="SBIN0001234", bank="State Bank of India"
                    ),
                }
            result = await service.create(StaffCreate.model_validate(body))
            staff = (await ctx.db.execute(select(Staff).where(Staff.id == result.staff.id))).scalar_one()
            ctx.count("staff")
        basic = BASIC_BY_CODE.get(code)
        if basic and hourly is None:
            has = (
                await ctx.db.execute(
                    select(StaffSalaryStructure.id).where(StaffSalaryStructure.staff_id == staff.id).limit(1)
                )
            ).first()
            if has is None:
                ctx.db.add(
                    StaffSalaryStructure(
                        institution_id=inst.id,
                        staff_id=staff.id,
                        effective_from=EFFECTIVE,
                        pay_level=code,
                        basic_paise=basic,
                        components={},
                        created_by=admin.id,
                    )
                )
                ctx.count("staff_salary_structures")
        if username == "faculty.1":
            loan = (
                await ctx.db.execute(select(LoanAdvance.id).where(LoanAdvance.staff_id == staff.id).limit(1))
            ).first()
            if loan is None:
                ctx.db.add(
                    LoanAdvance(
                        institution_id=inst.id,
                        staff_id=staff.id,
                        loan_type="festival",
                        principal_paise=10_000_000,
                        emi_paise=250_000,
                        start_month=EFFECTIVE,
                        balance_paise=10_000_000,
                        status="active",
                    )
                )
                ctx.count("loans_advances")
    await ctx.get_or_create(
        InstitutionSetting,
        {"value": {"lat": 12.9716, "lng": 77.5946, "radius_m": 200}, "value_type": "json"},
        institution_id=inst.id,
        college_id=None,
        category="attendance",
        key="geo_fence",
    )
    await ctx.db.flush()
