# Phase 32 — accreditation & compliance / IQAC (Prompts/32 §32.11). Run after
# `seed_demo_institution.py --only accreditation`. Written in the development-only run; not executed yet.
param([string]$BaseUrl = "http://localhost:8000/api/v1", [string]$Institution = "demo-uni")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl

$iqac = Login "iqac"
$vc = Login "principal"
$hod = Login "hod.cse"
$fac = Login "faculty.1"
$obe = Login "obe"
$acct = Login "accountant"
$aud = Login "auditor.tmp"
$colB = Login "college.admin.b"
$stu = Login "student.1"
$d = Get-Date
$ay = if ($d.Month -ge 6) { $d.Year } else { $d.Year - 1 }
$period = "$ay-$((($ay + 1) % 100).ToString('00'))"
$prev = "$($ay - 1)-$(($ay % 100).ToString('00'))"
$today = $d.ToString("yyyy-MM-dd")

Write-Host "== 1 frameworks"
$fw = Call $iqac GET "/accreditation/frameworks"
Assert (@($fw.data).Count -eq 6) "six frameworks"
$naac = Call $iqac GET "/accreditation/frameworks/NAAC_2024"
Assert (@($naac.data.criteria).Count -eq 7) "NAAC criteria 1-7 with children"
Call $stu GET "/accreditation/frameworks" $null 403 | Out-Null

Write-Host "== 2 registry"
$defs = Call $iqac GET "/accreditation/metrics/definitions"
Assert (@($defs.data).Count -ge 75) "metric registry populated"
Assert (-not (@($defs.data) | Where-Object { -not $_.registered })) "every definition has a registered computation"

Write-Host "== 3 compute"
$c = Call $iqac POST "/accreditation/metrics/compute?inline=true" @{ period_label = $period; framework_code = "NAAC_2024" }
Assert ($c.data.computed -ge 1 -and @($c.data.failed).Count -eq 0) "NAAC compute: no failures ($(@($c.data.failed) | ConvertTo-Json -Compress -Depth 3))"
$v = Call $iqac GET "/accreditation/metrics/faculty.fsr?period=$period"
Assert ($v.data.numerator -ge 1 -and $v.data.denominator -ge 1) "FSR numerator (students) / denominator (teachers)"
$c2 = Call $iqac POST "/accreditation/metrics/compute?inline=true" @{ period_label = $period; metric_keys = @("faculty.fsr") }
$v2 = Call $iqac GET "/accreditation/metrics/faculty.fsr?period=$period"
Assert ($v2.data.value -eq $v.data.value) "recompute idempotent"

Write-Host "== 4 drill-down"
$dd = Call $iqac GET "/accreditation/metrics/results.pass_pct_final_year/drilldown?period=$prev"
$ddh = Call $hod GET "/accreditation/metrics/results.pass_pct_final_year/drilldown?period=$prev"
Assert ($ddh.data.total -le $dd.data.total) "HOD sees department rows only"
Call $aud GET "/accreditation/metrics/results.pass_pct_final_year/drilldown?period=$prev" | Out-Null
Call $iqac GET "/accreditation/metrics/faculty.fsr/drilldown/export?period=$period" $null 202 | Out-Null

Write-Host "== 5 overrides / manual / lock"
$o = Call $hod PUT "/accreditation/metrics/research.publications_per_teacher/override" @{ period_label = $period; value = 1.5; reason = "Missed indexed papers of CSE" }
Assert ($o.data.pending_override) "HOD override pending"
Call $hod PUT "/accreditation/metrics/research.publications_per_teacher/override" @{ period_label = $period; value = 1.5 } 422 | Out-Null
$ver = Call $iqac POST "/accreditation/metrics/research.publications_per_teacher/verify" @{ period_label = $period; action = "verify" }
Assert ($ver.data.source -eq "override" -and $ver.data.verified) "override applied and locked"
Call $hod PUT "/accreditation/metrics/research.publications_per_teacher/override" @{ period_label = $period; value = 2; reason = "Another change" } 409 | Out-Null
$man = Call $iqac PUT "/accreditation/metrics/values.green_audit_score/manual" @{ period_label = $period; value = 8.4 }
Assert ($man.data.source -eq "manual") "manual input for a non-computable key"
Call $vc POST "/accreditation/metrics/research.publications_per_teacher/verify" @{ period_label = $period; action = "unverify" } | Out-Null

Write-Host "== 6 evidence"
$ev = Call $iqac POST "/accreditation/evidence" @{ criterion_code = "6.2.1"; period_label = $period; title = "Strategic plan"; doc_type = "policy"; file_url = "https://files.example/plan.pdf" } 201
Call $iqac POST "/accreditation/evidence/$($ev.data.id)/verify" @{ action = "verify" } | Out-Null
Call $iqac POST "/accreditation/evidence" @{ title = "Huge"; file_url = "https://files.example/x.pdf"; size_bytes = 900000000 } 413 | Out-Null
$sug = Call $iqac GET "/accreditation/evidence/suggestions"
if (@($sug.data).Count) { Call $iqac POST "/accreditation/evidence/suggestions/$($sug.data[0].id)/accept" | Out-Null }
Call $iqac POST "/accreditation/evidence/pack?criterion=3" $null 202 | Out-Null

Write-Host "== 7 cycles"
$cy = Call $iqac POST "/accreditation/cycles" @{ framework_code = "NAAC_2024"; name = "NAAC Cycle verify"; period_from = "$($ay - 4)-06-01"; period_to = "$($ay + 1)-05-31" } 201
Call $iqac POST "/accreditation/cycles/$($cy.data.id)/status" @{ status = "data_collection" } | Out-Null
$facStaff = (Call $fac GET "/staff/me").data.id
Call $iqac POST "/accreditation/cycles/$($cy.data.id)/criteria/assign" @{ criterion_codes = @("2.3.1"); owner_staff_id = $facStaff; due_on = $today } | Out-Null
Call $fac PUT "/accreditation/cycles/$($cy.data.id)/criteria/2.3.1" @{ narrative = "<p>Experiential learning in every course.</p>" } | Out-Null
$sub = Call $fac POST "/accreditation/cycles/$($cy.data.id)/criteria/2.3.1/submit"
Assert ($sub.data.status -eq "in_review") "response in review"
Call $fac PUT "/accreditation/cycles/$($cy.data.id)/criteria/2.3.1" @{ narrative = "edit" } 409 | Out-Null
$p = Call $iqac GET "/accreditation/cycles/$($cy.data.id)/progress"
Assert ($p.data.criteria_progress.total -ge 1) "progress endpoint"

Write-Host "== 8 exports"
Call $iqac POST "/accreditation/cycles/$($cy.data.id)/export" @{ format = "naac_ssr" } 202 | Out-Null
Call $iqac POST "/accreditation/cycles/$($cy.data.id)/export" @{ format = "nirf_dcf" } 202 | Out-Null

Write-Host "== 9 submissions"
& (Get-VenvPython (Resolve-Path (Join-Path $PSScriptRoot "..\.."))) (Join-Path $PSScriptRoot "_purge.py") compliance_submissions "period_label = '$period' AND submission_type = 'aishe'" | Out-Null   # the previous run's open submission
$s = Call $iqac POST "/accreditation/submissions" @{ period_label = $period; submission_type = "aishe" } 201
$g = Call $iqac POST "/accreditation/submissions/$($s.data.id)/generate?inline=true"
Assert ($g.data.status -eq "generated") "AISHE payload generated"
Call $iqac GET "/accreditation/submissions/$($s.data.id)/diff" | Out-Null
Call $iqac POST "/accreditation/submissions/$($s.data.id)/submitted" @{ submitted_on = $today; ack_ref = "AISHE-VERIFY" } | Out-Null
Call $iqac POST "/accreditation/submissions/$($s.data.id)/generate?inline=true" $null 409 | Out-Null
$af = Call $acct GET "/accreditation/submissions/$($s.data.id)"
Assert ($af.data.payload.section -eq "finance") "accountant sees the finance section only"

Write-Host "== 10 audits"
$a = Call $iqac POST "/accreditation/audits" @{ audit_type = "green"; period_label = $period; auditor = "Verify Auditor"; findings = @(@{ text = "Solar log missing" }) } 201
Call $iqac PUT "/accreditation/audits/$($a.data.id)/findings/1" @{ status = "closed"; action_taken = "Filed" } | Out-Null
Call $iqac GET "/accreditation/audits/dashboard" | Out-Null

Write-Host "== 11-13 consistency / disclosures / dashboard"
$k = Call $iqac POST "/accreditation/consistency/check?inline=true&period=$period"
Assert (@($k.data.checks).Count -ge 5) "consistency checks ran"
Call $iqac POST "/accreditation/disclosures/refresh" | Out-Null
$pub = Invoke-RestMethod "$BaseUrl/accreditation/disclosures/public?institution=$Institution"
Assert (@($pub.data.items).Count -ge 1) "public disclosures feed"
$dash = Call $iqac GET "/accreditation/dashboard?period=$period"
Assert ($dash.data.metrics_total -ge 1) "IQAC dashboard"
Call $colB GET "/accreditation/dashboard" | Out-Null
Call $obe GET "/accreditation/cycles" | Out-Null
Write-Host "Phase 32 verification complete"
