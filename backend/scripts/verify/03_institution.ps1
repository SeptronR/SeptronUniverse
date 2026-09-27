# API verification — Phase 03 institution structure, academic sessions & settings
# (Prompts/03_Phase03_Institution_Structure_Sessions_Settings.md §03.11).
#
# Run from backend/ with the API up, Redis and a Celery worker + Beat (step 7 waits for the outbox relay):
#   .\scripts\verify\03_institution.ps1 [-BaseUrl http://localhost:8000/api/v1]
#
# Seed first (RUN_AFTER_PHASE.md §3):
#   python scripts/seed_platform.py
#   python scripts/seed_demo_institution.py --type university --only institution      (runs base first)
#
# Roles: superadmin, inst.admin, registrar, college.admin.b, student.1 (+ faculty.1 as the HOD).
# Every run creates its own verification college (code V#####) and works inside it, so the script is re-runnable:
# the demo tenant already has colleges A/B/C and the ECE department, and the Phase 03 unique keys include soft-deleted
# rows — the prompt's "code C" / "ECE under college A" become a fresh college code / ECE under the fresh college.
#
#  1. GET /institution/profile as student.1 -> 200 (institution-wide read); PUT -> 403
#  2. PUT /institution/profile as inst.admin (timezone + statutory ids) -> 200 + audit row with the old/new diff;
#     changing the timezone while a term is in progress -> 409
#  3. colleges: POST (new code) -> 201; duplicate code -> 409 CONFLICT; college.admin.b PUT college A -> 404, B -> 200;
#     meta.visibility (college tab default for the college admin)
#  4. departments: ECE under the new college; PUT /departments/{ECE}/hod {staff_id: faculty.1} -> 200 and
#     GET /users/{faculty.1}/roles shows hod @department ECE
#  5. years/terms (registrar): 2026-27 + Odd/Even; a second set-current flips the previous year; overlapping term
#     dates -> 422; planned -> in_progress -> 409; planned -> registration -> 200
#  6. GET /academic-terms/current?college_id= as student.1 -> the current term
#  7. rollover -> new year + 2 terms, current switched, academic_year.rolled_over dispatched by the outbox relay
#  8. holidays: bulk CSV with 5 rows (row 3 invalid) -> {succeeded:4, failed:[{index:3, code:VALIDATION}]};
#     GET /holidays/export.ics -> a valid iCal calendar
#  9. sequences: regno:{yyyy}:{college_code} pattern {college_code}{yy}{seq:4} on college A -> preview A<yy>0001;
#     next twice -> A<yy>0001, A<yy>0002; 50 concurrent next calls -> 50 distinct values
# 10. settings: exams.discrepancy_pct_default "abc" -> 422, 15 -> 200; GET /settings/public (no auth) -> public keys only
# 11. POST /settings/test-provider {sms} -> 202 + message_logs row with provider mock
# 12. onboarding (super admin): autonomous_college / IN / standard -> 201; 1 main college, 49 roles with grants, pack
#     grading scale + settings + sequences, plan feature flags, admin credential e-mail logged; inst.admin -> 403
# 13. suspend -> the new tenant's users get 403 (institution_suspended); activate restores
# 14. clean-up of the verification college (HOD revoke, department + college delete)
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

function Raw($token, $method, $path, $body = $null, $headers = @{}) {
  $h = @{}
  if ($token) { $h['Authorization'] = "Bearer $token" }
  foreach ($k in $headers.Keys) { $h[$k] = $headers[$k] }
  $p = @{ Method = $method; Uri = "$script:BaseUrl$path"; Headers = $h; SkipHttpErrorCheck = $true }
  if ($null -ne $body) { $p['ContentType'] = 'application/json'; $p['Body'] = ($body | ConvertTo-Json -Depth 8) }
  return Invoke-WebRequest @p
}

try {
  $run = Get-Random -Minimum 10000 -Maximum 99999
  $admin = Login 'inst.admin' (Get-DemoPassword 'institution_admin')
  $student = Login 'student.1' (Get-DemoPassword 'student')
  $collegeAdminB = Login 'college.admin.b' (Get-DemoPassword 'college_admin')
  $registrar = Login-Mfa 'registrar' 'registrar'
  $sa = Login-SuperAdmin
  $me = Call $admin GET "/auth/me"
  $instId = $me.data.user.institution_id
  Assert ($me.data.features -contains 'institution.multi_college') "demo tenant has institution.multi_college (seed --only institution)"

  Write-Host "== 1. profile readable by every member"
  $p = Call $student GET "/institution/profile"
  Assert ($p.data.slug -eq 'demo-uni') "student.1 reads the profile ($($p.data.name))"
  $denied = Call $student PUT "/institution/profile" @{ short_name = 'X' } 403
  Assert ($denied.error.code -eq 'PERMISSION_DENIED') "student.1 PUT -> 403 PERMISSION_DENIED"

  Write-Host "== 2. profile update + audit diff"
  $naac = "KAVER$run"
  $upd = Call $admin PUT "/institution/profile" @{ timezone = 'Asia/Kolkata'; statutory_ids = @{ naac_id = $naac; aishe_code = 'U-0999'; gstin = '29ABCDE1234F1Z5' }; head_name = "Dr. Verify $run" }
  Assert ($upd.data.naac_id -eq $naac -and $upd.data.timezone -eq 'Asia/Kolkata') "PUT /institution/profile -> 200 (naac_id $naac)"
  $audit = Sql "SELECT old_values, new_values FROM audit_logs WHERE module = 'institutions' AND action = 'update' AND record_id = '$instId' ORDER BY occurred_at DESC LIMIT 1"
  Assert ($audit[0].new_values.naac_id -eq $naac -and $audit[0].old_values.PSObject.Properties.Name -contains 'naac_id') "audit row carries old/new naac_id"
  $tz = Call $admin PUT "/institution/profile" @{ timezone = 'Asia/Dubai' } 409
  Assert ($tz.error.code -eq 'RULE_VIOLATION') "timezone change while a term is in progress -> 409 RULE_VIOLATION"

  Write-Host "== 3. colleges"
  $colleges = Call $admin GET "/colleges?page_size=100"
  $collegeA = ($colleges.data | Where-Object { $_.code -eq 'A' }).id
  $collegeB = ($colleges.data | Where-Object { $_.code -eq 'B' }).id
  Assert ($collegeA -and $collegeB -and $colleges.meta.visibility) "GET /colleges -> A, B + meta.visibility"
  $code = "V$run"
  $newCollege = Call $admin POST "/colleges" @{ code = $code; name = "Verification College $run"; college_type = 'constituent'; is_exam_centre = $true; exam_centre_code = "EC-$run" } 201
  $collegeV = $newCollege.data.id
  Assert ($newCollege.data.code -eq $code) "POST /colleges ($code) -> 201"
  $dup = Call $admin POST "/colleges" @{ code = $code; name = 'Duplicate' } 409
  Assert ($dup.error.code -eq 'CONFLICT') "duplicate code -> 409 CONFLICT"
  Call $collegeAdminB PUT "/colleges/$collegeA" @{ name = 'Hijacked' } 404 | Out-Null
  $okB = Call $collegeAdminB PUT "/colleges/$collegeB" @{ affiliation_number = "AFF-$run" }
  Assert ($okB.data.affiliation_number -eq "AFF-$run") "college.admin.b PUT own college B -> 200"
  $mine = Call $collegeAdminB GET "/colleges"
  Assert ($mine.meta.visibility.default -eq 'college' -and ($mine.data | ForEach-Object id) -contains $collegeB -and $mine.data.Count -eq 1) "college.admin.b sees its college first (default tab 'college')"
  $all = Call $collegeAdminB GET "/colleges?scope=all&page_size=100"
  Assert ($all.data.Count -ge 4) "college.admin.b may read every college (scope=all -> $($all.data.Count))"
  Call $collegeAdminB POST "/colleges" @{ code = "X$run"; name = 'Not allowed' } 403 | Out-Null

  Write-Host "== 4. departments + HOD"
  $ece = Call $admin POST "/departments" @{ college_id = $collegeV; code = 'ECE'; name = 'Electronics & Communication'; department_type = 'academic' } 201
  $eceId = $ece.data.id
  $users = Call $admin GET "/users?page_size=200&q=faculty.1"
  $facultyId = ($users.data | Where-Object { $_.username -eq 'faculty.1' }).id
  $hod = Call $admin PUT "/departments/$eceId/hod" @{ staff_id = $facultyId }
  Assert ($hod.data.hod_user_id -eq $facultyId) "PUT /departments/{ECE}/hod -> 200 (hod_user_id = faculty.1)"
  $roles = Call $admin GET "/users/$facultyId/roles"
  $hodRole = $roles.data | Where-Object { $_.role_slug -eq 'hod' -and $_.scope_type -eq 'department' -and $_.scope_id -eq $eceId }
  Assert ($hodRole) "GET /users/{faculty.1}/roles -> hod@department:ECE ($($hodRole.scope_label))"
  Call $admin PUT "/departments/$eceId/hod" @{ staff_id = $me.data.user.id } 200 | Out-Null  # inst.admin is staff too
  $roles = Call $admin GET "/users/$facultyId/roles"
  Assert (-not ($roles.data | Where-Object { $_.role_slug -eq 'hod' -and $_.scope_id -eq $eceId })) "re-assigning the HOD revokes the previous holder"
  Call $admin PUT "/departments/$eceId/hod" @{ staff_id = $facultyId } 200 | Out-Null
  $stu = (Call $admin GET "/users?page_size=200&q=student.1").data | Where-Object { $_.username -eq 'student.1' }
  $notStaff = Call $admin PUT "/departments/$eceId/hod" @{ staff_id = $stu.id } 422
  Assert ($notStaff.error.code -eq 'VALIDATION') "a student as HOD -> 422 (must be staff of the college)"
  $depts = Call $student GET "/departments?college_id=$collegeV"
  Assert ($depts.data.Count -eq 1 -and $depts.meta.visibility) "departments are readable by the student (institution-wide)"

  Write-Host "== 5. academic years + terms (registrar)"
  $y1 = Call $registrar POST "/academic-years" @{ name = '2026-27'; start_date = '2026-06-01'; end_date = '2027-05-31'; college_id = $collegeV; is_current = $true } 201
  $y0 = Call $registrar POST "/academic-years" @{ name = '2025-26'; start_date = '2025-06-01'; end_date = '2026-05-31'; college_id = $collegeV } 201
  $odd = Call $registrar POST "/academic-terms" @{ academic_year_id = $y1.data.id; name = 'Odd Semester'; term_type = 'odd'; sequence = 1; start_date = '2026-07-01'; end_date = '2026-11-30'; registration_start = '2026-06-10'; registration_end = '2026-07-07'; add_drop_end = '2026-07-14'; last_instruction_date = '2026-11-10' } 201
  $even = Call $registrar POST "/academic-terms" @{ academic_year_id = $y1.data.id; name = 'Even Semester'; term_type = 'even'; sequence = 2; start_date = '2027-01-04'; end_date = '2027-05-15' } 201
  Assert ($odd.data.status -eq 'planned' -and $even.data.status -eq 'planned') "Odd/Even created (planned)"
  Call $registrar POST "/academic-years/$($y0.data.id)/set-current" | Out-Null
  $years = Call $registrar GET "/academic-years?college_id=$collegeV&page_size=50"
  $cur = @($years.data | Where-Object { $_.is_current -and $_.college_id -eq $collegeV })
  Assert ($cur.Count -eq 1 -and $cur[0].id -eq $y0.data.id) "set-current 2025-26 flips 2026-27 off (one current year per college)"
  Call $registrar POST "/academic-years/$($y1.data.id)/set-current" | Out-Null
  $overlap = Call $registrar POST "/academic-terms" @{ academic_year_id = $y1.data.id; name = 'Summer'; term_type = 'summer'; sequence = 3; start_date = '2026-11-01'; end_date = '2026-12-20' } 422
  Assert ($overlap.error.code -eq 'VALIDATION') "overlapping term dates -> 422 VALIDATION"
  $window = Call $registrar POST "/academic-terms" @{ academic_year_id = $y1.data.id; name = 'Summer'; term_type = 'summer'; sequence = 3; start_date = '2027-05-20'; end_date = '2027-05-30'; registration_start = '2027-05-25'; registration_end = '2027-05-21' } 422
  Assert ($window.error.details.field -eq 'registration_end') "registration_start > registration_end -> 422"
  $skip = Call $registrar POST "/academic-terms/$($odd.data.id)/status" @{ status = 'in_progress' } 409
  Assert ($skip.error.code -eq 'RULE_VIOLATION' -and $skip.error.details.allowed_next -eq 'registration') "planned -> in_progress -> 409 (must pass through registration)"
  $reg = Call $registrar POST "/academic-terms/$($odd.data.id)/status" @{ status = 'registration' }
  Assert ($reg.data.status -eq 'registration' -and $reg.data.next_status -eq 'in_progress') "planned -> registration -> 200"
  $back = Call $registrar POST "/academic-terms/$($odd.data.id)/status" @{ status = 'planned' } 409
  Assert ($back.error.code -eq 'RULE_VIOLATION') "going back -> 409"
  Call $student POST "/academic-terms/$($odd.data.id)/status" @{ status = 'in_progress' } 403 | Out-Null
  Call $registrar POST "/academic-years/$($y0.data.id)/lock" | Out-Null
  $locked = Call $registrar PUT "/academic-years/$($y0.data.id)" @{ name = '2025-26X' } 409
  Assert ($locked.error.code -eq 'RECORD_LOCKED') "a locked year refuses edits -> 409 RECORD_LOCKED"

  Write-Host "== 6. current term"
  Call $registrar POST "/academic-terms/$($odd.data.id)/set-current" | Out-Null
  $current = Call $student GET "/academic-terms/current?college_id=$collegeV"
  Assert ($current.data.id -eq $odd.data.id) "GET /academic-terms/current as student.1 -> Odd Semester of $code"
  $instCurrent = Call $student GET "/academic-terms/current"
  Assert ($instCurrent.data.college_id -eq $null) "without college_id -> the institution-wide current term ($($instCurrent.data.name))"

  Write-Host "== 7. rollover"
  $roll = Call $registrar POST "/academic-years/rollover" @{
    new_year_name = '2027-28'; start_date = '2027-06-01'; end_date = '2028-05-31'; college_id = $collegeV; promote_batches = $true
    terms = @(
      @{ name = 'Odd Semester'; term_type = 'odd'; sequence = 1; start_date = '2027-07-01'; end_date = '2027-11-30' },
      @{ name = 'Even Semester'; term_type = 'even'; sequence = 2; start_date = '2028-01-03'; end_date = '2028-05-15' }
    )
  } 201
  Assert ($roll.data.year.is_current -and $roll.data.year.terms.Count -eq 2 -and $roll.data.previous_year_id -eq $y1.data.id) "rollover -> 2027-28 current with 2 terms (previous 2026-27)"
  $cur2 = Call $student GET "/academic-terms/current?college_id=$collegeV"
  Assert ($cur2.data.id -eq $roll.data.current_term_id) "current term switched to the new Odd Semester"
  $status = $null
  for ($i = 0; $i -lt 30; $i++) {
    $ev = Sql "SELECT status FROM domain_events WHERE id = '$($roll.data.event_id)'"
    $status = $ev[0].status
    if ($status -eq 'dispatched') { break }
    Start-Sleep -Seconds 1
  }
  Assert ($status -eq 'dispatched') "academic_year.rolled_over dispatched by the outbox relay"

  Write-Host "== 8. holidays"
  $csv = @(
    "name,date,end_date,type,applies_to",
    "Verify Day $run A,2026-12-01,,institution,all",
    "Verify Day $run B,2026-12-02,2026-12-03,public,students",
    "Verify Day $run C,2026-12-04,,restricted,staff",
    "Verify Day $run D,2026-13-45,,public,all",
    "Verify Day $run E,05/12/2026,,exam_break,all"
  ) -join "`n"
  $bulk = Call $admin POST "/holidays/bulk-import" @{ csv = $csv }
  Assert ($bulk.data.succeeded -eq 4 -and $bulk.data.failed.Count -eq 1 -and $bulk.data.failed[0].index -eq 3 -and $bulk.data.failed[0].code -eq 'VALIDATION') "bulk import -> {succeeded:4, failed:[{index:3, code:VALIDATION}]}"
  $ics = Invoke-WebRequest -Uri "$script:BaseUrl/holidays/export.ics?from=2026-12-01&to=2026-12-31" -Headers @{ Authorization = "Bearer $student" } -SkipHttpErrorCheck
  $icsText = if ($ics.Content -is [byte[]]) { [Text.Encoding]::UTF8.GetString($ics.Content) } else { [string]$ics.Content }
  Assert ($ics.StatusCode -eq 200 -and $ics.Headers['Content-Type'] -match 'text/calendar' -and $icsText.StartsWith('BEGIN:VCALENDAR') -and $icsText -match 'END:VCALENDAR') "GET /holidays/export.ics -> text/calendar"
  Assert (([regex]::Matches($icsText, "SUMMARY:Verify Day $run")).Count -eq 4 -and $icsText -match 'DTSTART;VALUE=DATE:20261202') "iCal carries the 4 imported holidays as all-day events"

  Write-Host "== 9. number sequences"
  $scope = 'regno:{yyyy}:{college_code}'
  $existing = (Call $admin GET "/number-sequences?college_id=$collegeA&page_size=100").data | Where-Object { $_.scope_key -eq $scope }
  if ($existing) {
    $seq = Call $admin PUT "/number-sequences/$($existing.id)" @{ pattern = '{college_code}{yy}{seq:4}'; next_value = 1 }
  } else {
    $seq = Call $admin POST "/number-sequences" @{ scope_key = $scope; pattern = '{college_code}{yy}{seq:4}'; college_id = $collegeA; reset_policy = 'yearly' } 201
  }
  $seqId = $seq.data.id
  $yy = (Get-Date).ToString('yy')
  $preview = Call $admin POST "/number-sequences/$seqId/preview" @{ count = 2 }
  Assert ($preview.data.values[0] -eq "A$($yy)0001") "preview -> A$($yy)0001 (nothing consumed)"
  $n1 = Call $admin POST "/_dev/number-sequences/$seqId/next"
  $n2 = Call $admin POST "/_dev/number-sequences/$seqId/next"
  Assert ($n1.data.rendered -eq "A$($yy)0001" -and $n2.data.rendered -eq "A$($yy)0002") "next twice -> A$($yy)0001, A$($yy)0002"
  $bad = Call $admin POST "/number-sequences" @{ scope_key = "bad-$run"; pattern = '{foo}{seq}' } 422
  Assert ($bad.error.code -eq 'VALIDATION') "unknown pattern token -> 422"
  $url = "$script:BaseUrl/_dev/number-sequences/$seqId/next"
  $values = 1..50 | ForEach-Object -Parallel {
    (Invoke-RestMethod -Method Post -Uri $using:url -Headers @{ Authorization = "Bearer $using:admin" }).data.rendered
  } -ThrottleLimit 25
  $distinct = @($values | Sort-Object -Unique)
  Assert ($values.Count -eq 50 -and $distinct.Count -eq 50) "50 concurrent next calls -> 50 distinct values ($($distinct[0]) … $($distinct[-1]))"
  $after = (Call $admin GET "/number-sequences?college_id=$collegeA&page_size=100").data | Where-Object { $_.id -eq $seqId }
  Assert ($after.next_value -eq 53) "next_value = 53 after 52 reservations"

  Write-Host "== 10. settings"
  $badSetting = Call $admin PUT "/settings" @{ items = @(@{ category = 'exams'; key = 'discrepancy_pct_default'; value = 'abc' }) } 422
  Assert ($badSetting.error.code -eq 'VALIDATION' -and $badSetting.error.details.errors[0].field -eq 'exams.discrepancy_pct_default') "exams.discrepancy_pct_default = 'abc' -> 422"
  $goodSetting = Call $admin PUT "/settings" @{ items = @(@{ category = 'exams'; key = 'discrepancy_pct_default'; value = 15 }, @{ category = 'general'; key = 'theme'; value = 'ocean' }) }
  $exams = Call $admin GET "/settings?category=exams"
  Assert ((($exams.data[0].items | Where-Object { $_.key -eq 'discrepancy_pct_default' }).value) -eq 15) "= 15 -> 200 and read back"
  Call $student GET "/settings" $null 403 | Out-Null
  $public = Invoke-RestMethod -Uri "$script:BaseUrl/settings/public?institution=demo-uni"
  $cats = $public.data.settings.PSObject.Properties.Name
  Assert ($public.data.theme -eq 'ocean' -and -not ($cats -contains 'security') -and -not ($public.data.settings.exams.PSObject.Properties.Name -contains 'discrepancy_pct_default')) "GET /settings/public (no auth) -> theme 'ocean', only is_public keys"
  Call $admin PUT "/settings" @{ items = @(@{ category = 'general'; key = 'theme'; value = 'indigo' }) } | Out-Null

  Write-Host "== 11. provider test"
  $test = Call $admin POST "/settings/test-provider" @{ channel = 'sms'; to = '+911234567890' } 202
  $log = Sql "SELECT provider, status, channel FROM message_logs WHERE id = '$($test.data.message_log_id)'"
  Assert ($test.data.provider -eq 'mock' -and $log[0].provider -eq 'mock' -and $log[0].channel -eq 'sms' -and $log[0].status -eq 'sent') "POST /settings/test-provider -> 202 + message_logs row (mock)"

  Write-Host "== 12. onboarding"
  $slug = "verify-$run"
  $onboard = @{
    institution = @{ name = "Verification Autonomous College $run"; slug = $slug; code = "VAC$run"; institution_type = 'autonomous_college' }
    admin = @{ username = "admin.$run"; email = "admin.$run@$slug.septronuniverse.in"; display_name = "Verify Admin $run" }
    plan_code = 'standard'; pack = 'IN'; seed_demo = $false
  }
  Call $admin POST "/platform/institutions" $onboard 403 | Out-Null
  $new = Call $sa POST "/platform/institutions" $onboard 201
  $newId = $new.data.institution.id
  Assert ($new.data.main_college_id -and $new.data.roles_created -eq 49) "POST /platform/institutions -> 201, main college + 49 roles (51 templates minus the 2 platform roles)"
  $tenantCounts = Sql ("SELECT (SELECT count(*) FROM colleges WHERE institution_id = '$newId' AND is_main) AS mains, " +
    "(SELECT count(*) FROM roles WHERE institution_id = '$newId') AS roles, " +
    "(SELECT count(*) FROM role_permissions rp JOIN roles r ON r.id = rp.role_id WHERE r.institution_id = '$newId') AS grants, " +
    "(SELECT count(*) FROM grading_scales WHERE institution_id = '$newId') AS scales, " +
    "(SELECT count(*) FROM institution_settings WHERE institution_id = '$newId') AS settings, " +
    "(SELECT count(*) FROM number_sequences WHERE institution_id = '$newId') AS sequences, " +
    "(SELECT count(*) FROM institution_feature_flags WHERE institution_id = '$newId' AND source = 'plan') AS flags, " +
    "(SELECT count(*) FROM message_logs WHERE institution_id = '$newId' AND event_type = 'institution.admin_credentials') AS mails")
  $c = $tenantCounts[0]
  Assert ($c.mains -eq 1 -and $c.roles -eq 49 -and $c.grants -gt 1000) "1 main college, 49 roles, $($c.grants) grants"
  Assert ($c.scales -eq 1 -and $c.settings -ge 25 -and $c.sequences -eq 7) "pack defaults: grading scale, $($c.settings) settings, 7 number sequences"
  Assert ($c.flags -gt 100 -and $new.data.features_enabled -gt 50) "plan feature flags applied ($($c.flags) rows, $($new.data.features_enabled) effective)"
  Assert ($c.mails -eq 1 -and $new.data.admin_temp_password.Length -ge 12) "admin credential e-mail logged"
  Assert ($new.data.defaults.frameworks -contains 'NAAC_2024') "IN pack frameworks available (platform rows)"
  $list = Call $sa GET "/platform/institutions?q=$slug"
  Assert ($list.data[0].plan_code -eq 'standard' -and $list.data[0].college_count -eq 1) "GET /platform/institutions lists the new tenant (plan standard)"

  Write-Host "== 13. suspend / activate"
  $before = Raw $null POST "/auth/login" @{ identifier = "admin.$run"; password = $new.data.admin_temp_password; institution_slug = $slug }
  Assert ($before.StatusCode -in 200, 403 -and -not ($before.Content -match 'institution_suspended')) "new admin can sign in before the suspension ($($before.StatusCode))"
  Call $sa POST "/platform/institutions/$newId/suspend" @{ reason = 'verify 03' } | Out-Null
  $blocked = Raw $null POST "/auth/login" @{ identifier = "admin.$run"; password = $new.data.admin_temp_password; institution_slug = $slug }
  $bj = $blocked.Content | ConvertFrom-Json
  Assert ($blocked.StatusCode -eq 403 -and $bj.error.details.reason -eq 'institution_suspended') "suspended -> login 403 (institution_suspended)"
  Call $sa POST "/platform/institutions/$newId/activate" | Out-Null
  $again = Raw $null POST "/auth/login" @{ identifier = "admin.$run"; password = $new.data.admin_temp_password; institution_slug = $slug }
  Assert ($again.StatusCode -eq $before.StatusCode) "activate -> login behaves as before ($($again.StatusCode))"

  Write-Host "== 14. clean-up"
  $hodNow = (Call $admin GET "/users/$facultyId/roles").data | Where-Object { $_.role_slug -eq 'hod' -and $_.scope_id -eq $eceId }
  Call $admin DELETE "/users/$facultyId/roles/$($hodNow.id)" | Out-Null
  Call $admin DELETE "/departments/$eceId" | Out-Null
  Call $admin DELETE "/colleges/$collegeV" | Out-Null
  Assert $true "verification college $code, its ECE department and the HOD assignment removed"

  Summary "PHASE 03 institution structure, sessions, settings"
}
finally {
  Pop-Location
}
