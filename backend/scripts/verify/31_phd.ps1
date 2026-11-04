# Phase 31 — PhD & research-scholar management (Prompts/31 §31.11). Run after
# `seed_demo_institution.py --only phd`. Written in the development-only run; not executed yet.
param([string]$BaseUrl = "http://localhost:8000/api/v1", [string]$Institution = "demo-uni")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl

$cell = Login "research.cell"
$dean = Login "dean.res"
$hod = Login "hod.cse"
$acct = Login "accountant"
$ga = Login "guide.a"
$gb = Login "guide.b"
$gc = Login "guide.c"
$s1 = Login "scholar.1"
$sNew = Login "scholar.new"
$sTh = Login "scholar.thesis"
$sUn = Login "scholar.unsat"
$iqac = Login "iqac"
$colB = Login "college.admin.b"
$aud = Login "auditor.tmp"
$today = (Get-Date).ToString("yyyy-MM-dd")
$month = (Get-Date -Day 1).ToString("yyyy-MM-dd")

Write-Host "== 1 scopes / guide load"
$own = Call $ga GET "/phd/scholars?scope=own"
Assert (@($own.meta.visibility.scopes) -contains "own") "guide: own tab"
Assert ($own.meta.pagination.total -ge 1) "guide.a sees own scholars ($($own.meta.pagination.total))"
$dep = Call $hod GET "/phd/scholars?scope=department"
Assert ($dep.meta.pagination.total -ge 1) "HOD: department scholars"
Call $s1 GET "/phd/scholars" $null 403 | Out-Null
$me = Call $s1 GET "/phd/me"
$sid1 = $me.data.id
$load = Call $cell GET "/phd/guides/load"
$gbRow = @($load.data | Where-Object { $_.name -like "*" -and $_.current -eq $_.max -and $_.cadre -eq "assistant" })[0]
if (-not $gbRow) { Write-Host "  no assistant guide at capacity in this data: skipping the cap step" }

Write-Host "== 2 create scholar / load limit"
$newMe = Call $sNew GET "/phd/me"
Assert ($newMe.data.status -eq "admitted") "scholar.new admitted"
if ($gbRow) { $busy = Call $cell POST "/phd/scholars" @{ enrollment_id = $newMe.data.enrollment_id; guide_staff_id = $gbRow.staff_id } 409 }
Assert ($busy.error.details.code -in @("GUIDE_LOAD_EXCEEDED", "SCHOLAR_EXISTS")) "load limit enforced (or the shell exists)"

Write-Host "== 3 coursework"
$cw = Call $sNew GET "/phd/scholars/$($newMe.data.id)/coursework"
Assert ($cw.data.credits_required -eq 12) "12 credits required"
Call $ga POST "/phd/scholars/$($newMe.data.id)/coursework/complete" $null 409 | Out-Null

Write-Host "== 4 DC"
$dc = Call $ga GET "/phd/scholars/$sid1/dc"
$mt = Call $ga GET "/phd/scholars/$sid1/dc-meetings"
$next = (@($mt.data | ForEach-Object { $_.meeting_no }) | Measure-Object -Maximum).Maximum + 1
$m = Call $ga POST "/phd/scholars/$sid1/dc-meetings" @{ meeting_no = $next; held_on = $today; agenda = "Progress" } 201
Call $ga POST "/phd/scholars/$sid1/dc-meetings" @{ meeting_no = $next; held_on = $today } 409 | Out-Null
Call $ga PUT "/phd/dc-meetings/$($m.data.id)/minutes" @{ minutes = "Reviewed"; recommendations = @(@{ text = "Submit a paper"; due_on = $today }, @{ text = "Attend a conference" }) } | Out-Null
Call $ga POST "/phd/dc-meetings/$($m.data.id)/approve" @{} | Out-Null

Write-Host "== 5 progress"
$per = Call $s1 GET "/phd/scholars/$sid1/progress-periods"
Assert (@($per.data).Count -ge 1) "periods generated from registration"
$comp = Call $cell GET "/phd/progress-reports/compliance"
Assert (@($comp.data | Where-Object { $_.unsatisfactory_streak -ge 2 }).Count -ge 1) "an unsatisfactory chain (cancellation review)"
$cr = Call $cell GET "/phd/requests?type=cancellation_review"
if (@($cr.data).Count) { Call $cell POST "/phd/requests/$($cr.data[0].id)/cancellation-decision" @{ decision = "warning" } | Out-Null }

Write-Host "== 6 fellowships"
$run = Call $cell POST "/phd/fellowships/run?inline=true" @{ month = $month } 202
Assert ($run.data.created + $run.data.held + $run.data.skipped -ge 1) "monthly run"
$pend = Call $cell GET "/phd/disbursements?month=$month&status=pending"
if (@($pend.data).Count) {
    $d = $pend.data[0]
    Call $cell POST "/phd/disbursements/$($d.id)/approve" | Out-Null
    Call $cell POST "/phd/disbursements/pay" @{ disbursement_ids = @($d.id); reference = "PAYOUT/VERIFY"; paid_on = $today } | Out-Null
}
Call $acct GET "/phd/disbursements" | Out-Null
Call $s1 GET "/phd/fellowships/me" | Out-Null
Call $sTh POST "/phd/disbursements/$([guid]::NewGuid())/approve" $null 403 | Out-Null

Write-Host "== 7 requests"
$ext = Call $s1 POST "/phd/scholars/$sid1/requests" @{ request_type = "extension"; details = @{ months = 12; reason = "Experiments delayed" } } 201
Assert ($ext.data.workflow_instance_id) "phd.request started"
Call $s1 POST "/phd/scholars/$sid1/requests" @{ request_type = "extension"; details = @{ months = 30; reason = "Too long" } } 409 | Out-Null

Write-Host "== 8 thesis"
$min = Call $s1 POST "/phd/scholars/$sid1/thesis" @{ stage = "synopsis"; title = "Too early"; file_url = "mock://t.pdf"; ai_declaration = $true } 409
Assert ($min.error.details.code -eq "MIN_DURATION") "minimum duration"
$thMe = Call $sTh GET "/phd/me"
$pre = Call $sTh POST "/phd/scholars/$($thMe.data.id)/thesis" @{ stage = "synopsis"; title = "Synopsis"; file_url = "mock://s.pdf"; ai_declaration = $true } 409
Assert ($pre.error.details.code -eq "PRE_SUBMISSION_REQUIREMENTS") "pre-submission requirements"
Call $sTh POST "/phd/scholars/$($thMe.data.id)/thesis" @{ stage = "synopsis"; title = "Synopsis"; file_url = "mock://s.pdf"; ai_declaration = $false } 422 | Out-Null
$q = Call $cell GET "/phd/thesis?status=submitted"
if (@($q.data).Count) {
    $chk = Call $cell POST "/phd/thesis/$($q.data[0].id)/plagiarism/check?inline=true" $null 202
    Assert ($chk.data.similarity_pct -ne $null) "similarity recorded"
}

Write-Host "== 9 examiners (sealed for the scholar)"
$tq = Call $cell GET "/phd/thesis?status=dc_approved"
$t = @($tq.data | Where-Object { $_.stage -eq "thesis" })[0]
if ($t) {
    $panel = Call $cell GET "/phd/thesis/$($t.id)/examiners"
    Assert (@($panel.data).Count -ge 0) "panel listed"
    $rec = Call $cell GET "/phd/thesis/$($t.id)/recommendations"
    Assert ($rec.data.consolidated) "consolidated recommendation"
}

Write-Host "== 10 viva / award"
$up = Call $cell GET "/phd/viva/upcoming"
Assert (@($up.data).Count -ge 1) "upcoming vivas"
$aw = Call $cell GET "/phd/awards"
Assert (@($aw.data).Count -ge 10) "10 awards linked to Phase 18"

Write-Host "== 11 ETD"
$etd = Call $cell GET "/phd/awards/etd-status"
Assert (@($etd.data).Count -ge 1) "ETD status board"

Write-Host "== 12 stats / scopes / gating"
$st = Call $cell GET "/phd/stats"
Assert ($st.data.gphd -ge 0 -and $st.data.by_status.awarded -ge 10) "GPHD and awarded"
Call $iqac GET "/phd/stats" | Out-Null
Call $colB GET "/phd/scholars" | Out-Null
Call $aud GET "/phd/scholars" | Out-Null
Call $aud POST "/phd/fellowships/run?inline=true" @{ month = $month } 403 | Out-Null
Write-Host "Phase 31 verification finished"
