# PHASE 10 — TIMETABLE & ROOMS

## Pre-Requisite
Phases 01–09 complete (offerings with faculty and targets, registration rosters, HR leaves emitting `leave.approved`, holidays).

## Objective
Offering-based timetabling: buildings and rooms/labs (capacity, exam capacity, features, bookable flag), time-slot groups, per-scope versioned timetables (section/batch/department) with entries that reference **course offerings**, conflict detection for room/faculty/section (partial unique indexes + pre-checks), week patterns and multi-slot spans, publish → generation of `class_sessions` for every term date (minus holidays), substitutions (manual and auto-requested from approved leave), faculty/room/section/"my" weekly views, iCal feeds, optional constraint-based auto-generation (stretch, flagged).

## Feature keys
`timetable.core`, `timetable.rooms`, `timetable.ical` (on, starter); `timetable.substitutions` (on, standard; depends `hr.leaves`); `timetable.auto_generate` (off, professional).

## Visibility rules
- Rooms/slots: institution-wide read; `timetable:manage` (registrar, estate_officer, HOD for department labs) to edit.
- Timetables/entries: institution-wide read for staff; students see timetables of their section/batch (self via term record); parents wards'; faculty "my timetable" (ownership `timetable_entries.staff_id`); `timetable:create|publish` for HOD @department, registrar @institution, `college_admin` @college.
- Sessions: faculty own sessions (ownership `class_sessions.staff_id`), students own offerings' sessions, HOD department, registrar all.

## 10.1 Database tables
Section 12: `buildings, rooms, time_slots, timetables, timetable_entries, timetable_substitutions, class_sessions` (+ `holidays`, `course_offerings`, `course_offering_faculty`) — exist. Expected delta migration: none.

## 10.2 Alembic migration
`0010_phase10_timetable_seed.py` — data-only: default slot group template (P1–P8, breaks) per institution via settings template. Demo seed `--only timetable`: 2 buildings, 30 rooms (6 labs, 1 auditorium, 4 exam halls), slot group, published timetables for all 2024/2025 sections, sessions generated for the current term, 3 substitutions.

## 10.3 Models — `models/timetable.py`
`Building`, `Room`, `TimeSlot`, `Timetable`, `TimetableEntry`, `TimetableSubstitution`, `ClassSession`. Enums: `RoomType`, `SlotType`, `TimetableScope`, `TimetableStatus`, `SessionType`, `WeekPattern`, `SubstitutionStatus`, `SessionStatus`, `AttendanceStatus` (session-level).

## 10.4 Schemas — `app/schemas/timetable.py`
`BuildingIn/Out`, `RoomIn/Out` (+ `features` JSON, `is_bookable`), `SlotGroupReplace{slot_group, slots:[…]}`, `TimetableCreate{term_id, scope_type, scope_id, name, base_version_id?}`, `TimetableResponse` (+ entries), `EntryCreate/Update` (offering, section, day, slot, room, staff, type, week pattern, span), `ConflictReport{room[], staff[], section[], capacity[]}`, `PublishRequest{effective_from, regenerate_sessions: bool}`, `WeeklyView{days:[{slots:[{entry…}]}]}` for faculty/section/room/me, `SubstitutionCreate{entry_id, on_date, substitute_staff_id?, reason}`, `SubstitutionDecision`, `SessionResponse`, `ExtraSessionCreate{offering_id, date, start, end, room_id?, topic}`, `SessionUpdate{status, topic, room_id, online_link}`, `AutoGenerateRequest{constraints…}`, `ICalToken`.

## 10.5 Repository
`room_repository.py` (`module="timetable"`), `slot_repository.py`, `timetable_repository.py` (`module="timetable"`; scope columns institution/college/department via scope; entries with `selectinload(offering.course, room, staff)`), `session_repository.py` (`module="attendance"` shared with Phase 11; ownership `staff_id`; students via confirmed items), `substitution_repository.py`.

## 10.6 Services
- `room_service.py`: buildings/rooms CRUD (code unique per college; `exam_capacity ≤ capacity`; features tags for solver), slot groups (non-overlapping, ordered), room availability query (date range × slot).
- `timetable_service.py`
  1. Create draft for a scope (section/batch/department) — optionally cloning `base_version_id` entries (new version).
  2. `add/update entry`: pre-check conflicts with an explicit query (room, staff, section for the same term/day/slot/week-pattern including `slot_span` expansion and other scopes' published timetables) → return `ConflictReport` (409 when hard conflict; capacity warning when `room.capacity < roster size`); partial unique indexes are the last line of defence.
  3. Entries for an offering must reference a staff in `course_offering_faculty` (or a TA) and a section in `course_offering_targets` (when scope = section).
  4. `publish(effective_from, regenerate)`: validate no conflicts; previous published version → `archived`; **generate sessions**: for each entry × each date in `[effective_from, term.end_date]` on `day_of_week`, skipping `holidays` (college scope + applies_to students/all) and respecting `week_pattern` (odd/even ISO weeks) and `slot_span` (start/end from slots); existing `conducted/finalized` sessions preserved; future `scheduled` sessions replaced; emits `timetable.published`.
  5. Views: `weekly(scope, id, week)`; `my_timetable(principal)` — faculty by `staff_id`, student by section/batch of the current term record, room by id; today's sessions for dashboards.
  6. iCal: per-user signed token feed (`calendar_feed_tokens`, Phase 25 table — create here if absent in this phase's manifest: it is in §24; include in `phase_manifest["10"]`) `GET /timetables/ical/{token}.ics` and section/room feeds.
- `substitution_service.py`: manual request (HOD/faculty) → approval (HOD) → session `staff_id` swapped for that date, notify both; **auto from leave**: consumer of `leave.approved` creates `requested` rows (`source='leave_auto'`) for every session of the staff in the leave range and notifies HOD; on leave cancellation → substitutions withdrawn.
- `session_service.py`: extra/remedial session creation (conflict check for room/staff), cancel/reschedule (only when `attendance_status='not_taken'`), online link update, `today(principal)`; sessions are the anchor for attendance (Phase 11), lesson-plan delivery (Phase 13) and guest-faculty remuneration (Phase 06 payroll reads `conducted` sessions × `hourly_rate_paise`).
- `auto_generate_service.py` (flag): job that builds a CP-SAT model (`ortools`) with hard constraints (room/staff/section clashes, room type/capacity, faculty unavailability from settings, max consecutive slots) and soft constraints (preferences, spread); writes a draft timetable; document that this is optional and can be delivered later.

## 10.7 Events / jobs
Emits: `timetable.published`, `timetable.entry_changed`, `session.created/cancelled/rescheduled`, `substitution.requested/approved/rejected`. Consumers: Phase 11 `attendance.sessions_ready` ← `timetable.published`; notifications (published timetable to students/faculty, substitution decisions); `leave.approved` → `substitution.auto_request` (this phase); `holiday.changed` → `sessions.regenerate_future`. Jobs: `timetable.generate_sessions`, `timetable.auto_generate`, `timetable.export`. Beat: `sessions.mark_missed` (nightly: `scheduled` sessions past end without attendance → `status='conducted', attendance_status='not_taken'` flagged for follow-up; setting). Workflow: `timetable.substitution` (HOD approval) optional definition.

## 10.8 Endpoints
```
GET/POST /api/v1/buildings · PUT/DELETE /buildings/{id} [timetable:manage] {timetable.rooms}
GET/POST /api/v1/rooms · GET/PUT/DELETE /rooms/{id} · GET /rooms/availability?date&slot_id&type [timetable:view|manage]
GET/PUT  /api/v1/time-slots?slot_group= [timetable:view|manage]
GET/POST /api/v1/timetables · GET /timetables/{id} · POST /timetables/{id}/clone · DELETE (draft only) [timetable:view|create] {timetable.core}
POST     /api/v1/timetables/{id}/entries · PUT/DELETE /timetables/{id}/entries/{eid} · POST /timetables/{id}/check-conflicts [timetable:create]
POST     /api/v1/timetables/{id}/publish · POST /timetables/{id}/archive [timetable:publish]
POST     /api/v1/timetables/{id}/auto-generate (job) [timetable:generate] {timetable.auto_generate}
GET      /api/v1/timetables/view?scope=section|batch|department|faculty|room&id=&week= · GET /timetables/me?week= [timetable:view|auth]
GET      /api/v1/timetables/ical/{token}.ics · POST /timetables/ical/token (mine) · GET /timetables/sections/{id}.ics {public with token} {timetable.ical}
GET/POST /api/v1/substitutions · POST /substitutions/{id}/approve|reject|withdraw [timetable:substitute|view] {timetable.substitutions}
GET      /api/v1/class-sessions?offering_id&date&staff_id&section_id · GET /class-sessions/today [attendance:view|self]
POST     /api/v1/class-sessions/extra · PUT /class-sessions/{id} · POST /class-sessions/{id}/cancel|reschedule [attendance:mark|timetable:manage]
```

## 10.9 Frontend
- `/admin/facilities/rooms` (buildings tree, rooms table with type/capacity/features, availability finder), `/admin/timetable/slots` (slot group editor), `/admin/timetable/:termId` (scope picker → versions list → editor: weekly grid with drag-drop of offerings from a side palette (filtered by target section), cell shows course/faculty/room, conflict badges live from check-conflicts, capacity warnings, span/week-pattern controls, publish dialog with effective date and session regeneration summary; faculty view / room view switches; print), `/admin/timetable/substitutions` (queue with leave-auto badge, approve with substitute picker showing availability), `/admin/timetable/sessions` (per offering list: date, slot, room, status; extra session; cancel/reschedule).
- Faculty `/faculty/timetable` (my week, today's sessions with quick links to attendance), student portal `/student/timetable` (week/day; iCal subscribe button), parent ward timetable, room display page `/rooms/:id/today` (kiosk).
- Nav: ACADEMICS › Timetable, Rooms & Slots, Substitutions, Sessions.

## 10.10 Mobile
Student: Academics › Timetable (week/day, today card on Home, cached offline 24 h); Faculty: Home today's sessions → attendance (Phase 11), More › My timetable, substitution requests/approvals (HOD); Room display not on mobile.

## 10.11 API verification — `scripts/verify/10_timetable.ps1`
Roles: `registrar`, `hod.cse`, `faculty.1`, `faculty.2`, `student.1`, `estate` (estate_officer), `parent.1`.
1. Seed `--only timetable`; `POST /rooms` as `estate` → 201; `exam_capacity > capacity` → 422; duplicate code in college → 409.
2. Slot group with overlapping times → 422.
3. Draft timetable for section CSE-2024-A; add entry offering X (faculty.1, room R1, Mon P1) → 201; second entry same room/day/slot other section → `POST check-conflicts` reports `room` conflict; forcing insert → 409 (`CONFLICT`); same faculty other room same slot → `staff` conflict; entry with `slot_span=2` P1 → occupies P1–P2 (conflict with P2 entry detected); `week_pattern=odd` vs `even` same slot → no conflict.
4. Entry with staff not in `course_offering_faculty` → 422; room capacity 40 < roster 60 → `warnings.capacity`.
5. Publish (effective today) → `class_sessions` generated: count = entries × matching dates − holidays; holiday on a Monday → no session that day; odd-week entry → sessions only on odd ISO weeks; republish version 2 with a changed entry → future sessions regenerated, past `conducted` untouched.
6. Views: `GET /timetables/me` as `faculty.1` → own entries; as `student.1` → section entries; as `parent.1` for ward → 200; `GET /timetables/view?scope=room&id=R1` → entries; `GET /class-sessions/today` as `faculty.1` → today's sessions.
7. iCal: create token → `GET /timetables/ical/{token}.ics` returns VEVENTs equal to next 30 days of sessions; revoked token → 404.
8. Substitution: manual request for `faculty.1` on a date with substitute `faculty.2` → HOD approve → that session's `staff_id=faculty.2`, both notified; approve a substitute who has a clash at that slot → 409.
9. Auto from leave: approve a leave for `faculty.1` (Phase 06) covering 2 sessions → 2 `substitutions(source=leave_auto, status=requested)` and HOD notified; cancel the leave → substitutions `withdrawn`.
10. Extra session on a room busy at that time → 409; on a free room → 201; cancel a session after attendance finalized (dev-mark) → 409 `RECORD_LOCKED`.
11. Holiday added later (`holiday.changed`) → future sessions on that date removed (`sessions.regenerate_future`).
12. Auto-generate with feature off → 403; on (if implemented) → draft timetable without hard conflicts.

## 10.12 UI verification
1. Timetable editor: drag offering into a cell, live conflict badges, capacity warning, span control, publish dialog summary; version list; faculty/room views; print layout.
2. Substitutions queue shows leave-auto items with the leave reference; approve with availability-aware picker.
3. Sessions page: extra session, cancel/reschedule with lock messages.
4. Faculty and student timetable pages; iCal subscribe; parent ward timetable; room kiosk page.
5. Mobile: student timetable offline (airplane mode shows cached week); faculty today's sessions.

## 10.13 Deliverables checklist
- [ ] Rooms/buildings/slots; timetables with versions, conflict pre-checks + DB uniques, publish → session generation honouring holidays/week patterns/spans; weekly views; iCal feeds; substitutions (manual + auto from leave); sessions (extra/cancel/reschedule/today); optional auto-generate job
- [ ] Events/jobs/Beat; ownership links (faculty sessions/entries); demo seed `--only timetable`
- [ ] Web + mobile; `scripts/verify/10_timetable.ps1` passes; UI checklist done; guards green; commit `feat(phase-10): timetable & rooms`
