"""Aggregates module routers — Prompts/00_PREREQUISITE_Project_Setup.md §2.

Every module router is included with ``dependencies=[feature_required("<module>.core")]`` (coding standard 2);
core-key routers (``core.*``) pass through ``feature_required`` unchanged because core keys are never gated.
Phases append ``api_router.include_router(<module>.router, dependencies=[feature_required("<key>")])``.

Phase 01: ``platform`` (public config / read-only / mobile config — public routes, the write carries its own feature
dependency), ``jobs`` {core.background_jobs}, ``search`` {search.global}, ``help`` {platform.help_center},
``feedback`` {platform.in_app_feedback}; ``dev`` only when ``APP_ENV=development``.
Phase 02: ``auth`` {core.auth}, ``rbac`` (roles/users) {core.rbac}, ``features`` {core.rbac}, ``privacy``
(consents, DSRs, entitlements, install) {core.settings}; the development-only ``module_stubs`` (``/hostels``) carries
its own feature key and disappears with Phase 20 (Phase 07 replaced the ``/students`` stub).
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
``POST /students`` development stub was removed (``module_stubs`` keeps ``/hostels`` until Phase 20).
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
    admissions,
    announcements,
    appraisals,
    assessment,
    attendance,
    auth,
    catalog,
    communication,
    content,
    courses,
    credit_transfers,
    curriculum,
    enrollments,
    exams,
    features,
    feedback,
    fees,
    grading,
    help,
    institution,
    jobs,
    leaves,
    lms,
    no_dues,
    notifications,
    payroll,
    platform,
    platform_institutions,
    privacy,
    programs,
    rbac,
    recruitment,
    registration,
    regulations,
    post_result,
    results,
    scholarships,
    search,
    staff,
    staff_attendance,
    students,
    timetable,
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
api_router.include_router(exams.router, dependencies=[feature_required("exams.sessions")])
api_router.include_router(exams.public_router)  # hall-ticket verification (unguessable token)
api_router.include_router(results.router, dependencies=[feature_required("exams.sessions")])
api_router.include_router(results.public_router)  # public result lookup (rate-limited; audience=public only)
api_router.include_router(admissions.public_router)  # public; the tenant dependency checks the feature
api_router.include_router(jobs.router, dependencies=[feature_required("core.background_jobs")])
api_router.include_router(search.router, dependencies=[feature_required("search.global")])
api_router.include_router(help.router, dependencies=[feature_required("platform.help_center")])
api_router.include_router(feedback.router, dependencies=[feature_required("platform.in_app_feedback")])

if settings.APP_ENV == "development":
    from app.api.v1.endpoints import dev, module_stubs

    api_router.include_router(dev.router, dependencies=[feature_required("core.background_jobs")])
    api_router.include_router(module_stubs.router)
