# Phase 42 — Flutter mobile app: the API contract points the app depends on (Prompts/42 §42.11). Run after the full
# demo seed + `seed_demo_institution.py --only mobile`. Written in the development-only run; not executed yet.
# Device / emulator checks are the 42.12 checklist. Saves /portal/config snapshots for tool/check_portal_parity.dart.
param([string]$BaseUrl = "http://localhost:8000/api/v1")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl

$inst = @{ institution = "demo-uni" }
$root = $BaseUrl -replace "/api/v1$", ""
$snap = Join-Path $PSScriptRoot "../../../flutter/tool/portal_config"
New-Item -ItemType Directory -Force -Path $snap | Out-Null

Write-Host "== 1 /mobile/config"
$cfg = (Invoke-RestMethod "$BaseUrl/mobile/config?platform=android&app_version=1.0.0&institution_slug=demo-uni").data
foreach ($k in "min_versions", "force_update_below", "store_urls", "feature_hints", "write_queue", "screenshot_block_routes") { Assert ($null -ne $cfg.$k) "mobile config $k" }
Assert ($cfg.mobile_enabled) "mobile.app enabled"
$old = (Invoke-RestMethod "$BaseUrl/mobile/config?platform=android&app_version=0.0.1").data
Assert ($old.update_available) "old version → update available"

Write-Host "== 2 /auth/me + /portal/config + /dashboard per role"
$personas = @{ student = "student.1"; parent = "parent.1"; faculty = "faculty.1"; alumni = "alumni.1"; warden = "warden.h1"; gate = "gate.h1"; scholar = "scholar.1"; recruiter = "recruiter.1"; driver = "driver.1" }
$roleOf = @{ student = "student"; parent = "parent"; faculty = "faculty"; alumni = "alumni"; warden = "hostel_warden"; gate = "hostel_gate_staff"; scholar = "research_scholar"; recruiter = "recruiter"; driver = "driver" }
foreach ($p in $personas.Keys) {
  try { $t = Login $personas[$p] (Get-DemoPassword $roleOf[$p]) $inst } catch { Write-Host "  skip $p (no demo user)"; continue }
  $me = (Call $t GET "/auth/me").data
  Assert ($me.role_slugs.Count -ge 1 -and $me.permissions) "$p /auth/me"
  $pc = (Call $t GET "/portal/config").data
  $pc | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $snap "$p.json")
  $dash = (Call $t GET "/dashboard").data
  foreach ($w in @($dash.widgets)) { Assert (@("number", "sparkline", "bar", "line", "donut", "list", "actions", "table", "stat") -contains $w.type) "$p widget type $($w.type)" }
}

Write-Host "== 3 push devices"
$stu = Login "student.1" (Get-DemoPassword "student") $inst
$tok = "verify-fcm-$(Get-Random)"
Call $stu POST "/devices" @{ provider = "fcm"; platform = "android"; token = $tok; topics = @("role:student") } | Out-Null
Call $stu DELETE "/devices?provider=fcm&token=$tok" $null 204 | Out-Null

Write-Host "== 4 idempotent write-queue replay (SOS)"
$key = [guid]::NewGuid().ToString()
$a = Call $stu POST "/emergency/sos" @{ alert_type = "medical"; location = @{ text = "verify" } } 201 @{ "Idempotency-Key" = $key }
try { $b = Call $stu POST "/emergency/sos" @{ alert_type = "medical"; location = @{ text = "verify" } } 201 @{ "Idempotency-Key" = $key } } catch { $b = $null }
Assert ($null -eq $b -or $b.data.id -eq $a.data.id) "SOS replay returns the same alert"

Write-Host "== 6 association files"
$al = Invoke-RestMethod "$root/.well-known/assetlinks.json"
Assert ($al[0].target.package_name) "assetlinks package"
$aasa = Invoke-RestMethod "$root/.well-known/apple-app-site-association"
Assert ($aasa.applinks) "apple-app-site-association"

Write-Host "== 7 locales + tokens"
$te = Invoke-RestMethod "$BaseUrl/public/locales/te.json?institution=demo-uni"
Assert ($te) "telugu pack"
& (Get-VenvPython "$PSScriptRoot/../..") "$PSScriptRoot/../check_tokens_sync.py"
Assert ($LASTEXITCODE -eq 0) "tokens in sync"

Write-Host "== 8 visibility parity"
$hod = Login "hod.cse" (Get-DemoPassword "hod") $inst
$s = Call $hod GET "/students?limit=1"
Assert (-not ($s.meta.visibility.scopes -contains "all")) "HOD sees department scope only"
Summary "42"
