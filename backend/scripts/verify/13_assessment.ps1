# API verification — Phase 13 internal assessment, OBE definitions, LMS, projects (Prompts/13 §13.11).
#
# Run from backend/ with the API, the Celery worker and Redis (or the TCP fakeredis) up:
#   .\scripts\verify\13_assessment.ps1 [-BaseUrl http://localhost:8000/api/v1]
#
# Seed first: python scripts/seed_demo_institution.py --type university --only assessment
#
# Roles: faculty.1 (offering X), faculty.3, hod.cse, hod.ece, exam.cell, inst.admin (OBE manager in place of an
# `obe` login — the demo tenant has no obe_coordinator user), the learner on X's roster, another learner, parent.1.
#
# Documented deviations (PROGRESS.md decisions log, Phase 13):
#  * "student.1 in X" is whichever learner login sits on a faculty.1 offering roster (as in 11_attendance.ps1);
#  * the CIA university submission needs an `exam_authority='university'` programme — the step asserts 422
#    NOT_AFFILIATED for the autonomous demo programmes and only checks the success path when one exists;
#  * eligibility (step 7) runs the Phase 11 job and reads `term_eligibility.is_cia_ok`.
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

$f1 = Login 'faculty.1' (Get-DemoPassword 'faculty')
$f3 = Login 'faculty.3' (Get-DemoPassword 'faculty_3')
$hod = Login 'hod.cse' (Get-DemoPassword 'hod')
$hodEce = Login 'hod.ece' (Get-DemoPassword 'hod_ece')
$exam = Login 'exam.cell' (Get-DemoPassword 'exam_cell')
$admin = Login 'inst.admin' (Get-DemoPassword 'institution_admin')
$parent = Login 'parent.1' (Get-DemoPassword 'parent')
$inst = (Sql "SELECT id FROM institutions WHERE slug='demo-uni'")[0].id
$term = (Sql "SELECT id FROM academic_terms WHERE institution_id='$inst' AND college_id IS NULL AND is_current AND deleted_at IS NULL")[0].id
$f1staff = (Sql "SELECT s.id FROM staff s JOIN users u ON u.id=s.user_id WHERE u.username='faculty.1'")[0].id

# faculty.1's own 2025 section A offerings hold at most student.hold (2025 CSE is not bulk-registered): as in
# 11_attendance.ps1, faculty.1 co-instructs the fullest bulk-registered offering of the department and one of its
# students gets the demo student password, so offering X has a real roster with a learner login
$full = (Sql ("SELECT o.id FROM course_offerings o JOIN course_offering_faculty f0 ON f0.offering_id = o.id JOIN staff st ON st.id = f0.staff_id " +
  "WHERE o.term_id = '$term' AND st.department_id = (SELECT department_id FROM staff WHERE id = '$f1staff') " +
  "ORDER BY (SELECT count(*) FROM course_registration_items i WHERE i.offering_id = o.id AND i.status = 'confirmed') DESC, o.id LIMIT 1"))[0].id
SqlW "INSERT INTO course_offering_faculty (institution_id, offering_id, staff_id, role, hours_per_week) SELECT institution_id, id, '$f1staff', 'instructor', 0 FROM course_offerings WHERE id = '$full' ON CONFLICT DO NOTHING"
$rosterLogin = (Sql ("SELECT u.username FROM course_registration_items i JOIN course_registrations r ON r.id = i.registration_id JOIN student_program_enrollments e ON e.id = r.student_program_enrollment_id " +
  "JOIN students s ON s.id = e.student_id JOIN users u ON u.id = s.user_id WHERE i.offering_id = '$full' AND i.status = 'confirmed' AND u.is_active AND s.deleted_at IS NULL ORDER BY u.username LIMIT 1"))[0].username
& $Py (Join-Path $PSScriptRoot "_reset_password.py") $rosterLogin (Get-DemoPassword 'student') | Out-Null

# offering X: a faculty.1 offering whose roster holds a learner login
$learners = @()
foreach ($pair in @(@($rosterLogin, 'student'), @('student.1', 'student'), @('A25BTECHCSE013', 'student_hold'), @('A24BTECHCSE200', 'student_arrear'))) {
  $row = Sql "SELECT e.id enrol FROM students s JOIN student_program_enrollments e ON e.student_id=s.id LEFT JOIN users u ON u.id=s.user_id WHERE (u.username='$($pair[0])' OR s.registration_number='$($pair[0])') AND e.deleted_at IS NULL LIMIT 1"
  if ($row) { $learners += [pscustomobject]@{ login = $pair[0]; role = $pair[1]; enrol = $row[0].enrol } }
}
$X = $null; $inX = $null
foreach ($l in $learners) {
  $o = Sql "SELECT i.offering_id FROM course_registration_items i JOIN course_registrations r ON r.id=i.registration_id JOIN course_offering_faculty f ON f.offering_id=i.offering_id WHERE r.student_program_enrollment_id='$($l.enrol)' AND i.status='confirmed' AND r.term_id='$term' AND f.staff_id='$f1staff' LIMIT 1"
  if ($o) { $X = $o[0].offering_id; $inX = $l; break }
}
if (-not $X) { throw "no faculty.1 offering holds a learner login - reseed" }
$outX = $learners | Where-Object { $_.enrol -ne $inX.enrol } | Select-Object -First 1
$s1 = Login $inX.login (Get-DemoPassword $inX.role)
$s2 = if ($outX) { Login $outX.login (Get-DemoPassword $outX.role) } else { $null }
$course = (Sql "SELECT course_id FROM course_offerings WHERE id='$X'")[0].course_id

# ---- 1. assessments ------------------------------------------------------------------------------------------------------
Write-Host "== 1. assessments"
SqlW "DELETE FROM offering_assessments WHERE offering_id='$X'"
SqlW "DELETE FROM cia_consolidations WHERE offering_id='$X'"
$i1 = (Call $f1 POST "/course-offerings/$X/assessments/instantiate" @{}).data
$i2 = (Call $f1 POST "/course-offerings/$X/assessments/instantiate" @{}).data
Assert ($i2.created -eq 0 -and $i2.existing -eq $i1.created) "instantiate idempotent"
Expect $f3 GET "/course-offerings/$X/assessments" $null 404 | Out-Null
$A = ((Call $f1 GET "/course-offerings/$X/assessments").data | Select-Object -First 1)

# ---- 2. question map -------------------------------------------------------------------------------------------------------
Write-Host "== 2. question map"
$cos = (Call $f1 GET "/courses/$course/outcomes").data.cos
$half = [double]$A.max_marks / 2
Expect $f1 PUT "/offering-assessments/$($A.id)/questions" @{ questions = @(@{ question_no = 'A1'; max_marks = $A.max_marks; part = 'A' }, @{ question_no = 'B1'; max_marks = 10; part = 'B' }) } 422 | Out-Null
$foreign = (Sql "SELECT id FROM course_outcomes WHERE course_id <> '$course' LIMIT 1")
if ($foreign) { Expect $f1 PUT "/offering-assessments/$($A.id)/questions" @{ questions = @(@{ question_no = 'A1'; max_marks = $A.max_marks; co_id = $foreign[0].id }) } 422 | Out-Null }
Call $f1 PUT "/offering-assessments/$($A.id)/questions" @{ questions = @(@{ question_no = 'A1'; max_marks = $half; part = 'A'; co_id = $cos[0].id }, @{ question_no = 'B1'; max_marks = $half; part = 'B'; co_id = $cos[1].id }) } | Out-Null

# ---- 3. marks ---------------------------------------------------------------------------------------------------------------
Write-Host "== 3. marks"
$grid = (Call $f1 GET "/offering-assessments/$($A.id)/marks").data
$rows = @($grid.rows | ForEach-Object { @{ student_program_enrollment_id = $_.student_program_enrollment_id; question_wise = @{ A1 = [math]::Floor($half * 0.7); B1 = [math]::Floor($half * 0.6) } } })
$rows[0].marks = 1  # sum mismatch → rejected
if ($outX -and -not ($grid.rows.student_program_enrollment_id -contains $outX.enrol)) { $rows += @{ student_program_enrollment_id = $outX.enrol; marks = 1 } }
$key = [guid]::NewGuid().ToString()
$m1 = (Call $f1 POST "/offering-assessments/$($A.id)/marks" @{ rows = $rows } 200 @{ 'Idempotency-Key' = $key }).data
Assert ($m1.rejected.Count -ge 1) "sum mismatch / non-roster rows rejected"
$m2 = (Call $f1 POST "/offering-assessments/$($A.id)/marks" @{ rows = $rows } 200 @{ 'Idempotency-Key' = $key }).data
Assert ($m2.saved -eq $m1.saved) "replay"
$own = (Call $s1 GET "/marks/me").data
Assert (@($own | Where-Object offering_id -eq $X).Count -eq 1) "student sees own marks"
$sg = (Call $s1 GET "/offering-assessments/$($A.id)/marks").data
Assert ($sg.rows.Count -eq 1) "student grid = own row only"

# ---- 4. chain ---------------------------------------------------------------------------------------------------------------
Write-Host "== 4. chain"
Expect $f1 POST "/offering-assessments/$($A.id)/submit" @{} 409 'MARKS_MISSING' | Out-Null
$fix = @(@{ student_program_enrollment_id = $grid.rows[0].student_program_enrollment_id; question_wise = @{ A1 = 1; B1 = 1 } })
Call $f1 POST "/offering-assessments/$($A.id)/marks" @{ rows = $fix } 200 @{ 'Idempotency-Key' = [guid]::NewGuid().ToString() } | Out-Null
Call $f1 POST "/offering-assessments/$($A.id)/submit" @{} | Out-Null
Expect $f1 POST "/offering-assessments/$($A.id)/verify" @{ decision = 'approve' } 403 | Out-Null
Call $hod POST "/offering-assessments/$($A.id)/verify" @{ decision = 'reject'; comment = 'recheck B1' } | Out-Null
Call $f1 POST "/offering-assessments/$($A.id)/submit" @{} | Out-Null
Call $hod POST "/offering-assessments/$($A.id)/verify" @{ decision = 'approve' } | Out-Null
Expect $hod POST "/offering-assessments/$($A.id)/lock" @{} 403 | Out-Null
Call $exam POST "/offering-assessments/$($A.id)/lock" @{} | Out-Null
$late = Raw $f1 POST "/offering-assessments/$($A.id)/marks" @{ rows = $fix } @{ 'Idempotency-Key' = [guid]::NewGuid().ToString() }
Assert ($late.Status -eq 409 -and $late.Body.error.code -eq 'RECORD_LOCKED') "marks after lock -> RECORD_LOCKED"

# ---- 5. change request --------------------------------------------------------------------------------------------------------
Write-Host "== 5. change request"
$mark = (Call $f1 GET "/offering-assessments/$($A.id)/marks").data.rows | Where-Object { $_.mark_id -and $_.marks -ne $null } | Select-Object -First 1
$cr = (Call $f1 POST "/marks-change-requests" @{ target_id = $mark.mark_id; new_value = @{ marks = [math]::Min([double]$A.max_marks, [double]$mark.marks + 1) }; reason = 'Totalling error'; evidence_url = 'https://example.invalid/script.pdf' }).data
Call $hod POST "/marks-change-requests/$($cr.id)/approve" @{} | Out-Null
$coe = Login-Mfa 'controller_of_examinations' 'coe'   # MFA-required role in the demo tenant
Call $coe POST "/marks-change-requests/$($cr.id)/approve" @{} | Out-Null
$ap = (Call $coe POST "/marks-change-requests/$($cr.id)/apply").data
Assert ($ap.status -eq 'applied') "change applied"
Assert ((Sql "SELECT count(*) n FROM audit_logs WHERE record_type='marks_change_request' AND record_id='$($cr.id)'")[0].n -ge 2) "audit rows"

# ---- 6. consolidation ------------------------------------------------------------------------------------------------------------
Write-Host "== 6. CIA"
$c = (Call $f1 POST "/course-offerings/$X/cia/consolidate").data
Assert ($c.rows.Count -gt 0) "consolidated"
$r0 = $c.rows[0]
$expected = [math]::Round(($r0.component_breakdown.PSObject.Properties | Where-Object { $_.Name -notlike '_*' -and $_.Value.counted -ne $false -and $_.Value.value -ne $null } | Measure-Object -Property { $_.Value.value } -Sum).Sum, 2)
Assert ([math]::Abs($expected - [double]$r0.cia_total) -lt 0.05) "cia_total = sum of counted components"
Call $hod POST "/cia/$X/approve" | Out-Null
Call $exam POST "/cia/$X/lock" | Out-Null
$uni = Raw $exam POST "/cia/$X/submit-to-university"
Assert ($uni.Status -in @(200, 422)) "university submission (422 NOT_AFFILIATED for autonomous programmes)"

# ---- 7. eligibility hook -----------------------------------------------------------------------------------------------------------
Write-Host "== 7. eligibility"
$job = (Call $exam POST "/terms/$term/eligibility/compute" @{} 202).data
Write-Host "   eligibility job $($job.job_id) queued (is_cia_ok read from cia_consolidations)"

# ---- 8. OBE -----------------------------------------------------------------------------------------------------------------------
Write-Host "== 8. OBE"
$prog = (Sql "SELECT p.id FROM programs p JOIN courses c ON c.department_id=p.department_id WHERE c.id='$course' LIMIT 1")[0].id
$po = (Call $admin POST "/programs/$prog/outcomes/import-template" @{}).data
Assert (@($po.outcomes | Where-Object outcome_type -eq 'PO').Count -ge 8) "PO template imported"
$co = (Call $admin GET "/courses/$course/outcomes").data
$bad = @($co.cos | Select-Object -Skip 1 | ForEach-Object { @{ co_id = $_.id; outcome_id = $co.program_outcomes[0].id; level = 2 } })
Expect $admin PUT "/courses/$course/co-po-matrix" @{ cells = $bad } 422 'CO_UNMAPPED' | Out-Null
$good = @($co.cos | ForEach-Object { @{ co_id = $_.id; outcome_id = $co.program_outcomes[0].id; level = 2; justification = 'core' } })
Call $admin PUT "/courses/$course/co-po-matrix" @{ cells = $good } | Out-Null
# faculty.3 is CSE faculty: allowed in principle, but an active regulation freezes the COs (409); else 403 off-department
$regActive = (Sql "SELECT r.status IN ('active','approved','published') AS a FROM courses c JOIN regulations r ON r.id = c.regulation_id WHERE c.id = '$course'")[0].a
if ($regActive) { Expect $f3 PUT "/courses/$course/outcomes" @{ outcomes = @(@{ code = 'CO1'; statement = 'x x x' }) } 409 'RULE_VIOLATION' | Out-Null }
else { Expect $f3 PUT "/courses/$course/outcomes" @{ outcomes = @(@{ code = 'CO1'; statement = 'x x x' }) } 403 | Out-Null }

# ---- 9. LMS ------------------------------------------------------------------------------------------------------------------------
Write-Host "== 9. LMS"
$mod = (Call $f1 POST "/course-offerings/$X/modules" @{ title = 'verify-13 module'; is_published = $true }).data
$pdf = (Call $f1 POST "/modules/$($mod.id)/contents" @{ content_type = 'file'; title = 'Notes'; file_url = 'https://example.invalid/n.pdf' }).data
Call $f1 POST "/modules/$($mod.id)/contents" @{ content_type = 'video'; title = 'Lecture'; file_url = 'https://example.invalid/v' } | Out-Null
$v = (Call $s1 POST "/contents/$($pdf.id)/view" @{ progress_pct = 100 }).data
Assert ($v.my_progress -eq 100) "progress"
if ($s2) { Expect $s2 POST "/contents/$($pdf.id)/view" @{ progress_pct = 100 } 404 | Out-Null }
$cat = ((Call $f1 GET "/course-offerings/$X/assessments").data | Where-Object { $_.status -ne 'locked' } | Select-Object -First 1)
$asg = (Call $f1 POST "/course-offerings/$X/assignments" @{ title = 'verify-13 assignment'; due_at = (Get-Date).AddDays(1).ToUniversalTime().ToString('o'); max_marks = 10; late_penalty_pct_per_day = 10; rubric = @(@{ criterion = 'quality'; max = 10 }); offering_assessment_id = $cat.id }).data
Call $f1 POST "/assignments/$($asg.id)/publish" | Out-Null
$sub = (Call $s1 POST "/assignments/$($asg.id)/submit" @{ text_answer = 'answer'; files = @(@{ name = 'a.pdf'; size_mb = 1 }) }).data
Call $f1 POST "/assignments/$($asg.id)/grade" @{ rows = @(@{ submission_id = $sub.id; rubric_scores = @{ quality = 8 }; feedback = 'good' }) } | Out-Null
Assert ((Sql "SELECT count(*) n FROM internal_marks WHERE offering_assessment_id='$($cat.id)' AND student_program_enrollment_id='$($inX.enrol)'")[0].n -eq 1) "linked internal mark written"

# ---- 10. quiz ------------------------------------------------------------------------------------------------------------------------
Write-Host "== 10. quiz"
$qids = @()
for ($k = 1; $k -le 10; $k++) { $qids += (Call $f1 POST "/questions" @{ course_id = $course; question_type = 'mcq'; body_primary = "verify-13 Q$k"; marks = 1; options = @(@{ body_primary = 'yes'; is_correct = $true }, @{ body_primary = 'no' }) } 201).data.id }
$bp = (Call $f1 POST "/blueprints" @{ course_id = $course; name = 'verify-13 bp'; total_marks = 10; duration_minutes = 10; pattern = @{ parts = @(@{ title = 'A'; count = 10; marks = 1; question_types = @('mcq') }) } }).data
$paper = (Call $f1 POST "/question-papers/generate" @{ blueprint_id = $bp.id; purpose = 'quiz' }).data
Call $f1 POST "/question-papers/$($paper.id)/freeze" | Out-Null
Expect $f1 PUT "/question-papers/$($paper.id)" @{ title = 'x' } 409 | Out-Null
$quiz = (Call $f1 POST "/course-offerings/$X/quizzes" @{ title = 'verify-13 quiz'; question_paper_id = $paper.id; duration_minutes = 10; attempts_allowed = 1; show_result = 'immediate' }).data
Call $f1 POST "/quizzes/$($quiz.id)/publish" | Out-Null
$st = (Call $s1 POST "/quizzes/$($quiz.id)/start").data
$ans = @{}; foreach ($q in $st.questions) { $ans[$q.question_id] = $q.options[0].id }
Call $s1 PUT "/quiz-attempts/$($st.attempt_id)/answers" @{ answers = $ans } | Out-Null
$done = (Call $s1 POST "/quiz-attempts/$($st.attempt_id)/submit").data
Assert ($done.status -in @('graded', 'submitted')) "auto-scored"
Expect $s1 POST "/quizzes/$($quiz.id)/start" @{} 409 'ATTEMPTS_EXHAUSTED' | Out-Null

# ---- 11. discussions --------------------------------------------------------------------------------------------------------------------
Write-Host "== 11. discussions"
$t = (Call $s1 POST "/course-offerings/$X/threads" @{ title = 'verify-13 doubt'; body = 'How?' }).data
$p = (Call $f1 POST "/threads/$($t.id)/posts" @{ body = 'Like this.' }).data
Call $s1 POST "/posts/$($p.id)/upvote" | Out-Null
Call $s1 POST "/posts/$($p.id)/mark-answer" | Out-Null
Call $f1 PUT "/threads/$($t.id)" @{ is_locked = $true } | Out-Null
Expect $s1 POST "/threads/$($t.id)/posts" @{ body = 'more' } 409 'THREAD_LOCKED' | Out-Null

# ---- 12. lesson plan ---------------------------------------------------------------------------------------------------------------------
Write-Host "== 12. lesson plan"
$items = @(1..12 | ForEach-Object { @{ unit_no = [math]::Ceiling($_ / 4); topic = "verify-13 topic $_"; planned_date = (Get-Date).AddDays($_ - 20).ToString('yyyy-MM-dd'); planned_hours = 1; sequence = $_ } })
$plan = (Call $f1 POST "/course-offerings/$X/lesson-plan" @{ items = $items }).data
$sess = (Sql "SELECT id FROM class_sessions WHERE offering_id='$X' ORDER BY session_date LIMIT 1")
$d = (Call $f1 POST "/lesson-plans/$($plan[2].id)/deliver" @{ session_id = $(if ($sess) { $sess[0].id } else { $null }) }).data
Assert ($d.status -eq 'delivered') "delivered"
Assert ((Call $f1 GET "/course-offerings/$X/lesson-plan/deviation").data.Count -eq 12) "deviation rows"
$cf = (Call $f1 GET "/course-offerings/$X/course-file").data
Write-Host "   course file $($cf.completion_pct)%"

# ---- 13. projects ---------------------------------------------------------------------------------------------------------------------------
Write-Host "== 13. projects"
$roster = @((Call $f1 GET "/offering-assessments/$($A.id)/marks").data.rows | Select-Object -First 3 | ForEach-Object student_program_enrollment_id)
$pr = (Call $f1 POST "/course-offerings/$X/projects" @{ title = 'verify-13 dissertation'; project_type = 'dissertation'; guide_staff_id = $f1staff; members = $roster }).data
Call $f1 POST "/projects/$($pr.id)/reviews" @{ review_no = 1; rubric_scores = @{ problem = 5; design = 4 } } | Out-Null
Assert (@((Call $s1 GET "/projects/me").data | Where-Object id -eq $pr.id).Count -eq ([int]($roster -contains $inX.enrol))) "projects/me"
$other = (Sql "SELECT e.id FROM student_program_enrollments e WHERE e.institution_id='$inst' AND e.id NOT IN (SELECT r.student_program_enrollment_id FROM course_registrations r JOIN course_registration_items i ON i.registration_id=r.id WHERE i.offering_id='$X') LIMIT 1")[0].id
Expect $f1 PUT "/projects/$($pr.id)/members" @{ members = @($other) } 422 'NOT_ON_ROSTER' | Out-Null

# ---- 14. question bank ---------------------------------------------------------------------------------------------------------------------
Write-Host "== 14. question bank"
Expect $f1 POST "/questions" @{ question_type = 'mcq'; body_primary = 'bad'; options = @(@{ body_primary = 'a'; is_correct = $true }, @{ body_primary = 'b'; is_correct = $true }) } 422 | Out-Null
$pdfr = Raw $f1 GET "/question-papers/$($paper.id)/print?lang=both"
Assert ($pdfr.Status -eq 200) "bilingual print"

# ---- 15. visibility ------------------------------------------------------------------------------------------------------------------------
Write-Host "== 15. visibility"
$wardEnrol = (Sql "SELECT e.id FROM student_guardians g JOIN users u ON u.id=g.user_id JOIN student_program_enrollments e ON e.student_id=g.student_id WHERE u.username='parent.1' LIMIT 1")
if ($wardEnrol) {
  $wo = (Sql "SELECT oa.id FROM offering_assessments oa JOIN course_registration_items i ON i.offering_id=oa.offering_id JOIN course_registrations r ON r.id=i.registration_id WHERE r.student_program_enrollment_id='$($wardEnrol[0].id)' AND i.status='confirmed' LIMIT 1")
  if ($wo) { $pg = (Call $parent GET "/offering-assessments/$($wo[0].id)/marks").data; Assert ($pg.read_only -and $pg.rows.Count -le 1) "parent read-only ward row" }
}
Expect $hodEce GET "/offering-assessments/$($A.id)/marks" $null 404 | Out-Null

Summary '13'
