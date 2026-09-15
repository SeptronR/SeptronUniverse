# SeptronUniverse — Mobile Application UI Structure (Flutter)

The mobile app mirrors SeptronOrbit's Flutter architecture (Riverpod, go_router, dio, feature-first folders, 11 locales) and adds offline-first behaviour, deep links, a role-based shell with a defined information architecture, and visibility-aware screens (Mine / Dept / All).

## 1. App architecture

```
lib/
  main.dart                  ProviderScope, PushService.init, RemoteConfig.load, date formatting
  app.dart                   MaterialApp.router; watches routerProvider, themeModeProvider, institutionThemeProvider, localeProvider, readOnlyModeProvider
  core/
    config/env.dart          --dart-define APP_API_URL, APP_MAP_TILE_URL, APP_ENV
    constants.dart           kAppName, Roles, statuses, ModuleColors
    providers.dart           secureStorage, dioClient, dio, fileDownloader, connectivity
    network/
      dio_client.dart        interceptors: Bearer + X-Institution-Id/Slug + X-College-Id; envelope unwrap ({success,data,meta}) exposing meta.visibility;
                             single-flight refresh on 401; Idempotency-Key on POST (uuid per submit); retry/backoff on 5xx/network; 503 READ_ONLY handling
      api_exception.dart     maps error-code catalogue (FEATURE_DISABLED, PERMISSION_DENIED, VALIDATION, READ_ONLY…)
      auth_events.dart       force-logout bus
    auth/
      auth_controller.dart   bootstrap → /auth/me → {user, roles, permissions, features, scopes}; login/OTP/SSO; logout (unregister push, clear cache)
      auth_state.dart        can(module, action), hasFeature(key), visibility(module) → {self, scopes}
      biometric_lock.dart    local_auth gate on resume after timeout
      session.dart           session list/revoke (settings)
    router/
      app_router.dart        go_router; redirects: unauth → /login; role shell; permission+feature gate per route; read-only banner
      routes.dart            /app/<module>/<screen> constants
      role_shells.dart       tabsForRole(role) (§3), moreMenuModules (permission + feature + roles)
      screen_registry.dart   single route → widget map (tabs and pushed routes)
      deeplinks.dart         push payload {route, params} → navigation; universal links /verify/:token, /apply/:cycle
    offline/
      db.dart                drift (sqlite) tables: cache_entries(key, json, fetched_at, ttl), write_queue(id, method, path, body, idempotency_key, status, attempts, last_error)
      cache_repository.dart  read-through cache for timetable, attendance summaries, hall ticket PDF path, results, dues, notices, hostel status
      sync_service.dart      flush queue on connectivity; conflict rules; OfflineBanner/SyncStatus providers
    theme/
      tokens.dart            shared JSON tokens (brand ramps, semantic colours, 5 themes, table styles) → ColorScheme
      app_theme.dart         Material 3 light/dark; institution branding (logo, primary)
    l10n/                    11 locales (ARB), nav labels, completeness tests
    notifications/           FCM + local notifications; topics per role/college; inbox provider; deep-link dispatch
    remote_config/           /mobile/config → min_version/force_update, maintenance banner, feature hints
    analytics/               Sentry/Crashlytics + screen/event tracking
    print/                   ESC/POS thermal receipts; PDF viewer/share
    scan/                    QR/barcode scanner (attendance, gate, library, hall-ticket verify)
    payments/                Razorpay SDK + UPI intent
  shared/
    models/                  hand-written models (+ generated for stable read APIs), Paginated<T> with meta.visibility
    utils/                   Fmt (dates/currency/locale), media_url, validators
    widgets/                 catalogue (§4)
  features/<feature>/{data,domain,application,presentation}
```

Gating everywhere: `AuthState.can(module, action)`, `hasFeature(key)`, `visibility(module)`; `moreMenuModules` entries carry `{titleKey, icon, route, color, permission, feature, roles}`; unknown route → `PlaceholderScreen`.

## 2. Global navigation model

1. **Splash → Login** (identifier/password · OTP · SSO button when `security.sso`) → **institution/college picker** for multi-scope users → **role shell**.
2. **Role shell** = bottom `NavigationBar` (≤ 5 tabs) + **More** grid (feature/permission-gated modules) + tab-specific FAB (primary action) + app bar (college/term chip, global search, notifications, profile).
3. **Multi-role users** (e.g., HOD who also teaches): shell of the highest role; "Switch view" in profile; **Approvals inbox** aggregates all workflow items.
4. **Visibility inside screens**: `SegmentedScope` control **Mine | Dept | College | All** driven by `meta.visibility` (hidden when only one scope).
5. **Deep links**: push payload `{route, params}`; cold-start routing after auth; universal links for `/verify` and `/apply`.
6. **Tablet** (`mobile.tablet_layout`): master-detail for HOD/COE/accountant/registrar; landscape grids for marks/attendance.
7. **Read-only mode**: banner; write actions disabled with tooltip.

## 3. Role shells (tabs → screens)

### 3.1 Student
| Tab | Screens |
|---|---|
| **Home** | Today's classes (from cache), attendance ring, dues chip, holds banner, notices, quick actions (pay, out-pass, hall ticket), risk/standing badge |
| **Academics** | Timetable (week/day), Attendance (per course, shortfall calculator, QR check-in, OD request, condonation request), Registration (cart, electives priority list, arrears, credit meter, submit), Courses → LMS (modules/content viewer, assignments submit, quizzes, discussions, announcements), Marks (internal components, CO progress), Projects |
| **Exams** | Sessions, Register & pay, Hall ticket (offline PDF, QR), Seating, Results (SGPA/CGPA trend), Grade cards, Revaluation/photocopy requests, Supplementary registration, Transcripts requests, Malpractice notices |
| **Fees** | Dues by head/instalment, Pay (UPI/gateway), Receipts (download/share), Scholarships (apply/track), No-dues status, Refund status |
| **More** | Hostel (apply, allocation, out-pass with guardian OTP status, mess plan/attendance/bills, complaints, room change, visitors), Library (my books, renew, OPAC, fines), Placement (profile & resume builder, drives, applications, rounds, offers, internships, training), Mentor (sessions, book slot), Surveys, Grievances (incl. anonymous), Clubs & activity hours, Certificates & requests, ID card (QR), Credit transfers (MOOC), Convocation & degree, Alumni (after exit), Profile & undertakings, Settings (language, theme, biometric lock, notifications, sessions) |

### 3.2 Parent
| Tab | Screens |
|---|---|
| **Home** | Ward switcher, attendance, dues, notices, alerts (absence, low attendance, hold) |
| **Academics** | Attendance per course, Results/grade cards, Timetable, Marks |
| **Fees** | Dues, Pay, Receipts |
| **More** | Hostel (out-pass consent OTP, status), Transport live, Mentor meeting booking, Surveys, Grievances, Notices with acknowledgement, Profile |

### 3.3 Faculty
| Tab | Screens |
|---|---|
| **Home** | Today's sessions, pending tasks (marks deadlines, approvals), mentee alerts, invigilation duties, evaluator bundles |
| **Attendance** | Session list (today/date) → tap-mark grid (cycle statuses), QR mode (projected code), offline queue status, extra class, finalize |
| **Marks** | Offerings → assessments → question-wise entry grid (numpad, keyboard), absent/exempt toggles, submit; CO heatmap preview; change requests |
| **Courses** | LMS (modules/content upload, assignments grading with rubric, quizzes, announcements, discussions), Lesson plan tick-off, Course file checklist, Projects & reviews |
| **More** | My timetable, Mentees (360°, logs, risk flags, referrals), Advisee registrations approval, Leaves (apply/balance) & My attendance, Payslips, Workload, Research profile (publications, projects, incentives), Duties (invigilation swaps), Evaluator bundles (dummy numbers, per-question entry), Survey results, Appraisal (PBAS), Approvals inbox, Events, Profile |

### 3.4 HOD / Dean
| Tab | Screens |
|---|---|
| **Home** | Department/faculty KPIs (attendance %, marks submission status, pending approvals, risk students) |
| **Approvals** | Workflow inbox: leaves, condonation, marks verify, registrations, indents, change requests, events |
| **Department** | Staff, Students (Dept scope), Offerings & allocation, Workload, Attendance/marks monitoring |
| **Reports** | Department reports, accreditation metrics (dept) |
| **More** | Timetable, BoS meetings/minutes, budgets, events, + all faculty screens (self) |

### 3.5 Registrar / Institution admin
| Tab | Screens |
|---|---|
| **Home** | Institution KPIs (admissions, enrolment, dues, exams status, holds) |
| **Approvals** | Workflow inbox |
| **Students** | Global search → 360° (enrolment, attendance, results, dues, holds, hostel, documents, undertakings) |
| **Reports** | Registry of reports, statutory exports (web preferred) |
| **More** | Admissions cycle status, Affiliation (university), Certificates queue, Holds, Announcements (with acknowledgement stats), Settings & Features (read-only), Integrations health, Read-only mode toggle |

### 3.6 Controller of Examinations / exam cell
| Tab | Screens |
|---|---|
| **Home** | Session status board (registrations, hall tickets, valuation %, discrepancies, results stage) |
| **Sessions** | Papers & date-sheet (clash badge), Registrations, Eligibility apply, Hall tickets job, Seating, Invigilation roster |
| **Valuation** | Bundles & custody, Assignments, Discrepancies, Moderation proposals, Decode (decoder role) |
| **Results** | Runs, anomaly review, verify/approve/publish, Reval queue, Malpractice cases |
| **More** | QP management (invite/scrutiny/print log), Remuneration, Exam audit, Reports |

### 3.7 Accountant
| Tab | Screens |
|---|---|
| **Home** | Today's collections by mode, dues summary, pending reconciliation, receipt cancellations pending |
| **Collect** | Search student → dues → collect (cash/UPI QR/card/challan) → receipt → thermal print/share |
| **Fees** | Invoices, Receipts, Refunds, Scholarships disbursement, No-dues sign-offs, Offline reconciliation (UTR) |
| **HR** | **All staff · All leaves · All staff attendance** with **Mine** segment (own leaves/attendance) |
| **More** | Payroll runs & payslips, Accounting/budgets, Vendor bills, Tally export, Reports, Profile |

### 3.8 HR officer
Home · Staff · Leaves (All + Approvals + Mine) · Attendance (devices, All + Mine) · More (Payroll, Recruitment, Appraisals, CAS, Service book).

### 3.9 Admissions officer
Home · Applicants (verification queue, docs) · Merit/Counselling · Enquiries · More (seat status, offers, imports).

### 3.10 Placement officer
Home · Drives (funnel by round) · Students (eligibility, overrides) · Companies (recruiters) · More (offers, internships, training, stats).

### 3.11 Hostel warden / gate staff
| Tab | Screens |
|---|---|
| **Home** | Occupancy, pending out-passes, late returns, complaints |
| **Out-passes** | Approve/reject; **Gate scan** (QR mark-out/return), late list; guardian consent status |
| **Residents** | Rooms/beds map, allocations, check-in/vacate, room changes, roll call, discipline |
| **Mess** | Plans, subscriptions, attendance, rebates, bills |
| **More** | Visitors, Staff quarters, Fees, Reports |
Gate staff shell: **Gate scan** · **Today** (expected out/in) · **Settings** only.

### 3.12 Librarian
Home · Circulation (scan issue/return/renew) · Catalogue · Members · More (reservations, fines, e-resources, reports).

### 3.13 IQAC coordinator
Home (criteria completion) · Metrics · Evidence (camera upload) · Cycles · More (surveys, audits, exports).

### 3.14 Research scholar (PhD)
Home · Progress (reports, DC meetings) · Thesis (uploads, similarity, examiners, viva) · Fellowship · More (coursework, requests, publications, profile).

### 3.15 Alumni
Home · Directory (consent-filtered) · Events · Give (campaigns/donations) · Profile (employment, mentorship flags, jobs board, transcript requests).

### 3.16 Driver
Home · Route (trip start/stop, stops, GPS queue) · Settings.

### 3.17 External examiner
Bundles · Entry (dummy numbers, question-wise) · Profile (remuneration).

### 3.18 Recruiter
Drives · Applicants (consented fields) · Rounds · Offers · Profile.

### 3.19 Super admin / support agent
Institutions · Features (toggle) · Health · Impersonate (audited; web-first, mobile read-mostly).

## 4. Shared widget catalogue

`StatCard`, `ModuleCard`, `ActionTile`, `ApprovalCard` (workflow item with approve/reject/delegate), `FilterChipBar`, `SegmentedScope` (Mine/Dept/College/All), `SearchField`, `DetailRow`, `Timeline`, `AttendanceRing`, `ShortfallCalculator`, `GradeBadge`, `DueChip`, `HoldBanner`, `StandingBadge`, `QRScannerSheet`, `QRCodeCard` (ID/hall ticket), `OfflineBanner`/`SyncStatus`, `PdfViewerScreen`, `ReceiptPrintSheet`, `MarksEntryGrid` (numpad/keyboard, question-wise, absent/exempt), `AttendanceGrid` (tap-cycle statuses, bulk present), `TimetableWeek`/`TimetableDay`, `CalendarStrip`, `EmptyStateIllustration`, `Skeletons`, `ConfirmDialog`, `BottomSheetPicker`, `WardSwitcher`, `CollegeTermChip`, `NotificationTile`, `JobProgressTile`, `ReadOnlyBanner`, `FeatureHint`.

## 5. Cross-cutting behaviours

- **UX principles**: ≤ 3 taps to any daily action (mark attendance, pay, out-pass, hall ticket); large touch targets in grids; primary FAB within thumb reach; consistent empty/error/offline states; dark mode; font scaling & semantics (a11y).
- **Offline-first reads** with stale badges (cache TTL per model: timetable 24 h, attendance summary 6 h, hall ticket PDF until session end, results 24 h, dues 1 h).
- **Write queue**: attendance marks, GPS pings, gate scans, out-pass decisions, mess attendance; per-item status; idempotent (server dedupes by `Idempotency-Key`); conflicts: server wins for finalized sessions; otherwise the app prompts.
- **Push deep links**: notification → route; grouped channels (academics, fees, exams, hostel, approvals, emergency).
- **Security**: biometric app lock; session timeout; secure storage; certificate pinning optional; screenshots blocked on marks/valuation screens; PII masked per `meta.pii`.
- **Remote config**: force update, maintenance banner, feature hints; read-only mode.
- **Branding**: institution logo/colours; 5 named themes identical to web; light/dark.
- **Payments**: UPI intent (Google Pay/PhonePe/BHIM) + gateway SDK; receipts cached.
- **Scanning**: QR for attendance/gate/library/hall-ticket verify; barcode for library.
- **Printing**: ESC/POS thermal receipts (fee counter); PDF share for hall tickets/grade cards.
- **Localisation**: 11 locales; language switch; no hard-coded strings (test).
- **Analytics & crash reporting**; **release**: Fastlane/Codemagic; phased rollout; crash-free ≥ 99.5 %.

## 6. Verification (API + UI, per phase)

For each screen added in a phase: (1) the screen is registered and reachable from its tab/More grid only for allowed roles & enabled features; (2) it renders from a cold start via deep link; (3) its list screens honour `meta.visibility` (segment options match the API); (4) offline: with airplane mode the cached read renders and queued writes flush on reconnect without duplicates; (5) golden tests for the shell per role; (6) l10n completeness passes.
