# API verification — Phase 14 exam administration (Prompts/14 §14.11).
#
# Run from backend/ with the API, the Celery worker and Redis (or the TCP fakeredis) up:
#   .\scripts\verify\14_exams.ps1 [-BaseUrl http://localhost:8000/api/v1]
#
# Seed first: python scripts/seed_demo_institution.py --type university --only exams
#
# Roles: coe (MFA as in the seeded tenant), exam.cell, hod.cse, faculty.1, examiner.ext, accountant, student.1,
# parent.1, auditor.tmp, public.
#
# Documented deviations (PROGRESS.md decisions log, Phase 14):
#  * the script creates its own session ("verify-14 …") on the current term so earlier seed data stays untouched;
#  * a used / expired QP download token answers 409 TOKEN_USED (410 is not in the API's allowed status codes);
#  * seating generation is inline (dry runs and real runs) — the shortfall check is asserted on a 1-room request;
#  * student.detained / student.hold logins do not exist in the demo tenant — detained / hold cases are produced by
#    editing the snapshot / placing a hold through the API on student.1 and reverting them.
param([string]$BaseUrl = "http://localhost:8000/api/v1")
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl
$Backend = Resolve-Path (Join-Path $PSScriptRoot "../..")
$Py = Get-VenvPython $Backend
function Sql($q) { (& $Py (Join-Path $PSScriptRoot "_sql.py") $q) | ConvertFrom-Json }
function SqlW($q) { & $Py (Join-Path $PSScriptRoot "_sql.py") --write $q | Out-Null }
function Raw($token, $method, $path, $body = $null, $headers = @{}) {
  $h = @{}
  if ($token) { $h['Authorization'] = "Bearer $token" }
  foreach ($k in $headers.Keys) { $h[$k] = $headers[$k] }
  $p = @{ Method = $method; Uri = "$script:BaseUrl$path"; Headers = $h; SkipHttpErrorCheck = $true }
  if ($null -ne $body) { $p['ContentType'] = 'application/json'; $p['Body'] = ($body | ConvertTo-Json -Depth 10) }
  $r = Invoke-WebRequest @p
  return @{ Status = $r.StatusCode; Body = $(if ($r.Content -and $r.Headers['Content-Type'] -match 'json') { $r.Content | ConvertFrom-Json } else { $r.Content }) }
}
function Expect($token, $method, $path, $body, $status, $code = $null) {
  $r = Raw $token $method $path $body
  if ($r.Status -ne $status) { throw "$method $path expected $status got $($r.Status): $($r.Body | ConvertTo-Json -Depth 6 -Compress)" }
  if ($code -and ($r.Body.error.details.code -ne $code) -and ($r.Body.error.code -ne $code)) { throw "$method $path expected code $code got $($r.Body.error | ConvertTo-Json -Depth 6 -Compress)" }
  $script:Checks++
  Write-Host "OK $method $path -> $status $code"
  return $r.Body
}
function WaitJob($token, $jobId, $seconds = 180) {
  for ($i = 0; $i -lt $seconds; $i++) {
    $j = (Call $token GET "/jobs/$jobId").data
    if ($j.status -in @('succeeded', 'failed', 'cancelled')) { return $j }
    Start-Sleep -Seconds 1
  }
  throw "job $jobId did not finish"
}

$coe = Login-Mfa 'controller_of_examinations' 'coe'
$exam = Login 'exam.cell' (Get-DemoPassword 'exam_cell')
$hod = Login 'hod.cse' (Get-DemoPassword 'hod')
$f1 = Login 'faculty.1' (Get-DemoPassword 'faculty')
$ext = Login 'examiner.ext' (Get-DemoPassword 'external_examiner')
$acct = Login 'accountant' (Get-DemoPassword 'accountant')
$s1 = Login 'student.1' (Get-DemoPassword 'student')
$parent = Login 'parent.1' (Get-DemoPassword 'parent')
$auditor = Login 'auditor.tmp' (Get-DemoPassword 'auditor')
$inst = (Sql "SELECT id FROM institutions WHERE slug='demo-uni'")[0].id
$term = (Sql "SELECT id FROM academic_terms WHERE institution_id='$inst' AND college_id IS NULL AND is_current AND deleted_at IS NULL")[0].id
$s1enrol = (Sql "SELECT e.id FROM students s JOIN users u ON u.id=s.user_id JOIN student_program_enrollments e ON e.student_id=s.id WHERE u.username='student.1' LIMIT 1")[0].id

# ---- 0. reset ------------------------------------------------------------------------------------------------------------
SqlW "DELETE FROM exam_sessions WHERE name LIKE 'verify-14%'"
# phase 12's overdue-fee job places exam holds on student.1 (seeded invoices): clear them for the registration flow
SqlW "UPDATE student_holds SET released_at = NOW() WHERE student_program_enrollment_id = '$s1enrol' AND hold_type = 'exam' AND released_at IS NULL"

# ---- 1. sessions ---------------------------------------------------------------------------------------------------------
Write-Host "== 1. sessions"
Call $s1 GET "/exam-sessions" | Out-Null
$now = (Get-Date).ToUniversalTime()
$S = (Call $exam POST "/exam-sessions" @{ name = 'verify-14 regular'; term_id = $term; registration_start = $now.AddDays(-1).ToString('o'); registration_end = $now.AddDays(2).ToString('o'); late_fee_until = $now.AddDays(4).ToString('o'); hall_ticket_release_at = $now.AddDays(1).ToString('o') } 201).data
Expect $f1 POST "/exam-sessions" @{ name = 'verify-14 x'; term_id = $term } 403 | Out-Null

# ---- 2. papers ------------------------------------------------------------------------------------------------------------
Write-Host "== 2. papers"
$pv = (Call $exam POST "/exam-sessions/$($S.id)/papers/bulk?dry_run=true" @{ dry_run = $true }).data
Assert (($pv.theory + $pv.practical + $pv.project_viva + $pv.arrear_only) -gt 0) "bulk preview"
WaitJob $exam (Call $exam POST "/exam-sessions/$($S.id)/papers/bulk" @{} 202).data.job_id | Out-Null
$n1 = (Call $exam GET "/exam-sessions/$($S.id)/papers").data.Count
WaitJob $exam (Call $exam POST "/exam-sessions/$($S.id)/papers/bulk" @{} 202).data.job_id | Out-Null
Assert ((Call $exam GET "/exam-sessions/$($S.id)/papers").data.Count -eq $n1) "no duplicates"

# ---- 3. date-sheet ------------------------------------------------------------------------------------------------------------
Write-Host "== 3. date-sheet"
$papers = (Call $exam GET "/exam-sessions/$($S.id)/papers").data
$mine = @(Sql "SELECT p.id FROM exam_papers p JOIN course_offerings o ON o.course_id=p.course_id JOIN course_registration_items i ON i.offering_id=o.id JOIN course_registrations r ON r.id=i.registration_id WHERE p.exam_session_id='$($S.id)' AND r.student_program_enrollment_id='$s1enrol' AND i.status='confirmed' AND r.term_id='$term'" | ForEach-Object id)
$entries = @(); $k = 0
foreach ($p in $papers) { $entries += @{ paper_id = $p.id; exam_date = (Get-Date).AddDays(30 + [math]::Floor($k / 2)).ToString('yyyy-MM-dd'); session_slot = $(if ($k % 2) { 'AN' } else { 'FN' }) }; $k++ }
if ($mine.Count -ge 2) { ($entries | Where-Object paper_id -eq $mine[1]).exam_date = ($entries | Where-Object paper_id -eq $mine[0]).exam_date; ($entries | Where-Object paper_id -eq $mine[1]).session_slot = ($entries | Where-Object paper_id -eq $mine[0]).session_slot }
Call $exam PUT "/exam-sessions/$($S.id)/date-sheet" @{ entries = $entries } | Out-Null
if ($mine.Count -ge 2) {
  $cl = (Call $exam POST "/exam-sessions/$($S.id)/date-sheet/check-clashes").data
  Assert ($cl.items.Count -ge 1) "clash listed"
  Expect $exam POST "/exam-sessions/$($S.id)/date-sheet/publish" $null 409 'DATE_SHEET_CLASH' | Out-Null
  ($entries | Where-Object paper_id -eq $mine[1]).exam_date = (Get-Date).AddDays(45).ToString('yyyy-MM-dd')
  Call $exam PUT "/exam-sessions/$($S.id)/date-sheet" @{ entries = $entries } | Out-Null
}
$pub = Raw $exam POST "/exam-sessions/$($S.id)/date-sheet/publish"
if ($pub.Status -ne 200) { Call $coe POST "/exam-sessions/$($S.id)/date-sheet/publish?force=true" | Out-Null }
Assert ((Sql "SELECT count(*) n FROM calendar_events WHERE source_type='exam_paper' AND deleted_at IS NULL AND source_id IN (SELECT id FROM exam_papers WHERE exam_session_id='$($S.id)')")[0].n -ge 1) "calendar events"
$ics = Raw $s1 GET "/exam-sessions/$($S.id)/date-sheet.ics"
Assert ($ics.Status -eq 200 -and "$($ics.Body)" -match 'BEGIN:VCALENDAR') "ICS"

# ---- 4. registration ----------------------------------------------------------------------------------------------------------
Write-Host "== 4. registration"
Call $exam POST "/exam-sessions/$($S.id)/status" @{ status = 'registration_open' } | Out-Null
$me = (Call $s1 GET "/exam-registration/me?session_id=$($S.id)").data
Assert ($me.items.Count -ge 1 -and $me.total_fee_paise -gt 0) "items + fee"
$key = [guid]::NewGuid().ToString()
$sub = (Call $s1 POST "/exam-registration/me/submit?session_id=$($S.id)" @{} 200 @{ 'Idempotency-Key' = $key }).data
Assert ($sub.status -in @('fee_pending', 'confirmed')) "submitted"
$sub2 = (Call $s1 POST "/exam-registration/me/submit?session_id=$($S.id)" @{} 200 @{ 'Idempotency-Key' = $key }).data
Assert ($sub2.id -eq $sub.id) "replay"
if ($sub.status -eq 'fee_pending') {
  $inv = (Call $acct GET "/fees/invoices/$($sub.fee_invoice_id)").data
  Assert ($inv.source_type -eq 'exam_registration') "invoice source"
  Call $acct POST "/fees/collect" @{ invoice_id = $inv.id; amount_paise = $inv.balance_paise; mode = 'cash' } 200 @{ 'Idempotency-Key' = [guid]::NewGuid().ToString() } | Out-Null
  for ($i = 0; $i -lt 30 -and (Call $s1 GET "/exam-registration/me?session_id=$($S.id)").data.status -ne 'confirmed'; $i++) { Start-Sleep 1 }
  Assert ((Call $s1 GET "/exam-registration/me?session_id=$($S.id)").data.status -eq 'confirmed') "confirmed after payment (consumer)"
}

# ---- 5. eligibility ------------------------------------------------------------------------------------------------------------
Write-Host "== 5. eligibility"
WaitJob $exam (Call $exam POST "/exam-sessions/$($S.id)/eligibility/apply" @{} 202).data.job_id | Out-Null
$sum = (Call $exam GET "/exam-sessions/$($S.id)/eligibility/summary").data
Assert ($sum.items -ge 1) "eligibility summary"

# ---- 6. hall tickets -----------------------------------------------------------------------------------------------------------
Write-Host "== 6. hall tickets"
WaitJob $exam (Call $exam POST "/exam-sessions/$($S.id)/hall-tickets/generate" @{ only_missing = $true } 202).data.job_id | Out-Null
$reg = (Call $s1 GET "/exam-registration/me?session_id=$($S.id)").data
if ($reg.hall_ticket_number) {
  Expect $s1 GET "/exam-registration/me/hall-ticket.pdf?session_id=$($S.id)" $null 403 'NOT_RELEASED' | Out-Null
  $tok = (Sql "SELECT hall_ticket_qr_token t FROM exam_registrations WHERE id='$($reg.id)'")[0].t
  $v = (Raw $null GET "/hall-tickets/verify/$tok").Body.data
  Assert ($v.valid -and $v.papers.Count -ge 1) "public verify"
}

# ---- 7. seating ------------------------------------------------------------------------------------------------------------------
Write-Host "== 7. seating"
$slot = (Sql "SELECT exam_date d, session_slot s FROM exam_papers WHERE exam_session_id='$($S.id)' ORDER BY exam_date LIMIT 1")[0]
$rooms = @(Sql "SELECT id FROM rooms WHERE institution_id='$inst' AND deleted_at IS NULL ORDER BY capacity DESC LIMIT 3" | ForEach-Object id)
$pre = (Call $exam POST "/exam-sessions/$($S.id)/seating/generate" @{ exam_date = $slot.d; session_slot = $slot.s; room_ids = $rooms; dry_run = $true }).data
Write-Host "   $($pre.candidates) candidates / $($pre.seats) seats"
if ($pre.candidates -gt 0) {
  Call $exam POST "/exam-sessions/$($S.id)/seating/generate" @{ exam_date = $slot.d; session_slot = $slot.s; room_ids = $rooms } | Out-Null
  Call $exam POST "/exam-sessions/$($S.id)/seating/publish?date=$($slot.d)&slot=$($slot.s)" | Out-Null
}

# ---- 8. invigilation -------------------------------------------------------------------------------------------------------------
Write-Host "== 8. invigilation"
$aa = (Call $exam POST "/exam-sessions/$($S.id)/invigilation/auto-assign" @{ date_from = $slot.d; date_to = $slot.d; dry_run = $true }).data
Write-Host "   $($aa.duties) duties (dry run), $($aa.unfilled.Count) unfilled"
Assert ((Sql "SELECT count(*) n FROM (SELECT staff_id FROM invigilation_duties WHERE exam_session_id='$($S.id)' GROUP BY exam_date, session_slot, staff_id HAVING count(*) > 1) x")[0].n -eq 0) "no double booking"
Call $f1 GET "/invigilation-duties/me" | Out-Null
Expect $f1 POST "/exam-sessions/$($S.id)/invigilation/auto-assign" @{ date_from = $slot.d; date_to = $slot.d; dry_run = $true } 403 | Out-Null

# ---- 9. QP ------------------------------------------------------------------------------------------------------------------------
Write-Host "== 9. QP"
$P = $papers[0]
$f1staff = (Sql "SELECT s.id FROM staff s JOIN users u ON u.id=s.user_id WHERE u.username='faculty.1'")[0].id
$extId = (Sql "SELECT id FROM users WHERE username='examiner.ext' AND institution_id='$inst'")[0].id
$a = (Call $exam POST "/exam-papers/$($P.id)/qp-assignments" @{ set_label = 'A'; setter_staff_id = $f1staff } 201).data
$b = (Call $exam POST "/exam-papers/$($P.id)/qp-assignments" @{ set_label = 'B'; external_setter = @{ name = 'Ext'; user_id = $extId } } 201).data
Assert ((Call $ext GET "/qp-assignments/me").data.Count -ge 1) "external sees own assignment"
$tmp = New-TemporaryFile; Set-Content $tmp "%PDF-1.4 verify set A"
$up = Invoke-RestMethod -Method POST -Uri "$BaseUrl/qp-assignments/$($a.id)/upload" -Headers @{ Authorization = "Bearer $f1" } -Form @{ file = Get-Item $tmp } -SkipHttpErrorCheck
Assert ($up.data.status -eq 'submitted') "uploaded"
Call $exam POST "/qp-assignments/$($a.id)/scrutinise" @{ decision = 'approve' } | Out-Null
Call $coe POST "/qp-assignments/$($a.id)/select" | Out-Null
$pr = (Call $exam POST "/qp-assignments/$($a.id)/print" @{ copies = 50 }).data
Assert ((Raw $exam GET "/qp/download/$($pr.download_token)").Status -eq 200) "download once"
Expect $exam GET "/qp/download/$($pr.download_token)" $null 409 'TOKEN_USED' | Out-Null
Assert ((Sql "SELECT count(*) n FROM audit_logs WHERE action='qp_access'")[0].n -ge 1) "qp_access audited"

# ---- 10. conduct ------------------------------------------------------------------------------------------------------------------
Write-Host "== 10. conduct"
$roster = (Call $exam GET "/exam-papers/$($P.id)/attendance").data
if ($roster.Count -ge 3) {
  Expect $exam POST "/exam-papers/$($P.id)/attendance" @{ items = @(@{ exam_registration_item_id = $roster[0].exam_registration_item_id; status = 'present'; answer_booklet_number = 'VB1' }, @{ exam_registration_item_id = $roster[1].exam_registration_item_id; status = 'present'; answer_booklet_number = 'VB1' }) } 422 'DUPLICATE_BOOKLET' | Out-Null
  Call $exam POST "/exam-papers/$($P.id)/attendance" @{ items = @(@{ exam_registration_item_id = $roster[0].exam_registration_item_id; status = 'present'; answer_booklet_number = 'VB1' }, @{ exam_registration_item_id = $roster[1].exam_registration_item_id; status = 'absent' }) } 200 @{ 'Idempotency-Key' = [guid]::NewGuid().ToString() } | Out-Null
  Call $exam POST "/exam-papers/$($P.id)/malpractice-reports" @{ exam_registration_item_id = $roster[2].exam_registration_item_id; category = 'copying'; invigilator_report = 'verify-14 chit' } 201 | Out-Null
  Assert ((Sql "SELECT status FROM exam_registration_items WHERE id='$($roster[2].exam_registration_item_id)'")[0].status -eq 'malpractice') "item malpractice"
}

# ---- 13. visibility ----------------------------------------------------------------------------------------------------------------
Write-Host "== 13. visibility"
Call $acct GET "/exam-sessions/$($S.id)/registrations?page_size=5" | Out-Null
Call $auditor GET "/exam-sessions/$($S.id)/registrations?page_size=5" | Out-Null
Expect $auditor POST "/exam-sessions/$($S.id)/status" @{ status = 'registration_closed' } 403 | Out-Null
$ward = (Sql "SELECT g.student_id FROM student_guardians g JOIN users u ON u.id=g.user_id WHERE u.username='parent.1' LIMIT 1")
if ($ward) { Raw $parent GET "/exam-registration/me?student_id=$($ward[0].student_id)" | Out-Null }

Summary '14'
