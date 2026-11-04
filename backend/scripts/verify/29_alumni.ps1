# Phase 29 — alumni, endowments & fundraising (Prompts/29 §29.11). Run after
# `seed_demo_institution.py --only alumni`. Written in the development-only run; not executed yet.
param([string]$BaseUrl = "http://localhost:8000/api/v1", [string]$Institution = "demo-uni")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl

$coord = Login "alumni.coord"
$acct = Login "accountant"
$plc = Login "placement"
$hod = Login "hod.cse"
$iqac = Login "iqac"
$aa = Login "alumni.a"
$ab = Login "alumni.b"
$stu = Login "student.1"
$aud = Login "auditor.tmp"

Write-Host "== 1 stats"
$s = Call $coord GET "/alumni/stats"
Assert ($s.data.total -ge 1000 -and $s.data.verified_pct -gt 30 -and $s.data.verified_pct -lt 50) "verified % near the seeded 40 %"
Assert ($s.data.employed_pct -gt 50) "employed % from current employment"
Call $aa GET "/alumni/stats" $null 403 | Out-Null
Assert ((Call $iqac GET "/alumni/stats").data.total -eq $s.data.total) "IQAC reads aggregates"

Write-Host "== 2 self profile"
$me = Call $aa GET "/alumni/me"
Assert ($me.data.is_verified -and $me.data.consent_contact) "alumni.a verified with contact consent"
$emp = Call $aa POST "/alumni/me/employment" @{ company = "Verify Corp"; designation = "Engineer"; is_current = $true } 201
$me2 = Call $aa GET "/alumni/me"
Assert ((@($me2.data.employment | Where-Object { $_.is_current })).Count -eq 1 -and $me2.data.current_company -eq "Verify Corp") "new current job closes the previous one"
Assert ((Call $aa GET "/alumni/me/engagement").data.score -ge 0) "engagement recomputed"

Write-Host "== 3 claim (public)"
Call $null POST "/alumni/claim?institution=$Institution" @{ registration_number = "NOPE-000"; graduation_year = 2020; email = "x@example.com" } 404 | Out-Null
$legacy = (Call $coord GET "/alumni/profiles?q=ALM-LEGACY-0001").data[0]
# rerun: the previous run left this legacy profile claimed (claim_status lives in alumni_meta)
& (Get-VenvPython (Resolve-Path (Join-Path $PSScriptRoot "..\.."))) (Join-Path $PSScriptRoot "_sql.py") --write "UPDATE institution_settings SET value = value - 'claim_status' WHERE category = 'alumni_meta' AND key = 'profile:$($legacy.id)'" | Out-Null
$claim = Call $null POST "/alumni/claim?institution=$Institution" @{ registration_number = "ALM-LEGACY-0001"; graduation_year = $legacy.graduation_year; email = "legacy.alumnus@example.com" }
Assert ($claim.data.claim_token) "OTP sent for the legacy profile"
1..3 | ForEach-Object { Call $null POST "/alumni/claim/verify?institution=$Institution" @{ claim_token = $claim.data.claim_token; otp = "000000" } 422 | Out-Null }
Call $null POST "/alumni/claim/verify?institution=$Institution" @{ claim_token = $claim.data.claim_token; otp = "000000" } 429 | Out-Null
$v = Call $coord POST "/alumni/profiles/$($legacy.id)/verify" @{ approve = $true; remarks = "verified by document" }
Assert ($v.data.claim_status -eq "verified") "coordinator verifies"

Write-Host "== 4 directory / consent"
$dir = Call $aa GET "/alumni/directory?city=Bengaluru"
$b = @($dir.data.items | Where-Object { -not $_.contactable })[0]
Assert (@($dir.data.items | Where-Object { $_.fields.email -and -not $_.contactable }).Count -eq 0) "no contacts without consent"
Call $stu GET "/alumni/directory" $null 403 | Out-Null
$abMe = Call $ab GET "/alumni/me"
Call $aa POST "/alumni/directory/$($abMe.data.id)/contact-request" @{ message = "Hello from the verify script" } 403 | Out-Null
$c = Call $ab POST "/alumni/directory/$($me.data.id)/contact-request" @{ message = "Hello from the verify script" } 201
Assert ($c.data.relayed) "contact relayed to alumni.a"
$hp = Call $hod GET "/alumni/profiles?scope=department"
Assert ($hp.meta.pagination.total -ge 0) "HOD reads department alumni"
$ap = Call $aud GET "/alumni/profiles"
Assert (@($ap.data | Where-Object { $_.email -and $_.email -notmatch '\*' }).Count -eq 0) "auditor sees masked contacts"
Call $aud GET "/alumni/profiles/export" $null 403 | Out-Null

Write-Host "== 6 events"
$ev = Call $coord POST "/alumni/events" @{ title = "Verify reunion"; event_type = "reunion"; held_on = (Get-Date).AddDays(30).ToString("yyyy-MM-dd"); venue = "Main hall"; registration_fee_paise = 100000 } 201
Assert ($ev.data.event_id -and $ev.data.event_status -eq "scheduled") "alumni event on the Events engine"
$inv = Call $coord POST "/alumni/events/$($ev.data.id)/invite" @{ graduation_years = @((Get-Date).Year - 2) }
Assert ($inv.data.invited -ge 0) "segment invited"
$reg = Call $aa POST "/events/$($ev.data.event_id)/register" @{} 201
Assert ($reg.data.fee_invoice_id) "registration invoice (event_registration)"
Assert (@((Call $aa GET "/alumni/events/me").data | Where-Object { $_.id -eq $ev.data.id }).Count -eq 1) "my alumni events"

Write-Host "== 7 jobs"
$j = Call $aa POST "/alumni/jobs" @{ title = "Verify SDE"; company = "Verify Corp"; apply_url = "https://example.com/apply" } 201
Assert ($j.data.status -eq "pending") "moderated post pending"
$m = Call $coord POST "/alumni/jobs/$($j.data.id)/moderate" @{ approve = $true }
Assert ($m.data.status -eq "approved") "approved"
$k = Call $ab POST "/alumni/jobs/$($j.data.id)/click"
Assert ($k.data.clicks -ge 1) "click tracked"
Call $stu GET "/alumni/jobs" $null 403 | Out-Null
$lead = Call $plc POST "/alumni/jobs/$($j.data.id)/lead"
Assert ($lead.data.lead_company_id) "placement company lead"

Write-Host "== 8 fundraising"
$camp = Call $coord POST "/fundraising/campaigns" @{ title = "Verify endowment"; goal_paise = 500000000; is_restricted_fund = $true } 201
Call $aa POST "/fundraising/donate" @{ campaign_id = $camp.data.id; amount_paise = 5000 } 422 | Out-Null
$key = [guid]::NewGuid().ToString()
$o1 = Call $aa POST "/fundraising/donate" @{ campaign_id = $camp.data.id; amount_paise = 500000; wants_80g = $true; donor = @{ pan = "ABCPE1234F"; address = "Bengaluru" } } 201 @{ "Idempotency-Key" = $key }
$o2 = Call $aa POST "/fundraising/donate" @{ campaign_id = $camp.data.id; amount_paise = 500000; wants_80g = $true; donor = @{ pan = "ABCPE1234F"; address = "Bengaluru" } } 200 @{ "Idempotency-Key" = $key }
Assert ($o1.data.order.order_id) "gateway order created (replay returns the stored response)"
$off = Call $acct POST "/fundraising/donations" @{ donor_type = "individual"; donor_ref = @{ name = "Cheque Donor" }; campaign_id = $camp.data.id; amount_paise = 1000000; mode = "cheque"; on_date = (Get-Date).ToString("yyyy-MM-dd"); reference = "CHQ-0001" } 201
Assert ($off.data.mode -eq "cheque") "offline cheque recorded by the accountant"
$cc = Call $coord GET "/fundraising/campaigns/$($camp.data.id)"
Assert ($cc.data.raised_paise -ge 1000000) "raised updated"
Call $coord POST "/fundraising/campaigns/$($camp.data.id)/close" | Out-Null
Call $acct POST "/fundraising/donations" @{ donor_type = "individual"; donor_ref = @{ name = "Late Donor" }; campaign_id = $camp.data.id; amount_paise = 100000; mode = "upi"; on_date = (Get-Date).ToString("yyyy-MM-dd"); reference = "UPI-1" } 409 | Out-Null

Write-Host "== 9 80G"
Call $acct POST "/fundraising/donations" @{ donor_type = "individual"; donor_ref = @{ name = "No PAN" }; amount_paise = 500000; mode = "bank_transfer"; on_date = (Get-Date).ToString("yyyy-MM-dd"); reference = "UTR-1"; wants_80g = $true } 422 | Out-Null
$r = Call $acct POST "/fundraising/donations/$($off.data.id)/receipt-80g" $null 422
$d80 = Call $acct POST "/fundraising/donations" @{ donor_type = "individual"; donor_ref = @{ name = "Small Donor" }; amount_paise = 150000; mode = "bank_transfer"; on_date = (Get-Date).ToString("yyyy-MM-dd"); reference = "UTR-2"; wants_80g = $true } 201
Assert ($d80.data.receipt_no -match '^80G/') "receipt number from the 80g:{fy} sequence"
$re = Call $acct POST "/fundraising/donations/$($d80.data.id)/receipt-80g/reissue" @{ donor_name = "Small Donor (corrected)"; reason = "Name correction" }
Assert ($re.data.superseded_document_id) "reissue supersedes"
$fy = if ((Get-Date).Month -ge 4) { (Get-Date).Year } else { (Get-Date).Year - 1 }
$fyl = "$fy-$((($fy + 1) % 100).ToString('00'))"
Assert ((Call $acct GET "/fundraising/80g/register?fy=$fyl").data.Count -ge 1) "80G register"
Assert ((Call $acct GET "/fundraising/80g/10bd?fy=$fyl" $null 202).data.job_id) "10BD job"
$mine = Call $ab GET "/fundraising/donations/me"
Assert (@($mine.data | Where-Object { $_.alumni_id -and $_.alumni_id -ne $abMe.data.id }).Count -eq 0) "own donations only"

Write-Host "== 10 requests bridge"
Assert ((Call $aa GET "/degrees/me" $null 200) -ne $null) "degree download route reachable"

Summary "Phase 29"
