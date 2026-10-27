# Phase 36 — reports: registry, registers, builder, statutory, schedules (Prompts/36 §36.11). Run after
# `seed_demo_institution.py --only reports` (demo-uni). Written in the development-only run; not executed yet.
# Role names of the prompt map to the seeded users: principal = vice_chancellor, inst.admin = institution admin.
param([string]$BaseUrl = "http://localhost:8000/api/v1", [string]$Institution = "demo-uni")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl

$admin = Login "inst.admin" (Get-DemoPassword "institution_admin")
$prin = Login "principal" (Get-DemoPassword "vice_chancellor")
$reg = Login "registrar" (Get-DemoPassword "registrar")
$coe = Login "coe" (Get-DemoPassword "controller_of_examinations")
$hod = Login "hod.cse" (Get-DemoPassword "hod")
$hodE = Login "hod.ece" (Get-DemoPassword "hod_ece")
$fac = Login "faculty.1" (Get-DemoPassword "faculty")
$acct = Login "accountant" (Get-DemoPassword "accountant")
$hr = Login "hr" (Get-DemoPassword "hr_officer")
$plc = Login "placement" (Get-DemoPassword "placement_officer")
$lib = Login "librarian" (Get-DemoPassword "librarian")
$iqac = Login "iqac" (Get-DemoPassword "iqac_coordinator")
$pio = Login "pio" (Get-DemoPassword "pio")
$rc = Login "research.cell" (Get-DemoPassword "research_cell")
$colB = Login "college.admin.b" (Get-DemoPassword "college_admin")
$stu = Login "student.1" (Get-DemoPassword "student")
$aud = Login "auditor.tmp" (Get-DemoPassword "auditor")

function Wait-Job($session, $jobId, [int]$seconds = 60) {
  for ($i = 0; $i -lt $seconds; $i += 2) {
    $r = Call $session GET "/reports/runs/$jobId"
    if ($r.data.status -in @("succeeded", "failed", "cancelled")) { return $r.data }
    Start-Sleep -Seconds 2
  }
  throw "job $jobId did not finish"
}

Write-Host "== 1 catalogue + registry guard"
$ca = Call $acct GET "/reports/catalogue"
Assert (@($ca.data | Where-Object { $_.module -eq "fees" }).Count -ge 3) "accountant: fee reports"
Assert (@($ca.data | Where-Object { $_.module -eq "exams" }).Count -eq 0) "accountant: no exam reports"
$cf = Call $fac GET "/reports/catalogue"
Assert (@($cf.data | Where-Object { $_.key -eq "attendance.register" }).Count -eq 1) "faculty: attendance register"
Call $stu GET "/reports/catalogue" $null 403 | Out-Null
Push-Location "$PSScriptRoot/../.."
python scripts/check_report_registry.py
Assert ($LASTEXITCODE -eq 0) "check_report_registry.py: 0 missing"
Pop-Location

Write-Host "== 2 inline preview + narrowing"
$colleges = Call $admin GET "/colleges?size=10"
$colA = @($colleges.data | Where-Object { $_.code -match "A$|^A" })[0].id
if (-not $colA) { $colA = $colleges.data[0].id }
$from = (Get-Date).AddDays(-60).ToString("yyyy-MM-dd"); $to = (Get-Date).ToString("yyyy-MM-dd")
$p = Call $acct POST "/reports/run" @{ key = "fees.collection_register"; params = @{ from = $from; to = $to; college_id = $colA }; format = "xlsx"; inline_preview = $true }
Assert (@($p.data.preview.rows).Count -le 2000) "preview ≤ 2000 rows"
$pb = Call $colB POST "/reports/run" @{ key = "fees.collection_register"; params = @{ from = $from; to = $to; college_id = $colA }; format = "xlsx"; inline_preview = $true }
Assert ($pb.data.scope -eq "college") "college admin B narrowed to college scope"
Assert ($pb.data.params.college_id -ne $colA) "college A pick replaced by college B"
Call $acct POST "/reports/run" @{ key = "fees.collection_register"; params = @{ from = $to; to = $from }; format = "xlsx"; inline_preview = $true } 422 | Out-Null

Write-Host "== 3 job run + visibility + cancel"
$offs = Call $hod GET "/offerings?size=1&scope=department"
$off = $offs.data[0].id
$month = (Get-Date).ToString("yyyy-MM")
$j = Call $hod POST "/reports/run" @{ key = "attendance.register"; params = @{ offering_id = $off; month = $month }; format = "xlsx" } 202
$done = Wait-Job $hod $j.data.job_id
Assert ($done.status -eq "succeeded" -and $done.checksum) "attendance register job with checksum"
Call $hodE POST "/reports/run" @{ key = "attendance.register"; params = @{ offering_id = $off }; format = "xlsx"; inline_preview = $true } 404 | Out-Null
$slow = Call $reg POST "/reports/run" @{ key = "students.list_export"; params = @{ slow = $true }; format = "csv" } 202
Start-Sleep -Seconds 3
Call $reg POST "/reports/runs/$($slow.data.job_id)/cancel" | Out-Null
$c = Wait-Job $reg $slow.data.job_id 90
Assert ($c.status -eq "cancelled") "slow run cancelled"
$log = Call $admin GET "/reports/access-log?key=attendance.register"
Assert (@($log.data | Where-Object { $_.action -eq "run" }).Count -ge 1) "access log shows the run"

Write-Host "== 4 formats"
foreach ($fmt in @("xlsx", "csv", "pdf")) {
  $r = Call $coe POST "/reports/run" @{ key = "results.register"; params = @{ draft = ($fmt -eq "pdf") }; format = $fmt } 202
  $d = Wait-Job $coe $r.data.job_id
  Assert ($d.status -eq "succeeded") "results.register $fmt"
}
$a1 = Wait-Job $coe (Call $coe POST "/reports/run" @{ key = "results.register"; format = "pdf" } 202).data.job_id
$a2 = Wait-Job $coe (Call $coe POST "/reports/run" @{ key = "results.register"; format = "pdf" } 202).data.job_id
Assert ($a1.checksum -eq $a2.checksum) "pdf checksum stable"

Write-Host "== 5 alias"
$al = Call $lib GET "/library/reports/circulation?format=xlsx" $null 202
$ar = Call $lib GET "/reports/runs/$($al.data.job_id)"
Assert ($ar.data.key -eq "library.circulation") "alias → report.run library.circulation"

Write-Host "== 6 registers"
$cycles = Call $reg GET "/admissions/cycles?size=1"
$rg = Call $reg POST "/reports/registers/run" @{ register = "admission"; scope = @{ cycle_id = $cycles.data[0].id }; format = "pdf" } 202
Assert ((Wait-Job $reg $rg.data.job_id).status -eq "succeeded") "admission register"
Call $hod POST "/reports/registers/run" @{ register = "degree"; format = "pdf" } 403 | Out-Null

Write-Host "== 7 builder"
$m = Call $hr GET "/reports/models"
Assert (@($m.data | Where-Object { $_.key -in @("staff", "leaves") }).Count -eq 2) "hr: staff / leaves models"
$bp = Call $hr POST "/reports/builder/preview" @{ model_key = "staff"; columns = @("employee_id", "phone"); joins = @("leaves") }
Assert ($bp.data.masked_fields -contains "phone") "phone masked without hr:view_pii"
Call $hr POST "/reports/builder/preview" @{ model_key = "staff"; columns = @("salary") } 422 | Out-Null
Call $hr POST "/reports/builder/preview" @{ model_key = "students"; columns = @("name"); joins = @("program", "department", "batch", "college") } 422 | Out-Null
$fp = Call $fac POST "/reports/builder/preview" @{ model_key = "students"; columns = @("registration_number") }
Write-Host "   faculty own-offering students: $($fp.data.total)"
$sv = Call $hr POST "/reports/saved" @{ name = "My staff list"; definition = @{ model_key = "staff"; columns = @("employee_id", "name") } } 201
Call $hr POST "/reports/saved/$($sv.data.id)/share" @{ roles = @("hod") } 403 | Out-Null
Call $admin POST "/reports/saved/$($sv.data.id)/share" @{ roles = @("hod") } | Out-Null
$hs = Call $hod GET "/reports/saved"
Assert (@($hs.data | Where-Object { $_.id -eq $sv.data.id }).Count -eq 1) "shared saved report visible to hod"
$rs = Call $hr POST "/reports/saved/$($sv.data.id)/run?format=xlsx" $null 202
Assert ((Wait-Job $hr $rs.data.job_id).status -eq "succeeded") "saved report run"

Write-Host "== 8 statutory"
$prev = "$((Get-Date).Year - 1)-$((Get-Date).ToString('yy'))"
$g = Call $reg POST "/reports/statutory/aishe/generate" @{ period_label = $prev } 202
Wait-Job $reg $g.data.job_id 120 | Out-Null
$st = Call $reg GET "/reports/statutory/aishe?period=$prev"
Assert (@($st.data.files).Count -ge 3) "aishe files xlsx+csv+pdf"
Assert ($st.data.compliance_submission_id) "linked Phase 32 submission"
Call $reg POST "/reports/statutory/aishe/$prev/review" @{ action = "request_review" } | Out-Null
Call $reg POST "/reports/statutory/aishe/$prev/review" @{ action = "sign_off"; role = "registrar" } | Out-Null
$so = Call $prin POST "/reports/statutory/aishe/$prev/review" @{ action = "sign_off"; role = "principal" }
Assert ($so.data.status -eq "signed_off") "aishe signed off"
Call $reg GET "/reports/statutory/aishe/$prev/diff" | Out-Null
$pk = Call $reg POST "/reports/statutory/aishe/$prev/pack" $null 202
Assert ((Wait-Job $reg $pk.data.job_id 120).status -eq "succeeded") "pack zip"
Call $iqac POST "/reports/statutory/nirf/generate" @{ period_label = $prev; discipline = "engineering" } 202 | Out-Null
Call $pio POST "/reports/statutory/rti_annual/generate" @{ period_label = $prev } 202 | Out-Null
Call $acct POST "/reports/statutory/nsp_return/generate" @{ period_label = $prev } 202 | Out-Null
Call $hod POST "/reports/statutory/aishe/generate" @{ period_label = $prev } 403 | Out-Null

Write-Host "== 9 schedules"
$sc = Call $admin POST "/reports/schedules" @{ key = "attendance.shortfall_list"; cadence = "weekly"; weekday = 0; at = "07:00"; recipients = @{ roles = @("hod") }; format = "xlsx" } 201
Assert ($sc.data.next_run_at) "next_run_at computed"
$rn = Call $admin POST "/reports/schedules/$($sc.data.id)/run-now" $null 202
Assert ([int]$rn.data.recipients -ge 2) "one job per HOD"
Call $admin POST "/reports/schedules" @{ key = "students.list_export"; cadence = "daily"; at = "07:00"; recipients = @{ emails = @("x@example.com") } } 422 | Out-Null
Call $admin POST "/reports/schedules" @{ key = "fees.daily_collection"; cadence = "daily"; at = "23:00" } 422 | Out-Null
Call $fac POST "/reports/schedules" @{ key = "assessment.marks_sheet"; cadence = "weekly"; at = "08:00" } 201 | Out-Null
Call $fac POST "/reports/schedules" @{ key = "assessment.marks_sheet"; cadence = "weekly"; at = "08:00"; recipients = @{ roles = @("hod") } } 422 | Out-Null
Call $admin GET "/reports/schedules/$($sc.data.id)/history" | Out-Null

Write-Host "== 11 visibility & gating"
$ra = Call $aud POST "/reports/run" @{ key = "hr.headcount"; format = "xlsx"; inline_preview = $true }
Assert ($ra.data.preview) "auditor runs read-only"
Call $aud POST "/reports/saved" @{ name = "x"; definition = @{ model_key = "staff"; columns = @("employee_id") } } 403 | Out-Null
Write-Host "Phase 36 verification complete"
