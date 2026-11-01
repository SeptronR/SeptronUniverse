# API verification — Phase 15 evaluation & results (Prompts/15 §15.11).
#
# Run from backend/ with the API, the Celery worker and Redis (or the TCP fakeredis) up:
#   .\scripts\verify\15_results.ps1 [-BaseUrl http://localhost:8000/api/v1]
#
# Seed first: python scripts/seed_demo_institution.py --type university --only results
# (the seeder leaves the last theory paper with hall attendance uncoded — "P2" below).
#
# Roles: coe (MFA), exam.cell, decoder, faculty.1, faculty.5, faculty.6, examiner.ext, hod.cse, registrar, student.1,
# parent.1, auditor.tmp, public.
#
# Documented deviations (PROGRESS.md decisions log, Phase 15):
#  * double valuation needs exams.double_valuation (professional tier): the script enables it through the dev feature
#    route when present and otherwise skips sections 5 (round 2 / third valuation) with a notice;
#  * computing a run retires the session's other unpublished runs (one open version per row);
#  * the IP allow-list check is exercised only when security.ip_allowlist_exam_ops is on and an allow-list exists;
#  * student.arrear / student.hold logins do not exist in the demo tenant — the hold case places a hold on student.1
#    through the API and releases it afterwards.
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
  if ($code -and ($r.Body.error.details.code -ne $code) -and ($r.Body.error.code -ne $code) -and ($r.Body.error.details.reason -ne $code)) { throw "$method $path expected code $code got $($r.Body.error | ConvertTo-Json -Depth 6 -Compress)" }
  $script:Checks++
  Write-Host "OK $method $path -> $status $code"
  return $r.Body
}
function WaitJob($token, $jobId, $seconds = 300) {
  for ($i = 0; $i -lt $seconds; $i++) {
    $j = (Call $token GET "/jobs/$jobId").data
    if ($j.status -in @('succeeded', 'failed', 'cancelled')) { return $j }
    Start-Sleep -Seconds 1
  }
  throw "job $jobId did not finish"
}

$coe = Login-Mfa 'controller_of_examinations' 'coe'
$exam = Login 'exam.cell' (Get-DemoPassword 'exam_cell')
$dec = Login-Mfa 'exam_decoder' 'decoder'
$f1 = Login 'faculty.1' (Get-DemoPassword 'faculty')
# the demo seed has no faculty.5 / faculty.6: faculty.3 and faculty.2 (CSE faculty with logins) are the 2nd / 3rd evaluators
$f5 = Login 'faculty.3'
$f6 = Login 'faculty.2'
$ext = Login 'examiner.ext' (Get-DemoPassword 'external_examiner')
$hod = Login 'hod.cse' (Get-DemoPassword 'hod')
$reg = Login-Mfa 'registrar' 'registrar'
$s1 = Login 'student.1' (Get-DemoPassword 'student')
$parent = Login 'parent.1' (Get-DemoPassword 'parent')
$auditor = Login 'auditor.tmp' (Get-DemoPassword 'auditor')
$inst = (Sql "SELECT id FROM institutions WHERE slug='demo-uni'")[0].id
$term = (Sql "SELECT id FROM academic_terms WHERE institution_id='$inst' AND college_id IS NULL AND is_current AND deleted_at IS NULL")[0].id
$S = (Sql "SELECT id FROM exam_sessions WHERE institution_id='$inst' AND exam_kind='regular' AND name LIKE '%End-semester (regular)' ORDER BY created_at LIMIT 1")[0]
# the learner: a student who sits session S (student.1 when it does; 09's reset removes student.1's registrations), given
# the demo student password; parent.1's ward check below stays on student.1
$s1row = (Sql ("SELECT u.username AS login, e.id AS enr, s.id AS sid, s.registration_number AS rno, s.dob FROM exam_registrations er " +
  "JOIN student_program_enrollments e ON e.id = er.student_program_enrollment_id JOIN students s ON s.id = e.student_id JOIN users u ON u.id = s.user_id " +
  "WHERE er.exam_session_id = '$($S.id)' AND u.is_active AND s.deleted_at IS NULL AND s.dob IS NOT NULL ORDER BY (u.username = 'student.1') DESC, u.username LIMIT 1"))[0]
if ($s1row.login -ne 'student.1') {
  & (Get-VenvPython (Resolve-Path (Join-Path $PSScriptRoot "..\.."))) (Join-Path $PSScriptRoot "_reset_password.py") $s1row.login (Get-DemoPassword 'student') | Out-Null
  $s1 = Login $s1row.login (Get-DemoPassword 'student')
}
$ward = (Sql "SELECT s.id AS sid FROM students s JOIN users u ON u.id = s.user_id WHERE u.username = 'student.1'")[0]
$staff = @{}
foreach ($u in @(@('faculty.1', 'faculty.1'), @('faculty.5', 'faculty.3'), @('faculty.6', 'faculty.2'))) { $staff[$u[0]] = (Sql "SELECT st.id FROM staff st JOIN users u ON u.id=st.user_id WHERE u.username='$($u[1])'")[0].id }

# reset: a previous run coded P2 — purge bundles made well after the seed (FK-aware: scripts, valuations, …) and the
# moderation proposals of those papers, so the seeded uncoded paper is uncoded again
$late = "exam_paper_id IN (SELECT id FROM exam_papers WHERE exam_session_id = '$($S.id)') AND created_at > (SELECT created_at + INTERVAL '6 hours' FROM exam_sessions WHERE id = '$($S.id)')"
$Py15 = Get-VenvPython (Resolve-Path (Join-Path $PSScriptRoot "..\.."))
& $Py15 (Join-Path $PSScriptRoot "_purge.py") moderation_actions "exam_paper_id IN (SELECT exam_paper_id FROM answer_script_bundles WHERE $late)" | Out-Null
& $Py15 (Join-Path $PSScriptRoot "_purge.py") answer_script_bundles $late | Out-Null

# P2 = the paper with hall attendance but no bundles (left by the seeder)
$P2 = (Sql "SELECT p.id, p.course_id, p.max_marks, p.qp_pattern FROM exam_papers p WHERE p.exam_session_id='$($S.id)' AND EXISTS (SELECT 1 FROM exam_registration_items i JOIN exam_attendance a ON a.exam_registration_item_id=i.id WHERE i.exam_paper_id=p.id AND a.status='present') AND NOT EXISTS (SELECT 1 FROM answer_script_bundles b WHERE b.exam_paper_id=p.id) LIMIT 1")[0]
Assert ($null -ne $P2) "seeded uncoded paper P2"

# ---- 2. coding -----------------------------------------------------------------------------------------------------------------
Write-Host "== 2. coding"
$bundles = (Expect $exam POST "/exam-papers/$($P2.id)/bundles" @{ size = 30 } 201).data
Assert ($bundles.Count -ge 1) "bundles created"
$B = $bundles[0]
Expect $f1 POST "/exam-papers/$($P2.id)/bundles" @{ size = 30 } 403 | Out-Null
$coded = (Call $exam POST "/bundles/$($B.id)/code").data
$nums = $coded.scripts | ForEach-Object { $_.dummy_number }
Assert (($nums | Select-Object -Unique).Count -eq $nums.Count) "dummy numbers unique"
Expect $exam POST "/bundles/$($B.id)/code" $null 409 'BUNDLE_ALREADY_CODED' | Out-Null
foreach ($b in $bundles | Select-Object -Skip 1) { Call $exam POST "/bundles/$($b.id)/code" | Out-Null }
Call $exam POST "/bundles/$($B.id)/custody" @{ action = 'dispatched'; location = 'Valuation camp' } 201 | Out-Null
Call $exam POST "/bundles/$($B.id)/custody" @{ action = 'received'; location = 'Valuation camp' } 201 | Out-Null
$log = (Call $exam GET "/bundles/$($B.id)/custody").data
Assert (($log | Where-Object action -in @('created', 'dispatched', 'received')).Count -ge 3) "custody timeline"

# ---- 3. assignment ------------------------------------------------------------------------------------------------------------
Write-Host "== 3. assignment"
$teacher = (Sql "SELECT u.username FROM course_offering_faculty f JOIN course_offerings o ON o.id=f.offering_id JOIN staff st ON st.id=f.staff_id JOIN users u ON u.id=st.user_id WHERE o.course_id='$($P2.course_id)' AND o.term_id='$term' LIMIT 1")
if ($teacher) {
  $tid = (Sql "SELECT st.id FROM staff st JOIN users u ON u.id=st.user_id WHERE u.username='$($teacher[0].username)'")[0].id
  Expect $exam POST "/exam-papers/$($P2.id)/valuation/assign" @{ bundle_ids = @($B.id); evaluator_staff_id = $tid; round = 1 } 409 'EVALUATOR_CONFLICT' | Out-Null
}
$ids = @($bundles | ForEach-Object { $_.id })
Expect $exam POST "/exam-papers/$($P2.id)/valuation/assign" @{ bundle_ids = $ids; evaluator_staff_id = $staff['faculty.5']; round = 1 } 201 | Out-Null
$double = (Raw $exam POST "/exam-papers/$($P2.id)/valuation/assign" @{ bundle_ids = $ids; evaluator_type = 'external'; external_evaluator = @{ name = 'External examiner'; user_id = (Sql "SELECT id FROM users WHERE username='examiner.ext'")[0].id }; round = 2 })
if ($double.Status -eq 201) {
  $mine = (Call $ext GET "/valuation/me/bundles").data
  Assert ((@($mine | Where-Object { $_.bundle_id -notin $ids }).Count) -eq 0 -or $mine.Count -ge $ids.Count) "external sees own bundles"
} else { Write-Host "   double valuation not active ($($double.Body.error.details.code)) — round 2 skipped" }
$other = (Sql "SELECT s.id FROM answer_scripts s JOIN answer_script_bundles b ON b.id=s.bundle_id WHERE b.exam_paper_id<>'$($P2.id)' LIMIT 1")
if ($other) { Expect $f5 POST "/answer-scripts/$($other[0].id)/valuations/1" @{ marks = 10 } 404 | Out-Null }

# ---- 4. valuation ---------------------------------------------------------------------------------------------------------------
Write-Host "== 4. valuation (evaluator projection is anonymous)"
$scripts = (Call $f5 GET "/valuation/bundles/$($B.id)/scripts").data
foreach ($k in 'exam_registration_item_id', 'student_name', 'registration_number', 'student_id') {
  Assert (-not ($scripts[0].PSObject.Properties.Name -contains $k)) "no $k in the evaluator JSON"
}
$max = [double]$P2.max_marks
Expect $f5 POST "/answer-scripts/$($scripts[0].id)/valuations/1" @{ marks = $max + 1 } 422 | Out-Null
foreach ($b in $bundles) {
  $i = 0
  foreach ($sc in (Call $f5 GET "/valuation/bundles/$($b.id)/scripts").data) {
    $i++
    Call $f5 POST "/answer-scripts/$($sc.id)/valuations/1" @{ marks = [math]::Round($max * (0.4 + ($i % 7) * 0.07), 1) } | Out-Null
  }
  Call $f5 POST "/valuation/bundles/$($b.id)/submit" | Out-Null
}
Expect $f5 POST "/answer-scripts/$($scripts[0].id)/valuations/1" @{ marks = 1 } 409 'RECORD_LOCKED' | Out-Null
if ($double.Status -eq 201) {
  foreach ($b in $bundles) {
    $i = 0
    foreach ($sc in (Call $ext GET "/valuation/bundles/$($b.id)/scripts").data) {
      $i++
      $shift = $(if ($i -eq 3) { 0.25 } else { 0.02 })
      Call $ext POST "/answer-scripts/$($sc.id)/valuations/2" @{ marks = [math]::Min($max, [math]::Round($max * (0.4 + ($i % 7) * 0.07 + $shift), 1)) } | Out-Null
    }
    Call $ext POST "/valuation/bundles/$($b.id)/submit" | Out-Null
  }
}

# ---- 5. reconcile ---------------------------------------------------------------------------------------------------------------
Write-Host "== 5. reconcile"
$rec = (Call $exam POST "/exam-papers/$($P2.id)/valuation/reconcile").data
if ($double.Status -eq 201) {
  Assert ($rec.needs_third -ge 1) "needs third valuation"
  Call $exam POST "/exam-papers/$($P2.id)/valuation/third-assign" @{ evaluator_staff_id = $staff['faculty.6'] } 201 | Out-Null
  foreach ($bb in (Call $f6 GET "/valuation/me/bundles").data | Where-Object { $_.valuation_round -eq 3 }) {
    foreach ($sc in (Call $f6 GET "/valuation/bundles/$($bb.bundle_id)/scripts").data) { Call $f6 POST "/answer-scripts/$($sc.id)/valuations/3" @{ marks = [math]::Round($max * 0.6, 1) } | Out-Null }
    Call $f6 POST "/valuation/bundles/$($bb.bundle_id)/submit" | Out-Null
  }
  $rec = (Call $exam POST "/exam-papers/$($P2.id)/valuation/reconcile").data
  $fm = (Sql "SELECT marks_v1, marks_v2, marks_v3, computed_marks FROM script_final_marks f JOIN answer_scripts s ON s.id=f.answer_script_id JOIN answer_script_bundles b ON b.id=s.bundle_id WHERE b.exam_paper_id='$($P2.id)' AND f.marks_v3 IS NOT NULL LIMIT 1")[0]
  $v = @([double]$fm.marks_v1, [double]$fm.marks_v2, [double]$fm.marks_v3) | Sort-Object
  $exp = $(if (($v[1] - $v[0]) -le ($v[2] - $v[1])) { ($v[0] + $v[1]) / 2 } else { ($v[1] + $v[2]) / 2 })
  Assert ([math]::Abs([double]$fm.computed_marks - $exp) -lt 0.01) "avg_closest_two"
}
Assert ($rec.needs_third -eq 0) "all resolved"

# ---- 6. moderation --------------------------------------------------------------------------------------------------------------
Write-Host "== 6. moderation"
$M = (Call $exam POST "/exam-papers/$($P2.id)/moderation" @{ action_type = 'add_flat'; rule = @{ marks = 3 }; justification = 'Paper harder than the blueprint' } 201).data
Expect $hod POST "/moderation-actions/$($M.id)/approve" @{} 403 | Out-Null
Call $coe POST "/moderation-actions/$($M.id)/approve" @{} | Out-Null
$applied = (Call $coe POST "/moderation-actions/$($M.id)/apply").data
Assert ($applied.affected_count -ge 1) "affected_count"
$chk = (Sql "SELECT computed_marks, moderated_marks FROM script_final_marks f JOIN answer_scripts s ON s.id=f.answer_script_id JOIN answer_script_bundles b ON b.id=s.bundle_id WHERE b.exam_paper_id='$($P2.id)' LIMIT 1")[0]
Assert ([math]::Abs([double]$chk.moderated_marks - [math]::Min($max, [double]$chk.computed_marks + 3)) -lt 0.01) "moderated = computed + 3 (capped)"
Call $coe POST "/moderation-actions/$($M.id)/revert" | Out-Null
Assert ((Sql "SELECT count(*) AS n FROM script_final_marks f JOIN answer_scripts s ON s.id=f.answer_script_id JOIN answer_script_bundles b ON b.id=s.bundle_id WHERE b.exam_paper_id='$($P2.id)' AND f.moderated_marks IS NOT NULL")[0].n -eq 0) "reverted"

# ---- 7. decode ------------------------------------------------------------------------------------------------------------------
Write-Host "== 7. decode"
Expect $exam POST "/exam-papers/$($P2.id)/decode" $null 403 | Out-Null
$d = (Call $dec POST "/exam-papers/$($P2.id)/decode").data
Assert ($d.decoded_count -ge 1) "decoded"
Assert ((Sql "SELECT count(*) AS n FROM audit_logs WHERE action='exams:decode' AND record_id='$($P2.id)'")[0].n -ge 1) "decode audited"
$after = (Call $f5 GET "/valuation/bundles/$($B.id)/scripts").data
Assert (-not ($after[0].PSObject.Properties.Name -contains 'exam_registration_item_id')) "still anonymous after decode"

# ---- 8. run --------------------------------------------------------------------------------------------------------------------
Write-Host "== 8. provisional run"
$q = Call $exam POST "/result-runs" @{ exam_session_id = $S.id; run_type = 'provisional' } 202
WaitJob $exam $q.data.job_id | Out-Null
$run = (Call $exam GET "/result-runs/$($q.data.run_id)").data
Assert ($run.status -eq 'computed') "computed"
Assert ($run.checksum.Length -eq 64) "checksum"
$an = (Call $exam GET "/result-runs/$($run.id)/anomalies").data
Write-Host "   anomalies: $(($an | Group-Object code | ForEach-Object { "$($_.Name)=$($_.Count)" }) -join ', ')"
$rows = (Call $exam GET "/result-runs/$($run.id)/rows?page_size=200").data | Where-Object { $_.student_program_enrollment_id -eq $s1row.enr }
foreach ($r in $rows | Where-Object { $_.result_status -in @('pass', 'fail') }) {
  $t = [double]$r.cia_marks + [double]$r.ese_marks
  Assert ([math]::Abs($t - [double]$r.total_marks) -lt 0.02) "total = CIA + ESE (+grace) for $($r.course_code)"
}

# ---- 10. SGPA ------------------------------------------------------------------------------------------------------------------
Write-Host "== 10. SGPA formula"
$tr = (Sql "SELECT t.sgpa FROM student_term_results t JOIN student_term_records r ON r.id=t.student_term_record_id WHERE t.run_id='$($run.id)' AND r.student_program_enrollment_id='$($s1row.enr)'")
if ($tr) {
  $g = $rows | Where-Object { $_.counts_toward_cgpa -and [double]$_.credits -gt 0 -and $_.result_status -notin @('withheld', 'withdrawn', 'incomplete') }
  $num = ($g | ForEach-Object { [double]$_.credits * [double]$_.grade_point } | Measure-Object -Sum).Sum
  $den = ($g | ForEach-Object { [double]$_.credits } | Measure-Object -Sum).Sum
  if ($den -gt 0) { Assert ([math]::Abs([math]::Round($num / $den, 2) - [double]$tr[0].sgpa) -lt 0.011) "SGPA = sum(C*GP)/sum(C)" }
}

# ---- 11. chain ------------------------------------------------------------------------------------------------------------------
Write-Host "== 11. verify / approve / rollback / publish"
Expect $coe POST "/result-runs/$($run.id)/publish" @{ audience = 'student' } 409 'INVALID_TRANSITION' | Out-Null
if ($an.Count -gt 0) { Expect $exam POST "/result-runs/$($run.id)/verify" @{} 409 'ANOMALIES_UNACKNOWLEDGED' | Out-Null }
Expect $hod GET "/result-runs/$($run.id)/rows" $null 403 | Out-Null
Call $exam POST "/result-runs/$($run.id)/verify" @{ acknowledge_anomalies = $true } | Out-Null
Expect $hod GET "/result-runs/$($run.id)/rows" $null 200 | Out-Null
Expect $exam POST "/result-runs/$($run.id)/approve" @{} 403 | Out-Null
Call $coe POST "/result-runs/$($run.id)/approve" @{} | Out-Null
Call $coe POST "/result-runs/$($run.id)/rollback" @{} | Out-Null
Assert ((Sql "SELECT count(*) AS n FROM student_course_results WHERE run_id='$($run.id)'")[0].n -eq 0) "rolled back rows deleted"
$q = Call $exam POST "/result-runs" @{ exam_session_id = $S.id; run_type = 'final' } 202
WaitJob $exam $q.data.job_id | Out-Null
$F = $q.data.run_id
Call $exam POST "/result-runs/$F/verify" @{ acknowledge_anomalies = $true } | Out-Null
Call $coe POST "/result-runs/$F/approve" @{} | Out-Null
Expect $auditor POST "/result-runs/$F/publish" @{ audience = 'public' } 403 | Out-Null
$pub = (Call $coe POST "/result-runs/$F/publish" @{ audience = 'public'; notify = $true }).data
Assert ($pub.status -eq 'published') "published"
Assert ((Sql "SELECT count(*) AS n FROM student_course_results WHERE run_id='$F' AND (status<>'published' OR hash IS NULL)")[0].n -eq 0) "rows published with hash"
Assert ((Sql "SELECT count(*) AS n FROM result_publications WHERE run_id='$F'")[0].n -eq 1) "publication row"
Assert ((Sql "SELECT status FROM exam_sessions WHERE id='$($S.id)'")[0].status -eq 'results_published') "session results_published"
$sms = Sql "SELECT body FROM message_logs WHERE channel='sms' AND body LIKE 'Result declared%' ORDER BY created_at DESC LIMIT 1"
if ($sms) { Assert ($sms[0].body -notmatch $rows[0].course_code) "masked SMS has no course" }

# ---- 12. immutability ---------------------------------------------------------------------------------------------------------
Write-Host "== 12. immutability"
$pid1 = (Sql "SELECT id FROM student_course_results WHERE run_id='$F' LIMIT 1")[0].id
$err = & $Py (Join-Path $PSScriptRoot "_sql.py") --write "UPDATE student_course_results SET letter_grade='O' WHERE id='$pid1'" 2>&1
Assert ("$err" -match 'immutable|check_violation') "trigger blocks updates"
Expect $coe PUT "/result-runs/$F/rows" @{} 405 | Out-Null

# ---- 13. versioning -------------------------------------------------------------------------------------------------------------
Write-Host "== 13. correction run → version 2"
$c = (Sql "SELECT course_id FROM student_course_results WHERE run_id='$F' AND student_program_enrollment_id='$($s1row.enr)' AND result_status IN ('pass','fail') LIMIT 1")
if ($c) {
  $key = "$($s1row.enr):$($c[0].course_id)"
  $q = Call $exam POST "/result-runs" @{ exam_session_id = $S.id; run_type = 'correction'; scope = @{ enrollment_ids = @($s1row.enr); course_ids = @($c[0].course_id); marks_delta = @{ $key = 5 } } } 202
  WaitJob $exam $q.data.job_id | Out-Null
  Call $exam POST "/result-runs/$($q.data.run_id)/verify" @{ acknowledge_anomalies = $true } | Out-Null
  Call $coe POST "/result-runs/$($q.data.run_id)/approve" @{} | Out-Null
  Call $coe POST "/result-runs/$($q.data.run_id)/publish" @{ notify = $false } | Out-Null
  $v = Sql "SELECT version, status, is_current FROM student_course_results WHERE student_program_enrollment_id='$($s1row.enr)' AND course_id='$($c[0].course_id)' ORDER BY version"
  Assert ($v[-1].version -ge 2 -and $v[-1].is_current) "new version current"
  Assert ($v[-2].status -eq 'superseded' -and -not $v[-2].is_current) "old version superseded"
  $me = (Call $s1 GET "/results/me").data
  Assert ((@($me.terms.courses | Where-Object { $_.course_id -eq $c[0].course_id }) | Select-Object -First 1).revised) "revised flag"
}

# ---- 14. access -------------------------------------------------------------------------------------------------------------------
Write-Host "== 14. access"
Expect $s1 GET "/results/me" $null 200 | Out-Null
Expect $parent GET "/results/wards/$($ward.sid)" $null 200 | Out-Null
$own = (Sql "SELECT f.offering_id FROM course_offering_faculty f JOIN staff st ON st.id=f.staff_id JOIN users u ON u.id=st.user_id WHERE u.username='faculty.1' LIMIT 1")
if ($own) { Expect $f1 GET "/course-offerings/$($own[0].offering_id)/results" $null 200 | Out-Null }
$foreign = (Sql "SELECT o.id FROM course_offerings o WHERE o.term_id='$term' AND NOT EXISTS (SELECT 1 FROM course_offering_faculty f JOIN staff st ON st.id=f.staff_id JOIN users u ON u.id=st.user_id WHERE f.offering_id=o.id AND u.username='faculty.1') LIMIT 1")
if ($foreign) { Expect $f1 GET "/course-offerings/$($foreign[0].id)/results" $null 404 | Out-Null }
SqlW "INSERT INTO institution_settings (id, institution_id, category, key, value, value_type) SELECT gen_random_uuid(), '$inst', 'exams', 'result_public_lookup', 'true', 'bool' WHERE NOT EXISTS (SELECT 1 FROM institution_settings WHERE institution_id='$inst' AND category='exams' AND key='result_public_lookup')"
SqlW "UPDATE institution_settings SET value='true' WHERE institution_id='$inst' AND category='exams' AND key='result_public_lookup'"
Expect $null POST "/public/results/lookup" @{ reg_no = $s1row.rno; dob = '1990-01-01'; institution = 'demo-uni' } 404 | Out-Null
# a student with a published term result in run F (student.1 is not in this exam session)
$pubRow = (Sql "SELECT s.registration_number AS rno, s.dob FROM student_term_results t JOIN student_term_records r ON r.id = t.student_term_record_id JOIN student_program_enrollments e ON e.id = r.student_program_enrollment_id JOIN students s ON s.id = e.student_id WHERE t.run_id = '$F' AND t.status = 'published' AND t.is_current AND s.deleted_at IS NULL AND s.dob IS NOT NULL LIMIT 1")[0]
Expect $null POST "/public/results/lookup" @{ reg_no = $pubRow.rno; dob = $pubRow.dob; institution = 'demo-uni' } 200 | Out-Null
$cards = (Call $s1 GET "/grade-cards/me").data
if ($cards.Count -eq 0) { WaitJob $coe (Call $coe POST "/result-runs/$F/grade-cards" $null 202).data.job_id | Out-Null; $cards = (Call $s1 GET "/grade-cards/me").data }
Assert ($cards.Count -ge 1) "grade card"
$pdf = Raw $s1 GET "/grade-cards/$($cards[-1].id).pdf"
Assert ($pdf.Status -eq 200) "grade card PDF"
$ver = (Call $null GET "/verify/$($cards[-1].qr_token)").data
Assert ($ver.hash.Length -eq 64 -and $null -ne $ver.sgpa) "verify hash + SGPA"
Expect $auditor GET "/result-runs/$F/rows" $null 200 | Out-Null
Expect $auditor POST "/exam-papers/$($P2.id)/decode" $null 403 | Out-Null

# ---- 15. legacy import ------------------------------------------------------------------------------------------------------------
Write-Host "== 15. legacy import"
$imps = Sql "SELECT id, status, validation_report FROM legacy_result_imports WHERE institution_id='$inst' ORDER BY created_at"
Assert ($imps.Count -ge 1) "seeded legacy imports"
$last = $imps[-1]
Assert ($last.status -eq 'applied') "applied"
Call $coe POST "/legacy-results/imports/$($last.id)/rollback" | Out-Null
Assert ((Sql "SELECT status FROM legacy_result_imports WHERE id='$($last.id)'")[0].status -eq 'rolled_back') "rolled back"

# ---- 16. custody ------------------------------------------------------------------------------------------------------------------
Write-Host "== 16. custody & retention"
Call $exam POST "/exam-sessions/$($S.id)/scripts/archive" @{} | Out-Null
Expect $exam POST "/exam-sessions/$($S.id)/scripts/destroy" @{} 403 | Out-Null
Call $coe POST "/exam-sessions/$($S.id)/scripts/destroy" @{ approval_note = 'Retention elapsed (verify)' } | Out-Null
$regi = (Call $exam GET "/exam-sessions/$($S.id)/scripts/register").data
Assert (($regi | Where-Object last_action -eq 'destroyed').Count -ge 1) "destruction register"

Write-Host "Phase 15 verification: $script:Checks checks passed"
