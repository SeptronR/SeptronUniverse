"""Aggregates module routers — Prompts/00_PREREQUISITE_Project_Setup.md §2.

Every module router is included with ``dependencies=[feature_required("<module>.core")]`` (coding standard 2);
core-key routers (``core.*``) pass through ``feature_required`` unchanged because core keys are never gated.
Phases append ``api_router.include_router(<module>.router, dependencies=[feature_required("<key>")])``.

Phase 01: ``platform`` (public config / read-only / mobile config — public routes, the write carries its own feature
dependency), ``jobs`` {core.background_jobs}, ``search`` {search.global}, ``help`` {platform.help_center},
``feedback`` {platform.in_app_feedback}; ``dev`` only when ``APP_ENV=development``.
Phase 02: ``auth`` {core.auth}, ``rbac`` (roles/users) {core.rbac}, ``features`` {core.rbac}, ``privacy``
(consents, DSRs, entitlements, install) {core.settings}; the development-only ``module_stubs`` were removed by
Phase 07 (``/students``) and Phase 20 (``/hostels`` — the real hostel router carries {hostel.core}).
Phase 05: ``programs`` (+ batches) {academics.programs}, ``regulations`` / ``courses`` / ``grading``
{academics.regulations}, ``curriculum`` (programme-regulations, structure; baskets add
{academics.elective_baskets}) {academics.curriculum}, ``catalog`` (public, {academics.public_catalog} checked by
its tenant dependency).
Phase 06: ``staff`` (designations, staff, records) {hr.staff}, ``leaves`` {hr.leaves}, ``staff_attendance``
{attendance.staff} (+ the token-authenticated device punch route), ``payroll`` (+ salary structures, registers, loans)
{hr.payroll}, ``recruitment`` {hr.recruitment} (+ public careers), ``appraisals`` {hr.staff} with per-route
{hr.appraisal_pbas} / {hr.cas_promotions}, ``workload`` {hr.workload}.
Phase 07: ``students`` (master, self service, guardians, documents, undertakings, ID cards, import/export) and
``enrollments`` (enrolments, promotion, exit/re-entry, holds, standing, transfers) {students.core} with per-route
sub-features, ``credit_transfers`` {academics.credit_transfer_mooc}, ``verify`` (public ID-card verification). The
``POST /students`` development stub was removed.
Phase 11: ``attendance`` (session marking, QR / geo / offline, summaries, on duty, condonation, eligibility)
{attendance.core} with per-route sub-features (+ the token-authenticated student punch route).
Phase 12: ``fees`` {fees.core} (heads, structures, discounts, fines, invoices, collection, online / UPI, offline
reconciliation, day-book, refunds, reports) with per-route sub-features, ``scholarships`` {fees.scholarships},
``no_dues`` {fees.no_dues}; the public payment webhook is included before the Phase 04 ``/webhooks/{provider}/{channel}``
route so ``/webhooks/payments/{provider}`` is not shadowed.
Phase 13: ``assessment`` {assessment.internal_marks} (+ ``obe_router`` {obe.definitions}), ``lms`` {lms.content}
(+ ``projects_router`` {assessment.projects}), ``content`` {lms.question_bank} (+ ``materials_router``
{lms.study_materials}).
Phase 14: ``exams`` {exams.sessions} with per-route sub-features (+ the public hall-ticket verification).
Phase 15: ``results`` {exams.sessions} with per-route sub-features (+ the public result lookup).
"""

from fastapi import APIRouter

import app.features  # noqa: F401  (registers every feature key before routers cite them)
from app.api.v1.endpoints import (
    academic_sessions,
    accounting,
    accreditation,
    admissions,
    affiliation,
    alumni,
    analytics,
    audit_logs,
    billing,
    announcements,
    appraisals,
    assessment,
    attendance,
    auth,
    calendar,
    campus,
    catalog,
    clubs,
    comms_advanced,
    communication,
    content,
    courses,
    credit_transfers,
    curriculum,
    degrees,
    discipline,
    documents,
    enrollments,
    events,
    exams,
    facilities,
    features,
    feedback,
    fees,
    fundraising,
    governance,
    grading,
    grievances,
    help,
    hostel,
    institution,
    internships,
    inventory,
    jobs,
    leaves,
    library,
    lms,
    mentoring,
    no_dues,
    notifications,
    obe_attainment,
    payroll,
    phd,
    placement,
    platform,
    platform_institutions,
    post_result,
    privacy,
    public_saas,
    programs,
    rbac,
    recruiter,
    recruitment,
    registration,
    regulations,
    reports,
    research,
    results,
    saas_platform,
    scholarships,
    search,
    staff,
    staff_attendance,
    students,
    support,
    surveys,
    timetable,
    training,
    transport,
    verify,
    workflow,
    workload,
)
from app.api.v1.endpoints import settings as settings_routes
from app.core.config import settings
from app.core.features import feature_required

api_router = APIRouter()

api_router.include_router(auth.router, dependencies=[feature_required("core.auth")])
api_router.include_router(rbac.router, dependencies=[feature_required("core.rbac")])
api_router.include_router(features.router, dependencies=[feature_required("core.rbac")])
api_router.include_router(privacy.router, dependencies=[feature_required("core.settings")])
api_router.include_router(platform.router)
api_router.include_router(institution.router, dependencies=[feature_required("core.institution")])
api_router.include_router(academic_sessions.router, dependencies=[feature_required("core.institution")])
api_router.include_router(settings_routes.router, dependencies=[feature_required("core.settings")])
api_router.include_router(platform_institutions.router, dependencies=[feature_required("core.institution")])
api_router.include_router(fees.public_router)  # gateway webhook; signature + {fees.online_payment} checked inside
api_router.include_router(communication.router, dependencies=[feature_required("core.notifications_inapp")])
api_router.include_router(notifications.router, dependencies=[feature_required("core.notifications_inapp")])
api_router.include_router(announcements.router, dependencies=[feature_required("comms.announcements")])
api_router.include_router(workflow.router, dependencies=[feature_required("workflow.engine")])
api_router.include_router(programs.router, dependencies=[feature_required("academics.programs")])
api_router.include_router(regulations.router, dependencies=[feature_required("academics.regulations")])
api_router.include_router(courses.router, dependencies=[feature_required("academics.regulations")])
api_router.include_router(grading.router, dependencies=[feature_required("academics.regulations")])
api_router.include_router(curriculum.router, dependencies=[feature_required("academics.curriculum")])
api_router.include_router(catalog.router)  # public; the tenant dependency checks {academics.public_catalog}
api_router.include_router(staff.router, dependencies=[feature_required("hr.staff")])
api_router.include_router(leaves.router, dependencies=[feature_required("hr.leaves")])
api_router.include_router(staff_attendance.router, dependencies=[feature_required("attendance.staff")])
api_router.include_router(staff_attendance.public_router)  # device token; checks {attendance.biometric} itself
api_router.include_router(payroll.router, dependencies=[feature_required("hr.payroll")])
api_router.include_router(recruitment.router, dependencies=[feature_required("hr.recruitment")])
api_router.include_router(recruitment.public_router)  # public careers; the tenant dependency checks {hr.recruitment}
api_router.include_router(appraisals.router, dependencies=[feature_required("hr.staff")])
api_router.include_router(workload.router, dependencies=[feature_required("hr.workload")])
api_router.include_router(students.router, dependencies=[feature_required("students.core")])
api_router.include_router(enrollments.router, dependencies=[feature_required("students.core")])
api_router.include_router(credit_transfers.router, dependencies=[feature_required("academics.credit_transfer_mooc")])
api_router.include_router(verify.router)  # public ID-card verification (token-signed)
api_router.include_router(admissions.router, dependencies=[feature_required("admissions.cycles")])
api_router.include_router(registration.router, dependencies=[feature_required("registration.core")])
api_router.include_router(timetable.router, dependencies=[feature_required("timetable.core")])
api_router.include_router(timetable.public_router)  # token-authenticated iCal feeds; the services check the token
api_router.include_router(attendance.router, dependencies=[feature_required("attendance.core")])
api_router.include_router(attendance.public_router)  # device token; checks {attendance.biometric|rfid} itself
api_router.include_router(fees.router, dependencies=[feature_required("fees.core")])
api_router.include_router(scholarships.router, dependencies=[feature_required("fees.scholarships")])
api_router.include_router(no_dues.router, dependencies=[feature_required("fees.no_dues")])
api_router.include_router(assessment.router, dependencies=[feature_required("assessment.internal_marks")])
api_router.include_router(assessment.obe_router, dependencies=[feature_required("obe.definitions")])
api_router.include_router(lms.router, dependencies=[feature_required("lms.content")])
api_router.include_router(lms.projects_router, dependencies=[feature_required("assessment.projects")])
api_router.include_router(content.router, dependencies=[feature_required("lms.question_bank")])
api_router.include_router(content.materials_router, dependencies=[feature_required("lms.study_materials")])
# Phase 16 before the Phase 14 router: ``/exam-sessions/supplementary`` must win over ``/exam-sessions/{id}``; each
# route carries its own results.* / students.core feature
api_router.include_router(post_result.router)
api_router.include_router(post_result.public_router)  # masked public rank lists (published public + setting)
# Phase 17: OBE attainment / CQI / NBA export — each route carries its obe.* feature
api_router.include_router(obe_attainment.router)
# Phase 18: degrees, convocation, credentials, ABC — each route carries its degrees.* feature
api_router.include_router(degrees.router)
# Phase 19: library (each route carries its library.* feature) and the public OPAC
api_router.include_router(library.router)
api_router.include_router(library.public_router)
# Phase 20: hostel, mess, leaves & gate, staff quarters (each route carries its hostel.* feature)
api_router.include_router(hostel.router)
# Phase 21: transport (each route carries its transport.* feature) and the GPS device ingest (device token)
api_router.include_router(transport.router)
api_router.include_router(transport.public_router)  # X-Device-Token; checks {transport.gps_live} itself
# Phase 22: inventory, procurement, assets, bills (each route carries its inventory.* feature), the vendor portal
# and the public supplier self-registration (rate-limited + captcha; checks {inventory.vendor_portal} itself)
api_router.include_router(inventory.router)
api_router.include_router(inventory.vendor_router)
api_router.include_router(inventory.public_router)
# Phase 23: accounting, budgets, grants, reconciliation, GST, exports, statements (each route carries its accounting.* feature)
api_router.include_router(accounting.router)
# Phase 24: segments, campaigns, emergency broadcast, WhatsApp bot, AI assistant, simulator, analytics (per-route comms.*
# features) and the public WhatsApp webhook (verify token / signature; checks {comms.whatsapp_bot} itself)
api_router.include_router(comms_advanced.router)
api_router.include_router(comms_advanced.public_router)
# Phase 25: calendar (+ public institution / college / personal .ics), events (+ public list / external registration),
# facilities (bookings, service desk, AMC, lost & found, visitors, reports) and campus services (SOS, health,
# counselling, sports, wallet) — each route carries its calendar.* / events.* / facilities.* feature
api_router.include_router(calendar.router)
api_router.include_router(calendar.public_router)
api_router.include_router(events.router)
api_router.include_router(events.public_router)
api_router.include_router(facilities.router)
# Phase 26: document templates / renderer / issued register / signed downloads / bulk / serial registers /
# certificate requests ({documents.*} per route); public verification stays in ``verify``
api_router.include_router(documents.router)
# Phase 27: mentoring + risk, grievances (public anonymous form / tracking registered before ``/grievances/{id}``),
# discipline, surveys (+ public alumni / employer links), clubs / activity hours / achievements, the committees stub
# and student-support stats — each route carries its mentoring.* / grievances.* / discipline.* / surveys.* / clubs.*
api_router.include_router(mentoring.router)
api_router.include_router(grievances.public_router)
api_router.include_router(grievances.router)
api_router.include_router(discipline.router)
api_router.include_router(surveys.public_router)
api_router.include_router(surveys.router)
api_router.include_router(clubs.router)
# Phase 28: placement (companies / policies / drives / applications / rounds / offers / profiles / blacklist / stats —
# {placement.core}), internships {placement.internships}, training {placement.training} and the recruiter portal
# {placement.recruiter_portal}; ``/placement/drives/open`` and ``/placement/offers/me|wards|pending`` are declared before
# the ``/{id}`` routes of the same prefix
api_router.include_router(placement.router)
api_router.include_router(internships.router)
api_router.include_router(training.router)
api_router.include_router(recruiter.router)
# Phase 29: alumni (profiles / directory / events / jobs / stats — {alumni.core|portal|jobs_board}) and fundraising
# ({alumni.fundraising}, 80G {alumni.donations_80g}); claim / public campaigns / website donations are public
api_router.include_router(alumni.public_router)
api_router.include_router(alumni.router)
api_router.include_router(fundraising.public_router)
api_router.include_router(fundraising.router)
# Phase 30: research & faculty development (publications, patents, projects, consultancy, ethics, incentives, FDP,
# MoUs, start-ups, API score, stats) — feature keys per route group
api_router.include_router(research.router)
# Phase 31: PhD & research-scholar management — feature keys per route group; examiner token pages + plagiarism callback
api_router.include_router(phd.router)
api_router.include_router(phd.public_router)
# Phase 32: accreditation & compliance (IQAC) — feature keys per route group; public disclosures feed by institution slug
api_router.include_router(accreditation.router)
api_router.include_router(accreditation.public_router)
# Phase 33: governance — committees, meetings / minutes, legal, RTI, audit paras, e-File, policies (feature keys per route
# group; the public policies list is included first so /policies/public is not captured by /policies/{id})
api_router.include_router(governance.public_router)
api_router.include_router(governance.router)
# Phase 34: affiliation management — feature keys per route group (core / inspections / fees / data submissions / exam
# centres); the public college list (tenant by institution slug) is included first
api_router.include_router(affiliation.public_router)
api_router.include_router(affiliation.router)
# Phase 35: dashboards, analytics & early warning — {core.dashboard} for /dashboard*, {analytics.core} for /analytics/*,
# {analytics.early_warning} for the /risk cohort routes (Phase 27 keeps /risk/flags|heatmap|compute); public counters first
api_router.include_router(analytics.public_router)
api_router.include_router(analytics.router)
# Phase 36: reports — {reports.core} registry / catalogue / runs / registers / builder, {reports.scheduled} schedules,
# {reports.statutory} statutory renderers + sign-off
api_router.include_router(reports.router)
# Phase 37: audit explorer / chain integrity {core.audit_logs}, exam audit {exams.sessions}, security console
# {core.audit_logs} (+ {security.session_management} for sessions, checked in the service), retention {core.settings}
api_router.include_router(audit_logs.router)
api_router.include_router(campus.router)
api_router.include_router(exams.router, dependencies=[feature_required("exams.sessions")])
api_router.include_router(exams.public_router)  # hall-ticket verification (unguessable token)
api_router.include_router(results.router, dependencies=[feature_required("exams.sessions")])
api_router.include_router(results.public_router)  # public result lookup (rate-limited; audience=public only)
api_router.include_router(admissions.public_router)  # public; the tenant dependency checks the feature
api_router.include_router(jobs.router, dependencies=[feature_required("core.background_jobs")])
api_router.include_router(search.router, dependencies=[feature_required("search.global")])
# Phase 38: platform console (/platform/*: super admin / support agent; the core key {core.institution} as Phase 03),
# tenant billing {core.settings} (+ {data.export_portability} on the export), support tickets {core.settings}, public
# registration / demo / pricing / gateway webhook routes (PUBLIC_ROUTES)
api_router.include_router(saas_platform.router, dependencies=[feature_required("core.institution")])
api_router.include_router(billing.router, dependencies=[feature_required("core.settings")])
api_router.include_router(support.router, dependencies=[feature_required("core.settings")])
api_router.include_router(public_saas.router)
api_router.include_router(help.router, dependencies=[feature_required("platform.help_center")])
api_router.include_router(feedback.router, dependencies=[feature_required("platform.in_app_feedback")])

if settings.APP_ENV == "development":
    from app.api.v1.endpoints import dev

    api_router.include_router(dev.router, dependencies=[feature_required("core.background_jobs")])
