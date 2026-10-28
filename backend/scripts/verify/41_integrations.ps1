# Phase 41 — integrations hub, platform APIs & data migration toolkit (Prompts/41 §41.11). Run after
# `seed_demo_institution.py --type university --only integrations` (demo-uni; APP_ENV=development).
# Written in the development-only run; not executed yet. Users: inst.admin, student.1 (demo-uni) and an API key.
param([string]$BaseUrl = "http://localhost:8000/api/v1")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl

$inst = @{ institution = "demo-uni" }
$admin = Login "inst.admin" (Get-DemoPassword "institution_admin") $inst
$stu = Login "student.1" (Get-DemoPassword "student") $inst

Write-Host "== 1 catalogue + capabilities + connection test"
$prov = (Call $admin GET "/integrations/providers").data
Assert ($prov.Count -ge 20) "provider catalogue"
$caps = (Call $admin GET "/integrations/capabilities").data
$c = $caps | Where-Object { $_.connection_id } | Select-Object -First 1
$t = (Call $admin POST "/integrations/connections/$($c.connection_id)/test" @{ action = "ping" }).data
Assert ($t.ok) "mock connection test ok"
$conn = (Call $admin GET "/integrations/connections").data
Assert (-not (($conn | ConvertTo-Json -Depth 6) -match '"secret"\s*:\s*"[^*]')) "secrets redacted"

Write-Host "== 2 API key (scoped, X-API-Key)"
$k = (Call $admin POST "/integrations/api-keys" @{ name = "verify"; scopes = @("students:read") } 201).data
$r = Invoke-RestMethod "$BaseUrl/students?limit=1" -Headers @{ "X-API-Key" = $k.secret }
Assert ($r.success) "API key reads students"
try { Invoke-RestMethod "$BaseUrl/fees/invoices" -Headers @{ "X-API-Key" = $k.secret } | Out-Null; throw "expected 403" } catch { Assert ($_.Exception.Response.StatusCode.value__ -eq 403) "scope enforced" }
Call $admin DELETE "/integrations/api-keys/$($k.id)" $null 204 | Out-Null
try { Invoke-RestMethod "$BaseUrl/students?limit=1" -Headers @{ "X-API-Key" = $k.secret } | Out-Null; throw "expected 401" } catch { Assert ($_.Exception.Response.StatusCode.value__ -eq 401) "revoked key refused" }

Write-Host "== 3 webhooks (signed test delivery, retry)"
$w = (Call $admin POST "/integrations/webhooks" @{ name = "verify"; url = "https://hooks.example.test/verify"; events = @("student.enrolled") } 201).data
Assert ($w.secret) "secret shown once"
Call $admin POST "/integrations/webhooks/$($w.id)/test" @{ event_type = "ping" } | Out-Null
$d = (Call $admin GET "/integrations/deliveries?webhook_id=$($w.id)").data
Assert ($d.Count -ge 1) "delivery recorded"
Call $admin DELETE "/integrations/webhooks/$($w.id)" $null 204 | Out-Null

Write-Host "== 4 imports (templates, upload, validate)"
$tpl = (Call $admin GET "/imports/templates").data
Assert (($tpl | Where-Object { $_.entity -eq "students" })) "students template"
$imps = (Call $admin GET "/imports").data
Assert ($imps.Count -ge 3) "seeded imports"

Write-Host "== 5 exports + RBAC"
$e = (Call $stu POST "/exports/users/me" @{ include = @() }).data
Assert ($e.job_id) "self export queued"
Call $stu GET "/integrations/connections" $null 403 | Out-Null
Write-Host "Phase 41 verify: OK"
