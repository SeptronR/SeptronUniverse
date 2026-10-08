# API verification — Phase 07 students, enrolment, holds & academic standing
# (Prompts/07_Phase07_Students_Enrolment_Holds_Standing.md §07.11).
#
# Run from backend/ with the API up, Redis and a Celery worker + Beat (promotion, bulk import and ID cards are jobs;
# the outbox relay dispatches the notifications):
#   .\scripts\verify\07_students.ps1 [-BaseUrl http://localhost:8000/api/v1]
#
# Seed first: python scripts/seed_demo_institution.py --type university --only students   (base → … → hr → students)
#
# Roles: registrar (MFA in the demo tenant), hod.cse, hod.ece, advisor.1, faculty.2, accountant, student.1, parent.1,
# parent.noconsent, librarian, principal (vice_chancellor — step 2 of students.transfer), auditor.tmp.
# Re-runnable: step 0 resets the fixtures (student.1 consent / holds / credit transfers, the 2024 B.Tech promotion, the
# NEP-exit student, the standing student, the transfer student) and soft-deletes the students earlier runs created.
#
# Documented deviations from the prompt text (see PROGRESS.md decisions log, Phase 07):
#  * the institution scope tab is called "all" in meta.visibility (Phase 02 resolver naming), not "institution";
#  * the real promotion is the job students.promote (202 + job id); the dry run answers the preview directly;
#  * the transfer workflow is registrar → principal: the registrar's approval moves it to dues_check (Phase 12 holds it
#    there until no-dues clear), the principal's approval → approved;
#  * certificate numbers come from the institution's tc_no / migration_cert_no sequences (TC/{yyyy}/…, MIG/{yyyy}/…);
#    Phase 26 renders the certificates;
#  * a credit transfer's result row is created by Phase 15 (approval stores status=approved until then).
#  1. GET /students per role: scopes, totals, masking
#  2. POST /students (batch 2026 auto-created, guardians ×2, APAAR) → regno pattern, student user, guardian users
#     reused for a sibling; bad APAAR / category → 422
#  3. student self service (/students/me; first_name → 422; phone → 200)
#  4. undertakings: 2 pending for a fresh student; anti_ragging → accepted with ip; registration gate → 409
#     UNDERTAKING_PENDING until conduct
#  5. guardians: parent.1 sees 1 ward; consent off → 0 wards and 404; parent.noconsent sees nothing
#  6. holds: librarian library hold; registrar all hold; gate → 409 HOLD_BLOCKED; librarian cannot release all;
#     registrar releases with reason; student notified
#  7. promotion of 2024-BTECH-CSE: dry run (198 / 2 detained / 2 on break) → job → term 6 records, detained; re-run
#     idempotent
#  8. NEP exit: term 3 → 409; term 4 with 84 credits → exited_early + student.exited; re-entry → exit_reentry; second
#     open enrolment → 409
#  9. standing: CGPA history → probation (+ history); dismissal → all hold
# 10. transfer: request → registrar → dues_check → principal → approved → complete (TC / migration numbers,
#     transferred)
# 11. credit transfer: NPTEL 4 cr → hod.cse verify (equivalent course) → registrar approve; cap 12 → 4th 422
# 12. bulk import: dry run 50 rows (3 bad) → apply job 47; export masked (accountant) / unmasked (registrar)
# 13. ID cards: job → ZIP; GET /verify/{token} public → name, reg no, status; tampered → valid=false
# 14. auditor: reads OK, writes 403
param([string]$BaseUrl = "http://localhost:8000/api/v1")
. "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl
$Backend = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Python = Get-VenvPython $Backend
$env:PYTHONUTF8 = "1"
Push-Location $Backend

# hashtable merge where the right side wins (PowerShell's + throws on duplicate keys)
function Merge($a, $b) { $h = $a.Clone(); foreach ($k in $b.Keys) { $h[$k] = $b[$k] }; $h }

function Sql($query) {
  $out = & $Python scripts/verify/_sql.py $query
  if ($LASTEXITCODE -ne 0) { throw "sql failed: $query" }
  return @($out | ConvertFrom-Json)
}
function SqlWrite($query) { & $Python scripts/verify/_sql.py --write $query | Out-Null; if ($LASTEXITCODE -ne 0) { throw "sql failed: $query" } }
function WaitFor($label, [scriptblock]$probe, $seconds = 90) {
  for ($i = 0; $i -lt $seconds; $i++) { $v = & $probe; if ($v) { return $v }; Start-Sleep -Seconds 1 }
  throw "timed out waiting for: $label"
}
function Job($token, $jobId) {
  WaitFor "job $jobId" { $j = (Call $token GET "/jobs/$jobId").data; if ($j.status -in @('succeeded', 'failed', 'cancelled')) { $j } } 180
}
function Upload($token, $path, $file, $fields = @{}, $expect = 200) {
  $form = @{ file = Get-Item $file }
  foreach ($k in $fields.Keys) { $form[$k] = $fields[$k] }
  $r = Invoke-WebRequest -Method Post -Uri "$script:BaseUrl$path" -Headers @{ Authorization = "Bearer $token" } -Form $form -SkipHttpErrorCheck
  if ($r.StatusCode -ne $expect) { throw "POST $path expected $expect got $($r.StatusCode): $($r.Content)" }
  $script:Checks++
  Write-Host "OK POST $path (multipart) -> $($r.StatusCode)"
  return ($r.Content | ConvertFrom-Json)
}
function Download($token, $path, $outFile) {
  $h = @{}
  if ($token) { $h['Authorization'] = "Bearer $token" }
  $r = Invoke-WebRequest -Method Get -Uri "$script:BaseUrl$path" -Headers $h -OutFile $outFile -PassThru -SkipHttpErrorCheck
  if ($r.StatusCode -ne 200) { throw "GET $path expected 200 got $($r.StatusCode)" }
  $script:Checks++
  Write-Host "OK GET $path -> $($r.StatusCode) ($((Get-Item $outFile).Length) bytes)"
}
function Apaar([long]$seed) {
  # 12-digit APAAR id with a Luhn check digit (the IN pack's validator)
  $base = ("8" + $seed.ToString("D10")).Substring(0, 11)
  $digits = ($base + "0").ToCharArray() | ForEach-Object { [int][string]$_ }
  [array]::Reverse($digits)
  $total = 0
  for ($i = 0; $i -lt $digits.Length; $i++) { $n = $digits[$i]; if ($i % 2 -eq 1) { $n *= 2; if ($n -gt 9) { $n -= 9 } }; $total += $n }
  return $base + ((10 - $total % 10) % 10)
}
function Marker($m) { (Sql "SELECT s.id, s.user_id, s.registration_number, e.id AS enrollment_id FROM students s JOIN student_program_enrollments e ON e.student_id = s.id WHERE s.institution_id = '$script:InstId' AND s.enrolment_number = '$m' ORDER BY e.created_at LIMIT 1")[0] }

$tmp = Join-Path ([System.IO.Path]::GetTempPath()) "verify07"
New-Item -ItemType Directory -Force $tmp | Out-Null
$s1 = $null
try {
  $run = Get-Random -Minimum 10000 -Maximum 99999
  foreach ($u in @(@('registrar', 'registrar'), @('hod.cse', 'hod'), @('hod.ece', 'hod_ece'), @('advisor.1', 'class_advisor'), @('faculty.2', 'faculty_2'),
                   @('accountant', 'accountant'), @('student.1', 'student'), @('parent.1', 'parent'), @('parent.noconsent', 'parent_noconsent'),
                   @('librarian', 'librarian'), @('principal', 'vice_chancellor'), @('auditor.tmp', 'auditor'), @('inst.admin', 'institution_admin'))) {
    & $Python scripts/verify/_reset_password.py $u[0] (Get-DemoPassword $u[1]) | Out-Null
  }
  SqlWrite "UPDATE users SET valid_to = NOW() + INTERVAL '7 days', is_active = TRUE WHERE username = 'auditor.tmp'; UPDATE user_roles SET valid_to = NOW() + INTERVAL '7 days' WHERE user_id IN (SELECT id FROM users WHERE username = 'auditor.tmp')"
  $reg = Login-Mfa 'registrar' 'registrar'
  $hod = Login 'hod.cse' (Get-DemoPassword 'hod')
  $hodEce = Login 'hod.ece' (Get-DemoPassword 'hod_ece')
  $adv = Login 'advisor.1' (Get-DemoPassword 'class_advisor')
  $f2 = Login 'faculty.2' (Get-DemoPassword 'faculty_2')
  $acct = Login 'accountant' (Get-DemoPassword 'accountant')
  $stu = Login 'student.1' (Get-DemoPassword 'student')
  $par = Login 'parent.1' (Get-DemoPassword 'parent')
  $noc = Login 'parent.noconsent' (Get-DemoPassword 'parent_noconsent')
  $lib = Login 'librarian' (Get-DemoPassword 'librarian')
  $vc = Login 'principal' (Get-DemoPassword 'vice_chancellor')
  $auditor = Login 'auditor.tmp' (Get-DemoPassword 'auditor')
  $script:InstId = (Call $reg GET "/auth/me").data.user.institution_id
  $inst = $script:InstId

  Write-Host "== 0. fixture reset"
  $s1 = (Call $stu GET "/students/me").data
  $e1 = $s1.enrollment.id
  $b2024 = (Sql "SELECT id FROM batches WHERE institution_id = '$inst' AND code = '2024-BTECH-CSE'")[0].id
  $b2025 = (Sql "SELECT id FROM batches WHERE institution_id = '$inst' AND code = '2025-BTECH-CSE'")[0].id
  $cseProg = (Sql "SELECT id FROM programs WHERE institution_id = '$inst' AND code = 'BTECH-CSE'")[0].id
  $brk = Sql "SELECT s.id, s.user_id FROM students s WHERE s.institution_id = '$inst' AND s.enrolment_number IN ('DEMO0201','DEMO0202')"
  $brkIds = ($brk | ForEach-Object { "'$($_.id)'" }) -join ','
  $std = Marker 'DEMO0010'
  $trf = Marker 'DEMO0050'
  SqlWrite ("UPDATE students SET guardian_portal_consent = TRUE WHERE id = '$($s1.id)'; " +
    "DELETE FROM student_holds WHERE student_program_enrollment_id IN (SELECT id FROM student_program_enrollments WHERE student_id = '$($s1.id)'); " +
    "DELETE FROM student_undertakings WHERE student_id = '$($s1.id)' AND undertaking_type = 'conduct'; " +
    "DELETE FROM workflow_instances WHERE entity_type = 'credit_transfer' AND entity_id IN (SELECT id FROM credit_transfers WHERE student_program_enrollment_id = '$e1'); " +
    "DELETE FROM credit_transfers WHERE student_program_enrollment_id = '$e1'; " +
    "DELETE FROM student_term_records WHERE term_number = 6 AND student_program_enrollment_id IN (SELECT id FROM student_program_enrollments WHERE batch_id = '$b2024'); " +
    "UPDATE student_term_records SET status = 'in_progress' WHERE term_number = 5 AND status = 'detained' AND student_program_enrollment_id IN (SELECT id FROM student_program_enrollments WHERE batch_id = '$b2024'); " +
    "UPDATE students SET status = 'active' WHERE status = 'detained' AND id IN (SELECT student_id FROM student_program_enrollments WHERE batch_id = '$b2024'); " +
    "UPDATE student_program_enrollments SET status = 'active' WHERE batch_id = '$b2024' AND status = 'detained'; " +
    "UPDATE batches SET current_term_number = 5 WHERE id = '$b2024'; " +
    "DELETE FROM student_program_enrollments WHERE entry_type = 'exit_reentry' AND student_id IN ($brkIds); " +
    "UPDATE student_program_enrollments SET status = 'break', exit_award = NULL, exit_date = NULL WHERE batch_id = '$b2024' AND student_id IN ($brkIds); " +
    "UPDATE students SET status = 'on_break' WHERE id IN ($brkIds); UPDATE users SET is_active = TRUE WHERE id IN (SELECT user_id FROM students WHERE id IN ($brkIds)); " +
    "DELETE FROM student_holds WHERE student_program_enrollment_id = '$($std.enrollment_id)'; " +
    "UPDATE student_program_enrollments SET academic_standing = 'good' WHERE id = '$($std.enrollment_id)'; " +
    "DELETE FROM workflow_instances WHERE entity_type = 'student_transfer' AND entity_id IN (SELECT id FROM student_transfers WHERE student_id = '$($trf.id)'); " +
    "DELETE FROM student_transfers WHERE student_id = '$($trf.id)'; " +
    "UPDATE students SET status = 'active' WHERE id = '$($trf.id)'; UPDATE student_program_enrollments SET status = 'active' WHERE student_id = '$($trf.id)'; " +
    "UPDATE users SET is_active = TRUE WHERE id = '$($trf.user_id)'; " +
    "UPDATE users SET is_active = FALSE WHERE id IN (SELECT user_id FROM students WHERE institution_id = '$inst' AND last_name LIKE 'Verify%' AND deleted_at IS NULL); " +
    "UPDATE students SET deleted_at = NOW(), is_active = FALSE WHERE institution_id = '$inst' AND last_name LIKE 'Verify%' AND deleted_at IS NULL")
  Assert ($s1.registration_number -and $e1 -and $b2024 -and $b2025) "student.1 ($($s1.registration_number)) and the 2024/2025 B.Tech batches exist"

  Write-Host "== 1. list visibility"
  $total = (Sql "SELECT COUNT(*) AS n FROM students WHERE institution_id = '$inst' AND deleted_at IS NULL")[0].n
  $r = Call $reg GET "/students?page_size=200"
  Assert ($r.meta.pagination.total -eq $total -and $total -ge 400) "registrar sees every student ($total)"
  Assert (($r.meta.visibility.scopes -join ',') -eq 'all' -and $r.meta.visibility.pii) "registrar: scopes [all] (institution tab), pii=true"
  $cseTotal = (Sql "SELECT COUNT(DISTINCT s.id) AS n FROM students s JOIN student_program_enrollments e ON e.student_id = s.id JOIN departments d ON d.id = e.department_id WHERE s.institution_id = '$inst' AND s.deleted_at IS NULL AND e.deleted_at IS NULL AND d.code = 'CSE'")[0].n
  $r = Call $hod GET "/students?page_size=200"
  Assert ($r.meta.pagination.total -eq $cseTotal -and (($r.meta.visibility.scopes -join ',') -eq 'department')) "hod.cse: CSE only ($cseTotal), scopes [department]"
  Assert (-not ($r.data | Where-Object { $_.department_code -ne 'CSE' })) "hod.cse rows are all CSE"
  $r = Call $adv GET "/students?page_size=200"
  Assert ($r.meta.visibility.scopes.Count -eq 0 -and $r.meta.pagination.total -gt 0) "advisor.1: scopes [], $($r.meta.pagination.total) advisee(s)"
  Assert (-not ($r.data | Where-Object { $_.batch_code -ne '2025-BTECH-CSE' -or $_.section_name -ne 'B' })) "advisor.1 sees only 2025-BTECH-CSE section B"
  Call $adv GET "/students?scope=all&page_size=5" | Out-Null
  $r = Call $f2 GET "/students"
  Assert ($r.meta.pagination.total -eq 0 -and $r.meta.visibility.scopes.Count -eq 0) "faculty.2: empty (no offerings / advisees before Phase 09)"
  $r = Call $acct GET "/students?page_size=5"
  Assert ($r.meta.pagination.total -eq $total -and -not $r.meta.visibility.pii) "accountant: every student, pii=false"
  $masked = (Call $acct GET "/students/$($s1.id)").data
  Assert ($masked.aadhaar.StartsWith('*') -and $masked.phone.StartsWith('*')) "accountant sees Aadhaar / phone masked ($($masked.aadhaar))"
  $full = (Call $reg GET "/students/$($s1.id)").data
  Assert (-not $full.aadhaar.StartsWith('*') -and $full.aadhaar.Length -eq 12) "registrar (students:view_pii) sees the Aadhaar"
  Call $f2 GET "/students/$($s1.id)" $null 404 | Out-Null
  Call $hodEce GET "/students/$($s1.id)" $null 404 | Out-Null

  Write-Host "== 2. create"
  $fatherPhone = "+9188$('{0:D8}' -f ($run * 37 % 100000000))"
  $base = @{ first_name = "Verify"; last_name = "Verify$run"; dob = '2008-05-17'; gender = 'F'; category = 'GEN'; admission_quota = 'STATE';
             program_id = $cseProg; admission_year = 2026; admission_date = '2026-08-03'; phone = "+9177$('{0:D8}' -f $run)"; email = "verify$run@students.demo-uni.septronuniverse.in" }
  $new = (Call $reg POST "/students" (Merge $base @{ apaar_id = (Apaar ([long]$run * 101));
          guardians = @(@{ relation = 'father'; name = "Father Verify$run"; phone = $fatherPhone; is_primary = $true }, @{ relation = 'mother'; name = "Mother Verify$run"; phone = "+9166$('{0:D8}' -f $run)" }) }) 201).data
  Assert ($new.student.registration_number -match '^A26BTECHCSE\d{3}$') "registration number from regno:2026:BTECH-CSE ($($new.student.registration_number))"
  Assert ($new.username -eq $new.student.registration_number -and $new.temp_password) "student user = registration number, temporary password"
  $role = Sql "SELECT r.slug FROM user_roles ur JOIN roles r ON r.id = ur.role_id WHERE ur.user_id = '$($new.student.user_id)'"
  Assert (($role | Where-Object { $_.slug -eq 'student' })) "user created with role student"
  Assert ($new.student.batch_code -eq '2026-BTECH-CSE' -and $new.student.term_number -eq 1) "batch 2026 auto-created, term record for the current term"
  Assert ($new.guardian_accounts.Count -eq 2 -and -not ($new.guardian_accounts | Where-Object { $_.reused })) "two guardian users created"
  $father = $new.guardian_accounts | Where-Object { $_.username -like 'p*' } | Select-Object -First 1
  $sib = (Call $reg POST "/students" (Merge $base @{ first_name = "Sibling"; phone = "+9155$('{0:D8}' -f $run)"; email = "sib$run@students.demo-uni.septronuniverse.in";
          guardians = @(@{ relation = 'father'; name = "Father Verify$run"; phone = $fatherPhone; is_primary = $true }) }) 201).data
  Assert ($sib.guardian_accounts[0].reused -and $sib.guardian_accounts.Count -eq 1) "sibling: the guardian user is reused ($($sib.guardian_accounts[0].username))"
  $bad = Call $reg POST "/students" (Merge $base @{ first_name = "BadApaar"; apaar_id = '123456789012' }) 422
  Assert ($bad.error.details.field -eq 'apaar_id') "invalid APAAR checksum -> 422"
  $bad = Call $reg POST "/students" (Merge $base @{ first_name = "BadCat"; category = 'XYZ' }) 422
  Assert ($bad.error.details.field -eq 'category') "category XYZ -> 422 (pack)"

  Write-Host "== 3. self service"
  $me = (Call $stu GET "/students/me").data
  Assert ($me.id -eq $s1.id -and $me.is_self) "student.1 reads the own record"
  Call $stu PUT "/students/me" @{ first_name = 'X' } 422 | Out-Null
  $newPhone = "+9199$('{0:D8}' -f $run)"
  $upd = (Call $stu PUT "/students/me" @{ phone = $newPhone }).data
  Assert ($upd.phone -eq $newPhone) "phone updated by the student"

  Write-Host "== 4. undertakings"
  $freshTmp = $new.temp_password
  $freshPwd = "Fresh@$run" + "x9"
  $first = Invoke-RestMethod -Method Post -Uri "$script:BaseUrl/auth/login" -ContentType 'application/json' -Body (@{ identifier = $new.username; password = $freshTmp } | ConvertTo-Json)
  Call $first.data.access_token POST "/auth/change-password" @{ current_password = $freshTmp; new_password = $freshPwd } | Out-Null
  $fresh = Login $new.username $freshPwd
  $pending = (Call $fresh GET "/students/me/undertakings/pending").data
  Assert ($pending.Count -eq 2 -and ($pending.undertaking_type -contains 'anti_ragging') -and ($pending.undertaking_type -contains 'conduct')) "2 pending undertakings (anti_ragging, conduct) for a fresh student"
  Assert ($pending[0].body -like "*$($new.student.registration_number)*") "the undertaking text is rendered for the student"
  $acc = (Call $fresh POST "/students/me/undertakings" @{ undertaking_type = 'anti_ragging' } 201).data
  Assert ($acc.ip -and $acc.accepted_at) "anti_ragging accepted with ip ($($acc.ip))"
  $gate = Call $fresh POST "/_dev/gates/registration-check" $null 409
  Assert ($gate.error.code -eq 'RULE_VIOLATION' -and $gate.error.details.code -eq 'UNDERTAKING_PENDING' -and ($gate.error.details.pending -contains 'conduct')) "registration gate -> 409 UNDERTAKING_PENDING (conduct)"
  Call $fresh POST "/students/me/undertakings" @{ undertaking_type = 'conduct' } 201 | Out-Null
  Call $fresh POST "/_dev/gates/registration-check" | Out-Null

  Write-Host "== 5. guardians"
  $wards = (Call $par GET "/guardians/me/wards").data
  Assert ($wards.Count -eq 1 -and $wards[0].student_id -eq $s1.id) "parent.1 sees 1 ward (student.1)"
  Call $par GET "/guardians/me/wards/$($s1.id)/dashboard" | Out-Null
  Call $stu PUT "/students/$($s1.id)/guardian-consent" @{ guardian_portal_consent = $false } | Out-Null
  Assert (((Call $par GET "/guardians/me/wards").data).Count -eq 0) "consent off -> parent.1 sees 0 wards"
  Call $par GET "/students/$($s1.id)" $null 404 | Out-Null
  Call $par GET "/guardians/me/wards/$($s1.id)/dashboard" $null 404 | Out-Null
  Assert (((Call $noc GET "/guardians/me/wards").data).Count -eq 0 -and (Call $noc GET "/students").meta.pagination.total -eq 0) "parent.noconsent sees nothing"
  Call $stu PUT "/students/$($s1.id)/guardian-consent" @{ guardian_portal_consent = $true } | Out-Null

  Write-Host "== 6. holds"
  $libHold = (Call $lib POST "/students/$($s1.id)/holds" @{ hold_type = 'library'; reason = "verify ${run}: overdue books" } 201).data
  $allHold = (Call $reg POST "/students/$($s1.id)/holds" @{ hold_type = 'all'; reason = "verify ${run}: document verification pending" } 201).data
  Assert ($libHold.is_open -and $allHold.hold_type -eq 'all') "library hold (librarian) and all hold (registrar) placed"
  Call $lib POST "/students/$($s1.id)/holds" @{ hold_type = 'exam'; reason = "verify ${run}: not mine" } 403 | Out-Null
  $blocked = Call $reg POST "/_dev/gates/registration-check?student_id=$($s1.id)" $null 409
  Assert ($blocked.error.code -eq 'HOLD_BLOCKED' -and $blocked.error.details.hold_type -eq 'all') "registration gate -> 409 HOLD_BLOCKED (all hold)"
  Call $lib POST "/student-holds/$($allHold.id)/release" @{ reason = 'not allowed' } 403 | Out-Null
  $rel = (Call $reg POST "/student-holds/$($allHold.id)/release" @{ reason = "verify ${run}: documents verified" }).data
  Assert (-not $rel.is_open -and $rel.release_reason -eq "verify ${run}: documents verified") "registrar releases the all hold with a reason"
  $holds = (Call $stu GET "/students/$($s1.id)/holds").data
  Assert (($holds | Where-Object { $_.id -eq $allHold.id -and $_.released_at -and $_.release_reason })) "GET holds shows the released hold with its reason (student view)"
  Call $lib POST "/student-holds/$($libHold.id)/release" @{ reason = "verify ${run}: books returned" } | Out-Null
  $notified = WaitFor "hold.released notification for student.1" { (Sql "SELECT COUNT(*) AS n FROM notifications WHERE user_id = '$($s1.user_id)' AND event_type = 'hold.released' AND created_at > NOW() - INTERVAL '10 minutes'")[0].n -ge 1 } 90
  Assert $notified "student.1 notified (hold.released, in-app)"
  Call $reg POST "/_dev/gates/registration-check?student_id=$($s1.id)" $null 409 | Out-Null  # conduct still pending for student.1 (seed)

  Write-Host "== 7. promotion"
  $pre = (Call $reg POST "/batches/$b2024/promote?dry_run=true" @{ to_term_number = 6 }).data
  Assert ($pre.detained.Count -eq 2 -and $pre.promoted.Count -eq 198 -and $pre.on_break.Count -eq 2) "dry run: 198 promoted, 2 detained (5 backlogs > 4), 2 on break"
  Assert (($pre.detained | Where-Object { $_.backlogs -eq 5 }).Count -eq 2 -and $pre.to_term.name -eq 'Even Semester') "detained rows carry their backlogs; target term = the next term ($($pre.to_term.name))"
  $q = Call $reg POST "/batches/$b2024/promote" @{ to_term_number = 6 } 202
  $job = Job $reg $q.data.job_id
  Assert ($job.status -eq 'succeeded' -and $job.result.promoted -eq 198 -and $job.result.detained -eq 2) "students.promote job: 198 promoted, 2 detained"
  $t6 = (Sql "SELECT COUNT(*) AS n FROM student_term_records r JOIN student_program_enrollments e ON e.id = r.student_program_enrollment_id WHERE e.batch_id = '$b2024' AND r.term_number = 6")[0].n
  $batch = (Sql "SELECT current_term_number AS t FROM batches WHERE id = '$b2024'")[0].t
  $det = (Sql "SELECT COUNT(*) AS n FROM student_program_enrollments WHERE batch_id = '$b2024' AND status = 'detained'")[0].n
  $ev = (Sql "SELECT COUNT(*) AS n FROM domain_events WHERE institution_id = '$inst' AND event_type = 'student.detained' AND created_at > NOW() - INTERVAL '15 minutes'")[0].n
  Assert ($t6 -eq 198 -and $batch -eq 6 -and $det -eq 2 -and $ev -ge 2) "term-6 records 198, batch at term 6, 2 detained enrolments, student.detained events ($ev)"
  $again = (Call $reg POST "/batches/$b2024/promote?dry_run=true" @{ to_term_number = 6 }).data
  Assert ($again.promoted.Count -eq 0 -and $again.already_promoted -eq 198 -and $again.detained.Count -eq 0) "re-run preview: nothing new (198 already promoted)"
  $job2 = Job $reg (Call $reg POST "/batches/$b2024/promote" @{ to_term_number = 6 } 202).data.job_id
  $t6b = (Sql "SELECT COUNT(*) AS n FROM student_term_records r JOIN student_program_enrollments e ON e.id = r.student_program_enrollment_id WHERE e.batch_id = '$b2024' AND r.term_number = 6")[0].n
  Assert ($job2.status -eq 'succeeded' -and $t6b -eq 198) "re-run job is idempotent (no duplicate term records)"

  Write-Host "== 8. NEP exit / re-entry"
  $t3 = Marker 'DEMO0210'
  $x = Call $reg POST "/enrollments/$($t3.enrollment_id)/exit" @{ exit_award = 'diploma' } 409
  Assert ($x.error.code -eq 'RULE_VIOLATION' -and $x.error.details.term_number -eq 3) "term 3 is not an exit point -> 409"
  $brkStudent = Marker 'DEMO0201'
  Call $reg POST "/enrollments/$($brkStudent.enrollment_id)/exit" @{ exit_award = 'certificate' } 409 | Out-Null
  $ex = (Call $reg POST "/enrollments/$($brkStudent.enrollment_id)/exit" @{ exit_award = 'diploma'; reason = "verify $run" }).data
  Assert ($ex.status -eq 'exited_early' -and $ex.exit_award -eq 'diploma') "term 4 with 84 credits -> exited_early with a diploma"
  $exEv = (Sql "SELECT COUNT(*) AS n FROM domain_events WHERE event_type = 'student.exited' AND aggregate_id = '$($brkStudent.id)'")[0].n
  Assert ($exEv -ge 1 -and (Call $reg GET "/students/$($brkStudent.id)").data.status -eq 'exited') "student.exited emitted, student exited"
  $re = (Call $reg POST "/students/$($brkStudent.id)/reentry" @{ program_id = $cseProg; batch_id = $b2025; entry_term_number = 3 } 201).data
  Assert ($re.entry_type -eq 'exit_reentry' -and $re.status -eq 'active' -and [double]$re.credits_earned -eq 84) "re-entry: new exit_reentry enrolment carrying 84 credits"
  Call $reg POST "/students/$($brkStudent.id)/reentry" @{ program_id = $cseProg; batch_id = $b2025; entry_term_number = 3 } 409 | Out-Null
  $open = (Sql "SELECT COUNT(*) AS n FROM student_program_enrollments WHERE student_id = '$($brkStudent.id)' AND status IN ('active','break','detained')")[0].n
  Assert ($open -eq 1) "only one open enrolment (one_active_enrollment)"
  $carried = (Sql "SELECT COUNT(*) AS n FROM credit_transfers WHERE student_program_enrollment_id = '$($re.id)' AND source = 'internal_prior' AND status = 'approved'")[0].n
  Assert ($carried -ge 1) "prior credits carried as internal_prior credit transfers"

  Write-Host "== 9. standing"
  $st = (Call $reg POST "/_dev/students/$($std.id)/term-results" @{ terms = @(@{ term_number = 3; sgpa = 6.2; cgpa = 6.0 }, @{ term_number = 4; sgpa = 4.6; cgpa = 4.8 }) }).data
  Assert ($st.standing -eq 'probation') "CGPA 4.8 (< 5.0, 1 term) -> probation"
  $sr = (Call $reg GET "/students/$($std.id)/standing").data
  Assert ($sr.standing -eq 'probation' -and ($sr.history | Where-Object { $_.to_standing -eq 'probation' }) -and $sr.rules.Count -ge 3) "GET standing: probation with history and the rules"
  $dis = (Call $reg POST "/_dev/students/$($std.id)/term-results" @{ terms = @(@{ term_number = 3; cgpa = 3.9 }, @{ term_number = 4; sgpa = 3.5; cgpa = 3.8 }) }).data
  Assert ($dis.standing -eq 'dismissal') "CGPA < 4.0 for 2 terms -> dismissal"
  $dh = (Call $reg GET "/students/$($std.id)/holds").data | Where-Object { $_.hold_type -eq 'all' -and $_.is_open -and $_.source_type -eq 'standing' }
  Assert ($dh) "dismissal placed an all hold (source standing)"

  Write-Host "== 10. transfer"
  $tr = (Call $reg POST "/students/$($trf.id)/transfers" @{ transfer_type = 'migration_out'; reason = "verify $run"; to_ref = @{ institution = 'Other University' } } 201).data
  Assert ($tr.status -eq 'requested' -and $tr.workflow_instance_id -and $tr.can_act) "migration_out requested, workflow students.transfer waiting for the registrar"
  Call $reg POST "/student-transfers/$($tr.id)/complete" $null 409 | Out-Null
  $t1 = (Call $reg POST "/student-transfers/$($tr.id)/approve" @{ comment = 'dues clear' }).data
  Assert ($t1.status -eq 'dues_check' -and $t1.current_step -eq 2) "registrar approval -> dues_check, step 2 (principal)"
  $t2 = (Call $vc POST "/student-transfers/$($tr.id)/approve").data
  Assert ($t2.status -eq 'approved' -and $t2.workflow_status -eq 'approved') "principal approval -> approved"
  $done = (Call $reg POST "/student-transfers/$($tr.id)/complete" @{}).data
  Assert ($done.status -eq 'completed' -and $done.tc_no -like 'TC/*' -and $done.migration_certificate_no -like 'MIG/*') "completed: TC $($done.tc_no), migration certificate $($done.migration_certificate_no)"
  Assert ((Call $reg GET "/students/$($trf.id)").data.status -eq 'transferred') "student transferred"

  Write-Host "== 11. credit transfers"
  $ct = (Call $stu POST "/credit-transfers" @{ source = 'nptel'; source_course_code = "noc26-$run"; source_title = 'Deep Learning'; source_institution = 'NPTEL'; credits = 4; source_score_pct = 85 } 201).data
  Assert ($ct.status -eq 'submitted' -and $ct.workflow_instance_id) "student.1 submitted an NPTEL transfer (4 credits)"
  $pdf = Join-Path $tmp "cert.pdf"
  [System.IO.File]::WriteAllBytes($pdf, [System.Text.Encoding]::ASCII.GetBytes("%PDF-1.4`n1 0 obj<<>>endobj`ntrailer<<>>`n%%EOF`n"))
  $withCert = (Upload $stu "/credit-transfers/$($ct.id)/certificate" $pdf).data
  Assert ($withCert.certificate_url) "certificate attached"
  $course = (Sql "SELECT c.id FROM courses c JOIN program_regulations pr ON pr.regulation_id = c.regulation_id WHERE pr.id = (SELECT program_regulation_id FROM student_program_enrollments WHERE id = '$e1') AND c.code = 'CS308'")[0].id
  Call $reg POST "/credit-transfers/$($ct.id)/approve" $null 409 | Out-Null
  $hv = (Call $hod GET "/credit-transfers?status=submitted").data | Where-Object { $_.id -eq $ct.id }
  Assert ($hv.can_act) "hod.cse can act on the transfer (step 1)"
  $ver = (Call $hod POST "/credit-transfers/$($ct.id)/verify" @{ equivalent_course_id = $course; comment = 'maps to CS308' }).data
  Assert ($ver.status -eq 'verified' -and $ver.equivalent_course -like 'CS308*') "hod.cse verified with an equivalent course"
  $app = (Call $reg POST "/credit-transfers/$($ct.id)/approve").data
  Assert ($app.status -eq 'approved' -and $app.approved_at -and $app.letter_grade -eq 'A+') "registrar approved (letter grade A+ from the MOOC map; result row in Phase 15)"
  Call $stu POST "/credit-transfers" @{ source = 'swayam'; source_title = "Ethics $run"; credits = 4 } 201 | Out-Null
  Call $stu POST "/credit-transfers" @{ source = 'coursera'; source_title = "Statistics $run"; credits = 4 } 201 | Out-Null
  $cap = Call $stu POST "/credit-transfers" @{ source = 'nptel'; source_title = "One too many $run"; credits = 4 } 422
  Assert ($cap.error.details.cap -eq 12) "4th MOOC transfer beyond mooc_max_credits=12 -> 422"
  Assert (((Call $stu GET "/credit-transfers/me").data).Count -eq 3) "/credit-transfers/me lists the student's own 3"

  Write-Host "== 12. bulk import / export"
  $csv = Join-Path $tmp "import.csv"
  $lines = @("registration_number,first_name,last_name,dob,gender,category,quota,program_code,batch_code,section,entry_type,phone,email,guardian_name,guardian_relation,guardian_phone,apaar_id")
  for ($i = 1; $i -le 50; $i++) {
    $prog = 'BTECH-CSE'; $dob = '2008-02-11'; $cat = 'OBC-NCL'
    if ($i -eq 7) { $prog = 'NOPE-PROG' }
    if ($i -eq 19) { $dob = '2008-13-45' }
    if ($i -eq 33) { $cat = 'XYZ' }
    $lines += ",Import$i,Verify$run,$dob,$(if ($i % 2) { 'M' } else { 'F' }),$cat,STATE,$prog,2026-BTECH-CSE,A,regular,+9144$('{0:D4}' -f ($run % 10000))$('{0:D4}' -f $i),imp$run.$i@students.demo-uni.septronuniverse.in,Parent $i,father,,$(Apaar ([long]$run * 1000 + $i))"
  }
  Set-Content -Path $csv -Value $lines -Encoding UTF8
  $dry = (Upload $reg "/students/bulk-import?dry_run=true" $csv).data
  Assert ($dry.dry_run -and $dry.total -eq 50 -and $dry.succeeded -eq 47 -and $dry.failed.Count -eq 3) "dry run: 50 rows, 47 valid, 3 failed (rows $(($dry.failed.row) -join ', '))"
  $queued = (Upload $reg "/students/bulk-import" $csv).data
  $ij = Job $reg $queued.job_id
  Assert ($ij.status -eq 'succeeded' -and $ij.result.succeeded -eq 47 -and $ij.result.failed.Count -eq 3) "import job: 47 created, 3 failed"
  $xa = Join-Path $tmp "acct.xlsx"; $xr = Join-Path $tmp "reg.xlsx"
  Download $acct "/students/export?q=Verify$run" $xa
  Download $reg "/students/export?q=Verify$run" $xr
  $ra = & $Python scripts/verify/_xlsx.py $xa 3 | ConvertFrom-Json
  $rr = & $Python scripts/verify/_xlsx.py $xr 3 | ConvertFrom-Json
  $pi = [array]::IndexOf($ra[0], 'Phone')
  Assert (($ra[0] -notcontains 'Aadhaar') -and $ra[1][$pi].StartsWith('*')) "accountant export: PII masked, no Aadhaar column"
  Assert (($rr[0] -contains 'Aadhaar') -and -not $rr[1][$pi].StartsWith('*')) "registrar export: unmasked + Aadhaar column"

  Write-Host "== 13. ID cards"
  $idq = Call $reg POST "/students/id-cards" @{ student_ids = @($s1.id, $new.student.id) } 202
  $idj = Job $reg $idq.data.job_id
  Assert ($idj.status -eq 'succeeded' -and $idj.result.count -eq 2 -and $idj.result.result_url) "id-cards job: 2 cards in a ZIP"
  $zip = Join-Path $tmp "cards.zip"
  Invoke-WebRequest -Uri ("http://localhost:8000" + ($idj.result.result_url -replace '^https?://[^/]+', '')) -OutFile $zip | Out-Null
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $entries = [System.IO.Compression.ZipFile]::OpenRead($zip).Entries.Name
  Assert ($entries.Count -eq 2 -and ($entries -contains "$($s1.registration_number).pdf")) "ZIP holds one PDF per student"
  $card = (Call $stu GET "/students/me/id-card").data
  $v = (Call $null GET "/verify/$($card.token)").data
  Assert ($v.valid -and $v.holder_name -like 'Student*' -and $v.registration_number -eq $s1.registration_number -and $v.status -eq 'active') "public /verify: name, registration number, status"
  $v2 = (Call $null GET "/verify/$($idj.result.tokens.($new.student.id))").data
  Assert ($v2.valid -and $v2.registration_number -eq $new.student.registration_number) "job token verifies the new student"
  $bad = (Call $null GET "/verify/$($card.token)x").data
  Assert (-not $bad.valid) "tampered token -> valid=false"
  Download $stu "/students/me/id-card.pdf" (Join-Path $tmp "me.pdf")

  Write-Host "== 14. auditor"
  foreach ($p in '/students', "/students/$($s1.id)", "/students/$($s1.id)/holds", '/student-holds', '/credit-transfers', '/student-transfers') { Call $auditor GET $p | Out-Null }
  Call $auditor POST "/students" (Merge $base @{ first_name = 'Nope' }) 403 | Out-Null
  Call $auditor POST "/students/$($s1.id)/holds" @{ hold_type = 'all'; reason = 'audit' } 403 | Out-Null
  Call $auditor PUT "/students/$($s1.id)" @{ first_name = 'Nope' } 403 | Out-Null

  Summary "07_students"
}
finally {
  if ($s1) { try { SqlWrite "UPDATE students SET guardian_portal_consent = TRUE WHERE id = '$($s1.id)'" } catch { Write-Host "consent not restored: $_" } }
  Pop-Location
}
