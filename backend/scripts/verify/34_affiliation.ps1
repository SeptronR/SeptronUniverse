# Phase 34 — affiliation management (Prompts/34 §34.11, university tenant demo-uni). Run after
# `seed_demo_institution.py --type university --only affiliation`. Written in the development-only run; not executed yet.
# Role names of the prompt map to the seeded users: uni.registrar = registrar, uni.coe = coe, uni.accountant = accountant,
# uni.iqac = iqac, uni.vc = uni.vc, college.admin.b (base), college.principal.b / college.exam.coord.b / college.admin.c /
# college.exam.coord.c / college.admin.d / inspector.1 (affiliation seeder).
param([string]$BaseUrl = "http://localhost:8000/api/v1", [string]$Institution = "demo-uni")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl

$reg = Login "registrar" (Get-DemoPassword "registrar")
$coe = Login "coe" (Get-DemoPassword "controller_of_examinations")
$acct = Login "accountant" (Get-DemoPassword "accountant")
$iqac = Login "iqac" (Get-DemoPassword "iqac_coordinator")
$dean = Login "dean.eng" (Get-DemoPassword "dean")
$aud = Login "auditor.tmp" (Get-DemoPassword "auditor")
$vc = Login "uni.vc" (Get-DemoPassword "vice_chancellor_uni")
$insp = Login "inspector.1" (Get-DemoPassword "inspector")
$colB = Login "college.admin.b" (Get-DemoPassword "college_admin")
$prinB = Login "college.principal.b" (Get-DemoPassword "college_principal_b")
$coordB = Login "college.exam.coord.b" (Get-DemoPassword "college_exam_coordinator_b")
$colC = Login "college.admin.c" (Get-DemoPassword "college_admin_c")
$coordC = Login "college.exam.coord.c" (Get-DemoPassword "college_exam_coordinator_c")
$colD = Login "college.admin.d" (Get-DemoPassword "college_admin_d")
$d = Get-Date
$today = $d.ToString("yyyy-MM-dd")

Write-Host "== 1 portfolio / dashboards / standalone gating"
$pf = Call $reg GET "/affiliation/portfolio"
Assert ($pf.data.colleges_by_type.affiliated -ge 60) "60 affiliated colleges"
Assert ($pf.data.colleges_by_type.autonomous -ge 5) "5 autonomous colleges"
Call $colB GET "/affiliation/portfolio" $null 403 | Out-Null
$dbB = Call $colB GET "/affiliation/colleges/me/dashboard"
Assert ($dbB.data.profile.code -eq "B") "college B dashboard"
$dbC = Call $colC GET "/affiliation/colleges/me/dashboard"
Assert ($dbC.data.profile.college_type -eq "autonomous") "college C autonomous"
$colleges = Call $reg GET "/affiliation/colleges"
$B = @($colleges.data | Where-Object { $_.code -eq "B" })[0]
$C = @($colleges.data | Where-Object { $_.code -eq "C" })[0]
$D = @($colleges.data | Where-Object { $_.code -eq "D" })[0]

Write-Host "== 2 application: checklist / fees / invoice / payment"
$years = Call $reg GET "/academic-years"
$cur = @($years.data | Where-Object { $_.is_current })[0]
$apprB = Call $reg GET "/affiliation/program-approvals?college_id=$($B.college_id)&year=$($cur.id)"
$pB = $apprB.data[0]
$app = Call $colB POST "/affiliation/applications" @{
  college_id = $B.college_id; academic_year_id = $cur.id; application_type = "intake_increase"
  programs = @(@{ program_id = $pB.program_id; requested_intake = ($pB.sanctioned_intake * 2); lateral_intake = 12 })
} 201
Call $colB POST "/affiliation/applications/$($app.data.id)/action" @{ action = "submit" } 422 | Out-Null
$docs = @{}
foreach ($k in $app.data.missing_documents) { $docs[$k] = "https://files.example.in/B/$k.pdf" }
Call $colB PUT "/affiliation/applications/$($app.data.id)" @{ documents = $docs } | Out-Null
$fp = Call $colB GET "/affiliation/applications/$($app.data.id)/fee-preview"
Assert (@($fp.data.lines | Where-Object { $_.fee_type -eq "intake_increase" }).Count -eq 1) "intake increase fee line"
Assert (@($fp.data.lines | Where-Object { $_.fee_type -eq "inspection" }).Count -eq 1) "inspection fee line"
$sub = Call $colB POST "/affiliation/applications/$($app.data.id)/action" @{ action = "submit" }
Assert ($sub.data.status -eq "submitted") "submitted"
$inv = Call $acct GET "/fees/invoices/$($sub.data.fee_invoice_id)"
Assert ($inv.data.payer_type -eq "college" -and $inv.data.source_type -eq "affiliation_application") "college invoice"
Call $acct POST "/fees/invoices/$($sub.data.fee_invoice_id)/collect" @{ mode = "neft"; amount_paise = $inv.data.balance_paise; reference = "DEV-NEFT-34" } | Out-Null
Start-Sleep -Seconds 3
$a = Call $reg GET "/affiliation/applications/$($app.data.id)"
Assert ($a.data.status -eq "fee_paid") "fee_paid after payment"
Call $colC GET "/affiliation/applications/$($app.data.id)" $null 404 | Out-Null
Call $dean GET "/affiliation/applications/$($app.data.id)" | Out-Null

Write-Host "== 3 scrutiny / inspection / deficiencies"
Call $reg POST "/affiliation/applications/$($app.data.id)/scrutiny" @{ action = "return"; missing_documents = @("noc_state"); remarks = "NOC missing" } | Out-Null
Call $colB PUT "/affiliation/applications/$($app.data.id)" @{ documents = @{ noc_state = "https://files.example.in/B/noc-v2.pdf" } } | Out-Null
Call $colB POST "/affiliation/applications/$($app.data.id)/action" @{ action = "submit" } | Out-Null
$sc = Call $reg POST "/affiliation/applications/$($app.data.id)/scrutiny" @{ action = "proceed" }
Assert ($sc.data.status -eq "scrutiny") "inspection required"
$me = Call $insp GET "/users/me"
$staffList = Call $reg GET "/staff?per_page=200"
$inspStaff = @($staffList.data | Where-Object { $_.user_id -eq $me.data.id })[0]
Call $reg POST "/affiliation/applications/$($app.data.id)/inspection/schedule" @{
  committee = @{ staff_ids = @($inspStaff.id); external = @(@{ name = "Dr. AICTE Expert" }) }; inspection_on = $d.AddDays(2).ToString("yyyy-MM-dd"); mode = "physical"
} | Out-Null
$mine = Call $insp GET "/affiliation/inspections/me"
Assert (@($mine.data | Where-Object { $_.application_id -eq $app.data.id }).Count -eq 1) "assigned inspection"
$rep = Call $insp POST "/affiliation/applications/$($app.data.id)/inspection/report" @{
  report_url = "https://files.example.in/B/insp-1.pdf"; recommendation = "conditional"
  findings = @(@{ area = "Laboratories"; observation = "Lab equipment short"; is_deficiency = $true; severity = "critical" },
               @{ area = "Library"; observation = "Journals lapsed"; is_deficiency = $true; severity = "minor" })
}
Assert ($rep.data.status -eq "inspected") "inspected with deficiencies"
$minor = @($rep.data.deficiencies | Where-Object { $_.severity -eq "minor" })[0]
Call $colB POST "/affiliation/applications/$($app.data.id)/deficiencies/$($minor.id)/respond" @{ response_text = "Renewed"; evidence_url = "https://files.example.in/B/journals.pdf" } | Out-Null
Call $reg POST "/affiliation/applications/$($app.data.id)/deficiencies/$($minor.id)/close" @{ accept = $true } | Out-Null
Call $reg POST "/affiliation/applications/$($app.data.id)/reinspect" @{ inspection_on = $d.AddDays(5).ToString("yyyy-MM-dd") } | Out-Null
$crit = @($rep.data.deficiencies | Where-Object { $_.severity -eq "critical" })[0]
Call $insp POST "/affiliation/applications/$($app.data.id)/inspection/report" @{ report_url = "https://files.example.in/B/insp-2.pdf"; findings = @(); recommendation = "approve" } | Out-Null
Call $colB POST "/affiliation/applications/$($app.data.id)/deficiencies/$($crit.id)/respond" @{ response_text = "Equipment procured" } 409 | Out-Null
Call $reg POST "/affiliation/applications/$($app.data.id)/deficiencies/$($crit.id)/close" @{ accept = $true } 409 | Out-Null

Write-Host "== 4 decision / order / intake gate"
$a = Call $reg GET "/affiliation/applications/$($app.data.id)"
if ($a.data.status -ne "compliance_pending") {
  Call $reg POST "/affiliation/applications/$($app.data.id)/deficiencies/$($crit.id)/close" @{ accept = $true } | Out-Null
}
$progs = @(@{ program_id = $pB.program_id; sanctioned_intake = ($pB.sanctioned_intake * 2); lateral_intake = 12; approval_status = "conditional"; valid_to = $d.AddYears(1).ToString("yyyy-MM-dd") })
Call $vc POST "/affiliation/applications/$($app.data.id)/decide" @{ decision = "conditional"; conditions = @("Fill vacancies"); programs = $progs } 422 | Out-Null
$res = (Call $reg GET "/governance/resolutions?committee_type=executive_council&status=passed").data[0]
$dec = Call $vc POST "/affiliation/applications/$($app.data.id)/decide" @{ decision = "conditional"; conditions = @("Fill vacancies"); programs = $progs; resolution_id = $res.id }
Assert ($dec.data.status -eq "conditional" -and $dec.data.order_no) "decided with order"
Call $reg GET "/affiliation/applications/$($app.data.id)/order.pdf" | Out-Null
$chk = Call $reg GET "/affiliation/program-approvals/check?college_id=$($B.college_id)&program_id=$($pB.program_id)&year=$($cur.id)"
Assert ($chk.data.total_intake -eq ($pB.sanctioned_intake * 2 + 12)) "approval upserted"
Call $colB POST "/affiliation/applications/$($app.data.id)/action" @{ action = "withdraw" } 409 | Out-Null

Write-Host "== 5-7 programme addition / closure / autonomy / renewal variants (dev data)"
$auto = Call $colD POST "/affiliation/applications" @{ college_id = $D.college_id; academic_year_id = $cur.id; application_type = "autonomy" } 201
Assert ($auto.data.status -eq "draft") "autonomy draft"
$ren = Call $colD POST "/affiliation/applications" @{ college_id = $D.college_id; academic_year_id = $cur.id; application_type = "renewal" } 201
$fpD = Call $colD GET "/affiliation/applications/$($ren.data.id)/fee-preview"
Assert ($fpD.data.inspection_required) "D last inspected 4 years ago → inspection"
$profC = Call $reg GET "/affiliation/colleges/$($C.college_id)/profile"
Assert ($profC.data.college_type -eq "autonomous") "C autonomous"

Write-Host "== 8 submissions"
$terms = Call $reg GET "/academic-terms?is_current=true"
$term = $terms.data[0]
$win = Call $coordB GET "/affiliation/submissions/windows?term_id=$($term.id)"
Assert (@($win.data).Count -eq 7) "seven submission types"
$winC = Call $coordC GET "/affiliation/submissions/windows?term_id=$($term.id)"
Assert (@($winC.data | Where-Object { $_.applies -and $_.exam_related }).Count -eq 0) "autonomous: exam types do not apply"
$subsD = Call $colD GET "/affiliation/submissions?term_id=$($term.id)"
$ret = @($subsD.data | Where-Object { $_.status -eq "returned" })
if ($ret.Count -gt 0) {
  Call $colD POST "/affiliation/submissions/$($ret[0].id)/extract?inline=true" | Out-Null
}

Write-Host "== 9 result gating"
$sessions = Call $coe GET "/exam-sessions?term_id=$($term.id)"
$central = @($sessions.data | Where-Object { -not $_.college_id })[0]
$gate = Call $coe GET "/affiliation/exam-sessions/$($central.id)/college-status"
Assert (@($gate.data | Where-Object { $_.status -eq "gated" -and $_.college_code -eq "D" }).Count -eq 1) "D gated (practical marks missing)"
$comp = Call $reg GET "/affiliation/submissions/compliance?term_id=$($term.id)"
Assert (@($comp.data).Count -ge 60) "compliance per college"

Write-Host "== 10 exam centres"
$centres = Call $coe GET "/affiliation/exam-centres?exam_session_id=$($central.id)"
Assert (@($centres.data).Count -ge 8) "centres for the central session"
$alloc = Call $coe POST "/affiliation/exam-centres/allocate?inline=true" @{ exam_session_id = $central.id; strategy = "nearest" }
Assert ($alloc.data.centres -ge 8) "allocation run"
$cB = @($centres.data | Where-Object { $_.college_code -eq "B" })[0]
Call $coordB GET "/affiliation/exam-centres/me" | Out-Null
Call $coe PUT "/affiliation/exam-centres/$($cB.id)" @{ college_id = $cB.college_id; centre_code = $cB.centre_code; capacity = 1 } 409 | Out-Null

Write-Host "== 11 dues"
$dues = Call $acct GET "/affiliation/dues"
Assert (@($dues.data).Count -ge 1) "dues by college"

Write-Host "== 12 returns / public / scope"
$rt = Call $reg GET "/affiliation/returns/colleges_list?inline=true"
Assert (@($rt.data.rows).Count -ge 68) "colleges list"
$pub = Call (New-Session) GET "/affiliation/public/colleges?institution=$Institution"
Assert (-not ($pub.data[0].PSObject.Properties.Name -contains "dues_paise")) "public list without dues"
Call $aud GET "/affiliation/portfolio" | Out-Null
Call $aud POST "/affiliation/fee-schedules" @{ academic_year_id = $cur.id; fee_type = "recognition"; amount_paise = 1 } 403 | Out-Null
Call $iqac GET "/affiliation/portfolio" | Out-Null
Write-Host "Phase 34 verification passed"
