# PHASE 12 — FEES, SCHOLARSHIPS & NO-DUES

## Pre-Requisite
Phases 01–11 complete. Earlier phases called a **fee stub** (`fee_service.create_invoice` recording intents); this phase replaces the stub with the real service and back-fills intents recorded in `platform_settings['fee_stub_queue']`.

## Objective
Money end-to-end for a college/university: fee heads and **effective-dated fee structures** by programme × regulation × batch × category × quota × term with instalments and automatic late fees; the **fee-linkage pattern** (`fee_invoices.payer_type/source_type/source_id`) used by registration, exams, revaluation, hostel, mess, condonation, transcripts/certificates, convocation, affiliation, library fines, discipline; discounts/concessions (incl. staff-ward), **scholarships** (govt/NSP/institution, disbursement to fee credit or bank), fines, online payments through a `PaymentGateway` interface (Razorpay first) + UPI QR, **offline payments** (challan/NEFT/DD with UTR reconciliation, cheque bounce), receipts (PDF/thermal) with cancellation-by-approval, day-book/cash-bank registers, dues and reminders, **multi-department no-dues clearance**, refunds, GST-aware invoicing, ledgers and accounting export — with Mine vs counter/all views.

## Feature keys
`fees.core`, `fees.structures_by_quota`, `fees.instalments`, `fees.online_payment`, `fees.discounts`, `fees.fines` (on, starter); `fees.auto_late_fee`, `fees.upi_qr`, `fees.offline_challan_reconciliation`, `fees.scholarships`, `fees.no_dues`, `fees.refunds`, `fees.receipt_cancellation_approval`, `fees.thermal_receipts` (on, standard); `fees.staff_ward_concession`, `fees.gst_invoicing`, `fees.accounting_export` (off, standard); `fees.nsp_integration` (off, professional); `integrations.payments` (on).

## Visibility rules
| Role | Structures/heads | Invoices & payments | Scholarships | No-dues | Refunds |
|---|---|---|---|---|---|
| student | read own applicable structure | **S** (own dues/receipts, pay) | S (apply/track) | S (request/status) | S (status) |
| parent | — | **W** (pay for wards) | W (read) | W (read) | — |
| accountant | A (`fees:structure_manage`) | **A** (collect, cancel via approval, reconcile, refund) | A (verify/disburse) | A (accounts sign-off) | A |
| registrar / institution_admin | A | A (view) | A (sanction) | A | A (approve) |
| hod / advisor | — | D/O (view dues of department/advisees) | D (recommend) | D (department sign-off) | — |
| librarian / warden / lab in-charge / sports | — | own module fines | — | own department sign-off | — |
| college_admin | C | C | C | C | C |
| auditor | A (read) | A (read) | A (read) | A (read) | A (read) |

## 12.1 Database tables
Section 13: `fee_heads, fee_structures, fee_structure_items, fee_discounts, student_fee_assignments, student_discount_assignments, fine_configurations, fee_invoices, fee_invoice_items, fee_payments, offline_payment_reconciliations, fee_refunds, day_book_entries, scholarships, scholarship_applications, no_dues_requests, no_dues_signoffs`; `ledger_accounts` (§22; create the minimal chart here — Phase 23 extends); `integration_connections` — exist. Expected delta migration: none.

## 12.2 Alembic migration
`0012_phase12_fees_seed.py` — data-only: IN pack fee-head template (tuition, admission, exam, hostel, mess, transport, library, lab, caution deposit, fine, certificate, reval, condonation, convocation, affiliation) with GST flags; fine configuration defaults; minimal `ledger_accounts` chart (Fees receivable, Cash, Bank, Fee income by head, Refunds, Scholarship credits). Demo seed `--only fees`: structures for both programmes × categories/quotas × terms with 2 instalments, assignments for all students, invoices for the current term (60 % paid online/offline mix, 25 % partial, 15 % overdue), 3 scholarships with applications, 10 refund requests, 20 no-dues requests, day-book entries.

## 12.3 Models — `models/fees.py`
`FeeHead`, `FeeStructure`, `FeeStructureItem`, `FeeDiscount`, `StudentFeeAssignment`, `StudentDiscountAssignment`, `FineConfiguration`, `FeeInvoice`, `FeeInvoiceItem`, `FeePayment`, `OfflinePaymentReconciliation`, `FeeRefund`, `DayBookEntry`, `Scholarship`, `ScholarshipApplication`, `NoDuesRequest`, `NoDuesSignoff`, `LedgerAccount`. Enums: `HeadType`, `PayerType`, `InvoiceStatus`, `PaymentMode`, `PaymentStatus`, `RefundStatus`, `ScholarshipProvider`, `AmountType`, `ScholarshipStatus`, `DisbursementMode`, `NoDuesPurpose/Status`, `SignoffStatus`, `DepartmentKey`.

## 12.4 Schemas — `app/schemas/fees.py`, `scholarships.py`, `no_dues.py`
`FeeHeadIn/Out`, `StructureCreate/Update/Response` (+ items with instalments/due offsets), `StructureCloneRequest`, `ApplicableStructureResponse`, `AssignRequest{structure_id, enrollment_ids[]|batch_id}`, `DiscountIn/Out`, `DiscountAssign{discount_id, enrollment_id, reason, academic_year_id}`, `FineConfigIn/Out`, `InvoiceCreate` (internal use: payer, source, items), `InvoiceResponse` (+ items, payments, balance, status, source link), `DuesResponse{invoices[], total_due, overdue, next_due}`, `CollectRequest{invoice_id|allocation:[{invoice_id, amount}], amount_paise, mode, reference?, utr?, bank?, cheque{no,date,bank}?, counter, idempotency}`, `ReceiptResponse`, `OnlineInitiateRequest{invoice_ids[]|amount, gateway?}` + `OnlineInitiateResponse{order_id, gateway, key, amount, checkout}`, `UpiQrResponse{qr_png, vpa, amount, ref}`, `GatewayWebhook` (per provider), `CancelReceiptRequest{reason}`, `ReconcileUpload{file_url|rows}` + `ReconcileMatch{row_id, payment_id|invoice_id}`, `BounceRequest{payment_id, reason, bank_charges_paise}`, `RefundCreate/Decision/Process`, `DayBookResponse`, `ScholarshipIn/Out`, `ScholarshipApply`, `ScholarshipDecision`, `DisburseRequest{mode, reference?}`, `NoDuesCreate{purpose}`, `NoDuesResponse` (+ signoffs), `SignoffRequest{status, dues_paise?, remarks}`, `FeeReportQuery`, `AccountingExportRequest`.

## 12.5 Repository
`fee_repository.py` (`module="fees"`; invoice self predicate via `payer_type='student' AND payer_id IN own student ids` or applicant/alumni user link; wards; department via enrolment; `FOR UPDATE` on invoice during collection; payments by date/mode/counter), `structure_repository.py` (`applicable(enrollment, term_number, on_date)` resolving the most specific effective structure: batch > regulation > programme, then category/quota, then college/institution), `scholarship_repository.py` (`module="scholarships"`), `no_dues_repository.py` (`module="no_dues"`; sign-off ownership by department role), `ledger_repository.py`.

## 12.6 Services
- `structure_service.py`: heads CRUD (GST flag/rate, refundable, ledger mapping), structures CRUD with effective dates and dimension validation (no overlapping identical dimension sets for the same period), items with instalments/due offsets, clone to next year, `applicable(enrollment, term)`; `assign(structure, enrollments)` (auto on `student.created` and `batch.promoted` per term via consumers), per-credit fee for arrears (`per_credit_paise`).
- `invoice_service.py`
  1. `create_invoice(payer, source_type, source_id, items, due_date, term)` — the universal linkage API (idempotent on `(source_type, source_id)` unless `allow_multiple`); GST computation when head taxable and `fees.gst_invoicing`; `invoice_number` from sequences (`inv:{yyyy}`); emits `fees.invoice_created` → notification.
  2. Registration invoices (Phase 09 consumer): tuition instalments from the applicable structure + arrear per-credit + late fee; exam registration (Phase 14), reval (16), hostel/mess (20), condonation (11), certificates/transcripts (26/16), convocation (18), affiliation (34), library fines (19), discipline fines (27) all call `create_invoice`.
  3. Discounts: assignment (workflow `fees.concession` when `requires_approval`) → invoice `discount_paise`; staff-ward concession auto when guardian is active staff (`fees.staff_ward_concession`).
  4. Late fees (Beat `fees.late_fees`): per `fine_configurations(applies_to='late_fee')` after grace → `fine_paise` + item; reminders (`fees.due_reminder` D-7/D-1/D+7); overdue → optional automatic `registration`/`exam` hold via `hold_service` (setting `fees.hold_on_overdue_days`).
  5. Status: `pending → partial → paid | overdue | cancelled | refunded`; cancel invoice only with zero payments (or after refund).
- `payment_service.py`
  1. Counter `collect` (accountant; `Idempotency-Key`): lock invoice(s); allocate amount across items/instalments (oldest due first, or explicit allocation); modes cash/UPI/card/cheque/DD/NEFT/challan; receipt number from sequence (`rcpt:{yyyy}:{counter}`); receipt PDF job (template with GST when applicable) + thermal print payload (`ESC/POS` JSON for mobile); day-book entry update; emits `fees.payment_received` → notification, ledgers (`ledger_entries` in Phase 23; here `income_records`-style posting stub), Phase 08/09/11/14 consumers unblock (`fee_paid` transitions).
  2. Online: `initiate` → `PaymentGateway.create_order` (Razorpay adapter; mock in dev) → order row (`fee_payments.status='initiated'`); webhook (`verify_signature` mandatory) or client verify → `success` → same post-payment path; failure/timeout → `failed`; UPI QR (`UpiCollect.generate_qr` dynamic with ref) polled by mobile/counter.
  3. Offline: challan/NEFT/DD recorded as `initiated` (student self-declares UTR) → **reconciliation** upload (bank statement CSV) → auto-match by UTR/amount/date → accountant confirms → `reconciled`; cheque bounce → `bounced`, reversal item + bank charges, invoice reopened, notification.
  4. Receipt cancellation → workflow `fees.receipt_cancel` (accountant → principal) → reversal, invoice balance restored, audit.
  5. Day-book: per counter/collector/date totals by mode; close & deposit; cash-bank register export.
- `refund_service.py`: request (student/admissions withdrawal/hostel vacate caution deposit) → workflow `fees.refund` → process (mode/reference) → `refunded` invoice status when full; refund policies from cycle/hostel settings.
- `scholarship_service.py`: schemes (eligibility rules JSON: categories, income cap, min CGPA, programmes), applications with documents/income, verify → recommend (HOD) → sanction (registrar/principal via workflow `scholarship.sanction`) → disburse: `fee_credit` (creates `scholarship_credit` payment against invoices) or `bank_transfer` (record) or `external_portal` (NSP reference; `fees.nsp_integration` adapter sync); reports for NAAC 5.1.1.
- `no_dues_service.py`: request per purpose (graduation/transfer/hostel vacate/exit/transcript; auto-created by Phase 07 transfer/exit, Phase 18 degree, Phase 20 vacate); parallel sign-offs for departments configured per purpose (`accounts, library, hostel, lab, department, sports, transport, placement`) via workflow `no_dues.clearance` (parallel steps) — each sign-off by the department role (accounts = accountant, library = librarian, hostel = warden, department = HOD, lab = lab in-charge, sports = sports officer); `dues_pending` blocks; all cleared → `cleared` + certificate (Phase 26 template; number from sequence) + event `no_dues.cleared` (consumed by degree eligibility Phase 18, transcript Phase 16, hostel vacate Phase 20).
- `fee_report_service.py`: daily/monthly collection by mode/head/college, dues by programme/batch/category, defaulters, scholarship summary, refunds; exports; `accounting_export` (Tally XML / CSV vouchers) when enabled.
- Stub back-fill: on install of this phase, process `fee_stub_queue` intents (registration/condonation/application/admission fees recorded by earlier phases in dev) into real invoices.

## 12.7 Events / jobs
Emits: `fees.invoice_created/updated/cancelled`, `fees.payment_received/failed/bounced/reconciled`, `fees.receipt_cancelled`, `fees.refund_requested/processed`, `fees.late_fee_applied`, `fees.due_reminder`, `scholarship.applied/sanctioned/disbursed`, `no_dues.requested/signoff/cleared/blocked`. Consumers: notifications (invoice, reminders, receipts, refunds, scholarship, no-dues), Phase 08 (`applicant.fee_paid`), Phase 09 (registration fee status), Phase 11 (condonation paid), Phase 14 (exam registration confirmed), Phase 16/18/20/26 consumers, Phase 23 ledger posting, Phase 07 holds (`fees.overdue_hold`). Jobs: `fees.receipt_pdf`, `fees.bulk_invoice` (term invoices for a batch), `fees.reconcile_upload`, `fees.reports_export`, `fees.accounting_export`, `scholarships.nsp_sync`. Beat: `fees.late_fees` (nightly), `fees.due_reminders` (08:00), `fees.overdue_holds` (nightly), `fees.day_book_close_reminder` (18:00), `fees.gateway_status_poll` (10 min for `initiated`). Workflows: `fees.concession`, `fees.receipt_cancel`, `fees.refund`, `scholarship.sanction`, `no_dues.clearance` (parallel).

## 12.8 Endpoints
```
GET/POST /api/v1/fee-heads · PUT/DELETE /fee-heads/{id} [fees:structure_manage] {fees.core}
GET/POST /api/v1/fee-structures · GET/PUT /fee-structures/{id} · POST /fee-structures/{id}/clone · GET /fee-structures/applicable?enrollment_id&term_number [fees:structure_manage|view]
POST     /api/v1/fee-structures/{id}/assign · POST /fees/bulk-invoice (job) [fees:structure_manage]
GET/POST /api/v1/fee-discounts · PUT /fee-discounts/{id} · POST /fee-discounts/{id}/assign · GET /students/{id}/discounts [fees:concession|view] {fees.discounts}
GET/PUT  /api/v1/fine-configurations [fees:structure_manage] {fees.fines}
GET      /api/v1/fees/invoices?scope=&payer_type&status&overdue&batch_id · GET /fees/invoices/{id} · POST /fees/invoices/{id}/cancel [fees:view|view_all|manage]
GET      /api/v1/fees/me/dues · GET /fees/me/invoices · GET /fees/me/receipts · GET /fees/wards/{student_id}/dues [fees:self]
POST     /api/v1/fees/collect (Idempotency-Key) · GET /fees/payments?date&mode&counter · GET /fees/payments/{id} · GET /fees/payments/{id}/receipt.pdf · GET /fees/payments/{id}/thermal [fees:collect|view]
POST     /api/v1/fees/payments/{id}/cancel-request · POST /fees/payments/{id}/bounce [fees:cancel_receipt] {fees.receipt_cancellation_approval}
POST     /api/v1/fees/online/initiate · POST /fees/online/verify · POST /webhooks/payments/{provider} {public, signature} · GET /fees/online/{order_id}/status [fees:self|collect] {fees.online_payment}
POST     /api/v1/fees/upi-qr · GET /fees/upi-qr/{ref}/status [fees:self|collect] {fees.upi_qr}
POST     /api/v1/fees/offline/declare · POST /fees/reconcile/upload (job) · GET /fees/reconcile?status= · POST /fees/reconcile/{id}/match|ignore [fees:self|reconcile] {fees.offline_challan_reconciliation}
GET      /api/v1/fees/day-book?date&counter · POST /fees/day-book/close · GET /fees/day-book/export [fees:collect|view_all]
GET/POST /api/v1/fees/refunds · POST /fees/refunds/{id}/approve|process|reject · GET /fees/refunds/me [fees:refund|self] {fees.refunds}
GET/POST /api/v1/scholarships · PUT /scholarships/{id} · POST /scholarships/{id}/apply · GET /scholarship-applications?status · POST /scholarship-applications/{id}/verify|recommend|sanction|disburse|reject · GET /scholarship-applications/me [scholarships:*|self] {fees.scholarships}
POST     /api/v1/no-dues · GET /no-dues?scope=mine|department|all · GET /no-dues/{id} · POST /no-dues/{id}/signoff · GET /no-dues/me [no_dues:request|approve|view] {fees.no_dues}
GET      /api/v1/fees/reports/{collection|dues|defaulters|scholarships|refunds}?…&format= · POST /fees/accounting-export (job) [fees:view_all|export] {fees.accounting_export}
```

## 12.9 Frontend
- `/admin/fees` dashboard (today's collection by mode, dues, overdue, reconciliation pending, refunds pending), `/admin/fees/structures` (heads; structure builder with dimension chips, items/instalments grid, effective dates, clone; applicability tester), `/admin/fees/discounts`, `/admin/fees/fines`, `/admin/fees/invoices` (ScopeTabs; filters; detail with items/payments/source link; cancel), **`/admin/fees/collect`** (search student → dues panel → allocation → mode-specific fields → collect → receipt print/thermal/PDF; UPI QR panel with live status), `/admin/fees/payments` (register; cancel request; bounce), `/admin/fees/online` (gateway orders), `/admin/fees/reconcile` (upload statement → matches/unmatched → confirm), `/admin/fees/day-book` (close/deposit), `/admin/fees/refunds` (queue with workflow timeline), `/admin/fees/scholarships` (schemes; applications pipeline; disbursement), `/admin/fees/no-dues` (requests; department sign-off tabs per role), `/admin/fees/reports`.
- Student portal `/student/fees` (dues cards by invoice/instalment, pay now → gateway checkout/UPI QR, declare offline payment with UTR, receipts list/download, scholarships apply/track, refunds, no-dues status), parent `/parent` pay for ward.
- Nav: FINANCE › Fees (dashboard), Collect, Structures, Invoices, Payments, Reconciliation, Refunds, Scholarships, No-dues, Reports.

## 12.10 Mobile
Student: **Fees tab** (dues, pay via UPI intent/gateway SDK, offline declare with UTR, receipts share, scholarships, refund status, no-dues); Parent: Fees tab for wards; **Accountant shell**: Home (collections today), **Collect** (search → dues → collect → thermal print via ESC/POS), Fees (invoices/receipts/refunds/scholarships/no-dues sign-off), reconciliation review (match/ignore); Librarian/Warden/HOD: no-dues sign-off cards.

## 12.11 API verification — `scripts/verify/12_fees.ps1`
Roles: `accountant`, `registrar`, `hod.cse`, `librarian`, `warden.h1`, `student.1`, `student.2`, `parent.1`, `auditor.tmp`.
1. Seed `--only fees`; `GET /fees/invoices?scope=all` as `accountant` → all, `meta.visibility.scopes=[institution]`; as `student.1` → own only; `GET /fees/wards/{ward}/dues` as `parent.1` → 200; non-consented ward → 404.
2. Structures: create overlapping structure (same dimensions, overlapping dates) → 409; `applicable?enrollment_id=student.1` → the batch-specific structure (most specific wins); assign to batch → invoices generated with 2 instalments and due dates; second run idempotent.
3. Linkage: dev `POST /_dev/fees/link {source_type:"condonation", source_id:X, amount}` → invoice with `source_type/source_id`; same call again → same invoice (idempotent); `GET /fees/invoices/{id}` shows the source link.
4. Collect cash ₹5,000 (`amount_paise=500000`) against instalment 1 → receipt number, `status=partial`, balance correct; replay with same `Idempotency-Key` → same receipt; overpay beyond balance without `allow_advance` → 422; receipt PDF job → URL; thermal payload → ESC/POS JSON.
5. Online: `POST /fees/online/initiate` as `student.1` → order (mock gateway); webhook with **invalid signature** → 401 and payment stays `initiated`; valid signature → `success`, invoice `paid`, notification, event `fees.payment_received`; duplicate webhook → idempotent.
6. UPI QR: generate → status `pending`; mock callback → `success`.
7. Offline: student declares NEFT with UTR `UTR123` → `initiated`; upload statement CSV containing `UTR123` amount match → auto-match proposed → accountant confirm → `reconciled`; unmatched row → listed; cheque payment → `bounce` with charges → invoice reopened + reversal items + notification.
8. Cancel receipt: request → workflow to principal → approve → reversal recorded, balance restored, audit rows; direct `DELETE` does not exist (405).
9. Late fee: set instalment 2 due yesterday, run `fees.late_fees` → fine item per config (grace respected); `fees.overdue_holds` with setting 30 days → hold placed for a 45-day overdue student; pay → hold released.
10. Discounts: assign 10 % sibling discount to `student.2` (workflow approve) → invoice discount recalculated; staff-ward auto concession when guardian user is active staff (feature on).
11. Scholarships: `student.1` applies (income under cap) → `hod.cse` recommend → registrar sanction (workflow) → accountant disburse `fee_credit` ₹20,000 → payment row `mode=scholarship_credit`, invoice balance reduced; ineligible (CGPA rule) application → 422.
12. Refund: withdrawal refund request (from Phase 08 dev) → workflow approve → process with reference → status `processed`, invoice `refunded`.
13. No-dues: `POST /no-dues {purpose:"transfer"}` as `student.1` → parallel sign-offs (accounts, library, hostel, department, lab, sports); `librarian` signoff `dues_pending` (₹200) → request `blocked`; pay fine → librarian `cleared`; all cleared → `cleared`, certificate issued, event `no_dues.cleared`; `warden.h1` signing off `department` step → 403.
14. Day-book: totals by mode for the day; close → deposit record; export CSV.
15. GST: enable `fees.gst_invoicing`, mark `mess` head taxable 5 % → new mess invoice items carry tax; receipt shows GSTIN.
16. Reports: collection by mode for the month, defaulters for batch 2024, scholarships summary; accounting export job (feature) → Tally XML file.
17. Auditor: reads OK; `POST /fees/collect` → 403.

## 12.12 UI verification
1. Collect screen: search → dues → allocation → cash/UPI/cheque fields → collect → print receipt; UPI QR panel updates on mock callback.
2. Student fees page: pay flow (mock checkout), offline declare, receipts download, scholarship apply with documents, no-dues status; parent pays for ward.
3. Structures builder validations; applicability tester; bulk invoice job.
4. Reconciliation page: upload → matches → confirm; bounce dialog.
5. Refunds/receipt-cancel queues with workflow timelines; scholarships pipeline; no-dues sign-off tabs appear only for the roles that own them (librarian sees Library tab, HOD Department tab, accountant Accounts tab).
6. Reports pages with exports; day-book close.
7. Mobile: accountant collect + thermal print (or preview when no printer); student UPI intent; librarian/warden sign-off cards.

## 12.13 Deliverables checklist
- [ ] Heads/structures (effective-dated, dimensions, instalments, clone, applicability, assignment), discounts/concessions (+ staff-ward), fines/late fees/reminders/overdue holds, universal `create_invoice` linkage + stub back-fill, collection (counter/online/UPI/offline/reconciliation/bounce), receipts (PDF/thermal, cancellation workflow), day-book, refunds workflow, scholarships pipeline + disbursement (+ NSP adapter), no-dues parallel workflow + certificate, GST, reports + accounting export
- [ ] `PaymentGateway`/`UpiCollect` adapters (Razorpay + mock) with signature verification; consumers for earlier phases' fee transitions
- [ ] Visibility (self/wards/department/all), events/jobs/Beat/workflows, demo seed `--only fees`
- [ ] Web + mobile; `scripts/verify/12_fees.ps1` passes; UI checklist done; guards green; commit `feat(phase-12): fees, scholarships, no-dues`
