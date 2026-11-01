# API verification — Phase 11 attendance & eligibility (Prompts/11 §11.11).
#
# Run from backend/ with the API, the Celery worker and Redis (or the TCP fakeredis) up:
#   .\scripts\verify\11_attendance.ps1 [-BaseUrl http://localhost:8000/api/v1]
#
# Seed first: python scripts/seed_demo_institution.py --type university --only attendance
#
# Roles: faculty.1 (owns offering X), faculty.3, hod.cse, registrar (MFA in the demo tenant), exam.cell, the learner
# logins with known passwords (student.1 / student_hold A25BTECHCSE013 / student_arrear), parent.1,
# parent.noconsent, advisor.1, hr (devices), super admin (feature flags).
#
# Documented deviations (PROGRESS.md decisions log, Phase 11):
#  * "student in X" is whichever learner login sits on the roster of a faculty.1 offering (student.1 has no
#    timetabled sessions in the demo term); "student not in X" is another learner login outside that roster;
#  * the session under test is an **extra session created today** by faculty.1 (POST /class-sessions/extra) so QR /
#    geo / punches run inside a live session window; the summary / condonation steps use a fixture offering pct set
#    through marks on the seeded sessions;
#  * condonation fees are mock fee orders until Phase 12 — payment is POST /_dev/condonations/{id}/paid;
#  * the checkpoint warning runs through POST /_dev/attendance/checkpoints?checkpoint=50 (Beat body in-process);
#  * guardian alerts are asserted on the outbox (`notification.requested` events with event_type
#    attendance.absent_alert) — one per streak.
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
  if ($null -ne $body) { $p['ContentType'] = 'application/json'; $p['Body'] = ($body | ConvertTo-Json -Depth 8) }
  $r = Invoke-WebRequest @p
  return @{ Status = $r.StatusCode; Body = $(if ($r.Content) { $r.Content | ConvertFrom-Json } else { $null }) }
}
function Expect($token, $method, $path, $body, $status, $code = $null) {
  $r = Raw $token $method $path $body
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

$registrar = Login-Mfa 'registrar' 'registrar'
$hod = Login 'hod.cse' (Get-DemoPassword 'hod')
$f1 = Login 'faculty.1' (Get-DemoPassword 'faculty')
$f3 = Login 'faculty.3' (Get-DemoPassword 'faculty_3')
$exam = Login 'exam.cell' (Get-DemoPassword 'exam_cell')
$parent = Login 'parent.1' (Get-DemoPassword 'parent')
$parentNo = Login 'parent.noconsent' (Get-DemoPassword 'parent_noconsent')
$advisor = Login 'advisor.1' (Get-DemoPassword 'class_advisor')
$hr = Login 'hr' (Get-DemoPassword 'hr_officer')
$sa = Login-SuperAdmin

$inst = (Sql "SELECT id FROM institutions WHERE slug='demo-uni'")[0].id
$tenant = @{ 'X-Institution-Id' = $inst }
function SetFlag($key, $on) {
  Call $sa PUT "/institutions/$inst/features/$key" @{ enabled = $on; confirm_dependencies = $true; reason = "verify 11" } 200 $tenant | Out-Null
}
$term = (Sql "SELECT id FROM academic_terms WHERE institution_id='$inst' AND college_id IS NULL AND is_current AND deleted_at IS NULL")[0].id
$f1staff = (Sql "SELECT s.id FROM staff s JOIN users u ON u.id=s.user_id WHERE u.username='faculty.1'")[0].id
# faculty.1's own 2025 section A offerings hold at most student.hold (2025 CSE is not bulk-registered): make faculty.1 a
# co-instructor of the fullest bulk-registered 2024 offering and give one of its students the demo student password, so
# offering X has a real roster with a learner login
$full = (Sql ("SELECT o.id FROM course_offerings o JOIN course_offering_faculty f0 ON f0.offering_id = o.id JOIN staff st ON st.id = f0.staff_id " +
  "WHERE o.term_id = '$term' AND st.department_id = (SELECT department_id FROM staff WHERE id = '$f1staff') " +
  "ORDER BY (SELECT count(*) FROM course_registration_items i WHERE i.offering_id = o.id AND i.status = 'confirmed') DESC, o.id LIMIT 1"))[0].id
SqlW "INSERT INTO course_offering_faculty (institution_id, offering_id, staff_id, role, hours_per_week) SELECT institution_id, id, '$f1staff', 'instructor', 0 FROM course_offerings WHERE id = '$full' ON CONFLICT DO NOTHING"
$rosterLogin = (Sql ("SELECT u.username FROM course_registration_items i JOIN course_registrations r ON r.id = i.registration_id JOIN student_program_enrollments e ON e.id = r.student_program_enrollment_id " +
  "JOIN students s ON s.id = e.student_id JOIN users u ON u.id = s.user_id WHERE i.offering_id = '$full' AND i.status = 'confirmed' AND u.is_active ORDER BY u.username LIMIT 1"))[0].username
& $Py (Join-Path $PSScriptRoot "_reset_password.py") $rosterLogin (Get-DemoPassword 'student') | Out-Null

# learner logins with known passwords and their enrolments
$learners = @()
foreach ($pair in @(@($rosterLogin, 'student'), @('student.1', 'student'), @('A25BTECHCSE013', 'student_hold'), @('A24BTECHCSE200', 'student_arrear'))) {   # roster login first: its offering has the full roster
  $row = Sql "SELECT e.id enrol, s.id student, s.registration_number reg FROM students s JOIN student_program_enrollments e ON e.student_id=s.id LEFT JOIN users u ON u.id=s.user_id WHERE (u.username='$($pair[0])' OR s.registration_number='$($pair[0])') AND e.deleted_at IS NULL ORDER BY e.created_at DESC LIMIT 1"
  if ($row) { $learners += [pscustomobject]@{ login = $pair[0]; role = $pair[1]; enrol = $row[0].enrol; student = $row[0].student; reg = $row[0].reg } }
}
# offering X: a faculty.1 offering of the term whose confirmed roster holds one of the learners
$X = $null; $inX = $null
foreach ($l in $learners) {
  $o = Sql "SELECT i.offering_id FROM course_registration_items i JOIN course_registrations r ON r.id=i.registration_id JOIN course_offering_faculty f ON f.offering_id=i.offering_id WHERE r.student_program_enrollment_id='$($l.enrol)' AND i.status='confirmed' AND r.term_id='$term' AND f.staff_id='$f1staff' LIMIT 1"
  if ($o) { $X = $o[0].offering_id; $inX = $l; break }
}
if (-not $X) { throw "no faculty.1 offering holds a learner login - reseed offerings/timetable/attendance" }
$outX = $learners | Where-Object { $_.enrol -ne $inX.enrol -and -not (Sql "SELECT 1 x FROM course_registration_items i JOIN course_registrations r ON r.id=i.registration_id WHERE i.offering_id='$X' AND i.status='confirmed' AND r.student_program_enrollment_id='$($_.enrol)'") } | Select-Object -First 1
$sIn = Login $inX.login (Get-DemoPassword $inX.role)
$sOut = if ($outX) { Login $outX.login (Get-DemoPassword $outX.role) } else { $null }
Write-Host "offering X=$X student-in-X=$($inX.login) student-out=$($outX.login)"

# ---- 0. reset --------------------------------------------------------------------------------------------------------
Write-Host "== 0. reset"
SqlW "DELETE FROM class_sessions WHERE topic LIKE 'verify-11%'"
SqlW "DELETE FROM on_duty_requests WHERE reason='verify-11'"
SqlW "DELETE FROM attendance_condonations WHERE reason='verify-11'"
SqlW "DELETE FROM attendance_devices WHERE name LIKE 'Verify 11%'"
SqlW "UPDATE workflow_instances SET status='cancelled' WHERE entity_type IN ('on_duty_request','attendance_condonation') AND status IN ('pending','escalated') AND entity_id NOT IN (SELECT id FROM on_duty_requests UNION SELECT id FROM attendance_condonations)"
foreach ($flag in @('attendance.geo_app', 'attendance.biometric')) { SetFlag $flag $false }

# ---- 1. roster ---------------------------------------------------------------------------------------------------------
Write-Host "== 1. roster visibility"
$now = Get-Date
$start = $now.AddMinutes(-5).ToString('HH:mm'); $end = $now.AddMinutes(50).ToString('HH:mm')
$sX = (Call $f1 POST "/class-sessions/extra" @{ offering_id = $X; date = $now.ToString('yyyy-MM-dd'); start = $start; end = $end; topic = 'verify-11 live' } 201).data
$sheet = (Call $f1 GET "/class-sessions/$($sX.id)/attendance").data
$rosterIds = @($sheet.roster | ForEach-Object { $_.student_program_enrollment_id })
# soft-deleted students (later phases' fixtures) are not on a roster
$expected = (Sql "SELECT count(*) n FROM course_registration_items i JOIN course_registrations r ON r.id=i.registration_id JOIN student_program_enrollments e ON e.id=r.student_program_enrollment_id JOIN students s ON s.id=e.student_id WHERE i.offering_id='$X' AND i.status='confirmed' AND r.term_id='$term' AND s.deleted_at IS NULL")[0].n
Assert ($rosterIds.Count -eq $expected) "roster = confirmed items ($($rosterIds.Count) = $expected)"
Expect $f3 GET "/class-sessions/$($sX.id)/attendance" $null 404 | Out-Null
Call $hod GET "/class-sessions/$($sX.id)/attendance" | Out-Null

# ---- 2. bulk mark --------------------------------------------------------------------------------------------------------
Write-Host "== 2. bulk mark"
$absent = @($rosterIds | Where-Object { $_ -ne $inX.enrol } | Select-Object -First 3)
$marks = @($absent | ForEach-Object { @{ student_program_enrollment_id = $_; status = 'absent' } })
$key = [guid]::NewGuid().ToString()
$m1 = (Call $f1 POST "/class-sessions/$($sX.id)/attendance" @{ marks = $marks; mark_rest_as = 'present'; source = 'manual' } 200 @{ 'Idempotency-Key' = $key }).data
Assert ($m1.created -eq $rosterIds.Count) "all roster rows created ($($m1.created))"
$replay = Raw $f1 POST "/class-sessions/$($sX.id)/attendance" @{ marks = $marks; mark_rest_as = 'present'; source = 'manual' } @{ 'Idempotency-Key' = $key }
# platform replay contract (main.py): the stored 200 body with meta.idempotent_replay
Assert ($replay.Status -eq 200 -and $replay.Body.meta.idempotent_replay -eq $true) "same Idempotency-Key replays"
$m2 = (Call $f1 POST "/class-sessions/$($sX.id)/attendance" @{ marks = @(@{ student_program_enrollment_id = $absent[0]; status = 'present' }) }).data
Assert ($m2.updated -eq 1) "changed status counts as updated"
$stranger = if ($outX) { $outX.enrol } else { [guid]::NewGuid().ToString() }
$m3 = (Call $f1 POST "/class-sessions/$($sX.id)/attendance" @{ marks = @(@{ student_program_enrollment_id = $stranger; status = 'present' }) }).data
Assert ($m3.rejected.Count -eq 1 -and $m3.rejected[0].reason -eq 'NOT_IN_ROSTER') "student outside the roster rejected"
$future = (Sql "SELECT id FROM class_sessions WHERE offering_id='$X' AND session_date > CURRENT_DATE + 2 AND status='scheduled' ORDER BY session_date LIMIT 1")
if ($future) { Expect $f1 POST "/class-sessions/$($future[0].id)/attendance" @{ marks = @(); mark_rest_as = 'present' } 409 'FUTURE_SESSION' | Out-Null }

# ---- 4. QR (before finalizing the live session) ------------------------------------------------------------------------
Write-Host "== 4. QR"
SqlW "DELETE FROM student_class_attendance WHERE session_id='$($sX.id)' AND student_program_enrollment_id='$($inX.enrol)'"
$qr = (Call $f1 POST "/class-sessions/$($sX.id)/qr").data
$c1 = (Call $sIn POST "/attendance/qr-checkin" @{ token = $qr.token }).data
Assert ($c1.source -eq 'qr' -and $c1.status -in @('present', 'late')) "QR check-in marks present (source=qr)"
$c2 = (Call $sIn POST "/attendance/qr-checkin" @{ token = $qr.token }).data
Assert ($c2.duplicate) "second scan is a no-op"
if ($sOut) { Expect $sOut POST "/attendance/qr-checkin" @{ token = $qr.token } 409 'NOT_REGISTERED' | Out-Null }
SqlW "UPDATE class_sessions SET qr_expires_at = now() - interval '1 minute' WHERE id='$($sX.id)'"
Expect $sIn POST "/attendance/qr-checkin" @{ token = $qr.token } 401 | Out-Null

# ---- 5. geo -------------------------------------------------------------------------------------------------------------
Write-Host "== 5. geo"
Expect $sIn POST "/attendance/geo-checkin" @{ session_id = $sX.id; lat = 12.97; lng = 77.59 } 403 | Out-Null
SetFlag 'attendance.geo_app' $true
SqlW "INSERT INTO institution_settings (institution_id, category, key, value, value_type) VALUES ('$inst','attendance','geo_fence','{""lat"":12.9716,""lng"":77.5946,""radius_m"":300}','json') ON CONFLICT DO NOTHING"
SqlW "UPDATE institution_settings SET value='{""lat"":12.9716,""lng"":77.5946,""radius_m"":300}' WHERE institution_id='$inst' AND category='attendance' AND key='geo_fence' AND college_id IS NULL"
SqlW "DELETE FROM student_class_attendance WHERE session_id='$($sX.id)' AND student_program_enrollment_id='$($inX.enrol)'"
Start-Sleep -Seconds 2
Expect $sIn POST "/attendance/geo-checkin" @{ session_id = $sX.id; lat = 13.10; lng = 77.80 } 422 | Out-Null
$g = (Call $sIn POST "/attendance/geo-checkin" @{ session_id = $sX.id; lat = 12.9717; lng = 77.5947 }).data
Assert ($g.source -eq 'app') "inside the fence -> present (source=app)"
SetFlag 'attendance.geo_app' $false

# ---- 6. device punches -----------------------------------------------------------------------------------------------------
Write-Host "== 6. device punches"
SetFlag 'attendance.biometric' $true
$room = (Sql "SELECT code FROM rooms WHERE id = (SELECT room_id FROM class_sessions WHERE id='$($sX.id)')")
$dev = (Call $hr POST "/attendance-devices" @{ name = 'Verify 11 gate'; device_type = 'biometric'; applies_to = 'students'; location = $(if ($room) { $room[0].code } else { $null }) } 201).data
SqlW "DELETE FROM student_class_attendance WHERE session_id='$($sX.id)' AND student_program_enrollment_id='$($inX.enrol)'"
$at = (Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
$p = (Call $null POST "/attendance/devices/$($dev.id)/punches" @{ device_token = $dev.token; punches = @(@{ identifier = $inX.reg; at = $at }, @{ identifier = 'NO-SUCH-REG'; at = $at }) }).data
Assert ($p.marked -eq 1) "punch marked (source=biometric)"
Assert ($p.unmatched.Count -eq 1) "unknown identifier returned as unmatched"
$un = (Call $hr GET "/attendance/punches/unmatched").data
Assert (@($un | Where-Object { $_.identifier -eq 'NO-SUCH-REG' }).Count -ge 1) "unmatched listed for review"
Expect $null POST "/attendance/devices/$($dev.id)/punches" @{ device_token = ('x' * 20); punches = @(@{ identifier = $inX.reg; at = $at }) } 401 | Out-Null
SetFlag 'attendance.biometric' $false

# ---- 3. finalize + edit -------------------------------------------------------------------------------------------------------
Write-Host "== 3. finalize"
Call $f1 POST "/class-sessions/$($sX.id)/finalize" @{ note = 'verify' } | Out-Null
Expect $f1 POST "/class-sessions/$($sX.id)/attendance" @{ marks = @(); mark_rest_as = 'present' } 409 'RECORD_LOCKED' | Out-Null
Expect $f1 POST "/class-sessions/$($sX.id)/attendance/edit-finalized" @{ marks = @(@{ student_program_enrollment_id = $absent[1]; status = 'present' }); reason = 'verify correction' } 403 | Out-Null
$e = (Call $hod POST "/class-sessions/$($sX.id)/attendance/edit-finalized" @{ marks = @(@{ student_program_enrollment_id = $absent[1]; status = 'present' }); reason = 'verify correction' }).data
Assert ($e.updated -eq 1) "HOD edit after finalize"
$audit = Sql "SELECT old_values->>'status' o, new_values->>'status' n FROM audit_logs WHERE action='edit_finalized' AND new_values->>'session_id'='$($sX.id)'"
Assert ($audit.Count -ge 1 -and $audit[0].o -eq 'absent' -and $audit[0].n -eq 'present') "audit row with old/new"

# ---- 7. offline batch ---------------------------------------------------------------------------------------------------------
Write-Host "== 7. offline batch"
$open = (Sql "SELECT id FROM class_sessions WHERE offering_id='$X' AND session_date < CURRENT_DATE AND attendance_status <> 'finalized' AND status IN ('scheduled','conducted') ORDER BY session_date DESC LIMIT 1")
$batchKey = "verify-11-$([guid]::NewGuid().ToString().Substring(0, 8))"
$items = @(@{ client_id = 'c1'; session_id = $sX.id; marks = @(); mark_rest_as = 'present' })
if ($open) { $items += @{ client_id = 'c2'; session_id = $open[0].id; marks = @(); mark_rest_as = 'present' } }
$ob = (Call $f1 POST "/attendance/offline-batch" @{ idempotency_key = $batchKey; items = $items }).data
Assert (($ob.items | Where-Object { $_.client_id -eq 'c1' }).code -eq 'RECORD_LOCKED') "finalized item -> RECORD_LOCKED"
if ($open) { Assert (($ob.items | Where-Object { $_.client_id -eq 'c2' }).ok) "open item applied" }
$ob2 = (Call $f1 POST "/attendance/offline-batch" @{ idempotency_key = $batchKey; items = $items }).data
Assert ($ob2.replayed) "duplicate batch key replays"

# ---- 8. summaries ---------------------------------------------------------------------------------------------------------------
Write-Host "== 8. summaries"
$sum = (Call $f1 GET "/attendance/summary?offering_id=$X&page_size=200").data
Assert ($sum.Count -ge 1) "per-student pct for offering X"
$row = $sum | Where-Object { $_.student_program_enrollment_id -eq $inX.enrol } | Select-Object -First 1
$att = $row.present + $row.on_duty + $row.late; $cnt = $row.total_sessions - $row.exempt
$need = if ($cnt -le 0 -or ($att * 100 / $cnt) -ge $row.min_pct) { 0 } else { [math]::Ceiling(($row.min_pct * $cnt - 100 * $att) / (100 - $row.min_pct)) }
Assert ($row.sessions_needed_for_threshold -eq $need) "calculator: sessions needed = $need"
$me = (Call $sIn GET "/attendance/summary/me").data
Assert ($me.per_offering.Count -ge 1) "own summary: overall $($me.overall_pct)% across $($me.per_offering.Count) offering(s)"
$ward = (Sql "SELECT s.id FROM students s JOIN student_guardians g ON g.student_id=s.id JOIN users u ON u.id=g.user_id WHERE u.username='parent.1' LIMIT 1")
if ($ward) {
  Call $parent GET "/attendance/summary/me?ward_id=$($ward[0].id)" | Out-Null
  Expect $parentNo GET "/attendance/summary/me?ward_id=$($ward[0].id)" $null 404 | Out-Null
}

# ---- 9. alerts ---------------------------------------------------------------------------------------------------------------------
Write-Host "== 9. alerts"
$victim = $absent[2]
$alertsBefore = (Sql "SELECT count(*) n FROM domain_events WHERE event_type='attendance.absent_alert' AND payload->>'student_program_enrollment_id'='$victim'")[0].n
for ($i = 0; $i -lt 3; $i++) {
  $t = (Get-Date).AddMinutes(60 + $i * 60)
  $sx = (Call $f1 POST "/class-sessions/extra" @{ offering_id = $X; date = (Get-Date).ToString('yyyy-MM-dd'); start = $t.ToString('HH:mm'); end = $t.AddMinutes(30).ToString('HH:mm'); topic = "verify-11 streak $i" } 201).data
  Call $f1 POST "/class-sessions/$($sx.id)/attendance" @{ marks = @(@{ student_program_enrollment_id = $victim; status = 'absent' }); mark_rest_as = 'present' } | Out-Null
}
$alertsAfter = (Sql "SELECT count(*) n FROM domain_events WHERE event_type='attendance.absent_alert' AND payload->>'student_program_enrollment_id'='$victim'")[0].n
Assert (($alertsAfter - $alertsBefore) -le 1) "one absent alert per streak (+$($alertsAfter - $alertsBefore))"
$cp = (Call $registrar POST "/_dev/attendance/checkpoints?checkpoint=50").data
Assert ($cp.changed -ge 1) "checkpoint warnings sent ($($cp.changed))"

# ---- 10. on duty -------------------------------------------------------------------------------------------------------------------
Write-Host "== 10. on duty"
$from = (Get-Date).AddDays(-2).ToString('yyyy-MM-dd'); $to = (Get-Date).AddDays(-1).ToString('yyyy-MM-dd')
$od = (Call $sIn POST "/on-duty" @{ from_date = $from; to_date = $to; reason_type = 'sports'; reason = 'verify-11' } 201).data
Call $f1 POST "/on-duty/$($od.id)/recommend" @{ comment = 'ok' } | Out-Null
$oda = (Call $hod POST "/on-duty/$($od.id)/approve" @{ comment = 'approved' }).data
Assert ($oda.status -eq 'approved') "OD approved; sessions applied: $(@($oda.sessions_applied).Count)"
$odMarks = (Sql "SELECT count(*) n FROM student_class_attendance a JOIN class_sessions s ON s.id=a.session_id AND s.session_date=a.session_date WHERE a.student_program_enrollment_id='$($inX.enrol)' AND a.status='on_duty' AND s.session_date BETWEEN '$from' AND '$to'")[0].n
Assert ($odMarks -eq @($oda.sessions_applied).Count) "sessions in range marked on_duty ($odMarks)"

# ---- 11. condonation ---------------------------------------------------------------------------------------------------------------
Write-Host "== 11. condonation"
# a live student in a section advisor.1 advises (the advisor files the request; others are outside their scope → 404)
$cand = (Sql ("SELECT a.student_program_enrollment_id e, a.offering_id o, a.pct FROM attendance_summaries a JOIN course_offerings c ON c.id=a.offering_id " +
  "JOIN student_program_enrollments en ON en.id = a.student_program_enrollment_id JOIN students st ON st.id = en.student_id AND st.deleted_at IS NULL " +
  "JOIN student_term_records tr ON tr.student_program_enrollment_id = en.id AND tr.term_id = c.term_id JOIN batch_sections bs ON bs.id = tr.section_id " +
  "JOIN staff sf ON sf.id = bs.class_advisor_staff_id JOIN users au ON au.id = sf.user_id AND au.username = 'advisor.1' " +
  "WHERE c.term_id='$term' AND a.eligibility='condonable' AND NOT EXISTS (SELECT 1 FROM attendance_condonations x WHERE x.student_program_enrollment_id=a.student_program_enrollment_id AND x.offering_id=a.offering_id) LIMIT 1"))
if ($cand) {
  $cd = (Call $advisor POST "/condonations" @{ offering_id = $cand[0].o; reason_type = 'medical'; reason = 'verify-11'; student_program_enrollment_id = $cand[0].e } 201).data
  Call $hod POST "/condonations/$($cd.id)/recommend" @{ comment = 'recommended' } | Out-Null
  $ca = (Call $registrar POST "/condonations/$($cd.id)/approve" @{ comment = 'approved' }).data
  if ($ca.fee_paise -gt 0) { Call $registrar POST "/_dev/condonations/$($cd.id)/paid" | Out-Null }
  $after = (Sql "SELECT eligibility FROM attendance_summaries WHERE student_program_enrollment_id='$($cand[0].e)' AND offering_id='$($cand[0].o)'")[0].eligibility
  Assert ($after -eq 'condoned') "summary condoned after approval + payment"
}
$low = (Sql "SELECT a.student_program_enrollment_id e, a.offering_id o FROM attendance_summaries a JOIN course_offerings c ON c.id=a.offering_id WHERE c.term_id='$term' AND a.eligibility='not_eligible' LIMIT 1")
if ($low) { Expect $hod POST "/condonations" @{ offering_id = $low[0].o; reason_type = 'medical'; reason = 'verify-11'; student_program_enrollment_id = $low[0].e } 409 'BELOW_CONDONATION_FLOOR' | Out-Null }

# ---- 12. eligibility -------------------------------------------------------------------------------------------------------------------
Write-Host "== 12. eligibility"
$v0 = (Call $exam GET "/terms/$term/eligibility/versions").data
$job = (Call $exam POST "/terms/$term/eligibility/compute" @{} 202).data
$done = WaitJob $exam $job.job_id 180
Assert ($done.status -eq 'succeeded') "eligibility job succeeded"
$v1 = (Call $exam GET "/terms/$term/eligibility/versions").data
Assert (@($v1).Count -eq @($v0).Count + 1) "new version written; earlier versions retained ($(@($v1) -join ','))"
$rows = (Call $exam GET "/terms/$term/eligibility?page_size=200").data
Assert ($rows.Count -ge 1) "rows for (term record, offering)"
$detained = @($rows | Where-Object { $_.decision -eq 'detained' })
if ($detained.Count) { Assert ($detained[0].reason_codes -contains 'ATT_BELOW_MIN' -or $detained[0].reason_codes -contains 'CIA_FAIL') "detained rows carry reason codes" }
$hold = $learners | Where-Object { $_.role -eq 'student_hold' }
if ($hold) {
  $hr2 = Sql "SELECT t.reason_codes FROM term_eligibility t JOIN student_term_records r ON r.id=t.student_term_record_id WHERE r.student_program_enrollment_id='$($hold.enrol)' AND t.version=$(@($v1)[-1]) LIMIT 1"
  # only an open *exam* hold blocks eligibility (student.hold's seeded hold is a registration hold)
  $examHold = Sql "SELECT 1 AS x FROM student_holds WHERE student_program_enrollment_id='$($hold.enrol)' AND hold_type='exam' AND released_at IS NULL"
  if ($hr2) { Assert ((("$($hr2[0].reason_codes)" -match 'HOLD_EXAM') -eq [bool]$examHold)) "HOLD_EXAM only with an open exam hold ($([bool]$examHold))" }
}
$pick = $rows | Select-Object -First 1
$dec = (Call $registrar POST "/eligibility/$($pick.id)/decide" @{ decision = 'eligible'; reason = 'verify-11 override' }).data
Assert ($dec.decision -eq 'eligible' -and $dec.decided_by) "manual decision recorded"
Assert ((Sql "SELECT count(*) n FROM audit_logs WHERE action='decide' AND record_id='$($pick.id)'")[0].n -ge 1) "decision audited"
$mine = (Call $sIn GET "/eligibility/me").data
Assert (@($mine | Where-Object { $_.student_program_enrollment_id -ne $inX.enrol }).Count -eq 0) "own rows only"
$exp = (Call $exam GET "/terms/$term/detention-list?export=true" $null 202).data
$ej = WaitJob $exam $exp.job_id 120
Assert ($ej.status -eq 'succeeded') "detention list XLSX exported"

# ---- 13. visibility ---------------------------------------------------------------------------------------------------------------------
Write-Host "== 13. visibility"
$fv = Call $f1 GET "/attendance/summary?scope=all&page_size=200"
Assert (@($fv.meta.visibility.scopes).Count -eq 0) "faculty narrowed to own offerings (scopes=[])"
$hv = Call $hod GET "/attendance/summary?scope=department&page_size=5"
Assert ($hv.meta.visibility.scopes -contains 'department') "HOD department tab"
$rv = Call $registrar GET "/attendance/summary?scope=all&page_size=5"
Assert ($rv.meta.visibility.scopes -contains 'all') "registrar institution tab"

Summary '11'
