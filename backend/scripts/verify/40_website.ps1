# Phase 40 — public website, catalogue, admission entry & marketing site (Prompts/40 §40.11). Run after
# `seed_demo_institution.py --type university --only website` (demo-uni; APP_ENV=development; EDGE_TOKEN set in .env).
# Written in the development-only run; not executed yet. Users: inst.admin, registrar, hod.cse, college.admin.b,
# admissions, student.1 (demo-uni), superadmin and public calls.
param([string]$BaseUrl = "http://localhost:8000/api/v1")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl

$inst = @{ institution = "demo-uni" }
$root = $BaseUrl -replace "/api/v1$", ""
$sa = Login-SuperAdmin
$admin = Login "inst.admin" (Get-DemoPassword "institution_admin") $inst
$reg = Login "registrar" (Get-DemoPassword "registrar") $inst
$stu = Login "student.1" (Get-DemoPassword "student") $inst

Write-Host "== 1 public site + SSR"
$site = Invoke-RestMethod "$BaseUrl/public/site?slug=demo-uni"
Assert ($site.data.institution.name) "institution block"
Assert ($site.data.sections.Count -ge 3) "sections"
$r = Invoke-WebRequest "$root/site/demo-uni/"
Assert ($r.Content -match "<title>") "SSR title"
Assert ($r.Content -match "CollegeOrUniversity") "JSON-LD"
$etag = $r.Headers["ETag"]
try { Invoke-WebRequest "$root/site/demo-uni/" -Headers @{ "If-None-Match" = $etag } | Out-Null; throw "expected 304" } catch { Assert ($_.Exception.Response.StatusCode.value__ -eq 304) "304 on If-None-Match" }

Write-Host "== 2 draft / preview / publish / rollback"
$cfg = (Call $reg GET "/website/config").data
$cfg.hero.title = "Verify hero $(Get-Random)"
Call $reg PUT "/website/config" $cfg | Out-Null
$tok = (Call $reg POST "/website/config/preview-token" @{}).data
$prev = Invoke-WebRequest "$root$($tok.url)"
Assert ($prev.Content -match [regex]::Escape($cfg.hero.title)) "preview shows the draft"
Call $reg POST "/website/config/publish" @{ notes = "verify" } | Out-Null
$v = (Call $reg GET "/website/config/versions").data
Assert ($v.Count -ge 2) "versions"
Call $reg POST "/website/config/rollback/$($v[-1].version)" @{} | Out-Null

Write-Host "== 3 content sanitising"
$c = Call $reg POST "/website/content" @{ section = "about"; slug = "verify-$(Get-Random)"; title = "Verify"; body = "<p>ok</p><script>alert(1)</script>"; is_published = $true } 201
Assert (-not ($c.data.body -match "<script")) "script stripped"

Write-Host "== 4 notices + RSS"
$n = Call $reg POST "/website/notices" @{ title = "Verify notice"; category = "general"; body = "x"; is_published = $true } 201
$rss = Invoke-WebRequest "$BaseUrl/public/site/notices.rss?slug=demo-uni"
Assert ($rss.Headers["Content-Type"] -like "application/rss+xml*") "RSS"

Write-Host "== 6 enquiries"
$e = Invoke-RestMethod -Method Post "$BaseUrl/public/site/enquiries?slug=demo-uni" -ContentType "application/json" -Body (@{ name = "Verify"; email = "v@example.test"; message = "Fee details please" } | ConvertTo-Json)
Assert ($e.data.reference) "reference"
Call $stu GET "/website/enquiries" $null 403 | Out-Null

Write-Host "== 7 catalogue"
$cat = Invoke-RestMethod "$BaseUrl/public/catalogue?slug=demo-uni"
Assert ($cat.data.Count -ge 1) "programmes"

Write-Host "== 8 admissions entry"
Invoke-RestMethod "$BaseUrl/public/site/admissions?slug=demo-uni" | Out-Null

Write-Host "== 11 SEO"
$sm = Invoke-WebRequest "$root/sitemap.xml?slug=demo-uni"
Assert ($sm.Content -match "<urlset") "sitemap"
$rb = Invoke-WebRequest "$root/robots.txt"
Assert ($rb.Content -match "Disallow: /admin") "robots"

Write-Host "== 13 marketing"
Call $sa PUT "/platform/marketing" @{ hero = @{ title = "Verify marketing" } } | Out-Null
Call $sa POST "/platform/marketing/publish" @{} | Out-Null
$m = Invoke-RestMethod "$BaseUrl/public/marketing"
Assert ($m.data.hero.title -eq "Verify marketing") "marketing published"
Call $admin PUT "/platform/marketing" @{ hero = @{ title = "x" } } 403 | Out-Null
$p = Invoke-RestMethod "$BaseUrl/public/pricing"
Assert ($p.data.Count -ge 1) "pricing"

Write-Host "Phase 40 verification passed"
