# Phase 43 — testing, security & privacy hardening (Prompts/43 §43.11). Run after the full demo seed +
# `seed_demo_institution.py --only hardening`. Written in the development-only run; not executed yet.
# Users: privacy.off, security.off, inst.admin, registrar, student.1, parent.1, hod.cse, auditor.tmp, college.admin.b.
param([string]$BaseUrl = "http://localhost:8000/api/v1")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl

$inst = @{ institution = "demo-uni" }
$root = $BaseUrl -replace "/api/v1$", ""
$py = Get-VenvPython "$PSScriptRoot/../.."
$priv = Login "privacy.off" (Get-DemoPassword "privacy_officer") $inst
$sec = Login "security.off" (Get-DemoPassword "security_officer") $inst
$admin = Login "inst.admin" (Get-DemoPassword "institution_admin") $inst
$stu = Login "student.1" (Get-DemoPassword "student") $inst

Write-Host "== 1-4 static / golden / isolation / immutability suites"
foreach ($s in "static", "golden", "visibility", "immutability") {
  & $py "$PSScriptRoot/run_all.py" --suite $s
  Assert ($LASTEXITCODE -eq 0) "suite $s green"
}

Write-Host "== 5 golden through the API"
$g = (Call $admin POST "/qa/golden/run" @{}).data
Assert ($g.passed -eq $g.total) "golden $($g.passed)/$($g.total)"

Write-Host "== 7 security headers + CORS"
$h = Invoke-WebRequest "$root/health"   # /health is mounted at the app root, not under /api/v1
foreach ($k in "X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy", "Permissions-Policy", "Cross-Origin-Opener-Policy") { Assert ($h.Headers[$k]) "header $k" }
Assert ($h.Headers["Content-Security-Policy"] -or $h.Headers["Content-Security-Policy-Report-Only"]) "CSP header"
$jw = Invoke-RestMethod "$root/.well-known/jwks.json"
Assert ($null -ne $jw.keys) "jwks.json"

Write-Host "== 9 input guards"
# a real 26 MB body: pwsh 7 will not send a forged Content-Length that disagrees with the body
$big = '{"x":"' + ('a' * 26MB) + '"}'
$ob = Invoke-WebRequest "$BaseUrl/consents/bulk" -Method Post -Headers @{ Authorization = "Bearer $stu" } -ContentType "application/json" -Body $big -SkipHttpErrorCheck
Assert (@(400, 413) -contains [int]$ob.StatusCode) "oversized body refused"
$big = $null
$deep = ("[" * 200) + ("]" * 200)
try { Call $stu POST "/consents/bulk" $deep 400 | Out-Null } catch { }
try { Call $admin POST "/integrations/webhooks" @{ name = "ssrf"; url = "https://10.0.0.1/hook"; events = @("ping") } 422 | Out-Null } catch { }

Write-Host "== 11 consents"
$b = (Call $stu GET "/privacy/consent-banner").data
Assert ($b.purposes.Count -ge 10) "purposes"
Call $stu POST "/consents/bulk" @{ grants = @{ communication_marketing = $false; photo_media = $true; location = $true }; notice_version = $b.notice_version } | Out-Null
Call $stu POST "/consents/location/withdraw" @{} | Out-Null
$r = (Call $priv GET "/privacy/consents/report?purpose=communication_marketing").data
Assert ($r.counts.communication_marketing) "consent report counts"
Call (Login "hr" (Get-DemoPassword "hr_officer") $inst) GET "/privacy/consents/report" $null 403 | Out-Null

Write-Host "== 12 DSR workflow"
$d = (Call $stu POST "/data-subject-requests" @{ request_type = "export" } 201).data
Assert ($d.status -eq "received" -and $d.due_at) "DSR received with due date"
Call $priv POST "/data-subject-requests/$($d.id)/action" @{ action = "start" } 409 | Out-Null   # identity first
Call $priv POST "/data-subject-requests/$($d.id)/action" @{ action = "verify_identity" } | Out-Null
$st = (Call $priv POST "/data-subject-requests/$($d.id)/action" @{ action = "start" }).data
Assert ($st.status -eq "in_progress") "started"
Call $priv POST "/data-subject-requests/$($d.id)/action" @{ action = "extend"; reason = "verify" } | Out-Null
Call $priv POST "/data-subject-requests/$($d.id)/action" @{ action = "extend"; reason = "again" } 409 | Out-Null
$dash = (Call $priv GET "/privacy/dsr/dashboard").data
Assert ($dash.total -ge 25) "DSR dashboard"

Write-Host "== 13 PII inventory + masking"
$inv = (Call $priv GET "/privacy/pii-inventory").data
Assert ($inv.Count -ge 50) "inventory fields"
$ma = (Call $priv POST "/privacy/masking-audit" @{}).data
Assert ($ma.ok) "masking audit ok"

Write-Host "== 14 posture + trackers"
$p = (Call $sec POST "/security/posture/check" @{}).data
Assert ($p.items.Count -ge 10 -and $null -ne $p.score) "posture items + score"
$v = (Call $sec GET "/security/vapt").data
Assert ($v.gate) "vapt gate"
$iso = (Call $sec GET "/security/iso-readiness").data
Assert ($iso.controls_total -ge 20) "iso controls"
Call (Login "college.admin.b" (Get-DemoPassword "college_admin") $inst) GET "/security/posture" $null 403 | Out-Null
Call (Login "auditor.tmp" (Get-DemoPassword "auditor") $inst) GET "/security/posture" | Out-Null

Write-Host "== 15 access matrix"
$m = (Call $admin GET "/qa/access-matrix").data
Assert ($m.diff_vs_docs.Count -eq 0) "no unexpected grants"
Summary "43"
