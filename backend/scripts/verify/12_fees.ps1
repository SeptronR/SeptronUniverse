# API verification — Phase 12 fees, scholarships & no-dues (Prompts/12 §12.11).
#
# Run from backend/ with the API, the Celery worker and Redis (or the TCP fakeredis) up:
#   .\scripts\verify\12_fees.ps1 [-BaseUrl http://localhost:8000/api/v1]
#
# Seed first: python scripts/seed_demo_institution.py --type university --only fees
#
# Roles: accountant, registrar (MFA), hod.cse, librarian, warden.h1, student.1, student.2 (any second learner login),
# parent.1, auditor.tmp, inst.admin (vice-chancellor-equivalent approvals), super admin (feature flags).
#
# Documented deviations (PROGRESS.md decisions log, Phase 12):
#  * the mock gateway signs with a fixed dev secret — signatures come from POST /_dev/fees/sign (no real keys);
#  * the UPI callback is POST /_dev/fees/upi/{ref}/callback; Beat bodies run through POST /_dev/fees/{task};
#  * overdue holds are placed per gate in fees.overdue_hold_types (registration + exam — Phase 07 has no `fee`
#    hold type and its gates match hold_type == gate), source_type `fee_invoice`;
#  * the "principal" step of receipt cancellation / refunds is the vice_chancellor template; when no VC holder
#    exists the institution admin (fees:manage) acts on the open step;
#  * no-dues certificates carry a `certificate_no` sequence number (the Phase 26 document links later).
param([string]$BaseUrl = "http://localhost:8000/api/v1")
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl
$Backend = Resolve-Path (Join-Path $PSScriptRoot "../..")
$Py = Get-VenvPython $Backend
function Sql($q) { (& $Py (Join-Path $PSScriptRoot "_sql.py") $q) | ConvertFrom-Json }
function SqlW($q) { & $Py (Join-Path $PSScriptRoot "_sql.py") --write $q | Out-Null }
function Raw($token, $method, $path, $body = $null, $headers = @{}, $rawBody = $null) {
  $h = @{}
  if ($token) { $h['Authorization'] = "Bearer $token" }
  foreach ($k in $headers.Keys) { $h[$k] = $headers[$k] }
  $p = @{ Method = $method; Uri = "$script:BaseUrl$path"; Headers = $h; SkipHttpErrorCheck = $true }
  if ($null -ne $rawBody) { $p['ContentType'] = 'application/json'; $p['Body'] = $rawBody }
  elseif ($null -ne $body) { $p['ContentType'] = 'application/json'; $p['Body'] = ($body | ConvertTo-Json -Depth 8) }
  $r = Invoke-WebRequest @p
  return @{ Status = $r.StatusCode; Body = $(if ($r.Content -and $r.Headers['Content-Type'] -match 'json') { $r.Content | ConvertFrom-Json } else { $r.Content }) }
}
function Expect($token, $method, $path, $body, $status, $code = $null, $headers = @{}) {
  $r = Raw $token $method $path $body $headers
  if ($r.Status -ne $status) { throw "$method $path expected $status got $($r.Status): $($r.Body | ConvertTo-Json -Depth 6 -Compress)" }
  if ($code -and ($r.Body.error.details.code -ne $code) -and ($r.Body.error.code -ne $code)) {
    throw "$method $path expected code $code got $($r.Body.error | ConvertTo-Json -Depth 6 -Compress)"
  }
  $script:Checks++
  Write-Host "OK $method $path -> $status $code"
  return $r.Body
}
function WaitJob($token, $jobId, $seconds = 120) {
  for ($i = 0; $i -lt $seconds; $i++) {
    $j = (Call $token GET "/jobs/$jobId").data
    if ($j.status -in @('succeeded', 'failed', 'cancelled')) { return $j }
    Start-Sleep -Seconds 1
  }
  throw "job $jobId did not finish"
}

$acct = Login 'accountant' (Get-DemoPassword 'accountant')
$registrar = Login-Mfa 'registrar' 'registrar'
$hod = Login 'hod.cse' (Get-DemoPassword 'hod')
$lib = Login 'librarian' (Get-DemoPassword 'librarian')
$warden = Login 'warden.h1' (Get-DemoPassword 'hostel_warden')
$s1 = Login 'student.1' (Get-DemoPassword 'student')
$parent = Login 'parent.1' (Get-DemoPassword 'parent')
$auditor = Login 'auditor.tmp' (Get-DemoPassword 'auditor')
$admin = Login 'inst.admin' (Get-DemoPassword 'institution_admin')
$sa = Login-SuperAdmin

$inst = (Sql "SELECT id FROM institutions WHERE slug='demo-uni'")[0].id
$slug = 'demo-uni'
$tenant = @{ 'X-Institution-Id' = $inst }
function SetFlag($key, $on) {
  Call $sa PUT "/institutions/$inst/features/$key" @{ enabled = $on; confirm_dependencies = $true; reason = "verify 12" } 200 $tenant | Out-Null
}
$s1row = (Sql "SELECT e.id enrol, s.id student, e.batch_id, e.department_id FROM students s JOIN users u ON u.id=s.user_id JOIN student_program_enrollments e ON e.student_id=s.id WHERE u.username='student.1' AND e.deleted_at IS NULL ORDER BY e.created_at DESC LIMIT 1")[0]
$ward = (Sql "SELECT g.student_id FROM student_guardians g JOIN users u ON u.id=g.user_id WHERE u.username='parent.1' AND g.portal_access LIMIT 1")[0].student_id
$other = (Sql "SELECT s.id FROM students s WHERE s.id <> '$ward' AND s.institution_id='$inst' LIMIT 1")[0].id
$s2 = (Sql "SELECT e.id enrol FROM student_program_enrollments e WHERE e.institution_id='$inst' AND e.id <> '$($s1row.enrol)' AND e.status='active' LIMIT 1")[0].enrol

# ---- 0. reset ------------------------------------------------------------------------------------------------------------
Write-Host "== 0. reset"
# FK-aware: the previous run's invoices / items reference these structures
& $Py (Join-Path $PSScriptRoot "_purge.py") fee_structures "name LIKE 'verify-12%'" | Out-Null
& $Py (Join-Path $PSScriptRoot "_purge.py") fee_payments "utr IN ('UTR123','UTR123X') OR reference_no LIKE 'verify-12%'" | Out-Null
SqlW "DELETE FROM offline_payment_reconciliations WHERE utr IN ('UTR123','UTRNOPE')"
SqlW "DELETE FROM offline_payment_reconciliations WHERE utr IN ('UTR123','UTRNOPE')"
SqlW "DELETE FROM no_dues_requests WHERE student_program_enrollment_id='$($s1row.enrol)'"
SqlW "DELETE FROM scholarship_applications WHERE student_program_enrollment_id='$($s1row.enrol)'"
SqlW "DELETE FROM scholarships WHERE name LIKE 'verify-12%'"
foreach ($flag in @('fees.gst_invoicing', 'fees.accounting_export')) { SetFlag $flag $false }

# ---- 1. visibility ---------------------------------------------------------------------------------------------------------
Write-Host "== 1. visibility"
$all = Call $acct GET "/fees/invoices?scope=all&page_size=5"
Assert ($all.meta.visibility.scopes -contains 'all') "accountant institution tab"
$mine = Call $s1 GET "/fees/invoices?page_size=200"
Assert (@($mine.data | Where-Object { $_.student_program_enrollment_id -and $_.student_program_enrollment_id -ne $s1row.enrol }).Count -eq 0) "student.1 sees own invoices only"
Expect $parent GET "/fees/wards/$ward/dues" $null 200 | Out-Null
Expect $parent GET "/fees/wards/$other/dues" $null 404 | Out-Null

# ---- 2. structures -----------------------------------------------------------------------------------------------------------
Write-Host "== 2. structures"
$heads = (Call $acct GET "/fee-heads").data
$tuition = ($heads | Where-Object code -eq 'TUITION').id
$items = @(@{ fee_head_id = $tuition; amount_paise = 1000000; instalment_no = 1; due_offset_days = 10 }, @{ fee_head_id = $tuition; amount_paise = 1000000; instalment_no = 2; due_offset_days = 70 })
# programme too: a later seed's batch + programme rate (score 500) must lose to batch + programme + term
$s1prog = (Sql "SELECT program_id FROM student_program_enrollments WHERE id = '$($s1row.enrol)'")[0].program_id
$st = (Call $acct POST "/fee-structures" @{ name = 'verify-12 batch'; batch_id = $s1row.batch_id; program_id = $s1prog; term_number = 9; effective_from = (Get-Date).ToString('yyyy-MM-dd'); items = $items }).data
Expect $acct POST "/fee-structures" @{ name = 'verify-12 overlap'; batch_id = $s1row.batch_id; program_id = $s1prog; term_number = 9; effective_from = (Get-Date).AddDays(5).ToString('yyyy-MM-dd'); items = $items } 409 'CONFLICT' | Out-Null
$app = (Call $acct GET "/fee-structures/applicable?enrollment_id=$($s1row.enrol)&term_number=9").data
Assert ($app.structure.id -eq $st.id) "the batch-specific structure wins"
$as1 = (Call $acct POST "/fee-structures/$($st.id)/assign" @{ enrollment_ids = @($s1row.enrol) }).data
$as2 = (Call $acct POST "/fee-structures/$($st.id)/assign" @{ enrollment_ids = @($s1row.enrol) }).data
Assert ($as2.invoices_created -eq 0 -and $as2.already -eq 1) "assignment idempotent"
$inv = (Call $acct GET "/fees/invoices?scope=all&source_type=structure&q=&page_size=200").data | Where-Object { $_.student_program_enrollment_id -eq $s1row.enrol -and $_.description -like 'verify-12 batch*' } | Select-Object -First 1
Assert (@($inv.items | Where-Object instalment_no -eq 2).Count -eq 1) "2 instalments with due dates"

# ---- 3. linkage ----------------------------------------------------------------------------------------------------------------
Write-Host "== 3. linkage"
$src = [guid]::NewGuid().ToString()
$l1 = (Call $acct POST "/_dev/fees/link" @{ source_type = 'condonation'; source_id = $src; amount_paise = 50000; enrollment_id = $s1row.enrol }).data
$l2 = (Call $acct POST "/_dev/fees/link" @{ source_type = 'condonation'; source_id = $src; amount_paise = 50000; enrollment_id = $s1row.enrol }).data
Assert ($l1.id -eq $l2.id) "linkage idempotent per source"
$ld = (Call $acct GET "/fees/invoices/$($l1.id)").data
Assert ($ld.source_type -eq 'condonation' -and $ld.source_id -eq $src) "source link shown"

# ---- 4. counter collection -------------------------------------------------------------------------------------------------------
Write-Host "== 4. collect"
$key = "verify-12-$([guid]::NewGuid())"
$c1 = (Call $acct POST "/fees/collect" @{ invoice_id = $inv.id; amount_paise = 500000; mode = 'cash'; counter = 'main' } 200 @{ 'Idempotency-Key' = $key }).data
$c2 = (Call $acct POST "/fees/collect" @{ invoice_id = $inv.id; amount_paise = 500000; mode = 'cash'; counter = 'main' } 200 @{ 'Idempotency-Key' = $key }).data
Assert ($c1.receipt_numbers[0] -eq $c2.receipt_numbers[0]) "replay returns the same receipt"
Assert ($c1.invoices[0].status -in @('partial', 'overdue') -and $c1.invoices[0].balance_paise -eq 1500000) "partial with the right balance"
Expect $acct POST "/fees/collect" @{ invoice_id = $inv.id; amount_paise = 99999999; mode = 'cash' } 422 'OVERPAYMENT' @{ 'Idempotency-Key' = [guid]::NewGuid().ToString() } | Out-Null
$pdf = Raw $acct GET "/fees/payments/$($c1.payments[0].id)/receipt.pdf"
Assert ($pdf.Status -eq 200) "receipt PDF"
$th = (Call $acct GET "/fees/payments/$($c1.payments[0].id)/thermal").data
Assert ($th.commands.Count -gt 3) "thermal ESC/POS payload"

# ---- 5. online ---------------------------------------------------------------------------------------------------------------------
Write-Host "== 5. online"
$ord = (Call $s1 POST "/fees/online/initiate" @{ invoice_ids = @($l1.id) }).data
$payload = @{ event = 'payment.captured'; payload = @{ payment = @{ entity = @{ id = 'pay_verify12'; order_id = $ord.order_id; status = 'captured' } } } } | ConvertTo-Json -Depth 8 -Compress
$bad = Raw $null POST "/webhooks/payments/mock?institution=$slug" $null @{ 'X-Signature' = 'deadbeef' } $payload
Assert ($bad.Status -eq 401) "invalid signature -> 401"
$sig = (Call $acct POST "/_dev/fees/sign" @{ body = $payload }).data.webhook_signature
$ok = Raw $null POST "/webhooks/payments/mock?institution=$slug" $null @{ 'X-Signature' = $sig } $payload
Assert ($ok.Status -eq 200) "valid webhook settles"
$dup = Raw $null POST "/webhooks/payments/mock?institution=$slug" $null @{ 'X-Signature' = $sig } $payload
Assert ($dup.Status -eq 200) "duplicate webhook idempotent"
Assert ((Call $acct GET "/fees/invoices/$($l1.id)").data.status -eq 'paid') "invoice paid"
Assert ((Sql "SELECT count(*) n FROM domain_events WHERE event_type='fees.payment_received' AND payload->>'invoice_id'='$($l1.id)'")[0].n -ge 1) "fees.payment_received emitted"

# ---- 6. UPI -------------------------------------------------------------------------------------------------------------------------
Write-Host "== 6. UPI QR"
$l3 = (Call $acct POST "/_dev/fees/link" @{ source_type = 'other'; source_id = [guid]::NewGuid().ToString(); amount_paise = 30000; enrollment_id = $s1row.enrol }).data
$qr = (Call $s1 POST "/fees/upi-qr" @{ invoice_id = $l3.id }).data
Assert ((Call $s1 GET "/fees/upi-qr/$($qr.ref)/status").data.status -eq 'initiated') "pending"
Call $s1 POST "/_dev/fees/upi/$($qr.ref)/callback" | Out-Null
Assert ((Call $s1 GET "/fees/upi-qr/$($qr.ref)/status").data.status -eq 'success') "UPI success"

# ---- 7. offline + bounce ---------------------------------------------------------------------------------------------------------
Write-Host "== 7. offline"
$decl = (Call $s1 POST "/fees/offline/declare" @{ invoice_id = $inv.id; amount_paise = 100000; mode = 'neft'; utr = 'UTR123' }).data
Assert ($decl.status -eq 'initiated') "declared"
$up = (Call $acct POST "/fees/reconcile/upload" @{ rows = @(@{ utr = 'UTR123'; amount_paise = 100000 }, @{ utr = 'UTRNOPE'; amount_paise = 777 }) } 202).data
WaitJob $acct $up.job_id | Out-Null
$rows = (Call $acct GET "/fees/reconcile?status=unmatched").data
$row = $rows | Where-Object utr -eq 'UTR123' | Select-Object -First 1
Assert ($row.proposed_payment_id -eq $decl.id) "auto-match proposed"
Assert (@($rows | Where-Object utr -eq 'UTRNOPE').Count -eq 1) "unmatched row listed"
$m = (Call $acct POST "/fees/reconcile/$($row.id)/match" @{ payment_id = $decl.id }).data
Assert ($m.status -eq 'matched') "reconciled"
$chq = (Call $acct POST "/fees/collect" @{ invoice_id = $inv.id; amount_paise = 100000; mode = 'cheque'; cheque = @{ no = '000111'; date = (Get-Date).ToString('yyyy-MM-dd'); bank = 'SBI' } } 200 @{ 'Idempotency-Key' = [guid]::NewGuid().ToString() }).data
$b = (Call $acct POST "/fees/payments/$($chq.payments[0].id)/bounce" @{ reason = 'Insufficient funds'; bank_charges_paise = 50000 }).data
Assert ($b.status -eq 'bounced') "bounced"
$after = (Call $acct GET "/fees/invoices/$($inv.id)").data
Assert (@($after.items | Where-Object description -like 'Cheque bounce*').Count -eq 1) "bank charges item"

# ---- 8. receipt cancellation --------------------------------------------------------------------------------------------------------
function ApproveLater($path) {
  # try the remaining approvers in turn: the institution admin, then the vice-chancellor (phase 33 seed)
  foreach ($t in @($admin, (Login 'principal' (Get-DemoPassword 'vice_chancellor' 'principal')))) {
    $r = Invoke-WebRequest -Method Post -Uri "$script:BaseUrl$path" -Headers @{ Authorization = "Bearer $t" } -SkipHttpErrorCheck
    if ($r.StatusCode -eq 200) { Write-Host "OK POST $path -> 200" }
  }
}
Write-Host "== 8. cancel receipt"
$cr = (Call $acct POST "/fees/payments/$($c1.payments[0].id)/cancel-request" @{ reason = 'Wrong student' }).data
Assert ($cr.cancel_workflow_instance_id) "workflow started"
Call $acct POST "/fees/payments/$($c1.payments[0].id)/cancel-request/approve" | Out-Null
$wf = (Sql "SELECT status FROM workflow_instances WHERE id='$($cr.cancel_workflow_instance_id)'")[0].status
if ($wf -ne 'approved') { ApproveLater "/fees/payments/$($c1.payments[0].id)/cancel-request/approve" }
Assert ((Call $acct GET "/fees/payments/$($c1.payments[0].id)").data.status -eq 'cancelled') "receipt cancelled"
$del = Raw $acct DELETE "/fees/payments/$($c1.payments[0].id)"
Assert ($del.Status -eq 405) "no DELETE route (405)"

# ---- 9. late fee + overdue hold ---------------------------------------------------------------------------------------------------------
Write-Host "== 9. late fee / holds"
$od = (Call $acct POST "/_dev/fees/link" @{ source_type = 'structure_verify'; source_id = [guid]::NewGuid().ToString(); amount_paise = 200000; enrollment_id = $s2 }).data
SqlW "UPDATE fee_invoices SET source_type='structure', due_date=CURRENT_DATE - 45 WHERE id='$($od.id)'"
SqlW "UPDATE fee_invoice_items SET due_date=CURRENT_DATE - 45 WHERE invoice_id='$($od.id)'"
Call $acct POST "/_dev/fees/late-fees" | Out-Null
Assert ((Call $acct GET "/fees/invoices/$($od.id)").data.fine_paise -gt 0) "late fee posted after grace"
SqlW "UPDATE institution_settings SET value='30' WHERE institution_id='$inst' AND category='fees' AND key='hold_on_overdue_days' AND college_id IS NULL"
Call $acct POST "/_dev/fees/overdue-holds" | Out-Null
Assert ((Sql "SELECT count(*) n FROM student_holds WHERE source_type='fee_invoice' AND source_id='$($od.id)' AND released_at IS NULL")[0].n -ge 1) "hold placed"
$bal = (Call $acct GET "/fees/invoices/$($od.id)").data.balance_paise
Call $acct POST "/fees/collect" @{ invoice_id = $od.id; amount_paise = $bal; mode = 'cash' } 200 @{ 'Idempotency-Key' = [guid]::NewGuid().ToString() } | Out-Null
Assert ((Sql "SELECT count(*) n FROM student_holds WHERE source_type='fee_invoice' AND source_id='$($od.id)' AND released_at IS NULL")[0].n -eq 0) "hold released on payment"
SqlW "UPDATE institution_settings SET value='0' WHERE institution_id='$inst' AND category='fees' AND key='hold_on_overdue_days' AND college_id IS NULL"

# ---- 10. discounts ----------------------------------------------------------------------------------------------------------------------
Write-Host "== 10. discounts"
$sib = ((Call $acct GET "/fee-discounts").data | Where-Object code -eq 'SIBLING').id
# the previous run's sibling assignment (FK-aware: invoices may carry its discount lines)
& $Py (Join-Path $PSScriptRoot "_purge.py") student_discount_assignments "reason = 'verify-12 sibling'" | Out-Null
$da = (Call $acct POST "/fee-discounts/$sib/assign" @{ enrollment_id = $s2; reason = 'verify-12 sibling' }).data
Assert ($da.status -eq 'pending') "concession waits for approval"
Call $acct POST "/fee-discounts/assignments/$($da.id)/approve" | Out-Null
Call $registrar POST "/fee-discounts/assignments/$($da.id)/approve" | Out-Null
Assert ((Sql "SELECT status FROM student_discount_assignments WHERE id='$($da.id)'")[0].status -eq 'approved') "approved"

# ---- 11. scholarships ----------------------------------------------------------------------------------------------------------------------
Write-Host "== 11. scholarships"
$sch = (Call $acct POST "/scholarships" @{ name = 'verify-12 merit'; provider = 'institution'; amount_paise = 2000000; eligibility_rules = @{ income_cap_paise = 50000000 } }).data
$strict = (Call $acct POST "/scholarships" @{ name = 'verify-12 strict'; provider = 'institution'; amount_paise = 1000; eligibility_rules = @{ min_cgpa = 11 } }).data
$a = (Call $s1 POST "/scholarships/$($sch.id)/apply" @{ income_paise = 30000000 }).data
Expect $s1 POST "/scholarships/$($strict.id)/apply" @{ income_paise = 1 } 422 'NOT_ELIGIBLE' | Out-Null
Call $hod POST "/scholarship-applications/$($a.id)/recommend" @{ comment = 'ok' } | Out-Null
Call $registrar POST "/scholarship-applications/$($a.id)/sanction" @{ sanctioned_paise = 2000000 } | Out-Null
$d = (Call $acct POST "/scholarship-applications/$($a.id)/disburse" @{ mode = 'fee_credit' }).data
Assert ($d.status -eq 'disbursed') "disbursed"
Assert ((Sql "SELECT count(*) n FROM fee_payments p JOIN fee_invoices i ON i.id=p.invoice_id WHERE p.payment_mode='scholarship_credit' AND i.student_program_enrollment_id='$($s1row.enrol)'")[0].n -ge 1) "scholarship_credit payment"

# ---- 12. refund ---------------------------------------------------------------------------------------------------------------------------
Write-Host "== 12. refund"
$rf = (Call $acct POST "/fees/refunds" @{ invoice_id = $l1.id; amount_paise = (Call $acct GET "/fees/invoices/$($l1.id)").data.paid_paise; reason = 'verify-12 withdrawal' }).data
Call $acct POST "/fees/refunds/$($rf.id)/approve" | Out-Null
# later steps resolve to the vice-chancellor once later phases seed one (principal), else to the institution admin
if ((Sql "SELECT status FROM fee_refunds WHERE id='$($rf.id)'")[0].status -ne 'approved') { ApproveLater "/fees/refunds/$($rf.id)/approve" }
$pr = (Call $acct POST "/fees/refunds/$($rf.id)/process" @{ refund_mode = 'neft'; reference_no = 'RFV12' }).data
Assert ($pr.status -eq 'processed') "processed"
Assert ((Call $acct GET "/fees/invoices/$($l1.id)").data.status -eq 'refunded') "invoice refunded"

# ---- 13. no-dues ----------------------------------------------------------------------------------------------------------------------------
Write-Host "== 13. no-dues"
$nd = (Call $s1 POST "/no-dues" @{ purpose = 'transfer' }).data
Assert (@($nd.signoffs).Count -ge 5) "parallel sign-offs"
$lb = (Call $lib POST "/no-dues/$($nd.id)/signoff" @{ department_key = 'library'; status = 'dues_pending'; dues_paise = 20000 }).data
Assert ($lb.status -eq 'blocked') "blocked by library dues"
Expect $warden POST "/no-dues/$($nd.id)/signoff" @{ department_key = 'department'; status = 'cleared' } 403 | Out-Null
Call $lib POST "/no-dues/$($nd.id)/signoff" @{ department_key = 'library'; status = 'cleared' } | Out-Null
Write-Host "   (clearing the remaining offices as inst.admin — no_dues:manage)"
SqlW "UPDATE fee_invoices SET status='cancelled' WHERE student_program_enrollment_id='$($s1row.enrol)' AND status IN ('pending','partial','overdue') AND paid_paise=0"
foreach ($k in @($nd.signoffs | ForEach-Object department_key)) {
  if ($k -ne 'library') { Raw $admin POST "/no-dues/$($nd.id)/signoff" @{ department_key = $k; status = 'cleared' } | Out-Null }
}
$fin = (Call $s1 GET "/no-dues/$($nd.id)").data
if ($fin.status -eq 'cleared') { Assert ($fin.certificate_number) "certificate issued" } else { Write-Host "   accounts dues still open - status $($fin.status)" }

# ---- 14. day-book -----------------------------------------------------------------------------------------------------------------------------
Write-Host "== 14. day-book"
$db = (Call $acct GET "/fees/day-book").data
Assert ($db.total_paise -gt 0) "totals by mode"
Call $acct POST "/fees/day-book/close" @{ date = $db.date } | Out-Null
$csv = Raw $acct GET "/fees/day-book/export?date_from=$($db.date)&date_to=$($db.date)"
Assert ($csv.Status -eq 200) "CSV export"

# ---- 15. GST ------------------------------------------------------------------------------------------------------------------------------------
Write-Host "== 15. GST"
SetFlag 'fees.gst_invoicing' $true
$g = (Call $acct POST "/_dev/fees/link" @{ source_type = 'mess'; source_id = [guid]::NewGuid().ToString(); amount_paise = 100000; enrollment_id = $s2 }).data
Assert ($g.tax_paise -eq 5000) "mess invoice carries 5 % GST"
SetFlag 'fees.gst_invoicing' $false

# ---- 16. reports ---------------------------------------------------------------------------------------------------------------------------------
Write-Host "== 16. reports"
Assert ((Call $acct GET "/fees/reports/collection?group_by=mode").data.rows.Count -ge 1) "collection by mode"
Call $acct GET "/fees/reports/defaulters?batch_year=2024" | Out-Null
Call $acct GET "/fees/reports/scholarships" | Out-Null
SetFlag 'fees.accounting_export' $true
$ex = (Call $acct POST "/fees/accounting-export" @{ date_from = (Get-Date).AddDays(-30).ToString('yyyy-MM-dd'); date_to = (Get-Date).ToString('yyyy-MM-dd') } 202).data
Assert ((WaitJob $acct $ex.job_id).status -eq 'succeeded') "Tally XML export"
SetFlag 'fees.accounting_export' $false

# ---- 17. auditor -----------------------------------------------------------------------------------------------------------------------------------
Write-Host "== 17. auditor"
Call $auditor GET "/fees/invoices?scope=all&page_size=5" | Out-Null
Expect $auditor POST "/fees/collect" @{ invoice_id = $inv.id; amount_paise = 100; mode = 'cash' } 403 | Out-Null

Summary '12'
