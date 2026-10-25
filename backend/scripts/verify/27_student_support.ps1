# Phase 27 — mentoring, grievances, discipline, surveys & clubs (Prompts/27 §27.11). Run after
# `seed_demo_institution.py --only student_support`. Written in the development-only run; not executed yet.
param([string]$Base = "http://localhost:8000/api/v1", [string]$Institution = "demo-university")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1"

$reg = Login "registrar"; $vc = Login "principal"; $hod = Login "hod.cse"; $fac = Login "faculty.1"
$stu = Login "student.1"; $par = Login "parent.1"; $aud = Login "auditor.tmp"; $iqac = Login "iqac"
$goff = Login "grievance.off"; $staff = Login "staff.1"

Step "1 assignments"
$me = Api GET "/students/me" $stu
$enrol = $me.data.enrollments[0].id
$mm = Api GET "/mentoring/me" $stu
Check ($mm.data.mentor_staff_id) "student has a mentor"
$prev = Api POST "/mentoring/assignments/bulk" $reg @{ term_id = $mm.data.term_id; rule = "round_robin"; ratio = 20; preview = $true }
Check ($prev.data.skipped_existing -ge 1) "bulk preview skips existing"
ExpectStatus 409 { Api POST "/mentoring/assignments" $reg @{ mentor_staff_id = $mm.data.mentor_staff_id; enrollment_ids = @($enrol); term_id = $mm.data.term_id } }
$load = Api GET "/mentoring/load?term_id=$($mm.data.term_id)" $reg
Check ($load.data.rows.Count -ge 1) "load report"
$own = Api GET "/mentoring/assignments" $fac
Check ($own.meta.visibility.scopes -contains "own") "faculty ScopeTabs own"
ExpectStatus 403 { Api GET "/mentoring/assignments" $stu }

Step "2 360"
$mentees = Api GET "/mentoring/mentees" $fac
if ($mentees.data.Count -ge 1) {
  $p = Api GET "/mentoring/mentees/$($mentees.data[0].student_program_enrollment_id)/360" $fac
  Check ($p.data.access -in @("mentor", "advisor")) "360 for own mentee"
}
ExpectStatus 404 { Api GET "/mentoring/mentees/$([guid]::NewGuid())/360" $fac }

Step "4 sessions"
$ss = Api GET "/mentoring/sessions/me" $stu
Check ((@($ss.data | Where-Object { $_.is_confidential -and $_.notes })).Count -eq 0) "confidential notes hidden from the student"
$ps = Api GET "/mentoring/sessions/me" $par
Check ((@($ps.data | Where-Object { $_.notes })).Count -eq 0) "guardian sees summaries only"

Step "5 referrals"
$rc = Api GET "/mentoring/referrals" $hod
Check ($null -ne $rc.data.total) "HOD gets counts only"

Step "7 grievances"
$g = Api POST "/grievances" $stu @{ category = "fee"; description = "Fee receipt not generated after payment." }
Check ($g.data.committee -eq "grievance_cell") "routed to grievance cell"
$a = Invoke-RestMethod -Method Post -ContentType "application/json" -Uri "$Base/grievances/anonymous?institution=$Institution" -Body (@{ category = "ragging"; description = "Seniors are harassing juniors in hostel block B." } | ConvertTo-Json)
Check ($a.data.committee -eq "anti_ragging" -and $a.data.tracking_secret) "anonymous ragging + secret"
$t = Invoke-RestMethod "$Base/grievances/track?institution=$Institution&ticket_number=$($a.data.ticket_number)&secret=$($a.data.tracking_secret)"
Check ($t.data.status -eq "open") "track by secret"
ExpectStatus 404 { Invoke-RestMethod "$Base/grievances/track?institution=$Institution&ticket_number=$($a.data.ticket_number)&secret=wrong-secret-xx" }
$tri = Api POST "/grievances/$($g.data.id)/triage" $goff @{ note = "internal check with accounts" }
$view = Api GET "/grievances/$($g.data.id)" $stu
Check ((@($view.data.timeline | Where-Object { $_.is_internal })).Count -eq 0) "internal notes hidden"
Api POST "/grievances/$($g.data.id)/resolve" $goff @{ resolution = "Receipt regenerated." } | Out-Null
$r = Api POST "/grievances/$($g.data.id)/rate" $stu @{ rating = 4 }
Check ($r.data.status -eq "closed") "rated + closed"
Api POST "/grievances/$($g.data.id)/reopen" $stu @{ reason = "Receipt still wrong" } | Out-Null
ExpectStatus 409 { Api POST "/grievances/$($g.data.id)/reopen" $stu @{ reason = "again" } }
$hl = Api GET "/grievances" $hod
Check ((@($hl.data | Where-Object { $_.confidential })).Count -eq 0) "HOD sees no confidential tickets"
$ugc = Api GET "/grievances/registers/ugc" $reg
Check ($ugc.data.rows.Count -ge 1) "UGC register"

Step "8 discipline"
$cs = Api GET "/discipline/cases" $reg
Check ($cs.data.Count -ge 1) "cases listed"
$mine = Api GET "/discipline/cases/me" $stu
$other = $cs.data | Where-Object { $mine.data.id -notcontains $_.id } | Select-Object -First 1
if ($other) { ExpectStatus 404 { Api GET "/discipline/cases/$($other.id)" $stu } }

Step "9 surveys"
$pend = Api GET "/surveys/me/pending" $stu
if ($pend.data.Count -ge 1) {
  $sv = $pend.data[0]; $tg = $sv.targets | Where-Object { -not $_.responded } | Select-Object -First 1
  $form = Api GET "/surveys/$($sv.survey_id)/form?target_id=$($tg.target_id)" $stu
  $ans = @{}; foreach ($q in $form.data.questions) { if ($q.type -ne "text") { $ans[$q.id] = 4 } }
  Api POST "/surveys/$($sv.survey_id)/respond" $stu @{ target_id = $tg.target_id; answers = $ans } | Out-Null
  ExpectStatus 409 { Api POST "/surveys/$($sv.survey_id)/respond" $stu @{ target_id = $tg.target_id; answers = $ans } }
}
$sss = Api GET "/surveys/sss/score" $iqac
Check ($sss.data.respondents -ge 1) "SSS score"

Step "10 clubs"
$clubs = Api GET "/clubs" $stu
$c1 = $clubs.data | Where-Object { -not $_.my_role } | Select-Object -First 1
$j = Api POST "/clubs/$($c1.id)/join" $stu
Check ($j.data.role -eq "pending") "join pending"
$h = Api POST "/activity-hours" $stu @{ activity_type = "nss"; hours = 6; on_date = (Get-Date -Format "yyyy-MM-dd"); description = "Village survey" }
ExpectStatus 403 { Api POST "/activity-hours/verify" $fac @{ ids = @($h.data.id); approve = $true } }
$led = Api GET "/activity-hours/ledger" $stu
Check ($led.data.total -ge 6) "ledger"

Step "11 achievements"
$ac = Api POST "/achievements" $stu @{ category = "hackathon"; title = "Smart India Hackathon finalist" }
$dl = Api GET "/achievements?department_id=$($me.data.enrollments[0].department_id)" $hod
Check ($dl.data.Count -ge 1) "HOD department achievements"

Step "12 stats"
$st = Api GET "/student-support/stats" $iqac
Check ($null -ne $st.data.grievances.total) "stats"
ExpectStatus 403 { Api POST "/clubs" $aud @{ name = "Audit club"; club_type = "technical" } }
Done
