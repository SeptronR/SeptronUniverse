# Phase 28 — placement, internships & training (Prompts/28 §28.11). Run after
# `seed_demo_institution.py --only placement`. Written in the development-only run; not executed yet.
param([string]$Base = "http://localhost:8000/api/v1", [string]$Institution = "demo-university")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1"

$off = Login "placement"; $hod = Login "hod.cse"; $fac = Login "faculty.1"
$stu = Login "student.1"; $par = Login "parent.1"; $aud = Login "auditor.tmp"; $iqac = Login "iqac"
$rec = Login "recruiter.acme"

Step "1 stats"
$s = Api GET "/placement/stats" $off
$den = $s.data.eligible - $s.data.opted_out
if ($den -gt 0) { Check ([math]::Abs($s.data.placed_pct - [math]::Round(100 * $s.data.placed / $den, 2)) -lt 0.01) "placed % = placed / (eligible - opted out)" }
ExpectStatus 403 { Api GET "/placement/stats" $stu }
$si = Api GET "/placement/stats" $iqac
Check ($si.data.eligible -ge 0) "iqac reads stats"

Step "2 companies / recruiters"
$cos = Api GET "/placement/companies" $off
$acme = @($cos.data | Where-Object { $_.name -like "Acme*" })[0]
Check ($acme) "ACME company exists"
$inv = Api POST "/placement/companies/$($acme.id)/recruiters/invite" $off @{ email = "talent@acme.example.com"; name = "ACME Talent" }
Check ($inv.data.company_id -eq $acme.id) "recruiter bound to ACME"
$me = Api GET "/recruiter/me" $rec
Check ((@($me.data.companies)).Count -ge 1 -and (@($me.data.companies | Where-Object { $_.id -ne $acme.id })).Count -eq 0) "recruiter sees own company only"
$bl = @($cos.data | Where-Object { $_.is_blacklisted })[0]
if ($bl) { ExpectStatus 409 { Api POST "/placement/drives" $off @{ company_id = $bl.id; title = "Blocked drive" } } }

Step "3 policy"
$smeP = Api GET "/students/me" $stu
$enrol = $smeP.data.enrollments[0]
$eff = Api GET "/placement/policies/effective?batch_id=$($enrol.batch_id)&program_id=$($enrol.program_id)" $off
Check ($eff.data.max_offers -ge 1 -and $eff.data.dream_ctc_threshold_paise -eq 100000000) "effective policy: one offer, 10 LPA dream"

Step "4 drive + eligibility"
$d = Api POST "/placement/drives" $off @{ company_id = $acme.id; title = "ACME GET verify"; ctc_min_paise = 80000000; eligibility_rules = @{ min_cgpa = 6.0; max_active_backlogs = 0 }; registration_deadline = (Get-Date).AddDays(5).ToString("o"); drive_on = (Get-Date).AddDays(10).ToString("yyyy-MM-dd") }
$pv = Api GET "/placement/drives/$($d.data.id)/eligibility-preview" $off
Check ($pv.data.total -ge $pv.data.eligible_count) "preview counts"
$pub = Api POST "/placement/drives/$($d.data.id)/action" $off @{ action = "publish" }
Check ($pub.data.status -eq "open") "published"
$open = Api GET "/placement/drives/open" $stu
$mine = @($open.data | Where-Object { $_.id -eq $d.data.id })[0]
Check ($null -ne $mine.my_eligibility) "student sees own eligibility + reasons"

Step "5 apply / override / withdraw"
if ($mine.my_eligibility.is_eligible) {
  $key = [guid]::NewGuid().ToString()
  $a1 = Api POST "/placement/drives/$($d.data.id)/apply" $stu @{} -Headers @{ "Idempotency-Key" = $key }
  $a2 = Api POST "/placement/drives/$($d.data.id)/apply" $stu @{} -Headers @{ "Idempotency-Key" = $key }
  Check ($a1.data.id -eq $a2.data.id) "idempotent apply"
  Check ($a1.data.eligibility_snapshot.cgpa -ne $null) "snapshot stored"
  $w = Api POST "/placement/applications/$($a1.data.id)/withdraw" $stu
  Check ($w.data.status -eq "withdrawn") "withdraw before shortlist"
} else {
  ExpectStatus 409 { Api POST "/placement/drives/$($d.data.id)/apply" $stu @{} }
  $ov = Api POST "/placement/applications/override-eligibility" $off @{ drive_id = $d.data.id; enrollment_id = $enrol.id; reason = "Verified CGPA correction pending" }
  Check ($ov.data.is_eligible) "override by officer"
}
ExpectStatus 403 { Api POST "/placement/applications/override-eligibility" $hod @{ drive_id = $d.data.id; enrollment_id = $enrol.id; reason = "HOD tries override" } }
$re = Api POST "/placement/drives/$($d.data.id)/re-evaluate" $off
Check ($re.data.processed -ge 0) "re-evaluate"

Step "7 rounds"
foreach ($n in 1..3) { Api POST "/placement/drives/$($d.data.id)/rounds" $off @{ round_no = $n; name = "Round $n"; round_type = @("aptitude", "technical", "hr")[$n - 1] } | Out-Null }
$sl = Api POST "/placement/drives/$($d.data.id)/shortlist" $off @{ rows = @(@{ registration_number = "NOPE-000" }) }
Check ($sl.data.failed.Count -eq 1) "unknown registration → partial report"
$fn = Api GET "/placement/drives/$($d.data.id)/funnel" $off
Check ($fn.data.rounds.Count -eq 3) "funnel per round"

Step "8 offers"
$offs = Api GET "/placement/offers?status=offered" $off
Check ($offs.meta.visibility) "offers ScopeTabs"
$mo = Api GET "/placement/offers/me" $stu
$wo = Api GET "/placement/offers/wards" $par
Check ($wo.data.Count -ge 0) "parent reads ward offers"
if ($offs.data.Count -ge 1) { ExpectStatus 404 { Api GET "/placement/offers/$($offs.data[0].id)" $stu } | Out-Null }

Step "9 recruiter portal"
$rd = Api POST "/recruiter/drives" $rec @{ title = "ACME intern drive (recruiter)"; ctc_min_paise = 60000000 }
Check ($rd.data.status -eq "draft") "recruiter drive stays draft"
$ap = Api GET "/recruiter/drives/$($d.data.id)/applicants" $rec
Check ((@($ap.data | Where-Object { $_.fields.Keys -contains "aadhaar" })).Count -eq 0) "consented fields only"

Step "10 profile"
$pr = Api PUT "/placement/profile/me" $stu @{ skills = @("python", "sql"); resume_json = @{ summary = "Verify summary" } }
Check ($pr.data.skills -contains "python") "skills saved"
ExpectStatus 422 { Api PUT "/placement/profile/me" $stu @{ cgpa = 9.9 } }
$rr = Api POST "/placement/profile/me/resume/render" $stu @{ template_key = "resume_modern" }
Check ($rr.data.document_id) "resume rendered via documents"
$hp = Api GET "/placement/profiles?scope=department" $hod
Check ($hp.meta.visibility) "HOD department profiles"
$ap2 = Api GET "/placement/profiles" $aud
if ($ap2.data.Count -ge 1 -and $ap2.data[0].phone) { Check ($ap2.data[0].phone -like "*•*") "auditor sees masked contacts" }

Step "11 internships"
$it = Api POST "/internships" $stu @{ company_id = $acme.id; role = "Intern"; from_on = (Get-Date).AddDays(-70).ToString("yyyy-MM-dd"); to_on = (Get-Date).AddDays(-14).ToString("yyyy-MM-dd") }
$noc = Api POST "/internships/$($it.data.id)/noc" $stu @{ purpose = "Summer internship" }
Check ($noc.data.noc_document_id) "NOC via documents"
ExpectStatus 409 { Api POST "/internships" $stu @{ company_name = "Short Co"; from_on = (Get-Date).AddDays(-14).ToString("yyyy-MM-dd"); to_on = (Get-Date).ToString("yyyy-MM-dd"); credits_course_id = [guid]::NewGuid().ToString() } }
$hi = Api GET "/internships?scope=department" $hod
Check ($hi.meta.visibility) "HOD internships"

Step "12 training"
$tp = Api POST "/training/programs" $off @{ training_type = "aptitude"; title = "Verify aptitude"; sessions = @(1..5 | ForEach-Object { @{ at = (Get-Date).AddDays($_).ToString("o"); topic = "Session $_" } }) }
$ta = Api POST "/training/programs/$($tp.data.id)/attendance" $off @{ rows = @(@{ enrollment_id = $enrol.id; sessions_attended = 4 }) }
Check ($ta.data.succeeded -eq 1) "attendance bulk"
$tm = Api GET "/training/me" $stu
Check ((@($tm.data | Where-Object { $_.program_id -eq $tp.data.id })).Count -eq 1) "own training"

Step "13 exports / features"
$job = Api GET "/placement/stats/nirf-sheet" $off
Check ($job.data.job_id) "NIRF sheet job"

Summary
