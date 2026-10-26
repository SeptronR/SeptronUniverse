# Phase 30 — research & faculty development (Prompts/30 §30.11). Run after
# `seed_demo_institution.py --only research`. Written in the development-only run; not executed yet.
param([string]$BaseUrl = "http://localhost:8000/api/v1", [string]$Institution = "demo-uni")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl

$cell = Login "research.cell" (Get-DemoPassword "research_cell")
$hod = Login "hod.cse" (Get-DemoPassword "hod")
$hodE = Login "hod.ece" (Get-DemoPassword "hod_ece")
$dean = Login "dean.eng" (Get-DemoPassword "dean")
$prin = Login "principal" (Get-DemoPassword "vice_chancellor")
$acct = Login "accountant" (Get-DemoPassword "accountant")
$fa = Login "faculty.a" (Get-DemoPassword "faculty_a")
$fb = Login "faculty.b" (Get-DemoPassword "faculty_b")
$fe = Login "faculty.ece" (Get-DemoPassword "faculty_ece")
$chair = Login "ethics.chair" (Get-DemoPassword "ethics_chair")
$member = Login "ethics.member" (Get-DemoPassword "ethics_member")
$iqac = Login "iqac" (Get-DemoPassword "iqac_coordinator")
$colB = Login "college.admin.b" (Get-DemoPassword "college_admin")
$aud = Login "auditor.tmp" (Get-DemoPassword "auditor")
$year = (Get-Date).Year

Write-Host "== 1 stats / scopes"
$s = Call $cell GET "/research/stats"
Assert ($s.data.publications -ge 1000 -and $s.data.per_teacher -gt 0) "verified counts and per-teacher"
Call $fa GET "/research/stats" $null 403 | Out-Null
$mine = Call $fa GET "/research/publications"
Assert ($mine.meta.visibility.self -and @($mine.meta.visibility.scopes).Count -eq 0) "faculty: self only"
$dep = Call $hod GET "/research/publications?scope=department"
Assert (@($dep.meta.visibility.scopes) -contains "department") "HOD: department tab"

Write-Host "== 2 publications"
$doi = "10.5555/verify.$([guid]::NewGuid().ToString('N').Substring(0, 8))"
$p = Call $fa POST "/research/publications" @{ title = "Verify paper"; venue = "IEEE Access"; year = $year; doi = $doi; indexing = "scopus"; pub_type = "journal" } 201
$dup = Call $fb POST "/research/publications" @{ title = "Verify paper"; doi = "https://doi.org/$doi"; indexing = "scopus" } 409
Assert ($dup.error.details.code -eq "DUPLICATE_DOI") "duplicate DOI blocked with claim hint"
$cl = Call $fb POST "/research/publications/$($p.data.id)/claim-coauthor" @{ author_position = 2 }
Assert ($cl.data.is_mine) "claimed — own for faculty.b"
$prev = Call $fa POST "/research/publications/import/preview" @{ source = "orcid"; identifier = "0000-0002-1825-0097" }
Assert ((@($prev.data.matches).Count + @($prev.data.duplicates).Count + @($prev.data.new).Count) -eq 8) "preview classifies 8 works"
$ap = Call $fa POST "/research/publications/import/apply?inline=true" @{ token = $prev.data.token } 202
Assert ($ap.data.created -eq @($prev.data.new).Count) "new rows imported unverified"
Call $hod POST "/research/publications/verify" @{ ids = @($p.data.id); approve = $true } | Out-Null
$fin = Call $cell POST "/research/publications/verify" @{ ids = @($p.data.id); approve = $true }
Assert ($fin.data.verified -eq 1) "research cell final verification"
$lock = Call $fa PUT "/research/publications/$($p.data.id)" @{ citations = 5 } 403
Assert ($lock.error.details.code -eq "LOCKED") "verified row locked for authors"
Call $hodE POST "/research/publications/verify" @{ ids = @($p.data.id); approve = $true } 404 | Out-Null
Call $cell POST "/research/publications/sync-citations" $null 202 | Out-Null

Write-Host "== 3 patents"
$pt = Call $fa POST "/research/patents" @{ title = "Verify patent"; application_no = "202641000001" } 201
Call $fa PUT "/research/patents/$($pt.data.id)" @{ status = "published" } | Out-Null
Call $fa PUT "/research/patents/$($pt.data.id)" @{ status = "granted" } | Out-Null
Call $fa PUT "/research/patents/$($pt.data.id)" @{ status = "filed" } 409 | Out-Null

Write-Host "== 4 projects"
$heads = @(@{ name = "equipment"; allocated_paise = 1000000000 }, @{ name = "manpower"; allocated_paise = 800000000 },
    @{ name = "consumables"; allocated_paise = 300000000 }, @{ name = "travel"; allocated_paise = 200000000 },
    @{ name = "contingency"; allocated_paise = 200000000 })
$pr = Call $fa POST "/research/projects" @{ title = "Verify DST project"; funding_agency = "DST"; sanctioned_paise = 2500000000; budget_heads = $heads } 201
$sa = Call $cell POST "/research/projects/$($pr.data.id)/action" @{ action = "sanction"; sanctioned_paise = 2500000000; sanction_letter_url = "https://example/letter.pdf" }
$inbox = Call $prin GET "/workflow/inbox"
$wf = @($inbox.data | Where-Object { $_.instance_id -eq $sa.data.workflow_instance_id })[0]
Call $prin POST "/workflow/instances/$($sa.data.workflow_instance_id)/act" @{ decision = "approve"; comment = "Acknowledged" } | Out-Null
Start-Sleep -Seconds 3
$prg = Call $fa GET "/research/projects/$($pr.data.id)"
Assert ($prg.data.status -eq "sanctioned" -and $prg.data.grant_ledger_id) "sanctioned + Phase 23 ledger linked"
Call $fe GET "/research/projects/$($pr.data.id)" $null 404 | Out-Null
Call $fa POST "/research/projects/$($pr.data.id)/expense-requests" @{ head = "travel"; amount_paise = 4000000; description = "Conference travel"; via = "direct" } 201 | Out-Null
Call $fa POST "/research/projects/$($pr.data.id)/expense-requests" @{ head = "travel"; amount_paise = 999999999; description = "Too much"; via = "direct" } 409 | Out-Null
Call $fa POST "/research/projects/$($pr.data.id)/expense-requests" @{ head = "equipment"; amount_paise = 30000000; description = "GPU workstation"; via = "indent" } 201 | Out-Null
Assert ((Call $acct GET "/research/projects/$($pr.data.id)/ledger").data.utilised_paise -ge 4000000) "accountant reads the ledger"

Write-Host "== 5 consultancy"
$c = Call $fa POST "/research/consultancies" @{ client = "L&T"; title = "Testing"; amount_paise = 20000000 } 201
Assert ($c.data.institution_share_paise -eq 6000000) "30 % institution share"
Call $fa POST "/research/consultancies" @{ client = "BEL"; amount_paise = 1000000; institution_share_paise = 1 } 403 | Out-Null
Call $acct POST "/research/consultancies/$($c.data.id)/receipts" @{ amount_paise = 20000000; mode = "bank_transfer"; reference = "UTR123" } 201 | Out-Null

Write-Host "== 6 ethics"
$com = (Call $cell GET "/research/ethics/committees").data | Where-Object { $_.committee_type -eq "iec" } | Select-Object -First 1
$app = Call $fa POST "/research/ethics/applications" @{ committee_id = $com.id; project_title = "Clinical verify study"; category = "full_review" } 201
Call $member POST "/research/ethics/applications/$($app.data.id)/review" @{ decision = "approved"; comments = "OK" } | Out-Null
$dec = Call $chair POST "/research/ethics/applications/$($app.data.id)/decide" @{ decision = "approved" }
Assert ($dec.data.approval_no -and $dec.data.is_valid) "approved with number and validity"
$cp = Call $fa POST "/research/projects" @{ title = "Clinical project"; funding_agency = "ICMR"; ethics_category = "clinical" } 201
Call $cell POST "/research/projects/$($cp.data.id)/action" @{ action = "sanction"; sanctioned_paise = 100000000 } | Out-Null
Call $prin POST "/workflow/instances/$((Call $cell GET "/research/projects/$($cp.data.id)").data.workflow_instance_id)/act" @{ decision = "approve" } | Out-Null
$st = Call $fa POST "/research/projects/$($cp.data.id)/action" @{ action = "start" } 409
Assert ($st.error.details.code -eq "ETHICS_REQUIRED") "start blocked without approval"
Call $cell POST "/research/ethics/approvals/$($app.data.id)/renew" @{ kind = "renew"; description = "Renewal" } | Out-Null
Call $fa POST "/research/ethics/approvals/$($app.data.id)/adverse-event" @{ kind = "adverse-event"; description = "Mild reaction" } | Out-Null

Write-Host "== 7 incentives"
$sci = @((Call $fa GET "/research/publications?indexing=sci&verified=true").data | Where-Object { $_.author_position -eq 1 })[0]
$inc = Call $fa POST "/research/incentives" @{ incentive_type = "publication_incentive"; linked_entity = @{ type = "publication"; id = $sci.id } } 201
Assert ($inc.data.amount_paise -eq 2500000) "SCI first-author slab ₹25,000"
Call $hod POST "/research/incentives/$($inc.data.id)/decide" @{ decision = "approve"; comment = "Recommended" } | Out-Null
Call $cell POST "/research/incentives/$($inc.data.id)/decide" @{ decision = "approve" } | Out-Null
$i2 = Call $fa GET "/research/incentives/$($inc.data.id)"
if ($i2.data.status -ne "approved") { Call $dean POST "/research/incentives/$($inc.data.id)/decide" @{ decision = "approve" } | Out-Null }
Assert ((Call $cell POST "/research/incentives/$($inc.data.id)/disburse" @{ via = "payroll" }).data.status -eq "disbursed") "disbursed"
Call $fa POST "/research/incentives" @{ incentive_type = "publication_incentive"; linked_entity = @{ type = "publication"; id = $sci.id } } 409 | Out-Null
Call $fa POST "/research/incentives" @{ incentive_type = "travel_grant"; amount_paise = 999999999 } 422 | Out-Null

Write-Host "== 8 FDP"
$f = Call $fa POST "/research/fdp" @{ title = "ATAL FDP on AI"; event_type = "fdp"; hours = 30; from_on = "$year-01-10"; to_on = "$year-01-15" } 201
$cmp = Call $hod GET "/research/fdp/compliance?year=$year"
Assert (@($cmp.data).Count -gt 0) "compliance rows for CSE"

Write-Host "== 9 MoUs"
$m = Call $cell POST "/research/mous" @{ partner = "Verify Industries"; partner_type = "industry"; mou_type = "placement" } 201
Call $cell POST "/research/mous/$($m.data.id)/submit" | Out-Null
Call $prin POST "/workflow/instances/$((Call $cell GET "/research/mous/$($m.data.id)").data.workflow_instance_id)/act" @{ decision = "approve" } | Out-Null
$sg = Call $cell POST "/research/mous/$($m.data.id)/sign" @{ signed_on = (Get-Date).ToString("yyyy-MM-dd"); valid_to = (Get-Date).AddDays(60).ToString("yyyy-MM-dd") }
Assert ($sg.data.status -eq "active" -and $sg.data.expiry -eq "expiring") "active, expiring chip"
Call $cell POST "/research/mous/$($m.data.id)/collaborations" @{ title = "Summer internships"; collaboration_type = "internship" } 201 | Out-Null
$rn = Call $cell POST "/research/mous/$($m.data.id)/renew"
Assert ($rn.data.version -eq 2) "renewal = new version"
$fm = Call $fa GET "/research/mous"
Assert (@($fm.data | Where-Object { $_.document_url -and $_.coordinator_name -ne "Faculty A (CSE)" }).Count -eq 0) "faculty read without documents"

Write-Host "== 10 incubation"
$su = Call $cell POST "/research/startups" @{ name = "VerifyTech"; founders = @(@{ type = "student"; name = "S1" }) } 201
Call $cell POST "/research/startups/$($su.data.id)/stage" @{ stage = "prototype" } | Out-Null
Call $cell POST "/research/startups/$($su.data.id)/stage" @{ stage = "incubated"; funding_paise = 50000000 } | Out-Null
Call $iqac GET "/research/startups" | Out-Null

Write-Host "== 11 API score"
$cs = Call $hod POST "/research/api-score/compute?inline=true" @{ department_id = $null; period_from = "$($year - 1)-04-01"; period_to = "$year-03-31" } 202
$own = Call $fa GET "/research/api-score?staff_id=self"
Assert ($own.data.total -ge 0 -and $own.data.breakdown.publications) "own breakdown"
Call $fe GET "/research/api-score?staff_id=$($own.data.staff_id)" $null 404 | Out-Null
Assert (@((Call $hod GET "/research/api-score/rankings").data).Count -gt 0) "department rankings"

Write-Host "== 12 stats / evidence / gating"
Call $cell GET "/research/stats?year=$year&publish=true" | Out-Null
Call $cell POST "/research/evidence-pack?criterion=3.3" $null 202 | Out-Null
Assert ((Call $colB GET "/research/publications").meta.pagination.total -ge 0) "college admin: college scope"
Call $aud GET "/research/publications" | Out-Null
Call $aud POST "/research/patents" @{ title = "Auditor patent" } 403 | Out-Null
Write-Host "Phase 30 verification complete"
