# API verification — Phase 08 admissions (Prompts/08_Phase08_Admissions.md §08.11).
#
# Run from backend/ with the API up, Redis and a Celery worker (merit generation, the allotment run and the CSV import
# are jobs; the outbox relay dispatches the notifications):
#   .\scripts\verify\08_admissions.ps1 [-BaseUrl http://localhost:8000/api/v1]
#
# Seed first: python scripts/seed_demo_institution.py --type university --only admissions   (base → … → students → admissions)
#
# Roles: admissions (admissions_officer), registrar (MFA in the demo tenant), inst.admin, hod.cse, college.admin.b,
# student.1, public, and applicant accounts created during the run (public start with OTP; counselling-import rows with
# a phone get an account whose password the script resets).
# Re-runnable: step 0 archives the cycles of earlier runs; every run works in its own cycles v08-<run> / v08i-<run>.
#
# Documented deviations from the prompt text (see PROGRESS.md decisions log, Phase 08):
#  * the application / admission fee is a mock-adapter payment kept in applicants.documents._payments until Phase 12
#    ships invoices; POST /_dev/fees/pay/{ref} is the payment event; paying moves submitted → fee_paid →
#    under_verification in one go;
#  * seat_matrix.filled counts held seats from the allotment on (so concurrent runs cannot over-allot); admitting an
#    allotted applicant does not count the seat twice;
#  * a round's is_final flag lives in admission_cycles.de_reservation_policy.final_round_number (no DDL column);
#  * the institution scope tab is called "all" in meta.visibility.
#  0. reset (archive earlier v08 cycles)
#  1. cycles: student.1 → 403, hod.cse → 200
#  2. cycle with Σ seats ≠ intake → open 409; fix → open; public cycle info
#  3. public start (OTP) → applicant account; profile + preferences + documents; submit without marksheet_12 → 422;
#     add → submitted (payment payer_type=applicant); payment event → under_verification
#  4. verification: verify 2, reject 1 → doc_rejected; resubmit → under_verification; verify → verified; timeline;
#     notifications
#  5. strict eligibility: second applicant below the B.Tech minimum → 422 NOT_ELIGIBLE (B.Tech only); MBA only → 200
#  6. merit: fixtures via the counselling CSV import (10 verified); generate (job) → ranks, dob tie-break, category
#     ranks; publish → public masked list; regenerate → previous superseded
#  7. round 1: choice filling; dry run (OBC applicant on a GEN seat, PwD on PWD, lateral on LATERAL); two concurrent
#     real runs → 6 allotments, filled ≤ seats
#  8. decisions: accept + pay → accepted; decline releases; float; freeze; lapse after the deadline
#  9. round 2 final: float upgrade, de-reservation SC → GEN (conversions) and the converted seat filled
# 10. admit: before fee → 409; after → 201 (registration number, user, category/quota copied); again → 409; lateral admit
# 11. counselling CSV import (100 rows, 5 bad): dry run report; apply job → 95, 50 allotted (source counselling_import)
# 12. withdrawal: before allotment → fee − processing fee (refund workflow); after acceptance → 50 % of the admission fee
# 13. enquiries: public form → assign → convert → funnel
# 14. visibility: college.admin.b only college-B preferences; hod.cse CSE preferences read-only, PII masked
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
function WaitFor($label, [scriptblock]$probe, $seconds = 90) {
  for ($i = 0; $i -lt $seconds; $i++) { $v = & $probe; if ($v) { return $v }; Start-Sleep -Seconds 1 }
  throw "timed out waiting for: $label"
}
function Job($token, $jobId) {
  WaitFor "job $jobId" { $j = (Call $token GET "/jobs/$jobId").data; if ($j.status -in @('succeeded', 'failed', 'cancelled')) { $j } } 180
}
function Upload($token, $path, $file, $fields = @{}, $expect = 200, $query = "") {
  $form = @{ file = Get-Item $file }
  foreach ($k in $fields.Keys) { $form[$k] = $fields[$k] }
  $r = Invoke-WebRequest -Method Post -Uri "$script:BaseUrl$path$query" -Headers @{ Authorization = "Bearer $token" } -Form $form -SkipHttpErrorCheck
  if ($r.StatusCode -ne $expect) { throw "POST $path expected $expect got $($r.StatusCode): $($r.Content)" }
  $script:Checks++
  Write-Host "OK POST $path (multipart) -> $($r.StatusCode)"
  return ($r.Content | ConvertFrom-Json)
}

$run = Get-Random -Minimum 10000 -Maximum 99999
$tmp = Join-Path ([IO.Path]::GetTempPath()) "v08-$run"
New-Item -ItemType Directory -Force $tmp | Out-Null
$pdf = Join-Path $tmp "doc.pdf"
Set-Content -Path $pdf -Value "%PDF-1.4`n1 0 obj << /Type /Catalog >> endobj`ntrailer << /Root 1 0 R >>`n%%EOF" -NoNewline
$png = Join-Path $tmp "photo.png"
[IO.File]::WriteAllBytes($png, [Convert]::FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="))

# ---- 0. reset -------------------------------------------------------------------------------------------------------------
Write-Host "`n== 0. reset" -ForegroundColor Cyan
SqlWrite "UPDATE admission_cycles SET status = 'archived' WHERE slug LIKE 'v08-%' OR slug LIKE 'v08i-%'"
$officer = Login 'admissions' (Get-DemoPassword 'admissions_officer')
$admin = Login 'inst.admin' (Get-DemoPassword 'institution_admin')
$registrar = Login-Mfa 'registrar' 'registrar'
$hod = Login 'hod.cse' (Get-DemoPassword 'hod')
$collegeB = Login 'college.admin.b' (Get-DemoPassword 'college_admin')
$student = Login 'student.1' (Get-DemoPassword 'student')
$slug = (Sql "SELECT i.slug FROM institutions i JOIN users u ON u.institution_id = i.id WHERE u.username = 'admissions'")[0].slug
$year = (Sql "SELECT t.academic_year_id AS id FROM academic_terms t JOIN institutions i ON i.id = t.institution_id WHERE i.slug = '$slug' AND t.college_id IS NULL AND t.is_current AND t.deleted_at IS NULL")[0].id
$progs = @{}
foreach ($p in (Sql "SELECT p.code, p.id, p.college_id FROM programs p JOIN institutions i ON i.id = p.institution_id WHERE i.slug = '$slug' AND p.code IN ('BTECH-CSE','MBA') AND p.deleted_at IS NULL")) { $progs[$p.code] = $p }
$BT = $progs['BTECH-CSE'].id; $MBA = $progs['MBA'].id

# ---- 1. cycles read ------------------------------------------------------------------------------------------------------
Write-Host "`n== 1. cycles per role" -ForegroundColor Cyan
Call $student GET "/admissions/cycles" $null 403 | Out-Null
$list = Call $hod GET "/admissions/cycles"
Assert (@($list.data | Where-Object slug -eq 'ug-2026').Count -eq 1) "hod.cse reads the seeded UG 2026 cycle"

# ---- 2. cycle, seat matrix, open -----------------------------------------------------------------------------------------
Write-Host "`n== 2. cycle + seat matrix" -ForegroundColor Cyan
$cslug = "v08-$run"
$opens = (Get-Date).ToUniversalTime().AddDays(-1).ToString("o"); $closes = (Get-Date).ToUniversalTime().AddDays(30).ToString("o")
$cycle = (Call $officer POST "/admissions/cycles" @{
  name = "Verify UG $run"; slug = $cslug; level = "ug"; academic_year_id = $year; application_fee_paise = 100000
  opens_at = $opens; closes_at = $closes
  form_config = @{ max_preferences = 3; strict_eligibility = $true; admission_fee_paise = 1000000; refund_policy = @{ processing_fee_paise = 50000; after_acceptance_pct = 50 } }
  de_reservation_policy = @{ convert = @{ SC = "GEN"; ST = "GEN" } }
} 201).data
$CID = $cycle.id
Call $officer POST "/admissions/cycles" @{ name = "dup"; slug = $cslug; level = "ug"; academic_year_id = $year } 409 | Out-Null
$formula = @(@{ field = "entrance_score"; weight = 60; max = 300 }, @{ field = "qualifying_pct"; weight = 40 })
Call $officer PUT "/admissions/cycles/$CID/programs" @{ programs = @(
  @{ program_id = $BT; intake = 5; lateral_intake = 1; entrance_source = "jee"; merit_formula = $formula; tie_break = @("entrance_score", "dob_asc", "submitted_at")
     eligibility_rules = @{ min_qualifying_pct = 60; category_relaxation_pct = @{ SC = 5 } } },
  @{ program_id = $MBA; intake = 2; entrance_source = "cat"; merit_formula = $formula; eligibility_rules = @{ min_qualifying_pct = 50 } }
) } | Out-Null
$rows = @(
  @{ program_id = $BT; quota = "STATE"; category = "GEN"; seats = 2 }, @{ program_id = $BT; quota = "STATE"; category = "OBC-NCL"; seats = 1 },
  @{ program_id = $BT; quota = "STATE"; category = "SC"; seats = 1 }, @{ program_id = $BT; quota = "PWD"; category = "GEN"; seats = 1 },
  @{ program_id = $MBA; quota = "STATE"; category = "GEN"; seats = 1 }, @{ program_id = $MBA; quota = "STATE"; category = "SC"; seats = 1 }
)
Call $officer PUT "/admissions/cycles/$CID/seat-matrix" @{ rows = $rows } | Out-Null
$r = Call $officer POST "/admissions/cycles/$CID/status" @{ status = "open" } 409
Assert ($r.error.details.reason -eq 'seat_matrix_unbalanced') "open refused: B.Tech Σ seats 5 ≠ intake 5 + lateral 1"
Call $officer PUT "/admissions/cycles/$CID/seat-matrix" @{ rows = @(@{ program_id = $BT; quota = "STATE"; category = "XX"; seats = 1 }) } 422 | Out-Null
$rows += @{ program_id = $BT; quota = "LATERAL"; category = "GEN"; seats = 1 }
$ss = (Call $officer PUT "/admissions/cycles/$CID/seat-matrix" @{ rows = $rows }).data
Assert (@($ss.programs | Where-Object { -not $_.balanced }).Count -eq 0) "seat matrix balanced (Σ = intake + lateral)"
$cycle = (Call $officer POST "/admissions/cycles/$CID/status" @{ status = "open" }).data
Assert ($cycle.status -eq 'open') "cycle open"
$pub = (Call $null GET "/public/admissions/cycles/$($cslug)?institution=$slug").data
Assert ($pub.is_open -and $pub.application_fee_paise -eq 100000 -and @($pub.programs).Count -eq 2) "public cycle info: programmes, fee, window"
Assert ((@((Call $null GET "/public/admissions/cycles?institution=$slug").data) | Where-Object slug -eq $cslug).Count -eq 1) "public listing shows the cycle"

# ---- 3. public application ------------------------------------------------------------------------------------------------
Write-Host "`n== 3. public application" -ForegroundColor Cyan
function Start-Applicant($first, $phone, $pwd) {
  $o = (Call $null POST "/public/admissions/$($cslug)/start?institution=$slug" @{ first_name = $first; last_name = "V$run"; phone = $phone; password = $pwd }).data
  Assert ($o.otp_sent -and $o.dev_otp) "OTP sent to $first (mock SMS)"
  Call $null POST "/public/admissions/$($cslug)/start?institution=$slug" @{ first_name = $first; phone = $phone; password = $pwd; otp_code = "000000" } 422 | Out-Null
  $o = (Call $null POST "/public/admissions/$($cslug)/start?institution=$slug" @{ first_name = $first; last_name = "V$run"; phone = $phone; password = $pwd; otp_code = $o.dev_otp }).data
  Assert ($o.application_number -and $o.username -eq $o.application_number) "applicant account $($o.username)"
  return $o
}
$pwdA = "Apply@$run!x"
$a1 = Start-Applicant "Asha" "+9177$($run)01" $pwdA
$tA1 = Login $a1.username $pwdA
Call $tA1 GET "/admissions/applicants" $null 403 | Out-Null
Call $tA1 PUT "/applicants/me" @{ dob = "2008-03-04"; gender = "F"; category = "OBC-NCL"; quota_claimed = "STATE"; domicile_state = "Karnataka"
  contact = @{ email = "asha$run@example.in"; guardian_name = "Ravi"; guardian_relation = "father"; guardian_phone = "+9177$($run)02" }
  entrance = @{ exam = "jee"; score = 200; max_score = 300 }; qualifying_exams = @(@{ level = "12"; board = "CBSE"; year = 2026; pct = 75; subjects = @("PHY", "MAT") }) } | Out-Null
$me = (Call $tA1 PUT "/applicants/me/preferences" @{ preferences = @(@{ program_id = $BT }, @{ program_id = $MBA }) }).data
Assert (@($me.preferences).Count -eq 2 -and $me.preferences[0].program_code -eq 'BTECH-CSE') "2 preferences in priority order"
Call $tA1 PUT "/applicants/me/preferences" @{ preferences = @(@{ program_id = $BT }, @{ program_id = $MBA }, @{ program_id = $BT }, @{ program_id = $MBA }) } 422 | Out-Null
Upload $tA1 "/applicants/me/documents" $png @{ doc_type = "photo" } | Out-Null
Upload $tA1 "/applicants/me/documents" $pdf @{ doc_type = "marksheet_10" } | Out-Null
$r = Call $tA1 POST "/applicants/me/submit" $null 422
Assert (@($r.error.details.missing) -contains 'marksheet_12') "submit without marksheet_12 → 422 listing it"
Upload $tA1 "/applicants/me/documents" $pdf @{ doc_type = "marksheet_12" } | Out-Null
$me = (Call $tA1 POST "/applicants/me/submit").data
Assert ($me.status -eq 'submitted' -and $me.payments.application.status -eq 'pending' -and $me.payments.application.payer_type -eq 'applicant' -and $me.payments.application.amount_paise -eq 100000) "submitted; application-fee payment (payer_type=applicant) pending"
Call $tA1 PUT "/applicants/me" @{ first_name = "Changed" } 409 | Out-Null
$paid = (Call $officer POST "/_dev/fees/pay/$($me.payments.application.ref)").data
Assert ($paid.applicant_status -eq 'under_verification') "payment event → fee_paid → under_verification"

# ---- 4. verification -------------------------------------------------------------------------------------------------------
Write-Host "`n== 4. verification" -ForegroundColor Cyan
$A1 = $me.id
$q = (Call $officer GET "/admissions/verification-queue?cycle_id=$CID").data
Assert (@($q | Where-Object id -eq $A1).Count -eq 1) "applicant in the verification queue"
Call $officer POST "/admissions/applicants/$A1/documents/photo/verify" @{ status = "verified" } | Out-Null
Call $officer POST "/admissions/applicants/$A1/documents/marksheet_10/verify" @{ status = "verified" } | Out-Null
$x = (Call $officer POST "/admissions/applicants/$A1/documents/marksheet_12/verify" @{ status = "rejected"; remarks = "Blurred scan" }).data
Assert ($x.status -eq 'doc_rejected') "rejected document → doc_rejected"
Call $hod POST "/admissions/applicants/$A1/documents/photo/verify" @{ status = "verified" } 403 | Out-Null
$me = (Upload $tA1 "/applicants/me/documents" $pdf @{ doc_type = "marksheet_12" }).data
Assert ($me.status -eq 'under_verification') "resubmitted → under_verification"
$x = (Call $officer POST "/admissions/applicants/$A1/documents/marksheet_12/verify" @{ status = "verified"; remarks = "OK" }).data
Assert ($x.status -eq 'verified') "all documents verified → verified"
$tl = (Call $tA1 GET "/applicants/me/timeline").data
$seen = @($tl | Where-Object status_to | ForEach-Object status_to)
foreach ($s in @('submitted', 'fee_paid', 'under_verification', 'doc_rejected', 'verified')) { Assert ($seen -contains $s) "timeline has $s" }
$uid = (Sql "SELECT user_id FROM applicants WHERE id = '$A1'")[0].user_id
WaitFor "applicant notifications" { (Sql "SELECT count(*) AS n FROM notifications WHERE user_id = '$uid' AND event_type = 'admissions.status_changed'")[0].n -ge 3 } | Out-Null
Assert $true "status notifications delivered to the applicant (in-app)"

# ---- 5. strict eligibility ---------------------------------------------------------------------------------------------------
Write-Host "`n== 5. eligibility" -ForegroundColor Cyan
$a2 = Start-Applicant "Bala" "+9177$($run)03" $pwdA
$tA2 = Login $a2.username $pwdA
Call $tA2 PUT "/applicants/me" @{ dob = "2008-05-06"; gender = "M"; category = "GEN"; qualifying_exams = @(@{ level = "12"; pct = 55 }); entrance = @{ score = 120 } } | Out-Null
Call $tA2 PUT "/applicants/me/preferences" @{ preferences = @(@{ program_id = $BT }, @{ program_id = $MBA }) } | Out-Null
foreach ($d in @(@{ t = 'photo'; f = $png }, @{ t = 'marksheet_10'; f = $pdf }, @{ t = 'marksheet_12'; f = $pdf })) { Upload $tA2 "/applicants/me/documents" $d.f @{ doc_type = $d.t } | Out-Null }
$r = Call $tA2 POST "/applicants/me/submit" $null 422
Assert ($r.error.code -eq 'RULE_VIOLATION' -and $r.error.details.reason -eq 'NOT_ELIGIBLE' -and @($r.error.details.preferences).Count -eq 1 -and $r.error.details.preferences[0].program_code -eq 'BTECH-CSE') "NOT_ELIGIBLE names B.Tech only (MBA allowed)"
Call $tA2 PUT "/applicants/me/preferences" @{ preferences = @(@{ program_id = $MBA }) } | Out-Null
$me2 = (Call $tA2 POST "/applicants/me/submit").data
Assert ($me2.status -eq 'submitted') "MBA-only application submitted"

# withdrawal before allotment (step 12a) — keeps A1 out of the merit pool
$w = (Call $tA1 POST "/applicants/me/withdraw" @{ reason = "Joining another institute" }).data
Assert ($w.applicant.status -eq 'withdrawn' -and $w.refund.amount_paise -eq 50000 -and $w.refund.workflow_instance_id) "12a. withdrawal before allotment → refund ₹1,000 − ₹500 processing (workflow admissions.refund)"

# ---- 6. merit --------------------------------------------------------------------------------------------------------------
Write-Host "`n== 6. merit lists" -ForegroundColor Cyan
$fx = @(
  @('X1', 'GEN', 290, 'N', 'BTECH-CSE', 'regular', '2007-06-01'), @('X2', 'OBC-NCL', 280, 'N', 'BTECH-CSE', 'regular', '2007-06-01'),
  @('X3', 'OBC-NCL', 270, 'N', 'BTECH-CSE', 'regular', '2007-06-01'), @('X5', 'GEN', 260, 'N', 'BTECH-CSE', 'regular', '2007-06-01'),
  @('X6', 'GEN', 200, 'N', 'BTECH-CSE', 'lateral', '2004-06-01'), @('X4', 'GEN', 150, 'Y', 'BTECH-CSE', 'regular', '2007-06-01'),
  @('X7', 'GEN', 100, 'N', 'BTECH-CSE', 'regular', '2007-06-01'), @('X8', 'GEN', 90, 'N', 'BTECH-CSE', 'regular', '2007-06-01'),
  @('X9', 'GEN', 50, 'N', 'BTECH-CSE', 'regular', '2007-01-01'), @('X10', 'GEN', 50, 'N', 'BTECH-CSE', 'regular', '2008-01-01')
)
$csv = @("Roll No,Candidate,last_name,dob,gender,category,quota,is_pwd,phone,email,Score,entrance_rank,qualifying_pct,Course,entry_type")
$i = 10
foreach ($f in $fx) { $i++; $csv += "V$run$($f[0]),$($f[0]),Fixture,$($f[6]),M,$($f[1]),STATE,$($f[3]),+9166$run$i,,$($f[2]),,80,$($f[4]),$($f[5])" }
$csvFile = Join-Path $tmp "fixtures.csv"; Set-Content -Path $csvFile -Value ($csv -join "`n")
$mapping = @{ application_number = "Roll No"; first_name = "Candidate"; entrance_score = "Score"; program_code = "Course" } | ConvertTo-Json -Compress
$d = (Upload $officer "/admissions/applicants/import" $csvFile @{ cycle_id = $CID; mapping = $mapping } 200 "?dry_run=true").data
Assert ($d.dry_run -and $d.succeeded -eq 10 -and @($d.failed).Count -eq 0) "fixture import dry run: 10 valid"
$d = (Upload $officer "/admissions/applicants/import" $csvFile @{ cycle_id = $CID; mapping = $mapping } 202 "?dry_run=false").data
$j = Job $officer $d.job_id
Assert ($j.status -eq 'succeeded' -and $j.result.succeeded -eq 10) "fixture import job: 10 verified applicants"
$X = @{}
foreach ($row in (Sql "SELECT application_number, id FROM applicants WHERE cycle_id = '$CID' AND source = 'counselling_import'")) { $X[$row.application_number.Replace("V$run", "")] = $row.id }
foreach ($k in $X.Keys) { & $Python scripts/verify/_reset_password.py "V$run$k" $pwdA | Out-Null }
$TX = @{}; foreach ($k in @('X1', 'X2', 'X3', 'X4', 'X5', 'X6', 'X7')) { $TX[$k] = Login "V$run$k" $pwdA }

$ml = Call $officer POST "/admissions/cycles/$CID/merit-lists" @{ name = "Overall merit $run" } 202
$j = Job $officer $ml.data.job_id
Assert ($j.status -eq 'succeeded' -and $j.result.count -eq 10) "merit job ranked 10 applicants"
$m = (Call $hod GET "/admissions/merit-lists/$($ml.data.id)").data
$rank = @{}; $crank = @{}; foreach ($e in $m.entries) { $rank[$e.application_number.Replace("V$run", "")] = $e.rank; $crank[$e.application_number.Replace("V$run", "")] = $e.category_rank }
Assert ($rank['X1'] -eq 1 -and $rank['X2'] -eq 2 -and $rank['X3'] -eq 3) "ranks by score (X1, X2, X3)"
Assert ($rank['X9'] -lt $rank['X10']) "equal scores ordered by dob asc (X9 older first)"
Assert ($crank['X2'] -eq 1 -and $crank['X3'] -eq 2) "category ranks within OBC-NCL"
Assert ($m.formula_snapshot.tie_break[1] -eq 'dob_asc') "formula snapshot keeps the tie-breaks"
Call $officer POST "/admissions/merit-lists/$($ml.data.id)/publish" | Out-Null
$pm = (Call $null GET "/public/admissions/$cslug/merit-lists/$($ml.data.id)?institution=$slug").data
$keys = @($pm.entries[0].PSObject.Properties.Name)
Assert (@($pm.entries).Count -eq 10 -and $keys.Count -eq 2 -and $keys -contains 'rank' -and $keys -contains 'application_number') "public list masked: application number + rank only"
$ml2 = Call $officer POST "/admissions/cycles/$CID/merit-lists" @{ name = "Overall merit $run (rev)" } 202
Job $officer $ml2.data.job_id | Out-Null
$old = (Call $officer GET "/admissions/merit-lists?cycle_id=$CID").data | Where-Object id -eq $ml.data.id
Assert ($old.status -eq 'superseded') "regenerate → previous list superseded"
Call $officer POST "/admissions/merit-lists/$($ml2.data.id)/publish" | Out-Null

# ---- 7. round 1 ------------------------------------------------------------------------------------------------------------
Write-Host "`n== 7. round 1 allotment" -ForegroundColor Cyan
$future = (Get-Date).ToUniversalTime().AddDays(5).ToString("o")
$r1 = (Call $officer POST "/admissions/cycles/$CID/rounds" @{ round_number = 1; choice_filling_start = (Get-Date).ToUniversalTime().AddHours(-1).ToString("o"); choice_filling_end = $future; reporting_deadline = $future } 201).data
Call $officer POST "/admissions/cycles/$CID/rounds" @{ round_number = 1 } 409 | Out-Null
Call $tA2 PUT "/applicants/me/choices" @{ preferences = @(@{ program_id = $MBA }) } 409 | Out-Null
Call $officer POST "/admissions/rounds/$($r1.id)/status" @{ status = "choice_filling" } | Out-Null
foreach ($k in @('X5', 'X7')) { Call $TX[$k] PUT "/applicants/me/choices" @{ preferences = @(@{ program_id = $BT }, @{ program_id = $MBA }) } | Out-Null }
$dry = (Call $officer POST "/admissions/rounds/$($r1.id)/run-allotment?dry_run=true").data
$by = @{}; foreach ($a in $dry.allotments) { $by[$a.application_number.Replace("V$run", "")] = $a }
Assert ($dry.dry_run -and $dry.allotted -eq 6) "dry run: 6 seats allotted"
Assert ($by['X2'].quota -eq 'STATE' -and $by['X2'].category -eq 'GEN') "OBC applicant inside the GEN merit gets a GEN seat"
Assert ($by['X3'].category -eq 'OBC-NCL') "next OBC applicant gets the OBC-NCL seat"
Assert ($by['X4'].quota -eq 'PWD') "PwD applicant gets the PWD earmarked seat"
Assert ($by['X6'].quota -eq 'LATERAL') "lateral applicant only on a LATERAL seat"
Assert ($by['X5'].program_code -eq 'MBA' -and -not $by.ContainsKey('X7')) "X5 falls to the 2nd preference; X7 unallotted"
Assert ((Sql "SELECT count(*) AS n FROM seat_allotments WHERE round_id = '$($r1.id)'")[0].n -eq 0) "dry run persists nothing"
$j1 = Call $officer POST "/admissions/rounds/$($r1.id)/run-allotment?dry_run=false" $null 202
$j2 = Call $officer POST "/admissions/rounds/$($r1.id)/run-allotment?dry_run=false" $null 202
Job $officer $j1.data.job_id | Out-Null; Job $officer $j2.data.job_id | Out-Null
Assert ((Sql "SELECT count(*) AS n FROM seat_allotments WHERE round_id = '$($r1.id)'")[0].n -eq 6) "two runs → still 6 allotments (no double allotment)"
Assert ((Sql "SELECT count(*) AS n FROM seat_matrix WHERE cycle_id = '$CID' AND filled > seats")[0].n -eq 0) "filled ≤ seats on every row"
$sum = (Call $officer GET "/admissions/rounds/$($r1.id)/summary").data
Assert ((@($sum.rows | Where-Object { $_.quota -eq 'STATE' -and $_.category -eq 'GEN' -and $_.program_code -eq 'BTECH-CSE' }))[0].filled -eq 2) "summary per programme × quota × category"

# ---- 8. decisions ----------------------------------------------------------------------------------------------------------
Write-Host "`n== 8. decisions" -ForegroundColor Cyan
function MyAllot($k) { (Call $TX[$k] GET "/applicants/me/allotment").data }
$al = MyAllot 'X1'
$d = (Call $TX['X1'] POST "/applicants/me/allotment/$($al.id)/decision" @{ action = "accept" }).data
Assert ($d.status -eq 'allotted' -and $d.payment.status -eq 'pending' -and $d.payment.amount_paise -eq 1000000) "accept → admission-fee payment pending"
Call $officer POST "/admissions/applicants/$($X['X1'])/admit" $null 409 | Out-Null
Assert $true "10a. admit before the fee is paid → 409"
Call $officer POST "/_dev/fees/pay/$($d.payment.ref)" | Out-Null
Assert ((MyAllot 'X1').status -eq 'accepted') "paid → allotment accepted"
Assert ((Call $officer GET "/admissions/applicants/$($X['X1'])").data.status -eq 'accepted') "applicant accepted"
$al6 = MyAllot 'X6'; $d6 = (Call $TX['X6'] POST "/applicants/me/allotment/$($al6.id)/decision" @{ action = "accept" }).data
Call $officer POST "/_dev/fees/pay/$($d6.payment.ref)" | Out-Null
$al2 = MyAllot 'X2'
Call $TX['X2'] POST "/applicants/me/allotment/$($al2.id)/decision" @{ action = "decline" } | Out-Null
Assert ((Sql "SELECT filled FROM seat_matrix WHERE cycle_id = '$CID' AND program_id = '$BT' AND quota = 'STATE' AND category = 'GEN'")[0].filled -eq 1) "decline releases the seat"
Call $TX['X2'] POST "/applicants/me/allotment/$($al2.id)/decision" @{ action = "accept" } 409 | Out-Null
$al5 = MyAllot 'X5'; Assert ((Call $TX['X5'] POST "/applicants/me/allotment/$($al5.id)/decision" @{ action = "float" }).data.status -eq 'float') "float keeps the seat"
$al3 = MyAllot 'X3'; Assert ((Call $TX['X3'] POST "/applicants/me/allotment/$($al3.id)/decision" @{ action = "freeze" }).data.status -eq 'freeze') "freeze"
SqlWrite "UPDATE counselling_rounds SET reporting_deadline = NOW() - interval '1 hour' WHERE id = '$($r1.id)'"
$lp = (Call $officer POST "/_dev/admissions/lapse-allotments").data
Assert ($lp.lapsed -ge 1 -and (MyAllot 'X4').status -eq 'lapsed') "Beat lapse_allotments: undecided allotment lapsed"
Assert ((Sql "SELECT filled FROM seat_matrix WHERE cycle_id = '$CID' AND program_id = '$BT' AND quota = 'PWD'")[0].filled -eq 0) "lapsed seat released"
Call $officer POST "/admissions/rounds/$($r1.id)/status" @{ status = "closed" } | Out-Null

# ---- 9. round 2 (final) ----------------------------------------------------------------------------------------------------
Write-Host "`n== 9. round 2 final + de-reservation" -ForegroundColor Cyan
$r2 = (Call $officer POST "/admissions/cycles/$CID/rounds" @{ round_number = 2; is_final = $true; reporting_deadline = $future } 201).data
Assert ($r2.is_final) "round 2 flagged final"
$dry = (Call $officer POST "/admissions/rounds/$($r2.id)/run-allotment?dry_run=true").data
Assert (@($dry.conversions | Where-Object { $_.from_category -eq 'SC' -and $_.to_category -eq 'GEN' }).Count -eq 2) "vacant SC seats convert to GEN (both programmes)"
$jr = Call $officer POST "/admissions/rounds/$($r2.id)/run-allotment?dry_run=false" $null 202
Job $officer $jr.data.job_id | Out-Null
$n5 = MyAllot 'X5'
Assert ($n5.round_number -eq 2 -and $n5.program_code -eq 'BTECH-CSE') "float applicant upgraded to the higher preference"
Assert ((Sql "SELECT status FROM seat_allotments WHERE id = '$($al5.id)'")[0].status -eq 'upgraded') "old allotment marked upgraded"
Assert ((MyAllot 'X7').program_code -eq 'MBA') "freed MBA seat goes to the next in merit"
$x8 = (Sql "SELECT sa.quota, sa.category FROM seat_allotments sa WHERE sa.round_id = '$($r2.id)' AND sa.applicant_id = '$($X['X8'])'")
Assert ($x8.Count -eq 1 -and $x8[0].category -eq 'GEN') "converted (ex-SC) seat filled as GEN"
$s2 = (Call $officer GET "/admissions/rounds/$($r2.id)/summary").data
Assert (@($s2.conversions).Count -eq 2) "summary shows the conversions"
Assert ((Sql "SELECT count(*) AS n FROM seat_matrix WHERE cycle_id = '$CID' AND filled > seats")[0].n -eq 0) "still filled ≤ seats"

# ---- 10. admit ---------------------------------------------------------------------------------------------------------------
Write-Host "`n== 10. admit" -ForegroundColor Cyan
Call $officer POST "/admissions/applicants/$($X['X5'])/admit" $null 409 | Out-Null
$ad = (Call $registrar POST "/admissions/applicants/$($X['X1'])/admit" @{} 201).data
Assert ($ad.student_id -and $ad.registration_number -and $ad.username -eq $ad.registration_number -and $ad.applicant.status -eq 'admitted') "admitted → student $($ad.registration_number) + user"
Call $registrar POST "/admissions/applicants/$($X['X1'])/admit" @{} 409 | Out-Null
$st = (Call $registrar GET "/students/$($ad.student_id)").data
Assert ($st.category -eq 'GEN' -and $st.admission_quota -eq 'STATE') "category / quota copied to the student"
Assert ((Sql "SELECT status FROM seat_allotments WHERE applicant_id = '$($X['X1'])' AND status = 'admitted'").Count -eq 1) "allotment → admitted (seat not counted twice)"
$ad6 = (Call $officer POST "/admissions/applicants/$($X['X6'])/admit" @{} 201).data
$e6 = Sql "SELECT entry_type, entry_term_number FROM student_program_enrollments WHERE student_id = '$($ad6.student_id)'"
Assert ($e6[0].entry_type -eq 'lateral' -and $e6[0].entry_term_number -eq 3) "lateral admit → entry_type lateral, entry term 3"

# ---- 11. counselling CSV import ------------------------------------------------------------------------------------------------
Write-Host "`n== 11. counselling import" -ForegroundColor Cyan
$c2 = (Call $officer POST "/admissions/cycles" @{ name = "State counselling $run"; slug = "v08i-$run"; level = "ug"; academic_year_id = $year } 201).data
Call $officer PUT "/admissions/cycles/$($c2.id)/programs" @{ programs = @(@{ program_id = $BT; intake = 100; entrance_source = "state_cet" }) } | Out-Null
Call $officer PUT "/admissions/cycles/$($c2.id)/seat-matrix" @{ rows = @(@{ program_id = $BT; quota = "STATE"; category = "GEN"; seats = 60 }, @{ program_id = $BT; quota = "STATE"; category = "OBC-NCL"; seats = 40 }) } | Out-Null
$lines = @("application_number,first_name,last_name,dob,gender,category,quota,entrance_score,entrance_rank,qualifying_pct,program_code,allotted")
for ($n = 1; $n -le 100; $n++) {
  $cat = if ($n % 3 -eq 0) { 'OBC-NCL' } else { 'GEN' }
  $prog = if ($n -in 7, 22, 51) { 'NOPE' } else { 'BTECH-CSE' }
  $dob = if ($n -eq 33) { 'not-a-date' } else { '2007-02-03' }
  $c = if ($n -eq 88) { 'ZZ' } else { $cat }
  $all = if ($n -le 52) { 'Y' } else { 'N' }
  $lines += "CI$run$($n.ToString('000')),Cand$n,Import,$dob,F,$c,STATE,$(100 + $n),$n,70,$prog,$all"
}
$imp = Join-Path $tmp "counselling.csv"; Set-Content -Path $imp -Value ($lines -join "`n")
$d = (Upload $officer "/admissions/applicants/import" $imp @{ cycle_id = $c2.id } 200 "?dry_run=true").data
Assert ($d.total -eq 100 -and $d.succeeded -eq 95 -and @($d.failed).Count -eq 5) "dry run: 100 rows, 95 valid, 5 reported"
Assert ((Sql "SELECT count(*) AS n FROM applicants WHERE cycle_id = '$($c2.id)'")[0].n -eq 0) "dry run writes nothing"
$d = (Upload $officer "/admissions/applicants/import" $imp @{ cycle_id = $c2.id } 202 "?dry_run=false").data
$j = Job $officer $d.job_id
Assert ($j.status -eq 'succeeded' -and $j.result.succeeded -eq 95 -and $j.result.allotted -eq 48) "import job: 95 applicants, 48 allotted (4 of the 52 allotment rows were bad)"
Assert ((Sql "SELECT count(*) AS n FROM applicants WHERE cycle_id = '$($c2.id)' AND source = 'counselling_import' AND status = 'allotted'")[0].n -eq 48) "allotted rows carry source=counselling_import, status=allotted"
$ex = Call $officer GET "/admissions/applicants/export?cycle_id=$($c2.id)" $null 202
Assert ((Job $officer $ex.data.job_id).result.result_url) "export job → XLSX"

# ---- 12b. withdrawal after acceptance -------------------------------------------------------------------------------------------
Write-Host "`n== 12. withdrawal after acceptance" -ForegroundColor Cyan
SqlWrite "UPDATE counselling_rounds SET reporting_deadline = NOW() + interval '2 days' WHERE id = '$($r1.id)'"
$al3 = MyAllot 'X3'
$d3 = (Call $TX['X3'] POST "/applicants/me/allotment/$($al3.id)/decision" @{ action = "accept" }).data
Call $officer POST "/_dev/fees/pay/$($d3.payment.ref)" | Out-Null
$w = (Call $TX['X3'] POST "/applicants/me/withdraw" @{ reason = "Changed plans" }).data
Assert ($w.refund.amount_paise -eq 500000 -and $w.refund.workflow_instance_id) "after acceptance → 50 % of the ₹10,000 admission fee (refund workflow)"
Assert ((Sql "SELECT status FROM seat_allotments WHERE id = '$($al3.id)'")[0].status -eq 'declined') "withdrawal releases the held seat"
$wf = Sql "SELECT d.key AS workflow_key FROM workflow_instances wi JOIN workflow_definitions d ON d.id = wi.definition_id WHERE wi.id = '$($w.refund.workflow_instance_id)'"
Assert ($wf[0].workflow_key -eq 'admissions.refund') "refund request runs the admissions.refund workflow"

# ---- 13. enquiries -------------------------------------------------------------------------------------------------------------
Write-Host "`n== 13. enquiries" -ForegroundColor Cyan
$ephone = "+9155$($run)77"
Call $null POST "/public/enquiries?institution=$slug" @{ name = "Web Visitor $run"; phone = $ephone; message = "MBA fees?"; program_interest = @("MBA"); captcha_token = "test" } 201 | Out-Null
$eq = @((Call $officer GET "/admissions/enquiries?q=$([uri]::EscapeDataString($ephone))").data)
Assert ($eq.Count -eq 1 -and $eq[0].source -eq 'web' -and $eq[0].stage -eq 'new') "public enquiry recorded (source web)"
$offId = (Sql "SELECT id FROM users WHERE username = 'admissions'")[0].id
$e = (Call $officer POST "/admissions/enquiries/$($eq[0].id)/assign" @{ user_id = $offId }).data
Assert ($e.assigned_to -eq $offId) "assigned to the admissions officer"
Call $officer PUT "/admissions/enquiries/$($e.id)" @{ stage = "counselled"; note = "Called back" } | Out-Null
$e = (Call $officer POST "/admissions/enquiries/$($e.id)/convert" @{ application_number = $a2.application_number }).data
Assert ($e.stage -eq 'applied' -and $e.application_number -eq $a2.application_number -and @($e.notes).Count -ge 2) "convert links the applicant (stage applied)"
$stats = (Call $officer GET "/admissions/enquiries/stats").data
Assert ($stats.by_stage.applied -ge 1 -and @($stats.funnel).Count -eq 5 -and $stats.funnel[0].stage -eq 'new' -and $stats.funnel[0].count -ge $stats.funnel[3].count) "funnel counts per stage"

# ---- 14. visibility --------------------------------------------------------------------------------------------------------------
Write-Host "`n== 14. visibility" -ForegroundColor Cyan
$vb = Call $collegeB GET "/admissions/applicants?cycle_id=$CID&page_size=100"
$nb = @($vb.data | ForEach-Object application_number)
Assert (($nb -contains $a2.application_number) -and ($nb -contains "V$($run)X7") -and -not ($nb -contains "V$($run)X1")) "college.admin.b sees only applicants preferring a college-B programme"
Assert (@($vb.data | Where-Object { $_.phone -and $_.phone -notmatch '\*' }).Count -eq 0) "college admin: phones masked (no admissions:view_pii)"
$vh = Call $hod GET "/admissions/applicants?cycle_id=$CID&page_size=100"
$nh = @($vh.data | ForEach-Object application_number)
Assert (($nh -contains "V$($run)X1") -and -not ($nh -contains $a2.application_number)) "hod.cse sees CSE-preference applicants only"
Assert ($vh.meta.visibility.scopes -contains 'department') "hod meta.visibility scopes = department"
Call $hod GET "/admissions/applicants/$($me2.id)" $null 404 | Out-Null
Call $hod PUT "/admissions/applicants/$($X['X8'])" @{ remarks = "x" } 403 | Out-Null
$vo = Call $officer GET "/admissions/applicants?cycle_id=$CID&page_size=100"
Assert ($vo.meta.visibility.pii -and $vo.meta.visibility.scopes -contains 'all' -and @($vo.data | Where-Object { $_.phone -match '\*' }).Count -eq 0) "admissions office: all applicants, PII unmasked"

Pop-Location
Summary "08_admissions"
