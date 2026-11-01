# Phase 33 — governance: committees, meetings, legal & e-File (Prompts/33 §33.11). Run after
# `seed_demo_institution.py --only governance`. Written in the development-only run; not executed yet.
param([string]$BaseUrl = "http://localhost:8000/api/v1", [string]$Institution = "demo-uni")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl

$reg = Login-Mfa 'registrar' 'registrar'
$vc = Login "principal" (Get-DemoPassword "vice_chancellor")
$secAc = Login "sec.ac" (Get-DemoPassword "committee_secretary_ac")
$chairAc = Login "chair.ac" (Get-DemoPassword "committee_chair_ac")
$memAc = Login "member.ac" (Get-DemoPassword "committee_member_ac")
$memStu = Login "member.student" (Get-DemoPassword "committee_member_student")
$secBos = Login "sec.bos.cse" (Get-DemoPassword "committee_secretary_bos_cse")
$hod = Login "hod.cse" (Get-DemoPassword "hod")
$fac = Login "faculty.1" (Get-DemoPassword "faculty")
$legal = Login "legal.off" (Get-DemoPassword "legal_officer")
$pio = Login "pio" (Get-DemoPassword "pio")
$acct = Login "accountant" (Get-DemoPassword "accountant")
$iqac = Login "iqac" (Get-DemoPassword "iqac_coordinator")
$colB = Login "college.admin.b" (Get-DemoPassword "college_admin")
$aud = Login "auditor.tmp" (Get-DemoPassword "auditor")
$d = Get-Date
$today = $d.ToString("yyyy-MM-dd")

Write-Host "== 1 seed / coverage / my committees"
$cov = Call $reg GET "/governance/committees/coverage"
foreach ($t in @("anti_ragging", "icc", "grievance")) {
  Assert (@($cov.data | Where-Object { $_.committee_type -eq $t -and $_.present }).Count -eq 1) "statutory $t present"
}
$mine = Call $memAc GET "/governance/committees/me"
Assert (@($mine.data | Where-Object { $_.committee_type -in @("academic_council", "academic_committee") }).Count -ge 1) "member.ac sees the Academic Council"
$none = Call $fac GET "/governance/committees/me"
Assert (@($none.data).Count -eq 0 -or -not (@($none.data | Where-Object { $_.committee_type -eq "academic_council" }))) "faculty.1 not on the AC"

Write-Host "== 2 committee from template / reconstitute"
$staff = Call $reg GET "/staff?per_page=5"
$s0 = $staff.data[0].id
$depts = Call $reg GET "/departments"
$cse = @($depts.data | Where-Object { $_.code -eq "CSE" })[0].id
$bos = Call $reg POST "/governance/committees/from-template" @{ template_key = "bos"; department_id = $cse; chair_staff_id = $s0; constituted_on = $today } 201
Call $reg POST "/governance/committees/$($bos.data.id)/members" @{ member_type = "external"; external = @{ name = "Prof. X"; org = "IIT" }; role = "member" } 201 | Out-Null
Call $reg POST "/governance/committees/$($bos.data.id)/members" @{ member_type = "external"; external = @{ name = "Dr. Y"; org = "Industry" }; role = "member" } 201 | Out-Null
$rec = Call $reg POST "/governance/committees/$($bos.data.id)/reconstitute" @{ constituted_on = $d.AddDays(1).ToString("yyyy-MM-dd") }
Assert (@($rec.data.history).Count -ge 1) "reconstitution keeps history"
Assert (@($rec.data.member_list | Where-Object { $_.to_on }).Count -ge 2) "old members closed"

Write-Host "== 3 meeting / notice / visibility"
$ac = @($mine.data | Where-Object { $_.committee_type -in @("academic_council", "academic_committee") })[0]
$m = Call $secAc POST "/governance/meetings" @{ committee_id = $ac.id; held_on = $d.AddDays(3).ToString("o"); venue_or_link = "Senate Hall"; agenda = @(@{ item = "Approval of regulation R2026" }) } 201
$sug = Call $secAc GET "/governance/meetings/$($m.data.id)/agenda/suggestions"
Assert ($null -ne $sug.data) "agenda suggestions"
$n = Call $secAc POST "/governance/meetings/$($m.data.id)/notice" @{ channels = @("in_app", "email") }
Assert ($n.data.short_notice) "3 days < 7 → short notice"
Call $memAc GET "/governance/meetings/$($m.data.id)" | Out-Null
Call $fac GET "/governance/meetings/$($m.data.id)" $null 404 | Out-Null
Call $secBos POST "/governance/meetings/$($m.data.id)/minutes" @{ minutes_text = "x" } 403 | Out-Null

Write-Host "== 4 attendance / quorum / minutes"
$det = Call $secAc GET "/governance/committees/$($ac.id)"
$ids = @($det.data.member_list | Where-Object { $_.active } | ForEach-Object { $_.id })
$few = $ids | Select-Object -First ([math]::Floor($ids.Count / 2) - 1)
$q = Call $secAc POST "/governance/meetings/$($m.data.id)/attendance" @{ present_member_ids = @($few) }
Assert (-not $q.data.met) "quorum not met"
Call $secAc POST "/governance/meetings/$($m.data.id)/minutes" @{ minutes_text = "Minutes" } 409 | Out-Null
$q = Call $secAc POST "/governance/meetings/$($m.data.id)/attendance" @{ present_member_ids = @($ids) }
Assert ($q.data.met) "quorum met"
$hodStaff = (Call $hod GET "/staff/me").data.id
Call $secAc POST "/governance/meetings/$($m.data.id)/minutes" @{ minutes_text = "Minutes of the AC"; resolutions = @(
    @{ subject = "Curriculum revision"; text = "Resolved"; action_owner_staff_id = $hodStaff },
    @{ subject = "Regulation R2026"; text = "Approved" },
    @{ subject = "Deferred item"; text = "Deferred"; status = "deferred" }) } | Out-Null
Call $secAc POST "/governance/meetings/$($m.data.id)/minutes/submit" | Out-Null
$ap = Call $chairAc POST "/governance/meetings/$($m.data.id)/minutes/approve" @{ approve = $true }
Assert ($ap.data.status -eq "minutes_approved") "chair approved"
Assert (@($ap.data.resolutions | Where-Object { $_.number -match "^[A-Z-]+/\d{4}/\d+$" }).Count -eq 3) "resolutions numbered"
Call $secAc POST "/governance/meetings/$($m.data.id)/minutes" @{ minutes_text = "edit" } 409 | Out-Null
$cg = Call $secAc POST "/governance/meetings/$($m.data.id)/corrigendum" @{ reason = "Typo"; minutes_text = "Minutes of the AC (corrected)" }
Assert ($cg.data.minutes_version -eq 2) "corrigendum version"

Write-Host "== 5 linkage"
$res = @($ap.data.resolutions | Where-Object { $_.subject -eq "Regulation R2026" })[0]
$regs = Call $reg GET "/regulations?per_page=1"
$rid = $regs.data[0].id
Call $secAc POST "/governance/resolutions/$($res.id)/link" @{ entity_type = "regulation"; entity_id = $rid } | Out-Null
$lk = Call $reg GET "/governance/resolutions/lookup?entity_type=regulation&entity_id=$rid"
Assert (@($lk.data | Where-Object { $_.id -eq $res.id }).Count -eq 1) "lookup returns the resolution"
Call $reg GET "/governance/resolutions/$($res.id)/extract.pdf" | Out-Null

Write-Host "== 6 ATR"
$own = Call $hod GET "/governance/resolutions?scope=mine"
$r1 = @($own.data | Where-Object { $_.subject -eq "Curriculum revision" })[0]
Call $hod POST "/governance/resolutions/$($r1.id)/atr" @{ report_text = "Revised scheme circulated" } 201 | Out-Null
$r1d = Call $hod GET "/governance/resolutions/$($r1.id)"
Call $secAc POST "/governance/atr/$($r1d.data.atr.id)/decide" @{ decision = "accepted" } | Out-Null
Assert ((Call $hod GET "/governance/resolutions/$($r1.id)").data.status -eq "implemented") "implemented"

Write-Host "== 7 legal"
$lc = Call $legal POST "/legal/cases" @{ court = "High Court"; case_type = "writ"; next_hearing = $d.AddDays(7).ToString("yyyy-MM-dd") } 201
Call $legal POST "/legal/cases/$($lc.data.id)/hearings" @{ held_on = $today; notes = "Adjourned"; next_hearing = $d.AddDays(21).ToString("yyyy-MM-dd") } | Out-Null
Call $legal POST "/legal/cases/$($lc.data.id)/outcome" @{ outcome = "Allowed"; status = "judgement" } | Out-Null
Call $reg GET "/legal/cases/$($lc.data.id)" | Out-Null
Call $hod GET "/legal/cases" $null 403 | Out-Null
Call $reg GET "/legal/cases/$($lc.data.id)/documents" $null 403 | Out-Null

Write-Host "== 8 RTI"
$pioStaff = (Call $pio GET "/staff/me").data.id
$rt = Call $pio POST "/rti/requests" @{ applicant = @{ name = "A. Citizen"; address = "Hyderabad"; is_bpl = $false }; subject = "Admission data"; fee_mode = "cash" } 201
Assert ($rt.data.due_on -eq $d.AddDays(30).ToString("yyyy-MM-dd")) "due +30"
Call $pio POST "/rti/requests/$($rt.data.id)/assign" @{ pio_staff_id = $pioStaff } | Out-Null
Call $pio POST "/rti/requests/$($rt.data.id)/consult" @{ to_role = "hod"; noting = "Please furnish the data" } | Out-Null
Call $pio POST "/rti/requests/$($rt.data.id)/respond" @{ response_text = "Information furnished" } | Out-Null
Call $pio POST "/rti/requests/$($rt.data.id)/appeal" @{ grounds = "Incomplete" } | Out-Null
Call $reg POST "/rti/requests/$($rt.data.id)/appeal/decide" @{ decision = "upheld"; remarks = "Reply adequate" } | Out-Null
Call $acct GET "/rti/requests" $null 403 | Out-Null
$masked = Call $iqac GET "/rti/requests"
Assert (@($masked.data | Where-Object { -not $_.masked }).Count -eq 0) "applicant masked for IQAC"
Call $pio GET "/rti/returns?period=$($d.Year)&inline=true" | Out-Null

Write-Host "== 9 audit paras"
$ar = Call $iqac GET "/accreditation/audits"
$fin = @($ar.data | Where-Object { $_.audit_type -eq "financial_statutory" })[0]
$acctStaff = (Call $acct GET "/staff/me").data.id
$p1 = Call $acct POST "/audit-paras" @{ audit_register_id = $fin.id; para_no = "V$($d.Second).1"; description = "Advances not adjusted"; owner_staff_id = $acctStaff } 201
$p2 = Call $acct POST "/audit-paras" @{ audit_register_id = $fin.id; para_no = "V$($d.Second).2"; description = "Idle equipment"; owner_staff_id = $hodStaff } 201
Call $acct POST "/audit-paras/$($p1.data.id)/reply" @{ reply_text = "Adjusted" } | Out-Null
Call $acct POST "/audit-paras/$($p1.data.id)/status" @{ status = "settled" } | Out-Null
$mp = Call $hod GET "/audit-paras/me"
Assert (@($mp.data | Where-Object { $_.id -eq $p2.data.id }).Count -eq 1) "hod sees own para"
Call $acct GET "/audit-paras/dashboard" | Out-Null

Write-Host "== 10 e-File"
$hodUser = (Call $hod GET "/auth/me").data.id
$f = Call $fac POST "/efiles" @{ subject = "Purchase proposal"; category = "purchase"; initial_noting = "Proposal for lab PCs" } 201
Call $fac POST "/efiles/$($f.data.id)/move" @{ to_user_id = $hodUser; action = "forward"; noting = "Kindly recommend" } | Out-Null
$inb = Call $hod GET "/efiles/inbox"
Assert (@($inb.data | Where-Object { $_.id -eq $f.data.id }).Count -eq 1) "hod inbox"
Call $fac PUT "/efiles/$($f.data.id)" @{ subject = "x" } 405 | Out-Null
Call $hod POST "/efiles/$($f.data.id)/move" @{ to_role = "accountant"; action = "forward"; noting = "Funds?" } | Out-Null
Call $acct POST "/efiles/$($f.data.id)/move" @{ action = "return"; noting = "Quote needed" } | Out-Null
Call $vc GET "/efiles/pendency" | Out-Null
Call $aud GET "/efiles/$($f.data.id)" | Out-Null
Call $fac GET "/efiles/$($f.data.id)/notings.pdf" | Out-Null

Write-Host "== 11 policies"
$po = Call $reg POST "/policies" @{ title = "POSH Policy"; category = "posh"; version = "2.0"; effective_from = $today; requires_ack = $true; website = $true } 201
Call $reg POST "/policies/$($po.data.id)/submit" | Out-Null
Call $reg POST "/policies/$($po.data.id)/approve" @{ approve = $true; resolution_id = $res.id } | Out-Null
Call $vc POST "/policies/$($po.data.id)/approve" @{ approve = $true; resolution_id = $res.id } | Out-Null
Call $reg POST "/policies/$($po.data.id)/publish" | Out-Null
$pend = Call $fac GET "/policies/me/pending-ack"
Assert (@($pend.data | Where-Object { $_.id -eq $po.data.id }).Count -eq 1) "pending acknowledgement"
Call $fac POST "/policies/$($po.data.id)/acknowledge" | Out-Null
Call (New-Session) GET "/policies/public?institution=$Institution" | Out-Null

Write-Host "== 12 stats / feature gates"
$st = Call $iqac GET "/governance/stats?year=$($d.Year)"
Assert ($st.data.meetings -ge 1) "stats"
Write-Host "Phase 33 verification passed"
