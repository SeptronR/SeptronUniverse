# SeptronUniverse — Authorization & Data-Visibility Model

Every request passes four layers; every list is filtered by a single row-level resolver; every "people/records" screen shows the user's **own** view and, when the role holds `view_all` within its scope, the wider view side by side. Example: an accountant sees **My leaves / My attendance** and **All staff · All leaves · All staff attendance**.

## 1. Four layers, evaluated in order

| # | Layer | Mechanism | On failure |
|---|---|---|---|
| 1 | **Feature** | `feature_required(key)` on router/route (`docs/Feature_Flags.md`) | `403 FEATURE_DISABLED` |
| 2 | **Permission** | `permission_required(module, action)`. Action semantics: `view` = self + ownership scopes; `view_all` = everything inside the role's scope; `create/update/delete/approve/publish/export/manage` act inside the scope; `view_pii` unmasks sensitive fields | `403 PERMISSION_DENIED` |
| 3 | **Scope** | `user_roles(user_id, role_id, scope_type, scope_id)`; `scope_type ∈ institution / college / faculty / department / program / offering / self`; a user with several roles gets the **union** of scopes | rows outside scope are invisible (never a 403) |
| 4 | **Visibility (row-level)** | `VisibilityResolver.predicate(user, module)` = `self ∪ ownership ∪ (scope if view_all)`, applied by `BaseRepository.visible_to()`; PostgreSQL RLS (`app.institution_id`) is the tenant backstop | rows filtered |

Plus:
- **Field-level masking**: Aadhaar, bank details, salary, medical notes, grievance identities are masked (`XXXX-1234`) unless the caller holds `<module>:view_pii`. Masking happens in the response schema layer (`mask_pii(schema, user)`), never in the DB.
- **Record-state rules**: published results, locked marks, finalized attendance, issued certificates are read-only regardless of permission; changes go through the corresponding request/workflow tables.
- **Impersonation**: super admin/support impersonation sets `request.state.impersonator`; every write is audited with both ids; the UI shows a banner.
- **Time-boxed roles**: `user_roles.valid_from/valid_to` (external examiners, auditors, applicants).

## 2. Scope and ownership definitions

| Symbol | Name | Rows visible | Derived from |
|---|---|---|---|
| S | self | the user's own records | `users.id` ↔ `staff.user_id` / `students.user_id` |
| W | wards | linked students | `student_guardians.user_id` + `students.guardian_portal_consent` |
| O | ownership | records the user is responsible for | `course_offering_faculty` (own offerings → registered students, sessions, marks), `mentor_assignments`, `batch_sections.class_advisor_staff_id` (advisees), `research_scholars.guide_staff_id`, `valuation_assignments` (bundles), `placement_drives.owner_staff_id`, `service_requests.assigned_to`, `committee_members`, `companies.recruiter_user_ids` (own drives) |
| H | hostel | residents of hostels the user wardens | `hostels.warden_staff_id` |
| D | department | rows of the department | `departments.hod_staff_id` or role scope `department` |
| F | faculty unit | rows of departments under the faculty | `faculties.dean_staff_id` or role scope `faculty` |
| C | college | rows of the college | role scope `college` |
| A | institution | all rows of the tenant | role scope `institution` + `view_all` |
| — | none | no access | |

Ownership links are **derived at query time** from the source tables (no duplicated "ownership" table). The resolver caches per request.

## 3. Resolver algorithm

```python
def predicate(user, module) -> ColumnElement:
    parts = []
    if module has a self column:            parts.append(self_predicate(user))          # e.g. Leave.staff_id == user.staff_id
    for link in OWNERSHIP_LINKS[module]:     parts.append(link.predicate(user))          # e.g. Student in offerings taught by user
    if user.has(f"{module}:view_all"):
        for scope in user.scopes:            parts.append(scope.predicate(module))       # institution / college / department …
    return or_(*parts) if parts else false()
```
- `BaseRepository.list(...)` always applies `predicate` unless the caller passes `visibility="system"` (Celery/system tasks, which set RLS context explicitly).
- `GET` of a single row uses the same predicate → 404 (not 403) when invisible, to avoid existence leaks.
- Writes check permission + scope + record-state; ownership writes (e.g., a faculty marking attendance) additionally require the link.

## 4. API & UI conventions

- One list endpoint per module (`GET /leaves`). `?scope=self|own|department|college|all` selects a tab; the server validates the requested scope against what the user may see and narrows silently if too broad.
- Shortcuts: `GET /leaves/me`, `GET /attendance/summary?me`, `GET /results/me`.
- Every list response carries `meta.visibility`:
  ```json
  { "self": true, "scopes": ["department", "all"], "default": "self", "pii": false }
  ```
  Web `useVisibility(module)` renders segmented tabs **Mine | Department | College | All**; mobile renders a `SegmentedScope`.
- Portals (student/parent/alumni/applicant/evaluator/scholar/recruiter) are self/ownership only; the admin shell shows all tabs the role has.
- Self-service is always present where it makes sense: My profile · My leaves (apply/track/balance) · My attendance · My payslips · My timetable · My courses/marks (faculty) · My dues/receipts · My hostel · My library · My requests · My approvals inbox.

## 5. Role × module visibility matrix

Legend: S self · O ownership · D department · F faculty unit · H own hostels · W wards · C college · A institution-wide (`view_all`) · — none · verb in brackets = capability beyond view.

| Role | Students | Staff/HR | Leaves | Staff attendance | Student attendance | Marks/Results | Fees | Hostel | Placement | Library | Payroll | Approvals inbox |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| institution_admin | A (manage) | A (manage) | S + A (approve) | S + A | A | A | A | A | A | A | A | A |
| vice_chancellor / principal | A | A | S + A (approve) | S + A | A | A | A | A | A | A | A (view) | escalations |
| registrar | A (manage) | A | S | S | A | A | A | A | A | — | S | students / admissions / affiliation / certificates |
| controller_of_examinations | A | A | S | S | A | A (approve, publish) | A (exam fees) | — | — | — | S | results / reval / malpractice |
| exam_cell | A | — | S | S | A | A (ops) | — | — | — | — | S | — |
| exam_decoder | — | — | S | S | — | decode only | — | — | — | — | S | — |
| dean | F | F | S + F (approve) | S + F | F | F | F | — | F | — | S | F workflows |
| hod | D (manage) | D | S + D (approve) | S + D | D | D (verify) | D | — | D | — | S | D workflows |
| faculty | O (own offerings + mentees) | S | S | S | O (mark) | O (enter) | — | — | — | S | S | own |
| class_advisor / mentor | O (advisees / mentees) | S | S | S | O | O | O (dues) | O | O | S | S | registrations |
| **accountant** | **A** | **A** | **S + A** | **S + A** | — | — | **A (collect, refund)** | A (fees) | — | A (fines) | **A (manage)** | fee refunds / receipt cancellations |
| hr_officer | — | A (manage) | S + A (manage) | S + A (manage) | — | — | — | — | — | — | A (generate) | leaves / recruitment / appraisal |
| admissions_officer | A (admit) | S | S | S | — | — | A (admission fees) | — | — | — | S | applications |
| placement_officer | A (profiles, CGPA/backlogs) | S | S | S | A (%) | A (CGPA) | — | — | A (manage) | — | S | drives |
| hostel_warden | H | S | S | S | H | — | H (dues) | H (manage) | — | — | S | out-passes / room changes |
| hostel_gate_staff | H (names only) | — | — | — | — | — | — | H (gate only) | — | — | — | — |
| librarian | A (members) | A (members) | S | S | — | — | A (fines) | — | — | A (manage) | S | — |
| iqac_coordinator | A (aggregates) | A (aggregates) | S | S | A (aggregates) | A (aggregates) | A (aggregates) | A | A | A | S | cycles |
| obe_coordinator | A (aggregates) | — | S | S | — | A (CO/PO) | — | — | — | — | S | — |
| research_guide | O (scholars) | S | S | S | — | O | — | — | — | S | S | scholar reports |
| research_cell | A (scholars) | A (research profiles) | S | S | — | — | A (grants) | — | — | — | S | incentives / ethics |
| external_examiner / invigilator | — (dummy numbers only) | — | — | — | — | O (bundles) | — | — | — | — | S (remuneration) | — |
| committee_secretary | — | — | S | S | — | — | — | — | — | — | S | meetings |
| grievance_officer / discipline_committee | O (cases) | O (cases) | S | S | — | — | — | — | — | — | S | grievances / discipline |
| college_admin | C | C | S + C (approve) | S + C | C | C | C | C | C | C | C | C workflows |
| college_exam_coordinator | C | — | S | S | C | C (submissions) | — | — | — | — | S | submissions |
| student | S | — | — | — | S | S | S | S | S | S | — | own requests |
| parent | W | — | — | — | W | W | W (pay) | W | W (view) | W | — | — |
| alumni | S | — | — | — | — | S (transcripts) | S (certificate fees) | — | S (jobs) | — | — | — |
| applicant | S (application) | — | — | — | — | — | S (application fee) | — | — | — | — | — |
| recruiter | O (applicants to own drives; consented fields) | — | — | — | — | O (CGPA / backlog flags) | — | — | O (own drives) | — | — | — |
| auditor (time-boxed) | A (read) | A (read) | A (read) | A (read) | A (read) | A (read) | A (read) | A (read) | A (read) | A (read) | A (read) | — |
| support_agent (platform) | A across institutions (read, masked PII, audited) | | | | | | | | | | | |
| super_admin | A across institutions (impersonation-audited) | | | | | | | | | | | |

Other modules follow the same pattern: **Timetable** (S for everyone; O for faculty/advisor; D/F/C/A with `timetable:view_all`), **LMS** (S student; O faculty; D HOD), **Events** (A read for all staff; manage per organiser), **Service desk** (S requester; O assignee; A estate officer), **Research** (S owner; D HOD; A research cell / IQAC), **PhD** (S scholar; O guide; A research cell/registrar), **Governance** (O committee members; A secretary/admin), **Accreditation** (A IQAC; D HOD for department metrics), **Affiliation** (C college admin; A registrar).

## 6. Default role → permission encoding

`docs/Roles_and_Permissions.md` encodes this matrix as `module:view` vs `module:view_all` (+ verbs) per role. Examples:

| Role | Grants (excerpt) |
|---|---|
| accountant | `hr:view_all`, `leaves:view_all`, `leaves:self`, `leaves:create`, `attendance:staff_view_all`, `attendance:self`, `payroll:manage`, `payroll:self`, `fees:manage`, `fees:collect`, `fees:refund`, `fees:view_all`, `no_dues:approve`, `library:fines_manage`, `students:view_all`, `students:view_pii` (bank only, via config) |
| faculty | `attendance:mark`, `attendance:self`, `marks:enter`, `marks:view`, `students:view` (ownership), `lms:manage` (own offerings), `leaves:self`, `leaves:create`, `payroll:self`, `research:manage` (self), `mentoring:manage` (own) |
| hod | faculty grants + `students:view_all`@department, `hr:view_all`@department, `leaves:approve`@department, `marks:verify`, `attendance:condone` (recommend), `offerings:manage`@department, `hr:workload_manage` |
| student | `students:self`, `registration:self`, `attendance:self`, `results:self`, `fees:self`, `hostel:self`, `library:self`, `placement:self`, `certificates:self`, `grievances:create` |
| parent | `students:wards`, `attendance:wards`, `results:wards`, `fees:wards_pay`, `hostel:wards`, `mentoring:wards` |

## 7. Verification (API + UI, no unit tests)

Per phase, the prompt's verification section includes visibility checks run against the API and the UI:

1. **Accountant**: `GET /leaves` → `meta.visibility.scopes` contains `all`; `GET /leaves?scope=self` returns only own; UI shows tabs *Mine | All* on Leaves and Staff attendance; Staff list visible; Payroll manage actions visible.
2. **Faculty**: `GET /students` returns only students in own offerings/mentees; `GET /students?scope=all` silently narrows; UI shows no *All* tab; attempting `GET /students/{other}` → 404.
3. **HOD**: `GET /staff` returns department staff; `PUT /leaves/{id}/approve` for another department → 403.
4. **Parent**: `GET /results/me` returns wards' results only; ward with `guardian_portal_consent=false` is excluded.
5. **Warden**: `GET /hostel/allocations` → own hostels only; gate staff cannot open resident profile.
6. **External examiner**: `GET /valuation/me/bundles` → dummy numbers only; response body contains no `exam_registration_item_id`, names or registration numbers.
7. **College admin (university tenant)**: all lists restricted to `college_id`; `GET /results?college_id=other` → empty.
8. **PII**: `GET /students/{id}` as HOD shows masked Aadhaar/bank; as registrar with `students:view_pii` shows full.
9. **Tenant**: with a raw SQL session and `SET app.institution_id = B`, a `SELECT` on any tenant table returns no rows of A (RLS).
10. **Impersonation**: super admin impersonating an institution admin sees the banner; audit rows carry `impersonator_id`.
