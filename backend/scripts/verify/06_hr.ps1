# API verification — Phase 06 staff, faculty, HR, recruitment & CAS
# (Prompts/06_Phase06_Staff_Faculty_HR_Recruitment_CAS.md §06.11).
#
# Run from backend/ with the API up, Redis and a Celery worker + Beat (payroll generation and payslips are jobs; the
# outbox relay dispatches leave.approved and the notifications):
#   .\scripts\verify\06_hr.ps1 [-BaseUrl http://localhost:8000/api/v1]
#
# Seed first: python scripts/seed_demo_institution.py --type university --only hr   (runs base → … → academics → hr)
#
# Roles: hr, accountant, hod.cse, hod.ece, dean.eng, faculty.1, faculty.2 (ECE), student.1, auditor.tmp
# (+ inst.admin, superadmin for feature flags). Re-runnable: step 0 resets faculty.1 / faculty.2 HR fixtures (leaves,
# balances, Oct/Nov 2026 payroll, verification salary structures, the CAS promotion, appraisals, today's attendance,
# the CSE allocation proposal); every run uses its own leave dates, holiday, staff member, posting and applicant.
#
# Documented deviations from the prompt text (see PROGRESS.md decisions log, Phase 06):
#  * leave.approval is the Phase 04 template HOD → HR: hod.cse's approval leaves the leave pending at step 2, hr's
#    approval completes it;
#  * the institution scope tab is called "all" in meta.visibility (Phase 02 resolver), not "institution";
#  * PUT /staff/{other} as faculty.1 is refused by the route permission (hr:update) → 403;
#  * marking someone else's attendance needs hr:manage (the accountant is view-only per the visibility table).
#  1. seed: 30 staff, designations, leave types, components, structures; unit holders back-filled by staff rows
#  2. POST /staff (hr) → 201, employee id + user with role faculty; PII masked for hod.cse, full for hr; hod.ece → 404
#  3. GET /staff: accountant → all, faculty.1 → self; PUT other → 403; PUT /staff/me → 200
#  4. CL over a holiday → days_count 1, balance pending; visibility of the leave per role
#  5. accountant approve → 403; hod.cse → step 2; hr → approved; balance used, on_leave rows, event, notification
#  6. overlap → 409; ML 5 days without document → 422; cancel approved before start → balance restored
#  7. encashment off → 403 FEATURE_DISABLED; on → workflow instance
#  8. geo check-in outside → 422, inside → 201; hr marks faculty.2 absent; device punches pair + unknown code; scopes
#  9. payroll generate → items (Basic/DA/HRA, PF, PT, LOP, EMI); regenerate idempotent; approve; mark paid → payslip
#     PDF; /payroll/me own only; student 403; registers; Form 16
# 10. increment effective 1 Oct → arrears in the November run; service-book increment entry
# 11. recruitment: invalid roster 422; publish → public careers; apply → screen → shortlist → panel score → select →
#     offer → join → staff created and linked
# 12. PBAS self-appraisal → hod.cse review → hr approve; CAS eligibility → submit → decide → designation, structure,
#     promotion entry
# 13. workload 0 h with norm + status; allocation proposal submit → dean approve → apply 409 (offerings: Phase 09)
# 14. auditor reads staff / leaves / payroll; POST /leaves → 403
param([string]$BaseUrl = "http://localhost:8000/api/v1")
. "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl
$Backend = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Python = Get-VenvPython $Backend
$env:PYTHONUTF8 = "1"
Push-Location $Backend

function Sql($query) {
  $out = & $Python scripts/verify/_sql.py $query
  if ($LASTEXITCODE -ne 0) { throw "sql failed: $query" }
  return @($out | ConvertFrom-Json)
}
function SqlWrite($query) { & $Python scripts/verify/_sql.py --write $query | Out-Null; if ($LASTEXITCODE -ne 0) { throw "sql failed: $query" } }
function WaitFor($label, [scriptblock]$probe, $seconds = 60) {
  for ($i = 0; $i -lt $seconds; $i++) { $v = & $probe; if ($v) { return $v }; Start-Sleep -Seconds 1 }
  throw "timed out waiting for: $label"
}
function Status($token, $method, $path, $body = $null) {
  $h = @{}
  if ($token) { $h['Authorization'] = "Bearer $token" }
  $p = @{ Method = $method; Uri = "$script:BaseUrl$path"; Headers = $h; SkipHttpErrorCheck = $true }
  if ($null -ne $body) { $p['ContentType'] = 'application/json'; $p['Body'] = ($body | ConvertTo-Json -Depth 8) }
  return (Invoke-WebRequest @p).StatusCode
}
function Job($token, $jobId) {
  WaitFor "job $jobId" { $j = (Call $token GET "/jobs/$jobId").data; if ($j.status -in @('succeeded', 'failed', 'cancelled')) { $j } } 120
}

$flags = @('hr.cas_promotions', 'hr.appraisal_pbas', 'hr.reservation_roster', 'hr.recruitment', 'hr.leave_encashment', 'attendance.biometric', 'attendance.geo_app')
try {
  $run = Get-Random -Minimum 10000 -Maximum 99999
  foreach ($u in @(@('hr', 'hr_officer'), @('accountant', 'accountant'), @('hod.cse', 'hod'), @('hod.ece', 'hod_ece'), @('dean.eng', 'dean'),
                   @('faculty.1', 'faculty'), @('faculty.2', 'faculty_2'), @('student.1', 'student'), @('auditor.tmp', 'auditor'), @('inst.admin', 'institution_admin'))) {
    & $Python scripts/verify/_reset_password.py $u[0] (Get-DemoPassword $u[1]) | Out-Null
  }
  # the time-boxed auditor (Phase 02 seed: 7 days) — extend it for this run
  SqlWrite "UPDATE users SET valid_to = NOW() + INTERVAL '7 days', is_active = TRUE WHERE username = 'auditor.tmp'; UPDATE user_roles SET valid_to = NOW() + INTERVAL '7 days' WHERE user_id IN (SELECT id FROM users WHERE username = 'auditor.tmp')"
  $hr = Login 'hr' (Get-DemoPassword 'hr_officer')
  $acct = Login 'accountant' (Get-DemoPassword 'accountant')
  $hod = Login 'hod.cse' (Get-DemoPassword 'hod')
  $hodEce = Login 'hod.ece' (Get-DemoPassword 'hod_ece')
  $dean = Login 'dean.eng' (Get-DemoPassword 'dean')
  $f1 = Login 'faculty.1' (Get-DemoPassword 'faculty')
  $f2 = Login 'faculty.2' (Get-DemoPassword 'faculty_2')
  $student = Login 'student.1' (Get-DemoPassword 'student')
  $auditor = Login 'auditor.tmp' (Get-DemoPassword 'auditor')
  $admin = Login 'inst.admin' (Get-DemoPassword 'institution_admin')
  $sa = Login-SuperAdmin
  $instId = (Call $admin GET "/auth/me").data.user.institution_id
  $tenant = @{ 'X-Institution-Id' = $instId }
  function SetFlag($key, $on) {
    Call $sa PUT "/institutions/$instId/features/$key" @{ enabled = $on; confirm_dependencies = $true; reason = "verify 06" } 200 $tenant | Out-Null
  }
  $depts = (Call $admin GET "/departments?page_size=200").data
  $cse = ($depts | Where-Object { $_.code -eq 'CSE' -and $_.college_code -eq 'A' }).id
  $ece = ($depts | Where-Object { $_.code -eq 'ECE' -and $_.college_code -eq 'A' }).id
  $me1 = (Call $f1 GET "/staff/me").data
  $me2 = (Call $f2 GET "/staff/me").data
  $s1 = $me1.id; $s2 = $me2.id

  Write-Host "== 0. fixture reset (faculty.1 / faculty.2)"
  foreach ($flag in $flags) { SetFlag $flag $false }
  $asst = (Sql "SELECT id FROM designations WHERE institution_id = '$instId' AND code = 'ASST'")[0].id
  SqlWrite ("DELETE FROM staff_attendance WHERE staff_id IN ('$s1','$s2') AND (attendance_date >= '2026-10-01' OR status = 'on_leave'); " +
    "DELETE FROM staff_leaves WHERE staff_id IN ('$s1','$s2'); DELETE FROM staff_leave_balances WHERE staff_id IN ('$s1','$s2'); " +
    "DELETE FROM staff_payrolls WHERE year = 2026 AND month IN (10, 11) AND institution_id = '$instId'; " +
    "DELETE FROM staff_salary_structures WHERE staff_id = '$s1' AND effective_from >= '2026-10-01'; " +
    "UPDATE staff_salary_structures SET effective_to = NULL WHERE staff_id = '$s1' AND effective_from = '2026-04-01'; " +
    "UPDATE loans_advances SET balance_paise = principal_paise, status = 'active' WHERE staff_id = '$s1'; " +
    "DELETE FROM cas_applications WHERE staff_id = '$s1'; DELETE FROM appraisals WHERE staff_id = '$s1'; " +
    "DELETE FROM service_book_entries WHERE staff_id = '$s1' AND entry_type IN ('promotion', 'increment'); " +
    "UPDATE faculty_profiles SET cadre = 'assistant' WHERE staff_id = '$s1'; UPDATE staff SET designation_id = '$asst' WHERE id = '$s1'; " +
    "DELETE FROM course_allocation_proposals WHERE department_id = '$cse'")
  Assert ($s1 -and $s2 -and $me1.employee_id -eq 'E1003') "faculty.1 / faculty.2 have staff rows"

  Write-Host "== 1. seed --only hr"
  $count = (Sql "SELECT COUNT(*) AS n FROM staff WHERE institution_id = '$instId' AND employee_id LIKE 'E1%'")[0].n
  Assert ($count -ge 30) "30 seeded staff ($count)"
  $holders = Sql "SELECT d.code, s.employee_id FROM departments d JOIN staff s ON s.id = d.hod_staff_id WHERE d.id IN ('$cse','$ece')"
  Assert ((($holders | Where-Object { $_.code -eq 'CSE' }).employee_id -eq 'E1002') -and (($holders | Where-Object { $_.code -eq 'ECE' }).employee_id -eq 'E1005')) "departments.hod_staff_id backed by staff rows (Phase 03 holders)"
  $deanRow = Sql "SELECT s.employee_id FROM faculties f JOIN staff s ON s.id = f.dean_staff_id WHERE f.institution_id = '$instId' AND f.code = 'ENG'"
  Assert ($deanRow[0].employee_id -eq 'E1001') "faculties.dean_staff_id backed by the dean's staff row"
  $types = (Call $hr GET "/leave-types").data
  Assert (($types | Where-Object { $_.code -eq 'EL' -and $_.accrual -eq 'monthly' }) -and ($types | Where-Object { $_.code -eq 'ML' -and $_.requires_document })) "pack leave types (EL monthly, ML needs a document)"
  $comps = (Call $hr GET "/payroll/components").data
  Assert (($comps | Where-Object { $_.code -eq 'PF_EE' -and $_.statutory_kind -eq 'pf' })) "statutory payroll components (PF)"

  Write-Host "== 2. create staff + PII masking"
  $designations = (Call $hr GET "/designations").data
  $pan = "VERIF$('{0:D4}' -f ($run % 10000))Z"
  $new = (Call $hr POST "/staff" @{ first_name = "Verify"; last_name = "Staff $run"; department_id = $cse; designation_id = $asst; employment_type = 'regular'; joining_date = '2026-07-01'; pan = $pan; email = "v$run@demo-uni.septronuniverse.in" } 201).data
  Assert ($new.staff.employee_id -like 'EMP*' -and $new.username -eq $new.staff.employee_id -and $new.temp_password) "employee id from the sequence, user = employee id, temporary password"
  $role = Sql "SELECT r.slug FROM user_roles ur JOIN roles r ON r.id = ur.role_id WHERE ur.user_id = '$($new.staff.user_id)'"
  Assert (($role | Where-Object { $_.slug -eq 'faculty' })) "user created with role faculty"
  $masked = (Call $hod GET "/staff/$($new.staff.id)").data
  Assert ($masked.pan.StartsWith('*') -and $masked.pan.EndsWith($pan.Substring(6)) -and $masked.pan -ne $pan) "hod.cse sees the PAN masked ($($masked.pan))"
  Assert (((Call $hr GET "/staff/$($new.staff.id)").data.pan) -eq $pan) "hr (hr:view_pii) sees the PAN"
  Call $hodEce GET "/staff/$($new.staff.id)" $null 404 | Out-Null

  Write-Host "== 3. list visibility"
  $all = Call $acct GET "/staff?page_size=200"
  $total = (Sql "SELECT COUNT(*) AS n FROM staff WHERE institution_id = '$instId' AND deleted_at IS NULL")[0].n
  Assert ($all.meta.visibility.scopes -contains 'all' -and $all.meta.pagination.total -eq $total) "accountant: scopes [all], every staff member ($total)"
  $mine = Call $f1 GET "/staff?scope=all"
  Assert ($mine.meta.pagination.total -eq 1 -and $mine.data[0].is_self -and $mine.meta.visibility.scopes.Count -eq 0) "faculty.1: only self"
  Call $f1 PUT "/staff/$($new.staff.id)" @{ first_name = 'X' } 403 | Out-Null
  $upd = Call $f1 PUT "/staff/me" @{ phone = "+919800$run" }
  Assert ($upd.data.phone -eq "+919800$run") "PUT /staff/me updates the phone"

  Write-Host "== 4. apply leave over a holiday"
  $d1 = (Get-Date '2026-11-02').AddDays($run % 35)
  while ($d1.DayOfWeek -in @('Friday', 'Saturday', 'Sunday')) { $d1 = $d1.AddDays(1) }
  $d2 = $d1.AddDays(1)
  $from = $d1.ToString('yyyy-MM-dd'); $to = $d2.ToString('yyyy-MM-dd')
  $hol = (Call $admin POST "/holidays" @{ name = "Verify holiday $run"; holiday_date = $to; holiday_type = 'institution'; applies_to = 'all' } 201).data
  $cl = ($types | Where-Object { $_.code -eq 'CL' }).id
  $before = (Call $f1 GET "/leaves/me/balance").data | Where-Object { $_.code -eq 'CL' }
  $leave = (Call $f1 POST "/leaves" @{ leave_type_id = $cl; from_date = $from; to_date = $to; reason = "verify 06 run $run" } 201).data
  Assert ([double]$leave.days_count -eq 1 -and $leave.status -eq 'pending' -and $leave.workflow_instance_id) "CL $from..$to spanning the holiday → days_count 1, pending, workflow started"
  $pend = (Call $f1 GET "/leaves/me/balance").data | Where-Object { $_.code -eq 'CL' }
  Assert ([double]$pend.pending -eq 1 -and [double]$pend.available -eq ([double]$before.available - 1)) "balance shows 1 day pending"
  $vf = Call $f1 GET "/leaves?scope=all"
  Assert ($vf.meta.visibility.scopes.Count -eq 0 -and -not ($vf.data | Where-Object { -not $_.is_mine })) "faculty.1 ?scope=all narrowed to self"
  $va = Call $acct GET "/leaves?scope=all&page_size=200"
  Assert ($va.meta.visibility.scopes -contains 'all' -and ($va.data | Where-Object { $_.id -eq $leave.id })) "accountant: scopes [all], leave listed"
  $vh = Call $hod GET "/leaves?scope=all&page_size=200"
  Assert (($vh.meta.visibility.scopes -join ',') -eq 'department' -and ($vh.data | Where-Object { $_.id -eq $leave.id })) "hod.cse: scopes [department], leave listed"
  $ve = Call $hodEce GET "/leaves?scope=all&page_size=200"
  Assert (-not ($ve.data | Where-Object { $_.id -eq $leave.id })) "hod.ece does not see it"

  Write-Host "== 5. approval through leave.approval"
  Call $acct POST "/leaves/$($leave.id)/approve" @{} 403 | Out-Null
  $a1 = (Call $hod POST "/leaves/$($leave.id)/approve" @{ comment = 'ok' }).data
  Assert ($a1.status -eq 'pending' -and $a1.current_step -eq 2) "hod.cse approves step 1 → HR step"
  $a2 = (Call $hr POST "/leaves/$($leave.id)/approve" @{}).data
  Assert ($a2.status -eq 'approved') "hr approves → approved"
  $after = (Call $f1 GET "/leaves/me/balance").data | Where-Object { $_.code -eq 'CL' }
  Assert ([double]$after.used -eq ([double]$before.used + 1) -and [double]$after.pending -eq 0) "balance used +1"
  $rows = Sql "SELECT status FROM staff_attendance WHERE staff_id = '$s1' AND attendance_date = '$from'"
  Assert ($rows[0].status -eq 'on_leave') "staff attendance $from = on_leave"
  WaitFor "leave.approved dispatched" { Sql "SELECT 1 AS x FROM domain_events WHERE aggregate_id = '$($leave.id)' AND event_type = 'leave.approved' AND status = 'dispatched'" } | Out-Null
  Assert $true "event leave.approved dispatched (Phase 10 substitutions consumer hook point)"
  WaitFor "faculty.1 notified" { (Call $f1 GET "/notifications?page_size=20").data | Where-Object { $_.event_type -eq 'leave.approved' } } | Out-Null
  Assert $true "faculty.1 notified (leave.approved)"

  Write-Host "== 6. overlap / document / cancel"
  Call $f1 POST "/leaves" @{ leave_type_id = $cl; from_date = $from; to_date = $from; reason = "verify overlap" } 409 | Out-Null
  $ml = ($types | Where-Object { $_.code -eq 'ML' }).id
  Call $f1 POST "/leaves" @{ leave_type_id = $ml; from_date = '2026-12-14'; to_date = '2026-12-18'; reason = "verify ML" } 422 | Out-Null
  $c = (Call $f1 POST "/leaves/$($leave.id)/cancel").data
  $restored = (Call $f1 GET "/leaves/me/balance").data | Where-Object { $_.code -eq 'CL' }
  Assert ($c.status -eq 'cancelled' -and [double]$restored.used -eq [double]$before.used) "cancel before start → cancelled, balance restored"

  Write-Host "== 7. encashment"
  $el = ($types | Where-Object { $_.code -eq 'EL' }).id
  $r = Invoke-WebRequest -Method Post -Uri "$script:BaseUrl/leaves/encash" -Headers @{ Authorization = "Bearer $f1" } -ContentType 'application/json' -Body (@{ leave_type_id = $el; days = 1 } | ConvertTo-Json) -SkipHttpErrorCheck
  Assert ($r.StatusCode -eq 403 -and ($r.Content | ConvertFrom-Json).error.code -eq 'FEATURE_DISABLED') "encashment off → 403 FEATURE_DISABLED"
  SetFlag 'hr.leave_encashment' $true
  $enc = WaitFor "encashment on" { $x = Invoke-WebRequest -Method Post -Uri "$script:BaseUrl/leaves/encash" -Headers @{ Authorization = "Bearer $f1" } -ContentType 'application/json' -Body (@{ leave_type_id = $el; days = 1 } | ConvertTo-Json) -SkipHttpErrorCheck; if ($x.StatusCode -eq 201) { ($x.Content | ConvertFrom-Json).data } } 90
  Assert ($enc.workflow_instance_id -and $enc.amount_paise -gt 0) "encashment → workflow hr.leave_encashment ($($enc.amount_paise) paise)"

  Write-Host "== 8. staff attendance"
  SetFlag 'attendance.geo_app' $true
  WaitFor "geo on" { (Status $f1 POST "/staff-attendance/self-checkin" @{ geo = @{ lat = 13.5; lng = 77.5946 } }) -eq 422 } 90 | Out-Null
  Assert $true "self check-in outside the 200 m fence → 422"
  $in = (Call $f1 POST "/staff-attendance/self-checkin" @{ geo = @{ lat = 12.9717; lng = 77.5947 } } 201).data
  Assert ($in.status -eq 'present' -and $in.source -eq 'geo') "inside the fence → 201 present (geo)"
  $abs = (Call $hr POST "/staff-attendance/mark" @{ staff_id = $s2; date = '2026-10-01'; status = 'absent' }).data
  Assert ($abs.status -eq 'absent') "hr marks faculty.2 absent on 2026-10-01"
  Call $acct POST "/staff-attendance/mark" @{ staff_id = $s2; date = '2026-10-01'; status = 'absent' } 403 | Out-Null
  SetFlag 'attendance.biometric' $true
  $dev = WaitFor "biometric on" { $x = Invoke-WebRequest -Method Post -Uri "$script:BaseUrl/attendance-devices" -Headers @{ Authorization = "Bearer $hr" } -ContentType 'application/json' -Body (@{ name = "Gate $run"; device_type = 'biometric' } | ConvertTo-Json) -SkipHttpErrorCheck; if ($x.StatusCode -eq 201) { ($x.Content | ConvertFrom-Json).data } } 90
  $punch = (Call $null POST "/attendance-devices/$($dev.id)/punches" @{ device_token = $dev.token; punches = @(
        @{ employee_code = 'E1006'; at = '2026-10-03T09:01:00+05:30'; direction = 'in' },
        @{ employee_code = 'E1006'; at = '2026-10-03T13:10:00+05:30' },
        @{ employee_code = 'E1006'; at = '2026-10-03T17:05:00+05:30'; direction = 'out' },
        @{ employee_code = "ZZ$run"; at = '2026-10-03T09:00:00+05:30' }) }).data
  Assert ($punch.days_updated -eq 1 -and ($punch.unknown_codes -contains "ZZ$run")) "punches paired into one day, unknown code reported"
  $prow = Sql "SELECT source, to_char(check_in_time AT TIME ZONE 'Asia/Kolkata', 'HH24:MI') AS i, to_char(check_out_time AT TIME ZONE 'Asia/Kolkata', 'HH24:MI') AS o FROM staff_attendance WHERE staff_id = '$s2' AND attendance_date = '2026-10-03'"
  Assert ($prow[0].source -eq 'biometric' -and $prow[0].i -eq '09:01' -and $prow[0].o -eq '17:05') "check-in 09:01 / check-out 17:05"
  Call $null POST "/attendance-devices/$($dev.id)/punches" @{ device_token = 'x' * 20; punches = @(@{ employee_code = 'E1006'; at = '2026-10-03T09:01:00+05:30' }) } 401 | Out-Null
  $sa1 = Call $acct GET "/staff-attendance?scope=all&month=2026-10&page_size=200"
  Assert ($sa1.meta.visibility.scopes -contains 'all' -and ($sa1.data | Where-Object { $_.staff_id -eq $s2 })) "accountant scope=all sees every member"
  $accStaff = (Call $acct GET "/staff/me").data.id
  $sa2 = Call $acct GET "/staff-attendance?scope=self&month=2026-10&page_size=200"
  Assert (-not ($sa2.data | Where-Object { $_.staff_id -ne $accStaff })) "accountant scope=self → own rows only"

  Write-Host "== 9. payroll"
  $job = (Call $acct POST "/payroll/generate" @{ month = 10; year = 2026 } 202).data
  $j = Job $acct $job.job_id
  Assert ($j.status -eq 'succeeded' -and $j.result.generated -ge 25) "generate Oct 2026 → $($j.result.generated) runs"
  $runs = (Call $acct GET "/payroll?month=10&year=2026&page_size=200").data
  $p1 = (Call $acct GET "/payroll/$(($runs | Where-Object { $_.staff_id -eq $s1 }).id)").data
  $labels = $p1.items | ForEach-Object { $_.label }
  Assert (($labels -contains 'Basic Pay') -and ($labels -contains 'Dearness Allowance') -and ($labels -contains 'House Rent Allowance')) "faculty.1: Basic / DA / HRA"
  Assert ((($p1.items | Where-Object { $_.label -like 'Provident Fund (employee)*' }).amount_paise) -eq 180000) "PF 12 % of the capped ₹15,000 wage = ₹1,800"
  Assert ((($p1.items | Where-Object { $_.label -eq 'Professional Tax' }).amount_paise) -eq 20000) "PT (KA slab) ₹200"
  Assert ((($p1.items | Where-Object { $_.source_type -eq 'loan' }).amount_paise) -eq 250000) "festival-advance EMI ₹2,500"
  $p2 = (Call $acct GET "/payroll/$(($runs | Where-Object { $_.staff_id -eq $s2 }).id)").data
  Assert ([double]$p2.lop_days -eq 1 -and ($p2.items | Where-Object { $_.source_type -eq 'lop' -and $_.amount_paise -gt 0 })) "faculty.2: 1 LOP day deducted"
  $job2 = (Call $acct POST "/payroll/generate" @{ month = 10; year = 2026 } 202).data
  $j2 = Job $acct $job2.job_id
  $dups = Sql "SELECT staff_id, COUNT(*) AS n FROM staff_payrolls WHERE month = 10 AND year = 2026 AND institution_id = '$instId' GROUP BY staff_id HAVING COUNT(*) > 1"
  Assert ($j2.result.recomputed -ge 25 -and $j2.result.generated -eq 0 -and $dups.Count -eq 0) "regenerate → drafts recomputed, no duplicates"
  $ap = (Call $acct POST "/payroll/$($p1.id)/approve").data
  Assert ($ap.status -eq 'approved') "approve → approved"
  $paid = (Call $acct POST "/payroll/$($p1.id)/mark-paid" @{ payment_ref = "NEFT$run" }).data
  Assert ($paid.status -eq 'paid') "mark paid"
  WaitFor "payslip stored" { (Call $acct GET "/payroll/$($p1.id)").data.payslip_url } 120 | Out-Null
  Assert $true "payslip PDF job stored the payslip"
  $pdf = Invoke-WebRequest -Uri "$script:BaseUrl/payroll/$($p1.id)/payslip.pdf" -Headers @{ Authorization = "Bearer $f1" }
  Assert ([System.Text.Encoding]::ASCII.GetString($pdf.RawContentStream.ToArray()[0..4]) -eq '%PDF-') "faculty.1 downloads the payslip PDF"
  $myPay = (Call $f1 GET "/payroll/me?year=2026").data
  Assert ($myPay.Count -ge 1 -and -not ($myPay | Where-Object { $_.staff_id -ne $s1 })) "/payroll/me → own payslips only"
  Call $student GET "/payroll/me" $null 403 | Out-Null
  foreach ($k in 'pf', 'esi', 'pt', 'tds') {
    $reg = (Call $acct GET "/payroll/registers/$($k)?month=10&year=2026").data
    Assert ($reg.rows.Count -ge 1) "register $k → $($reg.rows.Count) rows"
  }
  $f16 = (Call $acct GET "/payroll/form16?year=2026&staff_id=$s1").data
  Assert ($f16.financial_year -eq '2026-27' -and $f16.months.Count -eq 12 -and $f16.gross_salary_paise -gt 0) "Form 16 data for faculty.1 (FY 2026-27)"

  Write-Host "== 10. increment + arrears"
  $inc = (Call $acct POST "/staff/$s1/salary-structures" @{ effective_from = '2026-10-01'; basic_paise = 6100000; pay_level = 'VERIFY' } 201).data
  Assert ($inc.basic_paise -eq 6100000) "increment effective 1 Oct (basic ₹61,000)"
  $sb = (Call $hr GET "/staff/$s1/service-book").data
  Assert (($sb | Where-Object { $_.entry_type -eq 'increment' -and $_.effective_date -eq '2026-10-01' })) "service-book increment entry"
  $job3 = (Call $acct POST "/payroll/generate" @{ month = 11; year = 2026; staff_ids = @($s1) } 202).data
  Job $acct $job3.job_id | Out-Null
  $nov = (Call $acct GET "/payroll?month=11&year=2026&staff_id=$s1").data[0]
  $novD = (Call $acct GET "/payroll/$($nov.id)").data
  $arr = $novD.items | Where-Object { $_.source_type -eq 'arrears' }
  Assert ($arr.label -eq 'Arrears 10/2026' -and $arr.amount_paise -gt 0) "November run carries Arrears 10/2026 ($($arr.amount_paise) paise)"

  Write-Host "== 11. recruitment"
  SetFlag 'hr.recruitment' $true; SetFlag 'hr.reservation_roster' $true
  $bad = @{ title = "Assistant Professor (CSE) $run"; department_id = $cse; cadre = 'assistant'; vacancies = 4; reservation = @{ roster = '100_point'; vacancies = @{ GEN = 4 } } }
  WaitFor "recruitment on" { (Status $hr POST "/recruitment/postings" $bad) -eq 422 } 90 | Out-Null
  Assert $true "posting without the OBC-NCL roster entitlement → 422"
  $bad.reservation.vacancies = @{ GEN = 3; XYZ = 1 }
  Call $hr POST "/recruitment/postings" $bad 422 | Out-Null
  $bad.reservation.vacancies = @{ GEN = 3; 'OBC-NCL' = 1 }
  $post = (Call $hr POST "/recruitment/postings" $bad 201).data
  Call $hr POST "/recruitment/postings/$($post.id)/publish" | Out-Null
  $pub = Invoke-RestMethod -Uri "$script:BaseUrl/public/careers?institution=demo-uni"
  Assert (($pub.data | Where-Object { $_.id -eq $post.id })) "published posting on the public careers page"
  $appR = Call $null POST "/public/careers/$($post.id)/apply" @{ applicant = @{ name = "Candidate Verify$run"; email = "cand$run@example.org"; phone = "+919811$run"; experience_months = 36; publications = 4 }; category = 'GEN' } 201
  Assert ($appR.data.reference -like 'JA-*') "public application → $($appR.data.reference)"
  Call $null POST "/public/careers/$($post.id)/apply" @{ applicant = @{ name = "Candidate Verify$run"; email = "cand$run@example.org"; phone = "+919811$run" } } 409 | Out-Null
  $application = ((Call $hr GET "/recruitment/postings/$($post.id)/applications").data)[0]
  Call $hr POST "/recruitment/applications/$($application.id)/screen" @{ screening_score = 75 } | Out-Null
  $sl = (Call $hr POST "/recruitment/applications/$($application.id)/shortlist" @{ min_screening_score = 50 }).data
  Assert ($sl.status -eq 'shortlisted') "rule shortlist (score ≥ 50)"
  $hodUser = (Call $hod GET "/auth/me").data.user.id
  $panel = (Call $hr POST "/recruitment/postings/$($post.id)/panels" @{ scheduled_at = (Get-Date).AddDays(3).ToString('o'); venue = 'Board room'; members = @(@{ user_id = $hodUser; role = 'chair'; weight = 2 }) } 201).data
  $score = (Call $hod POST "/recruitment/panels/$($panel.id)/scores" @{ application_id = $application.id; scores = @{ subject = 80; teaching = 70 } }).data
  Assert ([double]$score.total -eq 75) "panel member hod.cse scores → weighted total 75"
  Call $hr POST "/recruitment/applications/$($application.id)/select" | Out-Null
  Call $hr POST "/recruitment/applications/$($application.id)/offer" @{ basic_paise = 5770000; designation_id = $asst } | Out-Null
  $joined = (Call $hr POST "/recruitment/applications/$($application.id)/join" @{ joining_date = (Get-Date).ToString('yyyy-MM-dd') }).data
  $js = (Call $hr GET "/staff/$($joined.staff_id)").data
  Assert ($joined.status -eq 'joined' -and $js.department_code -eq 'CSE' -and $js.designation_name -eq 'Assistant Professor') "join → staff $($js.employee_id) created and linked"
  Call $hr POST "/recruitment/postings/$($post.id)/close" | Out-Null

  Write-Host "== 12. PBAS appraisal + CAS"
  SetFlag 'hr.appraisal_pbas' $true; SetFlag 'hr.cas_promotions' $true
  $apr = WaitFor "pbas on" { $x = Invoke-WebRequest -Method Post -Uri "$script:BaseUrl/appraisals" -Headers @{ Authorization = "Bearer $f1" } -ContentType 'application/json' -Body (@{ self_assessment = @{ teaching = @{ lectures_engaged_pct = 90; student_feedback = 4 } } } | ConvertTo-Json -Depth 5) -SkipHttpErrorCheck; if ($x.StatusCode -eq 201) { ($x.Content | ConvertFrom-Json).data } } 90
  Assert ([double]$apr.self_score -eq 61 -and $apr.auto_filled.publications -ge 0) "self-appraisal saved (score 61, research auto-filled)"
  $sub = (Call $f1 POST "/appraisals/$($apr.id)/submit").data
  Assert ($sub.status -eq 'submitted' -and $sub.workflow_instance_id) "submitted → workflow hr.appraisal"
  Call $f2 POST "/appraisals/$($apr.id)/review" @{ decision = 'approve' } 404 | Out-Null
  $rev = (Call $hod POST "/appraisals/$($apr.id)/review" @{ decision = 'approve'; reviewer_score = 70 }).data
  Assert ($rev.status -eq 'reviewed' -and [double]$rev.reviewer_score -eq 70) "hod.cse reviews (70)"
  $fin = (Call $hr POST "/appraisals/$($apr.id)/review" @{ decision = 'approve' }).data
  Assert ($fin.status -eq 'approved' -and [double]$fin.final_score -eq 70) "hr approves → final score 70"
  $cas = (Call $f1 POST "/cas-applications" @{} 201).data
  Assert ($cas.from_cadre -eq 'assistant' -and $cas.to_cadre -eq 'associate' -and $cas.eligibility_date -eq '2021-07-02' -and $cas.eligible_now) "CAS eligibility = joining 2018-07-02 + 3 years"
  Call $f1 POST "/cas-applications" @{} 409 | Out-Null
  Call $f1 POST "/cas-applications/$($cas.id)/submit" | Out-Null
  $dec = (Call $hr POST "/cas-applications/$($cas.id)/decide" @{ decision = 'approve'; new_basic_paise = 13140000 }).data
  Assert ($dec.status -eq 'approved') "CAS approved"
  $promoted = (Call $hr GET "/staff/$s1").data
  $sb2 = (Call $hr GET "/staff/$s1/service-book").data
  $st = (Call $acct GET "/staff/$s1/salary-structures").data
  Assert ($promoted.designation_name -eq 'Associate Professor' -and ($sb2 | Where-Object { $_.entry_type -eq 'promotion' }) -and $st[0].basic_paise -eq 13140000) "designation, salary structure and promotion entry"

  Write-Host "== 13. workload + allocation"
  $wl = (Call $f1 GET "/faculty/$s1/workload").data
  Assert ([double]$wl.theory_hours -eq 0 -and [double]$wl.norm_hours -eq 16 -and $wl.load_status -eq 'under') "faculty.1: 0 teaching h vs associate norm 16 → under"
  $grid = (Call $hod GET "/workload?department_id=$cse").data
  Assert ($grid.Count -ge 5) "hod.cse department grid ($($grid.Count) teaching staff)"
  Call $f1 GET "/workload?department_id=$cse" $null 403 | Out-Null
  $course = (Call $hod GET "/courses?department_id=$cse&page_size=1").data[0]
  $prop = (Call $hod POST "/departments/$cse/course-allocation" @{ proposals = @(@{ course_id = $course.id; staff_id = $s1; hours = 4 }) }).data
  $subm = (Call $hod POST "/course-allocation/$($prop.id)/submit").data
  Assert ($subm.status -eq 'submitted') "proposal submitted to the dean"
  Call $hod POST "/course-allocation/$($prop.id)/approve" @{} 403 | Out-Null
  $appr = (Call $dean POST "/course-allocation/$($prop.id)/approve" @{}).data
  Assert ($appr.status -eq 'dean_approved' -and $appr.note -like '*Phase 09*') "dean.eng approves (apply deferred note)"
  $x = Invoke-WebRequest -Method Post -Uri "$script:BaseUrl/course-allocation/$($prop.id)/apply" -Headers @{ Authorization = "Bearer $hod" } -SkipHttpErrorCheck
  Assert ($x.StatusCode -eq 409 -and ($x.Content | ConvertFrom-Json).error.details.reason -eq 'offerings_missing') "apply → 409 until Phase 09 offerings exist"

  Write-Host "== 14. auditor"
  foreach ($p in '/staff', '/leaves?scope=all', '/payroll', '/staff-attendance?scope=all') { Call $auditor GET $p | Out-Null }
  Call $auditor POST "/leaves" @{ leave_type_id = $cl; from_date = $from; to_date = $from; reason = 'audit' } 403 | Out-Null

  Call $admin DELETE "/holidays/$($hol.id)" | Out-Null
  Summary "06_hr"
}
finally {
  if ($sa) { foreach ($flag in $flags) { try { SetFlag $flag $false } catch { Write-Host "flag $flag not restored: $_" } } }
  Pop-Location
}
