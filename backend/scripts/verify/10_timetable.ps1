# API verification — Phase 10 timetable & rooms (Prompts/10 §10.11).
#
# Run from backend/ with the API up and Redis (or the TCP fakeredis):
#   .\scripts\verify\10_timetable.ps1 [-BaseUrl http://localhost:8000/api/v1]
#
# Seed first: python scripts/seed_demo_institution.py --type university --only timetable
#
# Roles: registrar (MFA in the demo tenant), hod.cse, faculty.1, faculty.2, faculty.3 (not allocated), student.1,
# estate (estate_officer), parent.1.
# Re-runnable: step 0 removes the fixture rooms (VR*), the CSE department-scope timetables and their sessions, the
# fixture holidays / leaves / extra sessions and resets the workload setting.
#
# Documented deviations (PROGRESS.md decisions log, Phase 10):
#  * the conflict scenarios run on a CSE *department-scope* draft on Saturdays (the seed fills Monday–Friday), with
#    faculty.1's 2025 CSE section-A offerings (CS201 / CS202 / MA201) — a section draft would hide faculty.1's own
#    published entries (the version being replaced is ignored by design);
#  * the "other section" room clash compares two entries of the same draft (drafts of other scopes are invisible to
#    each other until published — only live entries of other scopes count);
#  * steps 9 / 11 drive the leave / holiday consumers through POST /_dev/timetable/consume/{event} (no Celery worker
#    needed) after inserting the approved leave / holiday rows;
#  * step 12 checks the feature-off 403 only (the greedy placer is exercised from the UI with the flag on).
param([string]$BaseUrl = "http://localhost:8000/api/v1")
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl
$Backend = Resolve-Path (Join-Path $PSScriptRoot "../..")
$Py = Get-VenvPython $Backend
function Sql($q) { (& $Py (Join-Path $PSScriptRoot "_sql.py") $q) | ConvertFrom-Json }
function SqlW($q) { & $Py (Join-Path $PSScriptRoot "_sql.py") --write $q | Out-Null }
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
function NextDow([datetime]$from, [int]$isoDow) {
  $d = $from.Date
  while ((([int]$d.DayOfWeek + 6) % 7) + 1 -ne $isoDow) { $d = $d.AddDays(1) }
  return $d
}
function IsoWeek([datetime]$d) { [System.Globalization.ISOWeek]::GetWeekOfYear($d) }

$registrar = Login-Mfa 'registrar' 'registrar'
$hod = Login 'hod.cse' (Get-DemoPassword 'hod')
$f1 = Login 'faculty.1' (Get-DemoPassword 'faculty')
$f2 = Login 'faculty.2' (Get-DemoPassword 'faculty_2')
$s1 = Login 'student.1' (Get-DemoPassword 'student')
$estate = Login 'estate' (Get-DemoPassword 'estate_officer')
$parent = Login 'parent.1' (Get-DemoPassword 'parent')

$inst = (Sql "SELECT id FROM institutions WHERE slug='demo-uni'")[0].id
$term = (Sql "SELECT id, start_date, end_date FROM academic_terms WHERE institution_id='$inst' AND college_id IS NULL AND is_current AND deleted_at IS NULL")[0]
$cse = (Sql "SELECT id, college_id FROM departments WHERE institution_id='$inst' AND code='CSE'")[0]
$f1staff = (Sql "SELECT s.id FROM staff s JOIN users u ON u.id=s.user_id WHERE u.username='faculty.1'")[0].id
$f2staff = (Sql "SELECT s.id FROM staff s JOIN users u ON u.id=s.user_id WHERE u.username='faculty.2'")[0].id
$f3staff = (Sql "SELECT s.id FROM staff s JOIN users u ON u.id=s.user_id WHERE u.username='faculty.3'")[0].id
$secA = (Sql "SELECT s.id FROM batch_sections s JOIN batches b ON b.id=s.batch_id WHERE b.code='2025-BTECH-CSE' AND s.name='A'")[0].id
function Off($code, $sec) {
  (Sql "SELECT o.id FROM course_offerings o JOIN courses c ON c.id=o.course_id WHERE o.term_id='$($term.id)' AND c.code='$code' AND o.section_code='$sec' AND o.deleted_at IS NULL")[0].id
}
$cs201A = Off 'CS201' 'A'; $cs201B = Off 'CS201' 'B'; $cs202A = Off 'CS202' 'A'; $ma201A = Off 'MA201' 'A'
$slots = (Call $registrar GET "/time-slots?slot_group=Default&college_id=$($cse.college_id)").data
$P = @{}; foreach ($s in $slots) { $P[$s.name] = $s.id }

# ---- 0. reset ----------------------------------------------------------------------------------------------------------
Write-Host "== 0. reset"
SqlW "DELETE FROM class_sessions WHERE topic LIKE 'verify-10%' OR timetable_entry_id IN (SELECT e.id FROM timetable_entries e JOIN timetables t ON t.id=e.timetable_id WHERE t.scope_type='department' AND t.scope_id='$($cse.id)')"
SqlW "UPDATE workflow_instances SET status='cancelled' WHERE entity_type='timetable_substitution' AND status IN ('pending','escalated') AND entity_id IN (SELECT s.id FROM timetable_substitutions s JOIN timetable_entries e ON e.id=s.timetable_entry_id JOIN timetables t ON t.id=e.timetable_id WHERE t.scope_type='department' AND t.scope_id='$($cse.id)')"
SqlW "DELETE FROM timetables WHERE scope_type='department' AND scope_id='$($cse.id)'"
SqlW "DELETE FROM rooms WHERE code LIKE 'VR%' AND institution_id='$inst'"
SqlW "DELETE FROM holidays WHERE name LIKE 'Verify holiday%' AND institution_id='$inst'"
SqlW "DELETE FROM staff_leaves WHERE reason='verify-10'"
SqlW "UPDATE institution_settings SET value='""warn""' WHERE category='hr' AND key='workload_enforce'"
SqlW "UPDATE course_offering_faculty SET hours_per_week=GREATEST(hours_per_week, 12) WHERE staff_id='$f1staff'"

# ---- 1. rooms ------------------------------------------------------------------------------------------------------------
Write-Host "== 1. rooms"
$r1 = (Call $estate POST "/rooms" @{ college_id = $cse.college_id; code = 'VR1'; name = 'Verify room 1'; room_type = 'classroom'; capacity = 70; exam_capacity = 35 } 201).data
$r2 = (Call $estate POST "/rooms" @{ college_id = $cse.college_id; code = 'VR2'; name = 'Verify room 2'; room_type = 'classroom'; capacity = 70 } 201).data
$small = (Call $estate POST "/rooms" @{ college_id = $cse.college_id; code = 'VR3'; name = 'Verify small room'; room_type = 'classroom'; capacity = 10 } 201).data
Err $estate POST "/rooms" @{ college_id = $cse.college_id; code = 'VR9'; name = 'Bad'; capacity = 40; exam_capacity = 50 } 422 | Out-Null
Err $estate POST "/rooms" @{ college_id = $cse.college_id; code = 'VR1'; name = 'Dup'; capacity = 40 } 409 | Out-Null
Err $f1 POST "/rooms" @{ college_id = $cse.college_id; code = 'VR8'; name = 'Nope'; capacity = 40 } 403 | Out-Null
$avail = Call $f1 GET "/rooms/availability?date=$((Get-Date).ToString('yyyy-MM-dd'))&slot_id=$($P['P1'])"
Assert ($avail.data.Count -gt 0) "availability finder answers ($($avail.data.Count) rooms)"

# ---- 2. slot groups ------------------------------------------------------------------------------------------------------
Write-Host "== 2. slot groups"
Err $registrar PUT "/time-slots" @{ college_id = $cse.college_id; slot_group = 'VerifyOverlap'; slots = @(
  @{ name = 'A'; start_time = '09:00'; end_time = '10:00' }, @{ name = 'B'; start_time = '09:30'; end_time = '10:30' }) } 422 | Out-Null
Err $estate PUT "/time-slots" @{ college_id = $cse.college_id; slot_group = 'Verify'; slots = @(@{ name = 'A'; start_time = '09:00'; end_time = '10:00' }) } 200 | Out-Null

# ---- 3. drafts + conflicts -----------------------------------------------------------------------------------------------
Write-Host "== 3. conflicts"
$tt = (Call $hod POST "/timetables" @{ term_id = $term.id; scope_type = 'department'; scope_id = $cse.id; name = 'Verify Saturday' } 201).data
Assert ($tt.status -eq 'draft') "HOD creates a CSE department draft"
$e1 = (Call $hod POST "/timetables/$($tt.id)/entries" @{ offering_id = $cs201A; section_id = $secA; day_of_week = 6; time_slot_id = $P['P2']; room_id = $r1.id; staff_id = $f1staff } 201).data
Assert ($e1.entry.room_code -eq 'VR1') "entry CS201-A / faculty.1 / VR1 / Sat P2"
$b201 = (Sql "SELECT staff_id FROM course_offering_faculty WHERE offering_id='$cs201B' LIMIT 1")
$cand = @{ offering_id = $cs201B; day_of_week = 6; time_slot_id = $P['P2']; room_id = $r1.id }
if ($b201) { $cand['staff_id'] = $b201[0].staff_id }
$rep = (Call $hod POST "/timetables/$($tt.id)/check-conflicts" $cand).data
Assert ($rep.room.Count -ge 1) "same room / day / slot → room conflict"
$e = Err $hod POST "/timetables/$($tt.id)/entries" $cand 409
Assert ($e.error.code -eq 'CONFLICT') "forcing the insert → 409 CONFLICT"
$rep = (Call $hod POST "/timetables/$($tt.id)/check-conflicts" @{ offering_id = $cs202A; day_of_week = 6; time_slot_id = $P['P2']; room_id = $r2.id; staff_id = $f1staff }).data
Assert ($rep.staff.Count -ge 1) "same faculty, other room → staff conflict"
$rep = (Call $hod POST "/timetables/$($tt.id)/check-conflicts" @{ offering_id = $cs202A; day_of_week = 6; time_slot_id = $P['P1']; room_id = $r2.id; staff_id = $f1staff }).data
Assert ($rep.staff.Count -eq 0) "P1 alone does not clash with the P2 entry"
$rep = (Call $hod POST "/timetables/$($tt.id)/check-conflicts" @{ offering_id = $cs202A; day_of_week = 6; time_slot_id = $P['P1']; room_id = $r2.id; staff_id = $f1staff; slot_span = 2 }).data
Assert ($rep.staff.Count -ge 1) "slot_span=2 from P1 occupies P2 → conflict detected"
$odd = (Call $hod POST "/timetables/$($tt.id)/entries" @{ offering_id = $cs202A; day_of_week = 6; time_slot_id = $P['P5']; room_id = $r2.id; staff_id = $f1staff; week_pattern = 'odd' } 201).data
$even = (Call $hod POST "/timetables/$($tt.id)/entries" @{ offering_id = $ma201A; day_of_week = 6; time_slot_id = $P['P5']; room_id = $r2.id; staff_id = $f1staff; week_pattern = 'even' } 201).data
Assert ($odd.warnings.staff.Count -eq 0 -and $even.warnings.room.Count -eq 0) "odd vs even in the same slot → no conflict"

# ---- 4. faculty / capacity / workload ------------------------------------------------------------------------------------
Write-Host "== 4. faculty + capacity"
$e = Err $hod POST "/timetables/$($tt.id)/entries" @{ offering_id = $cs201A; day_of_week = 6; time_slot_id = $P['P6']; room_id = $r1.id; staff_id = $f3staff } 422
Assert ($e.error.details.reason -eq 'staff_not_allocated') "staff not in course_offering_faculty → 422"
$cap = (Call $hod POST "/timetables/$($tt.id)/entries" @{ offering_id = $ma201A; section_id = $secA; day_of_week = 6; time_slot_id = $P['P7']; room_id = $small.id; staff_id = $f1staff } 201).data
Assert ($cap.warnings.capacity.Count -ge 1) "room of 10 < class size → warnings.capacity"

# ---- 5. publish + sessions --------------------------------------------------------------------------------------------------
Write-Host "== 5. publish"
$today = Get-Date -Format 'yyyy-MM-dd'
$sat = NextDow (Get-Date).AddDays(1) 6
$holiday = $sat.AddDays(7)
SqlW "INSERT INTO holidays (institution_id, college_id, name, holiday_date, applies_to) VALUES ('$inst', NULL, 'Verify holiday Saturday', '$($holiday.ToString('yyyy-MM-dd'))', 'all')"
$pub = (Call $hod POST "/timetables/$($tt.id)/publish" @{ effective_from = $today; regenerate_sessions = $true }).data
Assert ($pub.timetable.status -eq 'published') "published"
$end = [datetime]$term.end_date
$hol = @((Sql "SELECT holiday_date AS d FROM holidays WHERE institution_id='$inst' AND is_active AND deleted_at IS NULL AND applies_to IN ('all','students') AND (college_id IS NULL OR college_id='$($cse.college_id)')") | ForEach-Object { ([datetime]$_.d).ToString('yyyy-MM-dd') })
$expected = 0
for ($d = NextDow (Get-Date) 6; $d -le $end; $d = $d.AddDays(7)) {
  if ($hol -contains $d.ToString('yyyy-MM-dd')) { continue }
  $wk = IsoWeek $d
  $expected += 2  # e1 + capacity entry (week 'all')
  if ($wk % 2 -eq 1) { $expected++ } else { $expected++ }  # odd entry on odd weeks, even entry on even weeks
}
Assert ($pub.sessions_created -eq $expected) "sessions = entries × matching Saturdays − holidays ($($pub.sessions_created) = $expected)"
$onHol = (Sql "SELECT COUNT(*) AS n FROM class_sessions WHERE timetable_entry_id IN (SELECT id FROM timetable_entries WHERE timetable_id='$($tt.id)') AND session_date='$($holiday.ToString('yyyy-MM-dd'))'")[0].n
Assert ($onHol -eq 0) "no session on the holiday Saturday"
$oddDates = Sql "SELECT session_date AS d FROM class_sessions WHERE timetable_entry_id='$($odd.entry.id)'"
Assert (@($oddDates | Where-Object { (IsoWeek ([datetime]$_.d)) % 2 -eq 0 }).Count -eq 0 -and @($oddDates).Count -gt 0) "odd-week entry → sessions on odd ISO weeks only"
$firstS = (Sql "SELECT id FROM class_sessions WHERE timetable_entry_id='$($e1.entry.id)' ORDER BY session_date LIMIT 1")[0].id
Call $registrar POST "/_dev/class-sessions/$firstS/attendance?status=finalized" | Out-Null
$v2 = (Call $hod POST "/timetables/$($tt.id)/clone" $null 201).data
Assert ($v2.version -eq ($pub.timetable.version + 1)) "clone → version $($v2.version)"
$v2e1 = $v2.entries | Where-Object { $_.offering_id -eq $cs201A -and $_.day_of_week -eq 6 -and $_.slot_name -eq 'P2' } | Select-Object -First 1
Call $hod PUT "/timetables/$($v2.id)/entries/$($v2e1.id)" @{ room_id = $small.id } | Out-Null
$pub2 = (Call $hod POST "/timetables/$($v2.id)/publish" @{ effective_from = $today }).data
Assert ($pub2.archived_version_id -eq $tt.id -and $pub2.sessions_removed -gt 0) "republish archives v1 and replaces its future sessions ($($pub2.sessions_removed) removed)"
$kept = (Sql "SELECT COUNT(*) AS n FROM class_sessions WHERE id='$firstS'")[0].n
Assert ($kept -eq 1) "the finalized session of v1 is preserved"
Err $hod POST "/timetables/$($tt.id)/entries" @{ offering_id = $cs201A; day_of_week = 6; time_slot_id = $P['P8'] } 409 | Out-Null

# ---- 6. views ------------------------------------------------------------------------------------------------------------------
Write-Host "== 6. views"
$me = (Call $f1 GET "/timetables/me").data
$mine = @($me.days | ForEach-Object { $_.slots } | ForEach-Object { $_.entries })
Assert ($mine.Count -gt 0 -and @($mine | Where-Object { $_.staff_id -ne $f1staff }).Count -eq 0) "faculty.1 /me → own entries only ($($mine.Count))"
$sme = (Call $s1 GET "/timetables/me").data
Assert ($null -ne $sme.days) "student.1 /me → section week"
$ward = (Sql "SELECT g.student_id FROM student_guardians g JOIN users u ON u.id=g.user_id WHERE u.username='parent.1' LIMIT 1")[0].student_id
Call $parent GET "/timetables/me?ward_id=$ward" | Out-Null
$cr = (Sql "SELECT id FROM rooms WHERE code='CR101' AND institution_id='$inst'")[0].id
$rv = (Call $f1 GET "/timetables/view?scope=room&id=$cr").data
Assert (@($rv.days | ForEach-Object { $_.slots } | ForEach-Object { $_.entries }).Count -gt 0) "room view lists entries"
Err $s1 GET "/timetables/view?scope=room&id=$cr" $null 403 | Out-Null
Call $f1 GET "/class-sessions/today" | Out-Null

# ---- 7. iCal ---------------------------------------------------------------------------------------------------------------------
Write-Host "== 7. iCal"
$tok = (Call $f1 POST "/timetables/ical/token").data
$ics = Invoke-WebRequest -Uri "$BaseUrl/timetables/ical/$($tok.token).ics" -SkipHttpErrorCheck
Assert ($ics.StatusCode -eq 200) "feed answers without auth"
$events = ([regex]::Matches($ics.Content, 'BEGIN:VEVENT')).Count
$to = (Get-Date).AddDays(30).ToString('yyyy-MM-dd')
$list = (Call $f1 GET "/class-sessions?scope=self&date_from=$today&date_to=$to&page_size=200").data
$live = @($list | Where-Object { $_.status -in @('scheduled', 'conducted') }).Count
Assert ($events -eq $live) "VEVENTs = next 30 days of sessions ($events = $live)"
Call $f1 DELETE "/timetables/ical/token" | Out-Null
$ics = Invoke-WebRequest -Uri "$BaseUrl/timetables/ical/$($tok.token).ics" -SkipHttpErrorCheck
Assert ($ics.StatusCode -eq 404) "revoked token → 404"

# ---- 8. substitution --------------------------------------------------------------------------------------------------------------
Write-Host "== 8. substitution"
$target = (Sql "SELECT id, timetable_entry_id, session_date FROM class_sessions WHERE staff_id='$f1staff' AND status='scheduled' AND attendance_status='not_taken' AND session_date > CURRENT_DATE AND timetable_entry_id IN (SELECT id FROM timetable_entries WHERE timetable_id='$($v2.id)') ORDER BY session_date, start_time LIMIT 2")
$sub = (Call $hod POST "/substitutions" @{ entry_id = $target[0].timetable_entry_id; on_date = $target[0].session_date; substitute_staff_id = $f2staff; reason = 'verify' } 201).data
$ok = (Call $hod POST "/substitutions/$($sub.id)/approve" @{}).data
Assert ($ok.status -eq 'approved') "HOD approves"
$staffNow = (Sql "SELECT staff_id FROM class_sessions WHERE id='$($target[0].id)'")[0].staff_id
Assert ($staffNow -eq $f2staff) "session staff_id swapped to faculty.2"
$ev = (Sql "SELECT COUNT(*) AS n FROM domain_events WHERE event_type='substitution.approved' AND payload->>'substitution_id'='$($sub.id)'")[0].n
Assert ($ev -eq 1) "substitution.approved emitted (both members notified)"
$sub2 = (Call $f1 POST "/substitutions" @{ entry_id = $target[1].timetable_entry_id; on_date = $target[1].session_date; reason = 'verify' } 201).data
$t2 = (Sql "SELECT start_time, end_time FROM class_sessions WHERE id='$($target[1].id)'")[0]
Call $registrar POST "/class-sessions/extra" @{ offering_id = $cs201B; date = $target[1].session_date; start = $t2.start_time; end = $t2.end_time; staff_id = $f2staff; topic = 'verify-10 clash' } 201 | Out-Null
Err $hod POST "/substitutions/$($sub2.id)/approve" @{ substitute_staff_id = $f2staff } 409 | Out-Null

# ---- 9. auto from leave -----------------------------------------------------------------------------------------------------------------
Write-Host "== 9. leave → substitutions"
$two = (Sql "SELECT session_date FROM class_sessions WHERE staff_id='$f1staff' AND status='scheduled' AND session_date > CURRENT_DATE + 7 AND timetable_entry_id IS NOT NULL ORDER BY session_date LIMIT 1")[0].session_date
$from = ([datetime]$two).ToString('yyyy-MM-dd')
$expectedAuto = (Sql "SELECT COUNT(*) AS n FROM class_sessions c WHERE c.staff_id='$f1staff' AND c.status='scheduled' AND c.timetable_entry_id IS NOT NULL AND c.session_date='$from' AND NOT EXISTS (SELECT 1 FROM timetable_substitutions s WHERE s.timetable_entry_id=c.timetable_entry_id AND s.on_date=c.session_date AND s.status IN ('requested','approved'))")[0].n
$lt = (Sql "SELECT id FROM leave_types WHERE institution_id='$inst' LIMIT 1")[0].id
$leave = [guid]::NewGuid().ToString()
SqlW "INSERT INTO staff_leaves (id, institution_id, staff_id, leave_type_id, from_date, to_date, days_count, reason, status) VALUES ('$leave', '$inst', '$f1staff', '$lt', '$from', '$from', 1, 'verify-10', 'approved')"
$out = (Call $registrar POST "/_dev/timetable/consume/leave.approved" @{ leave_id = $leave; staff_id = $f1staff; from_date = $from; to_date = $from }).data
Assert ($out.result -eq $expectedAuto -and $expectedAuto -ge 1) "leave → $expectedAuto leave_auto request(s)"
$auto = (Call $hod GET "/substitutions?source=leave_auto&status=requested&date_from=$from&date_to=$from").data
Assert (@($auto | Where-Object { $_.leave_id -eq $leave }).Count -eq $expectedAuto) "HOD queue lists them with the leave reference"
Call $registrar POST "/_dev/timetable/consume/leave.cancelled" @{ leave_id = $leave } | Out-Null
$w = (Sql "SELECT COUNT(*) AS n FROM timetable_substitutions WHERE reason LIKE '[leave' || chr(58) || '$leave]%' AND status='withdrawn'")[0].n
Assert ($w -eq $expectedAuto) "leave cancelled → substitutions withdrawn"

# ---- 10. extra sessions / locks ------------------------------------------------------------------------------------------------------------
Write-Host "== 10. sessions"
$busy = (Sql "SELECT session_date, start_time, end_time, room_id FROM class_sessions WHERE room_id IS NOT NULL AND status='scheduled' AND session_date > CURRENT_DATE LIMIT 1")[0]
Err $f1 POST "/class-sessions/extra" @{ offering_id = $cs201A; date = $busy.session_date; start = $busy.start_time; end = $busy.end_time; room_id = $busy.room_id; topic = 'verify-10 busy' } 409 | Out-Null
$sun = (NextDow (Get-Date).AddDays(1) 7).ToString('yyyy-MM-dd')
$x = (Call $f1 POST "/class-sessions/extra" @{ offering_id = $cs201A; date = $sun; start = '10:00'; end = '11:00'; room_id = $r1.id; topic = 'verify-10 remedial' } 201).data
Call $f1 POST "/_dev/class-sessions/$($x.id)/attendance?status=finalized" | Out-Null
$e = Err $f1 POST "/class-sessions/$($x.id)/cancel" @{ reason = 'verify' } 409
Assert ($e.error.code -eq 'RECORD_LOCKED') "cancel after attendance finalized → 409 RECORD_LOCKED"

# ---- 11. holiday added later ------------------------------------------------------------------------------------------------------------------
Write-Host "== 11. holiday.changed"
$later = (Sql "SELECT MIN(session_date) AS d FROM class_sessions WHERE timetable_entry_id IN (SELECT id FROM timetable_entries WHERE timetable_id='$($v2.id)') AND session_date > '$($holiday.ToString('yyyy-MM-dd'))' AND attendance_status='not_taken'")[0].d
$ld = ([datetime]$later).ToString('yyyy-MM-dd')
SqlW "INSERT INTO holidays (institution_id, college_id, name, holiday_date, applies_to) VALUES ('$inst', NULL, 'Verify holiday later', '$ld', 'students')"
Call $registrar POST "/_dev/timetable/consume/holiday.changed" @{ dates = @($ld) } | Out-Null
$n = (Sql "SELECT COUNT(*) AS n FROM class_sessions WHERE session_date='$ld' AND status='scheduled' AND attendance_status='not_taken' AND timetable_entry_id IN (SELECT id FROM timetable_entries WHERE timetable_id='$($v2.id)')")[0].n
Assert ($n -eq 0) "future sessions on the new holiday removed"

# ---- 12. auto-generate --------------------------------------------------------------------------------------------------------------------------
Write-Host "== 12. auto-generate"
$draft = (Call $registrar POST "/timetables/$($v2.id)/clone" $null 201).data
$e = Err $registrar POST "/timetables/$($draft.id)/auto-generate?dry_run=true" @{} 403
Assert ($e.error.code -eq 'FEATURE_DISABLED') "timetable.auto_generate off → 403 FEATURE_DISABLED"
Call $registrar DELETE "/timetables/$($draft.id)" | Out-Null

Summary '10'
