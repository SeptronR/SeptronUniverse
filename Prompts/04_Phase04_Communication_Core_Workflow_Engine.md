# PHASE 04 — COMMUNICATION CORE & APPROVAL-WORKFLOW ENGINE

## Pre-Requisite
Phases 01–03 complete.

## Objective
Two cross-cutting services every later module depends on. **Communication core**: event-driven notification templates (versioned, bilingual-ready), channel abstraction (SMS/WhatsApp/email/push/in-app) with mock and live adapters, DLT and WhatsApp template registries, user preferences (quiet hours, digest, unsubscribe), message logs, announcements with acknowledgement, device tokens, the in-app notification centre over WebSocket. **Workflow engine**: institution-configurable multi-step approvals (definitions, instances, steps, delegation, SLA escalation, inbox) with module hooks — used by leaves, condonation, marks changes, registrations, procurement, refunds, certificates, affiliation, grievances, events and more.

## Feature keys
`comms.sms` (on), `comms.whatsapp` (off, standard), `comms.email` (on), `comms.push` (on), `comms.announcements` (on), `comms.announcement_ack` (on, standard), `comms.preferences` (on), `workflow.engine` (on), `workflow.delegation` (on, standard). (Bulk campaigns, bot, AI assistant and emergency broadcast come in Phase 24.)

## Visibility rules
- `notifications`: self only. `notification_preferences`: self. `device_tokens`: self.
- `message_logs`: `communication:view_all` (institution_admin, communication officer) — recipient masked unless `communication:view_pii`.
- `notification_templates`: read for admins; `communication:template_manage` to edit; platform defaults (institution_id NULL) read-only.
- `announcements`: audience-resolved (rules by role/college/department/programme/batch); creators and `communication:view_all` see all + acknowledgement stats.
- `workflow_*`: instances visible to requester (self), current/past approvers (ownership via `workflow_steps.approver_user_id`), and `workflow:view_all` admins; definitions editable with `settings:manage`.

## 04.1 Database tables
Section 23 (`notification_templates, dlt_templates, whatsapp_templates, notification_preferences, notifications, message_logs (+default), announcements, announcement_acknowledgements, conversation_sessions, wa_processed_messages`) and section 6 workflow tables (`workflow_definitions, workflow_instances, workflow_steps, workflow_delegations`) plus `device_tokens` — all exist. Expected delta migration: none.

## 04.2 Alembic migration
`0004_phase04_comms_seed.py` — data-only: platform `notification_templates` (institution_id NULL) for the event catalogue below (en + hi bodies where the pack supplies them), and the 12 shipped `workflow_definitions` templates stored in `platform_settings['workflow_templates']` (copied per institution by `seed_institution_defaults`).

## 04.3 Models
`models/communication.py`: `NotificationTemplate`, `DltTemplate`, `WhatsappTemplate`, `NotificationPreference`, `Notification`, `MessageLog` (partitioned parent), `Announcement`, `AnnouncementAcknowledgement`, `ConversationSession`, `WaProcessedMessage`. Workflow models are in `models/platform.py`. Enums: `Channel`, `MessageStatus`, `WorkflowStatus`, `StepStatus`, `StepDecision`.

## 04.4 Schemas — `app/schemas/communication.py`, `workflow.py`
`TemplateCreate/Update/Response` (event_trigger, channels[], subject_template, body_template, variables[], language, version, dlt_template_id, whatsapp_template_name), `TemplatePreviewRequest{context}`, `DltTemplateCreate/Response`, `WhatsappTemplateCreate/Response`, `PreferenceResponse/Update{category, channels[], quiet_hours{from,to}, digest}`, `NotificationResponse`, `MessageLogResponse` (masked recipient), `SendMessageRequest{event_type|template_id, audience:{user_ids[]|roles[]|college_id|department_id|batch_id|program_id|direct_contacts[]}, context, channels[]}`, `AnnouncementCreate/Update/Response` (+ `ack_stats{total, read, acknowledged}`), `DeviceRegister{provider, platform, token, topics[]}`, `WorkflowDefinitionCreate/Update/Response{module, key, name, steps[]}`, `WorkflowInstanceResponse{entity_type, entity_id, title, status, current_step, steps:[{order, approver, status, acted_by, acted_at, comment, sla_due_at}]}`, `WorkflowActRequest{decision: approve|reject|delegate, comment?, delegate_to?}`, `DelegationCreate/Response`, `InboxItem{instance, entity_summary, route}`.

## 04.5 Repository
`template_repository.py` (resolve template by `(institution_id → NULL fallback, event_trigger, language)` latest active version), `notification_repository.py` (`module="notifications"`, self predicate), `message_log_repository.py` (`module="communication"`), `announcement_repository.py` (audience SQL: rules JSON → predicates over `user_roles`, `students.college_id`, `student_program_enrollments.department_id/program_id/batch_id`), `preference_repository.py`, `device_repository.py`, `workflow_repository.py` (`module="workflow"`; ownership link: steps where `approver_user_id = p.id`; self: `started_by = p.id`).

## 04.6 Services
- `services/notifications/notify.py` — `notify_event(db, institution_id, event_type, *, audience, context, channels=None, priority="normal")`: never raises; writes a `domain_events` row (`notification.requested`) so delivery is at-least-once via the outbox.
- `services/notifications/dispatcher.py` (consumer of `notification.requested`): resolve recipients (`recipients.py`: user ids from audience rules, guardians for student events when `guardian_portal_consent`, direct contacts for applicants), resolve template (institution → platform; language = user locale → institution locale → en), honour `notification_preferences` (channels, quiet hours → defer, digest → batch), render with Jinja2 (`templating.py`, sandboxed, variables validated against `template.variables`), create `notifications` (in-app) + `message_logs` rows per channel, publish WebSocket `notifications:{user}`, enqueue `notifications.deliver` per message (queue `notifications`/`emails`).
- `services/notifications/delivery.py` (task `notifications.deliver`): picks the channel adapter (`integrations.registry.get("SmsProvider", institution_id)` → tenant connection or platform default; `mock` logs), sends, updates `message_logs.status/provider_message_id`; retries with backoff; webhook endpoints update delivery/bounce/read (`/webhooks/sms/{provider}`, `/webhooks/whatsapp`, `/webhooks/email`).
- DLT/WhatsApp compliance: SMS templates must reference a `dlt_templates.template_id` when `comms.sms` provider ≠ mock and pack = IN; WhatsApp template sends require `whatsapp_templates.status='approved'`; session messages only within 24 h of an inbound (`conversation_sessions`).
- `announcement_service.py`: CRUD, publish (audience → in-app + push + optional SMS/email), acknowledgements (`requires_ack`), stats, pin/expire; emits `announcement.published`.
- `device_service.py`: register/unregister tokens; topics per role/college (`role:student`, `college:{id}`).
- `preference_service.py`: get/update; unsubscribe link (signed) for email/SMS marketing categories.
- `core/workflow/engine.py` (complete implementation):
  1. `start(db, institution_id, key, entity_type, entity_id, started_by, context, title)`: load active definition (institution version, else platform template); create instance + resolve step 1 approvers (`role` within scope inferred from `context` — e.g., `{"department_id": …}` → users with role `hod@department`; `scope_rule` expressions `entity.department.hod`, `entity.college.principal`, `requester.manager`; `user`); apply delegations; `sla_due_at = now + sla_hours`; notify approvers (`workflow.step_pending`).
  2. `act(instance_id, actor, decision, comment, delegate_to)`: authorise (actor is a resolved approver or delegate); sequential mode → next step; parallel mode → all must approve (any reject → rejected); on final approve → `approved` + hook `on_approved`; reject → hook `on_rejected`; every action audited + event `workflow.acted`.
  3. `cancel(instance_id, by)` by requester while pending.
  4. `inbox(principal)` → pending steps for the user (direct or delegated) with entity summaries (modules register `summarise(entity_type, id)`).
  5. Escalation (Beat `workflow.escalate` every 15 min): steps past `sla_due_at` → `escalated`, escalate_to resolved, notify; re-escalation after another SLA window.
  6. Hooks: `@engine.on("leave.approval", "approved")` decorators in module services; the engine guarantees hooks run in the same transaction as the status change.
  7. Definitions API: institution admins edit steps (validation: approver types, roles exist, SLA > 0), versioned (new version on edit; running instances keep their version).
- Shipped workflow templates (keys): `leave.approval` (hod → hr_officer), `attendance.condonation` (hod recommend → registrar/principal), `marks.change` (hod → coe), `registration.advisor` (class_advisor), `procurement.indent` (hod → inventory_manager → accounts), `procurement.po` (accounts → principal), `fees.refund` (accountant → principal), `fees.receipt_cancel` (accountant → principal), `certificates.request` (registrar), `regulation.approval` (dean → academic council secretary), `affiliation.application` (registrar → inspection → vc), `grievance.escalation` (grievance_officer → principal), `event.approval` (hod → principal), `facilities.room_booking` (estate_officer), `scholarship.sanction` (accountant → principal), `hr.appraisal` (hod → hr_officer), `phd.request` (guide → research_cell → dean), `no_dues.clearance` (parallel: accounts, library, hostel, department, lab, sports).

Event catalogue (templates seeded; later phases emit them): `auth.password_reset`, `auth.otp`, `auth.welcome`, `announcement.published`, `workflow.step_pending`, `workflow.approved`, `workflow.rejected`, `workflow.escalated`, `admissions.status_changed`, `registration.approved`, `attendance.absent_alert`, `attendance.below_threshold`, `fees.invoice_created`, `fees.payment_received`, `fees.due_reminder`, `exams.hall_ticket_ready`, `results.published`, `results.reval_decided`, `hostel.leave_decided`, `hostel.late_return`, `library.due_reminder`, `placement.drive_published`, `placement.offer_received`, `mentoring.meeting_scheduled`, `grievance.updated`, `emergency.alert`.

## 04.7 Events / jobs
Emits: `notification.requested`, `notification.sent/failed`, `announcement.published`, `workflow.started/acted/approved/rejected/escalated`. Consumers: `notifications.dispatch` ← `notification.requested`; `notifications.workflow` ← `workflow.*` (notify requester/approvers). Beat: `workflow.escalate` (15 min), `notifications.digest` (daily 08:00), `notifications.retry_failed` (10 min), `message_logs.partition_ensure` (monthly). Queues: `notifications`, `emails`.

## 04.8 Endpoints
```
GET/POST /api/v1/communication/templates · GET/PUT /templates/{id} · POST /templates/{id}/preview · POST /templates/{id}/activate [communication:view_all|template_manage]
GET/POST /api/v1/communication/dlt-templates · /whatsapp-templates · POST /whatsapp-templates/{id}/sync-status [communication:template_manage] {comms.sms|comms.whatsapp}
POST     /api/v1/communication/send                            → ad-hoc event send to an audience [communication:send]
GET      /api/v1/communication/logs?channel&status&recipient   → message logs [communication:view_all]
GET      /api/v1/communication/logs/{id}                       → detail with provider response [communication:view_all]
POST     /api/v1/webhooks/{provider}/{channel}                 → delivery/bounce/read callbacks (signature verified) {public}
GET      /api/v1/notifications · POST /notifications/{id}/read · POST /notifications/read-all · GET /notifications/unread-count [auth]
GET/PUT  /api/v1/notification-preferences/me [auth] {comms.preferences}
GET      /api/v1/notification-preferences/unsubscribe?token=   → one-click unsubscribe {public}
POST/DELETE /api/v1/devices                                    → push token register/unregister [auth] {comms.push}
GET/POST /api/v1/announcements · GET/PUT/DELETE /announcements/{id} · POST /announcements/{id}/publish · GET /announcements/{id}/stats [communication:view|create|update|delete|send] {comms.announcements}
POST     /api/v1/announcements/{id}/acknowledge                → read/ack [auth] {comms.announcement_ack}
GET/POST /api/v1/workflow/definitions · GET/PUT /workflow/definitions/{id} · POST /workflow/definitions/{id}/versions [settings:view|manage] {workflow.engine}
GET      /api/v1/workflow/inbox                                → my pending approvals [auth]
GET      /api/v1/workflow/instances?entity_type&entity_id&mine · GET /workflow/instances/{id} [auth, visibility]
POST     /api/v1/workflow/instances/{id}/act                   → approve|reject|delegate [auth, must be approver]
POST     /api/v1/workflow/instances/{id}/cancel                → requester cancels [auth]
GET/POST /api/v1/workflow/delegations · DELETE /workflow/delegations/{id} [auth] {workflow.delegation}
```

## 04.9 Frontend
- `/admin/communications` (tabs **Templates** — list by event, editor with variables palette, bilingual body, channel toggles, DLT/WhatsApp mapping, preview with sample context, versions; **Logs** — DataTable with channel/status filters, masked recipients, provider detail drawer; **Announcements** — list, editor (TipTap), audience builder (roles/college/department/programme/batch), publish, acknowledgement stats; **DLT / WhatsApp** registries; **Send** — ad-hoc send form).
- `NotificationCenter` in the navbar: live list via WS, mark read, deep links; `/notifications` page.
- `/profile/notifications` preferences (categories × channels, quiet hours, digest).
- **Approvals inbox** `/approvals` (DataTable grouped by module with entity summary, approve/reject/delegate drawer with comment); `WorkflowTimeline` component reused inside entity pages (leave, registration, …); `/admin/workflows` (definitions list, step editor with approver type/role/scope-rule/user, SLA, escalation; versions).
- Nav: COMMUNICATION group (Communications, Announcements), MAIN › Approvals (badge with pending count), ADMIN › Workflows.

## 04.10 Mobile
`features/notifications` (inbox, deep links, preferences), `features/announcements` (list, detail, acknowledge), `features/approvals` (inbox tab for approver roles: card list, approve/reject with comment, delegate), device token registration on login.

## 04.11 API verification — `scripts/verify/04_comms_workflow.ps1`
Roles: `inst.admin`, `hod.cse`, `hr`, `faculty.1`, `student.1`, `parent.1`.
1. Templates: `GET /communication/templates?event_trigger=auth.password_reset` → platform template (institution_id null); `POST /templates` institution override v1 → `POST /templates/{id}/preview {context}` renders; activating a second version → resolver returns v2.
2. `POST /communication/send {event_type:"announcement.published", audience:{roles:["student"]}, channels:["in_app","sms"]}` → 202; within 10 s `GET /notifications` as `student.1` shows the item; `message_logs` has `in_app` and `sms(mock)` rows with `status=sent`; `GET /notifications/unread-count` = 1 → `read-all` → 0.
3. Preferences: `student.1` sets `sms` off for category `announcements` → resend → no SMS log for that user; quiet hours `21:00–08:00` with a send inside the window → log `status=deferred` and delivered by the digest/retry job.
4. Announcement with `requires_ack=true` to college A → `student.1` (college A) sees it; `college.admin.b` user does not; `POST /announcements/{id}/acknowledge` → stats `acknowledged=1`.
5. Device: `POST /devices {provider:"fcm", platform:"android", token:"t1"}` → 201; push delivery to mock provider logged on next announcement.
6. DLT: with pack IN and `SMS_PROVIDER=msg91` (dev flag), sending a template without `dlt_template_id` → `message_logs.status=failed` with error `DLT_TEMPLATE_MISSING`; add DLT id → sent.
7. Workflow definitions: `GET /workflow/definitions` shows the 18 shipped templates for the demo institution; `PUT` `leave.approval` to add a second step (`hr_officer`) → new version 2.
8. Workflow run (dev entity): `POST /_dev/workflow/start {key:"leave.approval", context:{department_id:CSE, requester: faculty.1}}` → instance pending, step 1 approver = `hod.cse`; `GET /workflow/inbox` as `hod.cse` shows it; as `faculty.1` empty; `act approve` as `student.1` → 403; as `hod.cse` → step 2 pending for `hr`; `act approve` as `hr` → `approved`, hook `on_approved` executed (dev hook writes a marker), events `workflow.acted`, `workflow.approved` dispatched, requester notified.
9. Delegation: `hod.cse` delegates module `leaves` to `dean.eng` for today; a new instance's inbox shows for `dean.eng`; `dean.eng` approves → step recorded with `acted_by=dean.eng` and `delegated_from=hod.cse`.
10. Escalation: set `sla_hours=0.01` on a definition, start instance, run Beat `workflow.escalate` → step `escalated`, `escalated_to` populated, notification sent.
11. Parallel: start `no_dues.clearance` (dev context) → 6 parallel steps; one reject → instance `rejected` immediately.
12. Webhook: `POST /webhooks/mock/sms {message_id, status:"delivered"}` with valid signature → log updated; invalid signature → 401.

## 04.12 UI verification
1. Communications › Templates: edit, preview, activate version; Logs filter and drawer; Announcements: compose with audience builder, publish, stats update as users acknowledge.
2. Notification bell updates live when an announcement is published in another browser session; deep link opens the announcement.
3. Preferences page saves per category; quiet hours picker.
4. Approvals inbox as `hod.cse`: pending card → approve with comment → disappears; as `hr`: appears; `WorkflowTimeline` on the dev entity page shows both steps with timestamps.
5. Workflows admin: edit steps, add escalation, save → version increments; running instance keeps its version.
6. Mobile: notifications inbox and approvals tab (approve/reject) work against the same data.

## 04.13 Deliverables checklist
- [ ] Notification core: templates (versioned, bilingual, DLT/WhatsApp mapping), dispatcher via outbox, channel adapters (mock + live skeletons), preferences/quiet hours/digest/unsubscribe, logs + webhooks, announcements + acknowledgements, devices, WebSocket bell
- [ ] Workflow engine: definitions (versioned), instances/steps, approver resolution (role@scope, scope rules, users), delegation, sequential/parallel, hooks, inbox, escalation Beat; 18 shipped templates seeded per institution
- [ ] Web pages + approvals inbox + timeline component; mobile inbox/announcements/approvals
- [ ] `scripts/verify/04_comms_workflow.ps1` passes; UI checklist done; guards green; commit `feat(phase-04): communication core & workflow engine`
