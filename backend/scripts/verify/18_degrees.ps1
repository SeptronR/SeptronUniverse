# Phase 18 — degrees, convocation & digital credentials (Prompts/18 §18.11). Run after `seed_demo_institution.py --only degrees`.
param([string]$Base = "http://localhost:8000/api/v1")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1"

$reg = Login "registrar"; $coe = Login "coe"; $hod = Login "hod.cse"; $acc = Login "accountant"; $stu = Login "student.1"; $par = Login "parent.1"

Step "2 eligibility"
$awards = Api GET "/degrees" $reg
Check ($awards.data.Count -ge 1) "awards seeded"
$batchCode = $awards.data[0].enrollment.batch_code
$checks = Api GET "/degree-eligibility" $reg
Check ($checks.data.Count -ge 1) "checks listed"
$inel = $checks.data | Where-Object { -not $_.is_eligible } | Select-Object -First 1
if ($inel) { Check ($inel.reasons.Count -ge 1) "ineligible has reasons" }
Api GET "/degree-eligibility/me" $stu | Out-Null
Api GET "/degree-eligibility" $hod | Out-Null

Step "3 override"
if ($inel) {
  ExpectStatus 403 { Api POST "/degree-eligibility/$($inel.id)/override" $coe @{ decision = "eligible"; reason = "coe cannot override" } }
  $o = Api POST "/degree-eligibility/$($inel.id)/override" $reg @{ decision = "eligible"; reason = "verify script override" }
  Check $o.data.overridden "override recorded"
}

Step "6 convocation"
$c = Api POST "/convocations" $reg @{ name = "Verify convocation"; fee_paise = 150000; registration_deadline = (Get-Date).AddDays(7).ToString("yyyy-MM-dd") }
Api POST "/convocations/$($c.data.id)/status" $reg @{ status = "registration_open" } | Out-Null
$rep = Api GET "/convocations/$($c.data.id)/reports/gowns" $reg
Check ($rep.data -ne $null) "gown report"

Step "7 awards"
$issued = $awards.data | Where-Object { $_.status -eq "issued" } | Select-Object -First 1
Check ($issued.certificate_number -ne $null) "issued has certificate number"
ExpectStatus 403 { Api GET "/degrees/me" $acc }
Api GET "/degrees/me" $par | Out-Null

Step "11 verification"
$v = Api GET "/verify/$($issued.verification_token)" $null
Check $v.data.valid "degree verifies"
$bad = Api GET "/verify/dg$('0' * 46)" $null
Check (-not $bad.data.valid) "tampered token invalid"
$revoked = $awards.data | Where-Object { $_.status -eq "cancelled" } | Select-Object -First 1
if ($revoked) { $rv = Api GET "/verify/$($revoked.verification_token)" $null; Check $rv.data.revoked "revoked shows revoked" }

Step "12 credentials"
$cr = Api GET "/credentials" $reg
Check ($cr.data -ne $null) "credential board"

Step "14 stats"
$s = Api GET "/degrees/stats" $reg
Check ($s.data.graduated -ge 1) "graduates counted"

Summary
