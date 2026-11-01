# Phase 16 — post-result services (Prompts/16 §16.11). Run after `seed_demo_institution.py --only post_result`.
param([Alias("BaseUrl")][string]$Base = "http://localhost:8000/api/v1")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1" -BaseUrl $Base

$coe = Login "coe"; $cell = Login "exam.cell"; $reg = Login "registrar"; $stu = Login "student.1"; $aud = Login "auditor"

Step "1 eligibility"
$sessions = Api GET "/exam-sessions" $cell
# the seeded end-semester session (later scripts create newer verify sessions that sort first)
$sid = (@($sessions.data | Where-Object { $_.name -like '*End-semester (regular)' }) + @($sessions.data))[0].id
$el = Api GET "/reval/eligibility?session_id=$sid" $stu
Check ($null -ne $el.data.items) "eligibility answers"

Step "2 session queue"
$q = Api GET "/exam-sessions/$sid/reval-requests" $cell
Check ($q.data.Count -ge 1) "reval requests seeded"

Step "7 malpractice"
$cases = Api GET "/malpractice-cases" $cell
Check ($cases.data.Count -ge 5) "5 cases"
ExpectStatus 404 { Api GET "/malpractice-cases/$($cases.data[0].id)" $stu }

Step "8 withheld"
$w = Api GET "/results/withheld?session_id=$sid" $coe
Check ($null -ne $w.data) "withheld list"

Step "10 transcripts"
$t = Api GET "/transcripts/requests" $reg
Check ($t.data.Count -ge 12) "12 transcripts"
$issued = $t.data | Where-Object { $_.status -eq "issued" } | Select-Object -First 1
if ($issued) { $v = Api GET "/verify/$($issued.verification_token)" $null; Check $v.data.valid "transcript verifies" }

Step "11 rank lists"
$pub = Api GET "/results/rank-lists/published" $coe
Check ($pub.data.Count -ge 1) "published rank list"
$m = Api GET "/results/medals" $coe
Check ($m.data.Count -ge 1) "gold medal"

Step "13 auditor"
Api GET "/transcripts/requests" $aud | Out-Null
ExpectStatus 403 { Api POST "/results/medals/$($m.data[0].id)/revoke" $aud @{} }

Summary
