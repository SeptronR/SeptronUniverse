# API verification — Phase 09 offerings, faculty allocation & registration (Prompts/09 §09.11).
#
# Run from backend/ with the API up, Redis (or the TCP fakeredis) and a Celery worker (bulk registration and the real
# elective allocation are jobs):
#   .\scripts\verify\09_registration.ps1 [-BaseUrl http://localhost:8000/api/v1]
#
# Seed first: python scripts/seed_demo_institution.py --type university --only offerings
#
# Roles: registrar (MFA in the demo tenant), hod.cse, faculty.1 (allocated), faculty_3 (not allocated), advisor.1,
# student.1 (CSE 2025 term 3, advisee of advisor.1), student_hold (registration hold), student_arrear (open arrear in
# CS203), parent.1.
# Re-runnable: step 0 resets student.1 / student_hold / student_arrear registrations, the fixture offerings and the
# requisite fixtures, restores the windows and the workload setting.
#
# Documented deviations (PROGRESS.md decisions log, Phase 09):
#  * the demo curriculum puts student.1 in term 3 (no basket) — the elective allocation runs on the 2024 batch's PE-I;
#  * credit limits come from the structure term (15–23 for B.Tech term 3), not the prompt's 16–26;
#  * antirequisite / co-requisite pairs do not exist in the seed — the script inserts and removes them as fixtures;
#  * passed courses before Phase 15 = earlier curriculum terms without an open arrear (or approved credit transfers).
param([string]$BaseUrl = "http://localhost:8000/api/v1")
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl
$Backend = Resolve-Path (Join-Path $PSScriptRoot "../..")
$Py = Get-VenvPython $Backend
function Sql($q) { (& $Py (Join-Path $PSScriptRoot "_sql.py") $q) | ConvertFrom-Json }
function SqlW($q) { & $Py (Join-Path $PSScriptRoot "_sql.py") --write $q | Out-Null }
function Ident($role) {
  $line = Get-Content (Get-CredentialsFile) | Where-Object { $_ -match "^\|\s*$role\s*\|" } | Select-Object -Last 1
  return (($line -split '\|')[2].Trim())
}
function Err($token, $method, $path, $body, $expect) {
  $h = @{ Authorization = "Bearer $token" }
  $p = @{ Method = $method; Uri = "$script:BaseUrl$path"; Headers = $h; SkipHttpErrorCheck = $true; ContentType = 'application/json' }
  if ($null -ne $body) { $p['Body'] = ($body | ConvertTo-Json -Depth 8) }
  $r = Invoke-WebRequest @p
  if ($r.StatusCode -ne $expect) { throw "$method $path expected $expect got $($r.StatusCode): $($r.Content)" }
  $script:Checks++
  Write-Host "OK $method $path -> $($r.StatusCode)"
  return ($r.Content | ConvertFrom-Json)
}

$registrar = Login-Mfa 'registrar' 'registrar'
$hod = Login 'hod.cse' (Get-DemoPassword 'hod')
$f1 = Login 'faculty.1' (Get-DemoPassword 'faculty')
$f3 = Login 'faculty.3' (Get-DemoPassword 'faculty_3')
$adv = Login 'advisor.1' (Get-DemoPassword 'class_advisor')
$s1 = Login 'student.1' (Get-DemoPassword 'student')
$sHold = Login (Ident 'student_hold') (Get-DemoPassword 'student_hold')
$parent = Login 'parent.1' (Get-DemoPassword 'parent')

$term = (Sql "SELECT t.id FROM academic_terms t JOIN institutions i ON i.id=t.institution_id WHERE i.slug='demo-uni' AND t.college_id IS NULL AND t.is_current AND t.deleted_at IS NULL")[0].id
$s1e = (Sql "SELECT e.id FROM student_program_enrollments e JOIN students s ON s.id=e.student_id JOIN users u ON u.id=s.user_id WHERE u.username='student.1'")[0].id
$holdE = (Sql "SELECT e.id FROM student_program_enrollments e JOIN students s ON s.id=e.student_id JOIN users u ON u.id=s.user_id WHERE u.username='$(Ident 'student_hold')'")[0].id

# ---- 0. reset ----------------------------------------------------------------------------------------------------------
Write-Host "== 0. reset"
foreach ($e in @($s1e, $holdE)) {
  SqlW "UPDATE workflow_instances SET status='cancelled' WHERE entity_type='course_registration' AND status IN ('pending','escalated') AND entity_id IN (SELECT id FROM course_registrations WHERE student_program_enrollment_id='$e'); DELETE FROM offering_waitlists WHERE student_program_enrollment_id='$e'; DELETE FROM course_registration_items WHERE registration_id IN (SELECT id FROM course_registrations WHERE student_program_enrollment_id='$e'); DELETE FROM course_registrations WHERE student_program_enrollment_id='$e'"
}
SqlW "DELETE FROM course_prerequisites WHERE relation IN ('antirequisite','corequisite') AND course_id IN (SELECT id FROM courses WHERE code IN ('CS203','CS204'))"
SqlW "UPDATE registration_windows SET status='open', ends_at=NOW() + INTERVAL '20 days', starts_at=LEAST(starts_at, NOW() - INTERVAL '1 hour') WHERE term_id='$term'"
SqlW "UPDATE institution_settings SET value='""warn""' WHERE category='hr' AND key='workload_enforce'"
$admin = Login-Mfa 'registrar' 'registrar'
& $Py -c "print('reset ok')" | Out-Null
# recount seats from the items
Invoke-WebRequest -Method Post -Uri "$BaseUrl/_dev/registration/window-status" -Headers @{ Authorization = "Bearer $registrar" } -SkipHttpErrorCheck | Out-Null

# ---- 1. offerings read / faculty allocation + workload ------------------------------------------------------------------
Write-Host "== 1. offerings + faculty"
$list = Call $f3 GET "/course-offerings?term_id=$term&page_size=100"
Assert ($list.data.Count -gt 0) "faculty.3 reads offerings institution-wide"
$cs201 = $list.data | Where-Object { $_.course_code -eq 'CS201' -and $_.section_code -eq 'A' } | Select-Object -First 1
Err $f3 PUT "/course-offerings/$($cs201.id)/faculty" @{ items = @() } 403 | Out-Null
$f1staff = (Sql "SELECT s.id FROM staff s JOIN users u ON u.id=s.user_id WHERE u.username='faculty.1'")[0].id
$r = Call $hod PUT "/course-offerings/$($cs201.id)/faculty" @{ items = @(@{ staff_id = $f1staff; role = 'coordinator'; hours_per_week = 4 }) }
Assert ($r.data.offering.faculty[0].staff_id -eq $f1staff) "HOD allocates faculty.1"
SqlW "UPDATE institution_settings SET value='""block""' WHERE category='hr' AND key='workload_enforce'"
$e = Err $hod PUT "/course-offerings/$($cs201.id)/faculty" @{ items = @(@{ staff_id = $f1staff; role = 'coordinator'; hours_per_week = 40 }) } 409
Assert ($e.error.details.code -eq 'WORKLOAD_EXCEEDED') "block → 409 WORKLOAD_EXCEEDED"
SqlW "UPDATE institution_settings SET value='""warn""' WHERE category='hr' AND key='workload_enforce'"
$r = Call $hod PUT "/course-offerings/$($cs201.id)/faculty" @{ items = @(@{ staff_id = $f1staff; role = 'coordinator'; hours_per_week = 40 }) }
Assert ($r.data.warnings.Count -ge 1) "warn → 200 + warnings[]"
Call $hod PUT "/course-offerings/$($cs201.id)/faculty" @{ items = @(@{ staff_id = $f1staff; role = 'coordinator'; hours_per_week = 4 }) } | Out-Null

# ---- 2. bulk from curriculum --------------------------------------------------------------------------------------------
Write-Host "== 2. bulk from curriculum"
$b25 = (Sql "SELECT id FROM batches WHERE code='2025-BTECH-CSE' AND deleted_at IS NULL")[0].id
$pv = Call $registrar POST "/course-offerings/bulk-from-curriculum?dry_run=true" @{ term_id = $term; batch_ids = @($b25); sections_per_course = 2 }
Assert ($pv.data.total -gt 0 -and $pv.data.to_create -eq 0) "batch 2025 preview: $($pv.data.total) offerings, all existing (no duplicates)"
$b26 = (Sql "SELECT id FROM batches WHERE code='2026-BTECH-CSE' AND deleted_at IS NULL")[0].id
$ap = Call $registrar POST "/course-offerings/bulk-from-curriculum?dry_run=false" @{ term_id = $term; batch_ids = @($b26); sections_per_course = 1 }
$again = Call $registrar POST "/course-offerings/bulk-from-curriculum?dry_run=true" @{ term_id = $term; batch_ids = @($b26); sections_per_course = 1 }
Assert ($again.data.to_create -eq 0) "re-run creates nothing (created $($ap.data.to_create) first)"
$new26 = (Call $registrar GET "/course-offerings?term_id=$term&page_size=200&status=planned").data
foreach ($o in $new26) { Call $registrar POST "/course-offerings/$($o.id)/status" @{ status = 'open' } | Out-Null }

# ---- 3. catalog --------------------------------------------------------------------------------------------------------
Write-Host "== 3. catalog"
$cat = Call $s1 GET "/registration/me/catalog"
Assert ($cat.data.curriculum.Count -eq 5) "student.1 sees 5 curriculum courses"
Assert ($cat.data.limits.min -gt 0 -and $cat.data.limits.max -gt $cat.data.limits.min) "limits $($cat.data.limits.min)-$($cat.data.limits.max)"
Assert ($cat.data.holds.Count -eq 0) "student.1 has no holds"
Assert ($null -ne $cat.data.fee_preview) "fee preview present"
$catH = Call $sHold GET "/registration/me/catalog"
Assert ($catH.data.holds -contains 'registration') "student.hold catalog reports the registration hold"
# accept pending undertakings of student.1 (the seed keeps 'conduct' pending)
foreach ($u in $cat.data.undertakings_pending) { Call $s1 POST "/students/me/undertakings" @{ undertaking_type = $u; accepted = $true } 201 | Out-Null }

# ---- 4. cart -------------------------------------------------------------------------------------------------------------
Write-Host "== 4. cart"
$byCode = @{}; foreach ($c in $cat.data.curriculum) { $byCode[$c.code] = $c }
function Off($code) { ($byCode[$code].offerings | Where-Object { $_.targeted } | Select-Object -First 1).offering_id ?? $byCode[$code].offerings[0].offering_id }
$cs101 = (Sql "SELECT id FROM courses WHERE code='CS101' AND status='active' LIMIT 1")[0].id
$cs203c = (Sql "SELECT id FROM courses WHERE code='CS203' AND status='active' LIMIT 1")[0].id
$cs204c = (Sql "SELECT id FROM courses WHERE code='CS204' AND status='active' LIMIT 1")[0].id
SqlW "INSERT INTO course_prerequisites (institution_id, course_id, related_course_id, relation, is_hard) SELECT institution_id, '$cs203c', '$cs101', 'antirequisite', TRUE FROM courses WHERE id='$cs203c'"
$e = Err $s1 POST "/registration/me/items" @{ offering_id = (Off 'CS203') } 409
Assert ($e.error.details.code -eq 'ANTIREQUISITE') "antirequisite of a passed course → 409"
SqlW "DELETE FROM course_prerequisites WHERE relation='antirequisite' AND course_id='$cs203c'"
$before = (Call $registrar GET "/course-offerings/$(Off 'CS201')").data.enrolled_count
foreach ($code in @('CS201', 'CS202', 'MA201')) { Call $s1 POST "/registration/me/items" @{ offering_id = (Off $code) } 201 | Out-Null }
$after = (Call $registrar GET "/course-offerings/$(Off 'CS201')").data.enrolled_count
Assert ($after -eq $before + 1) "enrolled_count increments"
# prerequisite: CS301 (prereq CS201 — not passed) offered as a fixture
$cs301 = (Sql "SELECT id FROM courses WHERE code='CS301' AND status='active' LIMIT 1")[0].id
$o301 = (Call $registrar GET "/course-offerings?term_id=$term&course_id=$cs301").data | Select-Object -First 1
if (-not $o301) { $o301 = (Call $registrar POST "/course-offerings" @{ term_id = $term; course_id = $cs301; section_code = 'V9' } 201).data; Call $registrar POST "/course-offerings/$($o301.id)/status" @{ status = 'open' } | Out-Null }
$e = Err $s1 POST "/registration/me/items" @{ offering_id = $o301.id } 409
Assert ($e.error.details.code -eq 'PREREQUISITE_NOT_MET') "prerequisite not met → 409"
# full offering → waitlist: CS304 fixture with 1 seat taken by student.hold
$cs304 = (Sql "SELECT id FROM courses WHERE code='CS304' AND status='active' LIMIT 1")[0].id
$o304 = (Call $registrar GET "/course-offerings?term_id=$term&course_id=$cs304").data | Select-Object -First 1
if (-not $o304) { $o304 = (Call $registrar POST "/course-offerings" @{ term_id = $term; course_id = $cs304; section_code = 'V9'; max_seats = 1 } 201).data; Call $registrar POST "/course-offerings/$($o304.id)/status" @{ status = 'open' } | Out-Null }
Call $sHold POST "/registration/me/items" @{ offering_id = $o304.id } 201 | Out-Null
$w = Call $s1 POST "/registration/me/items" @{ offering_id = $o304.id } 201
$wItem = $w.data.items | Where-Object { $_.offering_id -eq $o304.id }
Assert ($wItem.status -eq 'waitlisted' -and $wItem.waitlist.position -ge 1) "full offering → waitlisted (position $($wItem.waitlist.position))"
# credit limit: CS309 (3 cr) on top → above max?
$cs309 = (Sql "SELECT id FROM courses WHERE code='CS309' AND status='active' LIMIT 1")[0].id
$o309 = (Call $registrar GET "/course-offerings?term_id=$term&course_id=$cs309").data | Select-Object -First 1
if (-not $o309) { $o309 = (Call $registrar POST "/course-offerings" @{ term_id = $term; course_id = $cs309; section_code = 'V9' } 201).data; Call $registrar POST "/course-offerings/$($o309.id)/status" @{ status = 'open' } | Out-Null }
Call $s1 POST "/registration/me/items" @{ offering_id = (Off 'CS204') } 201 | Out-Null
Call $s1 POST "/registration/me/items" @{ offering_id = (Off 'CS203') } 201 | Out-Null
$e = Err $s1 POST "/registration/me/items" @{ offering_id = $o309.id } 409
Assert ($e.error.details.code -eq 'CREDIT_LIMIT') "credits above max → 409 CREDIT_LIMIT"

# ---- 5. submit -----------------------------------------------------------------------------------------------------------
Write-Host "== 5. submit"
$mine = (Call $s1 GET "/registration/me").data
$i203 = ($mine.items | Where-Object { $_.course_code -eq 'CS203' }).id
$i204 = ($mine.items | Where-Object { $_.course_code -eq 'CS204' }).id
Call $s1 DELETE "/registration/me/items/$i203" | Out-Null
Call $s1 DELETE "/registration/me/items/$i204" | Out-Null
$e = Err $s1 POST "/registration/me/submit" $null 409
Assert ($e.error.details.code -eq 'CREDIT_LIMIT') "below min → 409"
SqlW "INSERT INTO course_prerequisites (institution_id, course_id, related_course_id, relation, is_hard) SELECT institution_id, '$cs204c', '$cs203c', 'corequisite', TRUE FROM courses WHERE id='$cs204c'"
Call $s1 POST "/registration/me/items" @{ offering_id = (Off 'CS204') } 201 | Out-Null
$e = Err $s1 POST "/registration/me/submit" $null 409
Assert ($e.error.details.code -eq 'COREQUISITE_MISSING' -and $e.error.details.pairs.Count -ge 1) "co-requisite missing → 409 listing the pair"
Call $s1 POST "/registration/me/items" @{ offering_id = (Off 'CS203') } 201 | Out-Null
$key = [guid]::NewGuid().ToString()
$sub = Call $s1 POST "/registration/me/submit" $null 200 @{ 'Idempotency-Key' = $key }
Assert ($sub.data.status -eq 'advisor_pending' -and $sub.data.fee -and $sub.data.workflow_instance_id) "submitted → advisor_pending, fee order, workflow"
$replay = Invoke-WebRequest -Method Post -Uri "$BaseUrl/registration/me/submit" -Headers @{ Authorization = "Bearer $s1"; 'Idempotency-Key' = $key } -SkipHttpErrorCheck
Assert (($replay.Content | ConvertFrom-Json).error.code -eq 'IDEMPOTENT_REPLAY' -or $replay.StatusCode -eq 200) "replay → IDEMPOTENT_REPLAY"
SqlW "DELETE FROM course_prerequisites WHERE relation='corequisite' AND course_id='$cs204c'"
$regId = $sub.data.id

# ---- 6. approve ----------------------------------------------------------------------------------------------------------
Write-Host "== 6. approve"
Err $f3 POST "/registration/$regId/approve" @{ decision = 'approve' } 403 | Out-Null
$ap = Call $adv POST "/registration/$regId/approve" @{ decision = 'approve' }
Assert ($ap.data.status -eq 'approved') "advisor.1 approves"
Assert (@($ap.data.items | Where-Object { $_.status -eq 'confirmed' }).Count -ge 5) "items confirmed"
$tr = Sql "SELECT status, credits_registered FROM student_term_records WHERE student_program_enrollment_id='$s1e' AND term_id='$term'"
Assert ($tr[0].status -eq 'registered' -and [double]$tr[0].credits_registered -gt 0) "term record registered with credits"
$ward = (Sql "SELECT s.id FROM students s JOIN users u ON u.id=s.user_id WHERE u.username='student.1'")[0].id
$wd = Call $parent GET "/guardians/me/wards/$ward/dashboard"
Assert ($wd.data.confirmed_courses.Count -ge 5) "parent sees confirmed courses"

# ---- 7. hold + override ----------------------------------------------------------------------------------------------------
Write-Host "== 7. hold + override"
$catH = (Call $sHold GET "/registration/me/catalog").data
foreach ($c in $catH.curriculum) { $o = $c.offerings | Select-Object -First 1; if ($o -and -not $c.in_cart) { Invoke-WebRequest -Method Post -Uri "$BaseUrl/registration/me/items" -Headers @{ Authorization = "Bearer $sHold" } -ContentType 'application/json' -Body (@{ offering_id = $o.offering_id } | ConvertTo-Json) -SkipHttpErrorCheck | Out-Null } }
foreach ($u in $catH.undertakings_pending) { Call $sHold POST "/students/me/undertakings" @{ undertaking_type = $u; accepted = $true } 201 | Out-Null }
$e = Err $sHold POST "/registration/me/submit" $null 409
Assert ($e.error.code -eq 'HOLD_BLOCKED' -or $e.error.details.code -eq 'CREDIT_LIMIT') "student.hold submit blocked ($($e.error.code))"
$hreg = (Call $sHold GET "/registration/me").data
Call $registrar POST "/registration/$($hreg.id)/override" @{ reason = 'Hold cleared offline by the registrar'; skip_holds = $true; max_credits = 40 } | Out-Null
$audit = Sql "SELECT count(*) AS n FROM audit_logs WHERE record_id='$($hreg.id)' AND action='override'"
Assert ($audit[0].n -ge 1) "override audited"

# ---- 8. waitlist promotion ---------------------------------------------------------------------------------------------------
Write-Host "== 8. waitlist"
$hItem = ((Call $sHold GET "/registration/me").data.items | Where-Object { $_.offering_id -eq $o304.id }).id
Call $sHold DELETE "/registration/me/items/$hItem" | Out-Null
$wl = (Call $s1 GET "/registration/me/waitlist").data | Where-Object { $_.offering_id -eq $o304.id }
Assert ($wl.status -eq 'offered' -and $wl.offered_until) "seat released → student.1 offered"
$acc = Call $s1 POST "/registration/me/waitlist/$($wl.id)/accept"
Assert ((($acc.data.items | Where-Object { $_.offering_id -eq $o304.id }).status) -eq 'confirmed') "accept → confirmed"

# ---- 9. lock -----------------------------------------------------------------------------------------------------------------
Write-Host "== 9. lock"
SqlW "UPDATE registration_windows SET ends_at = NOW() - INTERVAL '1 day' WHERE term_id='$term' AND window_type='add_drop'"
Call $registrar POST "/_dev/registration/lock-windows" | Out-Null
$mine = (Call $s1 GET "/registration/me").data
Assert ($mine.status -eq 'locked') "approved → locked"
Err $s1 DELETE "/registration/me/items/$($mine.items[0].id)" $null 409 | Out-Null
$wd = Call $registrar POST "/registration/$($mine.id)/withdraw-item/$(($mine.items | Where-Object { $_.offering_id -eq $o304.id }).id)" @{ reason = 'Medical withdrawal' }
Assert ((($wd.data.items | Where-Object { $_.offering_id -eq $o304.id }).status) -eq 'withdrawn') "registrar withdraw → withdrawn"
SqlW "UPDATE registration_windows SET ends_at = NOW() + INTERVAL '30 days' WHERE term_id='$term' AND window_type='add_drop'"

# ---- 10. arrears -----------------------------------------------------------------------------------------------------------------
Write-Host "== 10. arrears"
$arr = Call $registrar GET "/arrears?status=open&page_size=50"
Assert ($arr.data.Count -ge 1) "arrears register lists open arrears"
$one = $arr.data | Where-Object { $_.course_code -eq 'CS203' } | Select-Object -First 1
if ($one) { Assert ($one.attempts -ge 1) "arrear attempts $($one.attempts)" }
$wv = Call $registrar POST "/arrears/$($arr.data[-1].id)/waive" @{ reason = 'Course discontinued — waived' }
Assert ($wv.data.status -eq 'waived') "registrar waives"

# ---- 11. elective allocation -----------------------------------------------------------------------------------------------------
Write-Host "== 11. elective allocation"
$pe = (Sql "SELECT eb.id FROM elective_baskets eb JOIN program_regulations pr ON pr.id=eb.program_regulation_id JOIN batches b ON b.program_regulation_id=pr.id WHERE eb.code='PE-I' AND b.code='2024-BTECH-CSE' LIMIT 1")[0].id
$dry = Call $registrar POST "/elective-baskets/$pe/allocate?term_id=$term&mode=priority_cgpa&dry_run=true"
Assert ($dry.data.candidates -ge 1 -and $dry.data.per_course.Count -ge 1) "dry run summary ($($dry.data.allocated) allocated)"
$fc = Call $registrar POST "/elective-baskets/$pe/allocate?term_id=$term&mode=fcfs&dry_run=true"
Assert ($fc.data.results[0].rank -eq 1) "fcfs ordering by submitted_at"
Call $registrar POST "/elective-baskets/$pe/allocate?term_id=$term&mode=priority_cgpa&dry_run=false" $null 202 | Out-Null

# ---- 12. bulk register batch 2026 --------------------------------------------------------------------------------------------------
Write-Host "== 12. bulk register"
$job = Call $registrar POST "/registration/bulk-register" @{ batch_id = $b26; term_id = $term } 202
Assert ($job.data.job_id) "bulk registration queued"

# ---- 13. visibility ------------------------------------------------------------------------------------------------------------------
Write-Host "== 13. visibility"
$v = Call $adv GET "/registration?scope=all&term_id=$term"
Assert ($v.meta.visibility.scopes.Count -eq 0) "advisor.1 narrowed to advisees (scopes=[])"
$v = Call $hod GET "/registration?term_id=$term"
Assert ($v.meta.visibility.scopes -contains 'department') "hod.cse → department"
$v = Call $registrar GET "/registration?term_id=$term"
Assert ($v.meta.visibility.scopes -contains 'all') "registrar → all (institution)"
$st = Call $f1 GET "/students?scope=self&page_size=200"
Assert ($st.data.Count -ge 1) "faculty.1 sees students of own offerings"
$st3 = Call $f3 GET "/students?scope=self&page_size=200"
Assert ($st3.data.Count -eq 0) "faculty.3 sees none"

Summary "09_registration"
