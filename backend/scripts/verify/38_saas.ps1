# Phase 38 — super admin & SaaS operations (Prompts/38 §38.11). Run after
# `seed_demo_institution.py --type university --only saas` (demo-uni + 5 SaaS tenants, APP_ENV=development, a worker
# for the jobs). Written in the development-only run; not executed yet. Users: superadmin / superadmin.2 /
# support.agent (platform), inst.admin (demo-uni), inst.admin.c (demo-college), college.admin.b / registrar /
# student.1 (demo-uni). The dev clock steps (dunning, SLA, auto-stop, registration expiry) call the Beat bodies through
# the /_dev routes of earlier phases where they exist and are otherwise checked through their visible state.
param([string]$BaseUrl = "http://localhost:8000/api/v1")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl

function Get-Pw($label) {
  $file = Get-CredentialsFile
  $line = Get-Content $file | Where-Object { $_ -match "^\|\s*$([regex]::Escape($label))\s*\|" } | Select-Object -Last 1
  if (-not $line) { throw "no credentials for '$label' in LOCAL_TEST_CREDENTIALS.md" }
  return (($line -split '\|')[3].Trim() -replace '`', '')
}
function Wait-Job($session, $jobId, [int]$seconds = 180) {
  for ($i = 0; $i -lt $seconds; $i += 2) {
    $r = Call $session GET "/jobs/$jobId"
    if ($r.data.status -in @("succeeded", "failed", "cancelled")) { return $r.data }
    Start-Sleep -Seconds 2
  }
  throw "job $jobId did not finish"
}

$sa = Login-SuperAdmin
$sa2 = Login "superadmin.2" (Get-Pw "super_admin")
$agent = Login "support.agent" (Get-Pw "support_agent")
$admin = Login "inst.admin" (Get-DemoPassword "institution_admin") @{ institution = "demo-uni" }
$adminC = Login "inst.admin.c" (Get-Pw "institution_admin (demo-college)") @{ institution = "demo-college" }
$colB = Login "college.admin.b" (Get-DemoPassword "college_admin") @{ institution = "demo-uni" }
$reg = Login-Mfa 'registrar' 'registrar'
$stu = Login "student.1" (Get-DemoPassword "student") @{ institution = "demo-uni" }

$tenants = (Call $sa GET "/platform/institutions").data
$uni = $tenants | Where-Object { $_.slug -eq "demo-uni" }
$col = $tenants | Where-Object { $_.slug -eq "demo-college" }

Write-Host "== 1 dashboard"
$d = Call $sa GET "/platform/dashboard?refresh=true"
Assert ($d.data.tenants_total -ge 6) "6 tenants"
Assert ($d.data.mrr_paise -gt 0) "MRR > 0"
Assert ($null -ne $d.data.tickets_open_by_priority) "tickets by priority"
Call $agent GET "/platform/dashboard" | Out-Null
Call $admin GET "/platform/dashboard" $null 403 | Out-Null

Write-Host "== 2 onboarding by template"
$slug = "verify-uni-$(Get-Random -Maximum 9999)"
$on = Call $sa POST "/platform/institutions" @{ template = "university"; trial = $true; plan_code = "university"; seed_demo = $false
  institution = @{ name = "Verify University"; slug = $slug; institution_type = "university" }
  admin = @{ username = "admin"; email = "admin@$slug.septronuniverse.in"; display_name = "Verify Admin" } } 201
Assert ($on.data.subscription_status -eq "trial") "trial subscription"
Assert ($on.data.forced_features.on -contains "institution.multi_college" -or $on.data.features_enabled -gt 0) "template features"
$aff = Call $sa POST "/platform/institutions" @{ template = "affiliated"; plan_code = "standard"
  institution = @{ name = "Verify Affiliated"; slug = "$slug-aff"; institution_type = "affiliated_college"; parent_university_name = "Verify University" }
  admin = @{ username = "admin"; email = "admin@$slug-aff.septronuniverse.in"; display_name = "Verify Admin" } } 201
Assert ($null -ne $aff.data.main_college_id) "affiliated: main college"
Call $sa POST "/platform/institutions" @{ template = "standalone"; institution = @{ name = "Dup"; slug = $slug; institution_type = "standalone_college" }; admin = @{ username = "admin"; email = "x@$slug.septronuniverse.in"; display_name = "X" } } 409 | Out-Null

Write-Host "== 3 lifecycle"
Call $sa POST "/platform/institutions/$($col.id)/status" @{ action = "suspend"; reason = "verification" } | Out-Null
Call $null POST "/auth/login" @{ identifier = "inst.admin.c"; password = (Get-Pw "institution_admin (demo-college)"); institution = "demo-college" } 403 | Out-Null
Call $sa POST "/platform/institutions/$($col.id)/status" @{ action = "activate"; reason = "verification done" } | Out-Null
$adminC = Login "inst.admin.c" (Get-Pw "institution_admin (demo-college)") @{ institution = "demo-college" }
Call $sa POST "/platform/institutions/$($on.data.institution.id)/status" @{ action = "archive"; reason = "no export" } $null 409 | Out-Null
$ex = Call $sa POST "/platform/institutions/$($on.data.institution.id)/export" @{ include = @("db", "files"); format = "json" } 202
$job = Wait-Job $sa $ex.data.job_id
Assert ($job.status -eq "succeeded") "export job"
Assert ($job.result.manifest.table_count -gt 50) "manifest lists tenant tables"
Call $sa POST "/platform/institutions/$($on.data.institution.id)/status" @{ action = "archive"; reason = "archived after export" } | Out-Null
Call $sa POST "/platform/institutions/$($on.data.institution.id)/erase" @{ confirm_slug = "wrong"; reason = "verify" } 422 | Out-Null
$e1 = Call $sa POST "/platform/institutions/$($on.data.institution.id)/erase" @{ confirm_slug = $slug; reason = "verify erase" } 202
Assert ($e1.data.status -eq "pending_approval") "four-eyes pending"
$e2 = Call $sa2 POST "/platform/institutions/$($on.data.institution.id)/erase" @{ confirm_slug = $slug; reason = "approved" } 202
Assert ((Wait-Job $sa2 $e2.data.job_id).status -eq "succeeded") "erase job"

Write-Host "== 4 tenant self-export"
Call $admin POST "/platform/institutions/$($uni.id)/export" @{ include = @("db") } 403 | Out-Null
$te = Call $admin POST "/billing/export" @{ include = @("db"); format = "csv" } 202
Assert ($null -ne $te.data.job_id) "tenant export job"
Call $stu POST "/billing/export" @{ include = @("db") } 403 | Out-Null

Write-Host "== 5 plans / subscriptions"
$plans = (Call $sa GET "/platform/plans").data
$standard = $plans | Where-Object { $_.code -eq "standard" }
$starter = $plans | Where-Object { $_.code -eq "starter" }
$prof = $plans | Where-Object { $_.code -eq "professional" }
Call $sa PUT "/platform/plans/$($standard.id)" @{ enabled_features = @($standard.enabled_features + "phd.core") } 422 | Out-Null
$pv = Call $sa GET "/platform/plans/$($starter.id)/change-preview?institution_id=$($uni.id)"
Assert (@($pv.data.features_disabled).Count -gt 0) "preview lists disabled features"
Call $sa POST "/platform/institutions/$($uni.id)/subscription/change" @{ plan_id = $starter.id; effective = "now" } 409 | Out-Null
$ch = Call $sa POST "/platform/institutions/$($col.id)/subscription/change" @{ plan_id = $standard.id; effective = "now" }
Assert ($ch.data.plan.code -eq "standard") "plan changed"
$rn = Call $sa POST "/platform/institutions/$($col.id)/subscription/renew" @{ billing_cycle = "yearly" }
Assert ($rn.data.invoices[0].number -match "^INV/FY\d{2}/\d{4}$") "invoice number format"
Assert ($rn.data.invoices[0].gst_paise -eq [math]::Round($rn.data.invoices[0].amount_paise * 0.18)) "GST 18%"

Write-Host "== 6 billing (tenant)"
$inv = (Call $adminC GET "/billing/invoices").data
Assert (@($inv | Where-Object { $_.institution_id -ne $col.id }).Count -eq 0) "own invoices only"
$open = $inv | Where-Object { $_.status -ne "paid" } | Select-Object -First 1
if ($open) { $p = Call $adminC POST "/billing/invoices/$($open.number)/pay" @{ mode = "gateway" }; Assert ($null -ne $p.data.order.order_id) "gateway order" }
Call $colB GET "/billing/subscription" $null 403 | Out-Null

Write-Host "== 7 usage"
$m = Call $sa POST "/platform/usage/meter" $null 202
Wait-Job $sa $m.data.job_id | Out-Null
$u = Call $sa GET "/platform/usage?institution_id=$($uni.id)"
Assert (@($u.data.months).Count -ge 1) "usage months"
Call $sa PUT "/platform/institutions/$($col.id)/usage-caps" @{ caps = @{ api_calls_per_day = 100 } } | Out-Null

Write-Host "== 8 impersonation"
$regUser = (Call $sa GET "/users?q=registrar" $null 200 @{ "X-Institution-Id" = $uni.id }).data[0]
$imp = Call $sa POST "/users/$($regUser.id)/impersonate" @{ reason = "ticket SPT/2026/0007" } 200 @{ "X-Institution-Id" = $uni.id }
$list = (Call $sa GET "/platform/impersonations?active=true").data
Assert (@($list).Count -ge 1) "active impersonation listed"
Call $sa2 POST "/platform/impersonations/$($imp.data.impersonation_log_id)/force-stop" @{ reason = "verification" } | Out-Null
Call $imp.data.access_token GET "/auth/me" $null 401 | Out-Null

Write-Host "== 9 support"
$t = Call $admin POST "/support/tickets" @{ subject = "Exam centre wrong"; description = "Hall tickets list the wrong centre"; priority = "high"; category = "exams" } 201
Assert ($t.data.ticket_number -match "^SPT/\d{4}/\d{4}$") "ticket number"
Call $agent POST "/support/tickets/$($t.data.id)/reply" @{ text = "Looking into it" } | Out-Null
Call $agent POST "/support/tickets/$($t.data.id)/reply" @{ text = "internal note"; internal = $true } | Out-Null
$tv = Call $admin GET "/support/tickets/$($t.data.id)"
Assert (@($tv.data.messages | Where-Object { $_.internal }).Count -eq 0) "internal note hidden from tenant"
Call $agent POST "/support/tickets/$($t.data.id)/status" @{ status = "resolved"; resolution = "Fixed" } | Out-Null
Call $admin POST "/support/tickets/$($t.data.id)/rate" @{ rating = 5 } | Out-Null
Call $agent GET "/support/tickets/$($t.data.id)/diagnostics" | Out-Null
Call $stu POST "/support/tickets" @{ subject = "x"; description = "xyz" } 403 | Out-Null
Call $adminC GET "/support/tickets/$($t.data.id)" $null 404 | Out-Null

Write-Host "== 10 help & feedback"
Call $admin GET "/help/articles?route=/admin/fees/collect" | Out-Null
$art = Call $admin POST "/help/admin/articles" @{ slug = "help:/admin/fees/collect"; title = "Our fee counter"; body = "Local steps" } 201
Call $agent POST "/help/admin/articles" @{ slug = "x-test"; title = "x"; body = "x" } 403 | Out-Null
Call $admin DELETE "/help/admin/articles/$($art.data.id)" $null 204 | Out-Null
Call $stu POST "/feedback" @{ page = "/student/results"; rating = 2; message = "Results page slow"; category = "bug" } 201 | Out-Null
$fb = (Call $agent GET "/platform/feedback?rating=2").data
Assert (@($fb).Count -ge 1) "feedback listed"
Call $sa POST "/platform/feedback/$($fb[0].id)/triage" @{ status = "planned"; respond_text = "On the roadmap" } | Out-Null
Call $sa POST "/platform/feedback/$($fb[0].id)/to-ticket" | Out-Null

Write-Host "== 11 announcements"
$an = Call $sa POST "/platform/announcements" @{ title = "University-only note"; body = "Hello universities"; audience = @{ type = "plan"; values = @("university") }; channels = @("banner") } 201
Assert (@((Call $reg GET "/platform/announcements/active").data | Where-Object { $_.id -eq $an.data.id }).Count -eq 1) "registrar sees it"
Assert (@((Call $adminC GET "/platform/announcements/active").data | Where-Object { $_.id -eq $an.data.id }).Count -eq 0) "demo-college does not"
Call $reg POST "/platform/announcements/$($an.data.id)/dismiss" | Out-Null

Write-Host "== 12 health & outages"
Assert (@((Call $sa GET "/platform/health/outages").data).Count -ge 1) "seeded msg91 outage"
$hrow = (Call $sa GET "/platform/health?status=failed").data[0]
Call $sa POST "/platform/health/retry" @{ connection_ids = @($hrow.connection_id) } 202 | Out-Null
Call $sa POST "/platform/health/connections/$($hrow.connection_id)/disable" @{ reason = "verification" } | Out-Null

Write-Host "== 13 read-only windows"
$start = (Get-Date).ToUniversalTime().AddMinutes(-1).ToString("o"); $end = (Get-Date).ToUniversalTime().AddHours(1).ToString("o")
$w = Call $admin POST "/platform/read-only/schedules" @{ reason = "Exam day"; starts_at = $start; ends_at = $end } 201
Call $admin POST "/support/tickets" @{ subject = "during RO"; description = "allowed path" } 201 | Out-Null
Call $colB POST "/platform/read-only/schedules" @{ reason = "nope"; starts_at = $start; ends_at = $end } 403 | Out-Null
Call $admin DELETE "/platform/read-only/schedules/$($w.data.id)" | Out-Null

Write-Host "== 14 platform settings"
Call $sa PUT "/platform/settings" @{ values = @{ "mobile.min_versions.android" = "2.3.0" } } | Out-Null
$mc = Call $null GET "/mobile/config?platform=android"
Assert ($mc.data.min_versions.android -eq "2.3.0") "mobile config reflects"
$cap = (Call $sa GET "/platform/settings").data | Where-Object { $_.key -eq "captcha" }
Assert ($cap.value.secret -in @("***", "")) "secret masked"

Write-Host "== 15 registration"
$rs = "verify-reg-$(Get-Random -Maximum 9999)"
$r = Call $null POST "/public/registrations" @{ institution_name = "Verify Reg College"; institution_type = "standalone_college"; slug = $rs; admin = @{ name = "Reg Admin"; email = "admin@$rs.septronuniverse.in" }; plan_code = "standard"; trial = $true } 201
Assert ($r.data.next -eq "verify_email") "verify next"
Call $null POST "/public/registrations" @{ institution_name = "Reserved"; institution_type = "standalone_college"; slug = "admin"; admin = @{ name = "X"; email = "x@reserved.septronuniverse.in" } } 422 | Out-Null
Call $sa POST "/platform/registrations/$($r.data.id)/action" @{ action = "verify" } | Out-Null
$dr = Call $null POST "/public/demo-requests" @{ name = "Lead"; email = "lead@verify.septronuniverse.in" } 201
$dl = (Call $sa GET "/platform/demo-requests?status=new").data | Where-Object { $_.id -eq $dr.data.id }
Call $sa PUT "/platform/demo-requests/$($dl.id)" @{ status = "contacted"; notes = "called" } | Out-Null

Write-Host "== 16 demo reset"
$demoCol = $tenants | Where-Object { $_.slug -eq "demo-college-2" }
Call $sa POST "/platform/institutions/$($demoCol.id)/reset" @{ confirm_slug = "demo-college-2" } 403 | Out-Null

Write-Host "== 17 platform audit"
$pa = Call $sa GET "/platform/audit?institution_id=$($col.id)"
Assert (@($pa.data | Where-Object { $_.action -in @("suspend", "activate") }).Count -ge 2) "lifecycle rows"
Assert (@((Call $sa GET "/platform/dashboard?refresh=true").data.chain_breaks).Count -ge 1) "chain break on dashboard"

Summary "Phase 38"
