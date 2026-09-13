# PHASE 19 — LIBRARY

## Pre-Requisite
Phases 01–12 complete (students/staff masters, fee linkage + `fine_configurations`, no-dues clearance workflow, holidays, number sequences, integration connections). Phases 13–18 are not required. Round 3 phases (19–26) may be built in parallel; each has its own Alembic revision and disjoint models.

## Objective
A complete academic library: catalogue (books, journals, theses, e-books, reference), copies with accession numbers/barcodes/RFID, members auto-provisioned from students/staff/scholars/alumni with per-type loan rules, circulation (issue/return/renew by scan, due dates skipping holidays, reservations queue with hold expiry), **fines through the fee-linkage** (`source_type='library_fine'`, lost-book replacement cost), library holds on chronic defaulters, OPAC (public search + availability), e-resources (IP/remote access, subscription costs for NAAC 4.2), inter-library loans, Koha/DSpace sync adapters (mock + live), no-dues sign-off, stock verification and statutory registers — with **My library** (self) vs librarian (all) views.

## Feature keys
`library.core`, `library.opac`, `library.fines` (on, starter); `library.eresources`, `library.rfid_barcode` (on, standard); `library.inter_library_loan`, `library.koha_sync` (off, professional; `koha_sync` depends `integrations.koha_dspace_shodhganga`).

## Visibility rules
| Role | Catalogue / OPAC | Members | Issues, reservations, fines | Reports |
|---|---|---|---|---|
| student / scholar / faculty / staff / alumni | public + availability | **S** (own card, limits, validity) | **S** (my books, due dates, renew, reserve, fines, pay) | — |
| parent | public | W | W (ward issues/fines; pay) | — |
| librarian | A (manage) | A (create/suspend, rules) | **A** (circulate, fines waive/collect, lost, ILL) | A |
| hod | public | D (read members of department) | D (read overdue of department students) | D (overdue lists) |
| accountant | — | — | A (fine invoices/receipts only) | fine collections |
| college_admin | C | C | C (read) | C |
| iqac | — | — | — | A (NAAC 4.2 metrics) |
| auditor | A (read) | A (read) | A (read) | A (read) |

## 19.1 Database tables
Section 18: `book_categories, books, library_copies, library_eresources, library_members, book_issues, library_reservations, library_ill_requests`; uses `fee_invoices, fine_configurations, no_dues_requests, no_dues_signoffs` (§13), `student_holds` (§8), `holidays, number_sequences` (§2), `integration_connections` (§6), `metric_values` (§29 — Phase 32 computes from these tables). Expected delta migration: none.

## 19.2 Alembic migration
`0019_phase19_library_seed.py` — data-only: default `book_categories` (DDC top classes), default member rules per `member_type` in `institution_settings['library.member_rules']` (student 3 books/14 days, faculty 10/30, scholar 6/30, staff 3/14, alumni 2/14 + deposit, external 1/7), `fine_configurations(applies_to='library_overdue', per_day ₹2, grace 0, max ₹500)`, `number_sequences` scope `lib:acc` (`ACC{000000}`) and `lib:member` (`LM{yy}{00000}`), notification templates (`library.issued`, `library.due_reminder` exists, `library.overdue`, `library.reservation_available`, `library.fine_created`). Demo seed `--only library`: 1,200 books (50 categories, ISBNs, trigram-searchable titles) with 3,000 copies (barcodes), 20 e-resources (2 expired), members for all active students/staff, 400 issues (60 overdue, 15 lost), 40 reservations (5 `available` expiring), 10 ILL requests, one no-dues request with a pending library sign-off.

## 19.3 Models — `models/library.py`
`BookCategory`, `Book`, `LibraryCopy`, `LibraryEresource`, `LibraryMember`, `BookIssue`, `LibraryReservation`, `LibraryIllRequest`. Enums: `ResourceType`, `CopyStatus` (available|issued|reserved|lost|damaged|withdrawn|reference_only), `MemberType`, `IssueStatus` (issued|returned|overdue|lost), `ReservationStatus` (waiting|available|fulfilled|cancelled|expired), `IllStatus` (requested|approved|received|returned|cancelled).

## 19.4 Schemas — `app/schemas/library.py`
`CategoryIn/Out`, `BookCreate/Update/Response` (+ copies summary, availability), `BookImportRequest{file_url, mapping}` (CSV/MARC-lite) + `ImportReport`, `CopyBulkCreate{book_id, count, location, price?, barcode_prefix?}` + `CopyResponse`, `CopyStatusChange{status, remarks}`, `EresourceIn/Out`, `MemberResponse{member_code, type, limits, valid_to, active_issues, outstanding_fine_paise, is_blocked, block_reasons[]}`, `MemberRulesUpdate`, `IssueRequest{member_code|user_id, barcode|accession_number|rfid_tag, due_on?}` + `IssueResponse`, `ReturnRequest{barcode|accession_number|rfid_tag, condition?}` + `ReturnResponse{fine_paise, invoice_id?, reservation_notified}`, `RenewRequest{issue_id}`, `LostRequest{issue_id, replacement_cost_paise?}`, `ReservationCreate{book_id}` + `ReservationResponse{position, expires_at}`, `FineWaiveRequest{issue_id, reason}`, `IllRequestIn/Decision`, `OpacQuery{q, category, author, year, resource_type, available_only}` + `OpacResult`, `StockVerificationRequest{location?, scanned_barcodes[]}` + `StockVerificationReport{found, missing[], unexpected[]}`, `KohaSyncRequest{direction, since}` + `SyncSummary`, `LibraryStatsResponse`.

## 19.5 Repository
`library_repository.py` (`module="library"`; self predicate for members/issues/reservations/fines via `library_members.user_id = principal.user_id`; wards via `student_guardians`; department via student enrolment or staff department when `view_all` scoped; `FOR UPDATE` on `library_copies` during issue/return and on `books.available_copies` counters), `catalogue_repository.py` (trigram search on title/authors/isbn/subject; facets), `member_repository.py`, `eresource_repository.py`. Ownership: none beyond self/wards; librarian is `view_all` at institution or college scope.

## 19.6 Services
- `catalogue_service.py`: books CRUD with `authors` JSONB array, ISBN normalisation (10→13), duplicate-ISBN warning (not block), categories tree, `total_copies/available_copies` maintained only through copy transactions (never edited directly); bulk copy creation with accession numbers from `number_sequences('lib:acc')` and barcodes (= accession number unless supplied); copy status changes (`damaged|withdrawn|reference_only`) with audit; CSV/MARC-lite import as job with report; cover fetch optional via adapter; `is_public` implicit — OPAC shows all active books.
- `member_service.py`: auto-provision on `student.activated` / `staff.joined` / `scholar.registered` / `alumni.created` events with rules from `institution_settings['library.member_rules']`; `valid_to` = enrolment expected exit or staff contract end; manual external members (deposit invoice optional); `is_blocked` computed: outstanding fines > `block_fine_threshold_paise` (setting), overdue items > `block_overdue_days`, `student_holds(hold_type in ('library','all'))`, membership expired/suspended; block reasons returned for the counter UI.
- `circulation_service.py` (`library.core`, `library.rfid_barcode` for scan endpoints)
  1. `issue(member, copy)`: checks member active & not blocked, copy `available` (not `reference_only`), `active_issues < max_books_allowed`, no other active issue of the same book by the member (setting); `due_on = issued_on + loan_days` moved forward past `holidays` and weekly-off (setting); if the book has `library_reservations` in `waiting/available` and the member is not the first eligible reservation holder → 409 `RESERVED_FOR_OTHER`; copy → `issued`, counters `-1`; emits `library.issued`; `Idempotency-Key` honoured.
  2. `return(copy, condition)`: locates the active issue; `fine = compute_fine(days_overdue)` from `fine_configurations(library_overdue)` (`per_day` × days after `grace_days`, capped at `max_paise`; slabs supported) → when > 0 create invoice `fee_service.create_invoice(payer=member person, source_type='library_fine', source_id=issue.id)` and store `fine_paise/fine_invoice_id`; `damaged` condition → copy `damaged` + optional damage charge; issue → `returned`; copy → `available` unless a `waiting` reservation exists → copy `reserved` and the first reservation → `available` with `expires_at = now + hold_hours` (48 h default) + notification; counters `+1` only when truly available.
  3. `renew(issue)`: allowed if `renewals < max_renewals` (rule), no waiting reservation on the book, not overdue beyond grace, member not blocked; new `due_on` from today; else 409 with reason.
  4. `mark_lost(issue, cost)`: issue → `lost`, copy → `lost`, replacement invoice (`price_paise` × replacement factor from setting, or given) `source_type='library_fine'` with item label `Lost book`; counters adjusted; can be reverted by `found` (return with condition).
  5. Reservations: create only when `available_copies = 0` (setting `allow_reserve_available=false`), one active per book per member (UNIQUE), FIFO position; `available` expires by Beat → next in queue; `fulfilled` on issue to that member; cancel by member.
  6. Fines: computed on return; `waive(issue, reason)` (librarian `library:fines`, audited; cancels/credit-notes the invoice via Phase 12 `fees.cancel_invoice`); payment through Phase 12 (counter/online); `library.fine_created` notification; outstanding fines visible on member card.
  7. Overdue processing (Beat): issues past `due_on` → `overdue` + reminders on D-3, D0, D+7, weekly; when overdue days > `hold_after_days` (setting, default 30) → `student_holds(hold_type='library', source_type='book_issue')` for students (released on return/settlement); staff → HR notification.
  8. Scan resolution: `barcode|accession_number|rfid_tag` → copy; member by `member_code`, user id, or ID-card QR (Phase 07 token).
- `opac_service.py` (`library.opac`): public search (`GET /opac/search`) with trigram ranking, facets (category, author, year, language, resource type), availability counts and copy locations; new arrivals; authenticated users see their own reservation eligibility; rate-limited.
- `eresource_service.py` (`library.eresources`): registry with access type (`ip|remote|open`), subscription period, cost; remote-access link proxied through an authenticated redirect (`/eresources/{id}/open`) that logs usage counts (for NAAC 4.2.4); expiry reminders 30 days before `subscription_to`.
- `ill_service.py` (`library.inter_library_loan`): member request → librarian approve (cost) → received (temporary copy record with `resource_type='ill'` and `withdrawn` on return) → returned; fee invoice optional.
- `sync_service.py` (`library.koha_sync`): `KohaAdapter` (REST: biblios, items, patrons, checkouts) and `DSpaceAdapter` (theses/ETD metadata pull) behind `integrations.koha_dspace_shodhganga` connection; import creates/updates books/copies keyed by `external_ref`; conflict rule: local circulation wins, catalogue fields from Koha win; mock adapters return fixtures.
- `no_dues_hook`: `@engine.on("no_dues.clearance", step="library")` auto-signs `cleared` when the member has no active issues and no outstanding fine invoices, else `dues_pending` with `dues_paise`; librarian can override manually (`no_dues:approve` library step).
- `reports_service.py`: accession register, circulation statistics (per day/member type/category), overdue list (department-wise for HODs), stock verification (scan list vs expected per location → missing/unexpected), e-resource usage, NAAC 4.2 metrics (`books_added`, `library_expenditure_paise`, `eresources_count`, `footfall` if gate counter integrated) published to Phase 32 via `metrics.publish`.

## 19.7 Events / jobs
Emits: `library.member_created/blocked/unblocked`, `library.issued/returned/renewed/overdue/lost`, `library.reservation_created/available/fulfilled/expired`, `library.fine_created/waived`, `library.eresource_expiring`, `library.ill_updated`. Consumers: notifications (issued receipt, due reminders, overdue, reservation available, fines), Phase 07 holds (`library.hold_requested/released`), Phase 12 (invoices; `fees.payment_received` for `library_fine` → member card refresh), Phase 32 metrics, Phase 27 (fines feed discipline? no — read-only). Jobs: `library.import_catalogue`, `library.bulk_copies`, `library.stock_verification`, `library.koha_sync`, `library.reports_export`. Beat: `library.overdue_scan` (nightly 01:00: overdue statuses, reminders, holds), `library.reservation_expiry` (hourly), `library.eresource_expiry_reminders` (daily), `library.membership_expiry` (daily; alumni/external validity). Workflow: none new (participates in `no_dues.clearance` library step).

## 19.8 Endpoints
```
GET/POST /api/v1/library/categories · PUT/DELETE /library/categories/{id} [library:manage] {library.core}
GET/POST /api/v1/library/books · GET/PUT/DELETE /library/books/{id} · POST /library/books/import (job) · GET /library/books/{id}/copies [library:view_all|manage]
POST     /api/v1/library/books/{id}/copies/bulk · PUT /library/copies/{id}/status · GET /library/copies/resolve?barcode|accession|rfid [library:manage|circulate] {library.rfid_barcode for rfid}
GET/POST /api/v1/library/eresources · PUT/DELETE /library/eresources/{id} [library:manage] {library.eresources}
GET      /api/v1/library/eresources/{id}/open (authenticated redirect, logs usage) [library:view] {library.eresources}
GET      /api/v1/library/members?type&status&department_id · GET /library/members/{id} · POST /library/members (external) · PUT /library/members/{id}/rules · POST /library/members/{id}/suspend|activate [library:manage|view_all]
GET      /api/v1/library/members/me · GET /library/members/me/issues · GET /library/members/me/fines · GET /library/members/wards [library:self]
POST     /api/v1/library/circulation/issue · POST /library/circulation/return · POST /library/circulation/renew · POST /library/circulation/lost (Idempotency-Key) [library:circulate] {library.core}
POST     /api/v1/library/circulation/self-renew {issue_id} [library:self]
GET      /api/v1/library/issues?status&member_id&overdue=true&department_id · GET /library/issues/{id} [library:view_all|view (self)]
GET/POST /api/v1/library/reservations · DELETE /library/reservations/{id} (cancel) [library:self|circulate]
POST     /api/v1/library/fines/{issue_id}/waive [library:fines] {library.fines} · GET /library/fines?status&member_id [library:fines|view (self)]
GET/POST /api/v1/library/ill-requests · POST /library/ill-requests/{id}/decide|receive|return [library:self|manage] {library.inter_library_loan}
GET      /api/v1/opac/search?q&category&author&year&resource_type&available_only · GET /opac/books/{id} · GET /opac/new-arrivals {public} {library.opac}
POST     /api/v1/library/stock-verification (job) · GET /library/stock-verification/{job_id} [library:manage]
POST     /api/v1/library/sync/koha (job) · GET /library/sync/status [library:manage] {library.koha_sync}
GET      /api/v1/library/reports/{accession_register|circulation|overdue|eresource_usage|naac_4_2}?format=xlsx (job) [library:view_all|reports:export]
GET      /api/v1/library/stats [library:view_all]
```
Every list endpoint returns `meta.visibility`; `department_id` filter is validated against the caller scope (HOD → own department).

## 19.9 Frontend
- `/admin/library/catalogue` (DataTable: title/authors/ISBN/category/copies available; import wizard; book drawer with copies table (accession, barcode, status, location) and bulk-add), `/admin/library/circulation` (counter: member scan/search → card with limits/fines/block reasons → scan copy → issue/return/renew/lost; keyboard-first; receipt print; ScopeTabs none), `/admin/library/issues` (tabs Active | Overdue | Returned | Lost; filters; department filter for HOD view), `/admin/library/reservations` (queue with expiry), `/admin/library/fines` (outstanding, waive dialog, collect → Phase 12 counter), `/admin/library/members` (types, rules editor, suspend), `/admin/library/eresources` (subscriptions with expiry chips, usage), `/admin/library/ill`, `/admin/library/stock-verification` (upload scans / live scanner → report), `/admin/library/reports`, `/admin/library/settings` (rules, fines, holds, sync).
- Portals: `/student/library` (My books with due chips and renew, reservations, fines & pay, OPAC link), `/faculty/library` (same), `/parent/library` (ward), `/alumni/library`.
- Public `/opac` (search, facets, availability, new arrivals; institution branding).
- Nav: CAMPUS › Library (Catalogue, Circulation, Issues, Reservations, Fines, Members, E-resources, ILL, Stock verification, Reports, Settings); HOD sees Issues (Department tab) only.

## 19.10 Mobile
Student/Faculty/Scholar/Alumni: More › Library (my books with due dates & renew, reservations, fines → pay, OPAC search with availability, e-resource open); Parent: ward library; Librarian shell: Home (today's issues/returns/overdue count) · Circulation (scan issue/return/renew with camera barcode/RFID reader; offline queue for returns) · Catalogue (search, copy status) · Members · More (reservations, fines, stock verification scanner, reports).

## 19.11 API verification — `scripts/verify/19_library.ps1`
Roles: `librarian`, `librarian.b` (college B scoped), `hod.cse`, `accountant`, `student.1`, `student.overdue`, `student.blocked` (library hold), `faculty.1`, `parent.1`, `alumni.1`, `iqac`, `auditor.tmp`, public.
1. Seed `--only library`; `GET /library/stats` as `librarian` → counts match seed; as `student.1` → 403; `GET /library/books` as `librarian` → `meta.visibility.scopes=["all"]`; as `librarian.b` → only college B books (`college_id`) + shared (`college_id NULL`).
2. Catalogue: create book (ISBN-10 → normalised 13), duplicate ISBN → 201 with `warnings[]`; bulk 5 copies → accession numbers sequential from `lib:acc`, barcodes = accession; `PUT copy status reference_only`; resolve by barcode/accession/rfid (rfid with feature off → 403 `FEATURE_DISABLED`).
3. Members: `GET /library/members/me` as `student.1` → limits from rules (3/14), `is_blocked=false`; `student.blocked` → `is_blocked=true`, reasons include `HOLD`; suspend `faculty.1` as `librarian` → `is_blocked` reasons `SUSPENDED`; external member create with deposit → invoice.
4. Issue: as `librarian` issue copy C1 to `student.1` → `due_on` = today + 14 skipping a seeded holiday and Sunday; copy `issued`, `available_copies` decremented; same `Idempotency-Key` → replay; 4th book → 409 `LIMIT_EXCEEDED`; `reference_only` copy → 409; to `student.blocked` → 409 `MEMBER_BLOCKED` with reasons; as `student.1` calling issue → 403.
5. Reservation: `student.overdue` reserves a book with 0 available → `waiting` position 1; return of that book by its holder → copy `reserved`, reservation `available` with `expires_at`, notification; issue to `student.1` (not the holder) → 409 `RESERVED_FOR_OTHER`; issue to `student.overdue` → `fulfilled`; Beat expiry (dev time shift) → `expired` → next in queue.
6. Renew: `student.1` `self-renew` → `renewals=1`, new due; second time when `max_renewals=1` → 409; renew a book with waiting reservation → 409 `RESERVED`.
7. Return & fines: return a seeded issue 10 days overdue → `fine_paise = 2000` (₹2 × 10), invoice `source_type=library_fine` and `source_id=issue`; `GET /library/members/me/fines` as that student → outstanding; pay at counter (Phase 12) → member card outstanding 0; waive another fine as `librarian` with reason → invoice cancelled + audit row; waive as `accountant` → 403.
8. Lost: mark lost with cost → issue `lost`, copy `lost`, invoice with `Lost book` item; found → copy `available`, invoice cancelled (setting) or kept.
9. Overdue Beat (dev trigger): statuses → `overdue`, reminders in `message_logs`, `student.overdue` (45 days overdue, threshold 30) gets `student_holds(hold_type=library)`; return → hold released (`hold.released` event).
10. Visibility: `GET /library/issues?overdue=true` as `hod.cse` → only CSE students, `meta.visibility.scopes=["department"]`; `?department_id=ECE` → 403; `parent.1` `GET /library/members/wards` → ward card + issues; `faculty.1` `GET /library/issues` → own only; `auditor.tmp` read-only list OK, issue → 403.
11. OPAC public: `GET /opac/search?q=algor` → trigram matches with availability; `available_only=true` filters; 61st request/min → 429.
12. E-resources: create with `subscription_to` in 20 days → expiry reminder in Beat run; `GET /eresources/{id}/open` as `student.1` → 302 with usage logged; unauthenticated → 401; feature off → 403.
13. ILL (feature on): request as `faculty.1` → approve with cost → received → returned; as `student.1` when policy allows students=false → 403.
14. Koha sync (feature on, mock): job imports 3 biblios/6 items keyed by `external_ref`; rerun → updates not duplicates; local issued copy remains `issued` after sync.
15. No-dues: request (Phase 12) for `student.1` with an active issue → library sign-off `dues_pending` automatically; return the book → hook re-evaluates → `cleared`; librarian manual override on a request with fines → `cleared` with remarks + audit.
16. Stock verification job with scanned list missing 2 barcodes → report `missing=2`, `unexpected=1`; reports export xlsx via job → signed URL; NAAC 4.2 metrics values published (`books_added`, `library_expenditure_paise`) readable by `iqac`.

## 19.12 UI verification
1. Catalogue page: search, import wizard with report, book drawer, bulk copies, copy status changes, barcode label print.
2. Circulation counter: member scan → card (limits, fines, block reasons), copy scan → issue/return/renew/lost with feedback (fine amount, reservation notice), receipt print, keyboard-only flow.
3. Issues page tabs & department filter (HOD sees only Department tab); reservations queue; fines page with waive dialog and collect hand-off.
4. Members page: rules editor, suspend/activate, external member with deposit; e-resources with expiry chips and open-link usage; ILL board; stock verification report; reports downloads; settings.
5. Portals: student/faculty/parent/alumni My library pages with renew and pay; public OPAC with facets and availability.
6. Mobile: librarian scan flows (camera barcode) incl. offline return queue; student library screen; OPAC.

## 19.13 Deliverables checklist
- [ ] Catalogue (books/categories/copies/accession sequences/import), members (auto-provision, rules, block logic, external), circulation (issue/return/renew/lost with holidays, limits, reservations, fines via fee linkage, waive), overdue Beat + holds, OPAC, e-resources with usage, ILL, Koha/DSpace adapters (mock+live), no-dues hook, stock verification, reports + NAAC 4.2 metrics
- [ ] Visibility registrations (self/wards/department/college/all); events/jobs/Beat; demo seed `--only library`
- [ ] Web + mobile; `scripts/verify/19_library.ps1` passes; UI checklist done; guards green; commit `feat(phase-19): library`
