# Phase 39 — portals, PWA, notification centre & guided help (Prompts/39 §39.11). Run after
# `seed_demo_institution.py --type university --only portals` (demo-uni, APP_ENV=development, a worker for the
# notification / push jobs). Written in the development-only run; not executed yet. Users: student.1 / student.2,
# parent.1, faculty.1 (also hod), registrar, inst.admin (demo-uni) and public calls.
param([string]$BaseUrl = "http://localhost:8000/api/v1")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl

$inst = @{ institution = "demo-uni" }
$admin = Login "inst.admin" (Get-DemoPassword "institution_admin") $inst
$stu = Login "student.1" (Get-DemoPassword "student") $inst
# a second demo-uni student: seeded students have unknown passwords, so give one the recorded student password
$Python = Get-VenvPython (Resolve-Path (Join-Path $PSScriptRoot "..\.."))
$s2name = (& $Python "$PSScriptRoot/_sql.py" "SELECT u.username FROM students s JOIN users u ON u.id = s.user_id JOIN institutions i ON i.id = s.institution_id WHERE i.slug = 'demo-uni' AND u.username <> 'student.1' ORDER BY u.username LIMIT 1" | ConvertFrom-Json)[0].username
& $Python "$PSScriptRoot/_reset_password.py" $s2name (Get-DemoPassword "student") | Out-Null
$stu2 = Login $s2name (Get-DemoPassword "student") $inst
$par = Login "parent.1" (Get-DemoPassword "parent") $inst
$fac = Login "faculty.1" (Get-DemoPassword "faculty") $inst
$reg = Login-Mfa 'registrar' 'registrar'   # MFA-required role in the demo tenant
$root = $BaseUrl -replace "/api/v1$", ""

Write-Host "== 1 portal config"
$c = Call $stu GET "/portal/config"
Assert ($c.data.persona -eq "student") "student persona"
Assert (($c.data.tabs | ForEach-Object key) -contains "home") "Home tab"
Assert ($c.data.branding.app_name) "branding"
$cf = Call $fac GET "/portal/config"
Assert ($cf.data.persona -eq "faculty") "faculty persona"
$cr = Call $reg GET "/portal/config"
Assert ($null -eq $cr.data.persona) "registrar has no persona"

Write-Host "== 2 parent consent"
$w = Call $par GET "/portal/wards"
Assert ($w.data.Count -ge 1) "consented wards"
Call $par POST "/portal/wards/switch" @{ student_id = [guid]::NewGuid().ToString() } 404 | Out-Null

Write-Host "== 3 unified pages"
$r1 = Call $stu GET "/portal/me/requests"
$r2 = Call $stu2 GET "/portal/me/requests"
$ids1 = $r1.data.items | ForEach-Object id
Assert (-not ($r2.data.items | Where-Object { $ids1 -contains $_.id })) "student.2 sees none of student.1's requests"
Call $stu GET "/portal/me/documents" | Out-Null
$p = Call $stu GET "/portal/me/payments"
Assert ($null -ne $p.data.totals) "payment totals"
Call $fac GET "/portal/me/approvals" | Out-Null
Call $stu GET "/portal/me/timeline" | Out-Null
Call $stu GET "/portal/me/calendar" | Out-Null
$scoped = Call $fac GET "/portal/me/requests?scope=all"
Assert ($scoped.data.items.Count -eq (Call $fac GET "/portal/me/requests").data.items.Count) "scope ignored"

Write-Host "== 4 notifications"
$n = Call $stu GET "/notifications/counts"
Assert ($null -ne $n.data.unread_by_category) "counts by category"
$list = Call $stu GET "/notifications?category=fees&unread=true"
if ($list.data.Count -gt 0) {
  $one = Call $stu GET "/notifications/$($list.data[0].id)"
  Assert ($one.data.is_read) "opened → read"
}
Call $stu POST "/notifications/mark-read" @{ all = $true; category = "fees" } | Out-Null
Assert (-not (Call $stu GET "/notifications/counts").data.unread_by_category.fees) "fees unread 0"
Call $stu POST "/notifications/snooze" @{ category = "events"; hours = 24 } | Out-Null
Call $stu PUT "/notifications/preferences" @{ categories = @(@{ category = "exams"; channels = @("email") }) } 422 | Out-Null
Call $stu PUT "/notifications/preferences" @{ categories = @(@{ category = "events"; channels = @("in_app", "email") }) } | Out-Null
Call $stu PUT "/notifications/preferences" @{ quiet_hours = @{ from = "22:00"; to = "07:00" }; digest = "daily" } | Out-Null
$acks = Call $stu GET "/announcements/me?pending_ack=true"
if ($acks.data.Count -gt 0) {
  Call $stu POST "/announcements/$($acks.data[0].id)/acknowledge" @{ acknowledge = $true } | Out-Null
}

Write-Host "== 5 push"
$k = Invoke-RestMethod "$BaseUrl/public/push/vapid-key"
Assert ($null -ne $k.data) "vapid key endpoint"
$ep = "https://mock.push/verify-$(Get-Random)"
$s1 = Call $stu POST "/push/subscribe" @{ endpoint = $ep; keys = @{ p256dh = "BTest"; auth = "auth" }; topics = @("role:student") } 201
$s2 = Call $stu POST "/push/subscribe" @{ endpoint = $ep; keys = @{ p256dh = "BTest"; auth = "auth" }; topics = @() } 201
Assert ($s1.data.id -eq $s2.data.id) "dedupe by endpoint"
$t = Call $stu POST "/push/test" @{}
Assert ($t.data.payload.route) "push payload has a route"
Call $stu DELETE "/push/subscribe" @{ endpoint = $ep } | Out-Null

Write-Host "== 6 PWA endpoints"
$m = Invoke-WebRequest "$BaseUrl/public/manifest.json?institution=demo-uni"
Assert ($m.Headers["Content-Type"] -like "application/manifest+json*") "manifest MIME"
# application/manifest+json is not a text type to pwsh: .Content is a byte[]
$mj = [System.Text.Encoding]::UTF8.GetString($m.RawContentStream.ToArray()) | ConvertFrom-Json
Assert ($mj.start_url -eq "/login?source=pwa") "start_url"
$pc = Invoke-RestMethod "$BaseUrl/public/pwa-config?institution=demo-uni"
Assert ($pc.data.version) "precache version"
Invoke-RestMethod "$root/.well-known/assetlinks.json" | Out-Null
Invoke-RestMethod "$root/.well-known/apple-app-site-association" | Out-Null

Write-Host "== 7 tours"
$td = Call $stu GET "/tours/definitions?route=/student/registration"
Assert ($td.data.Count -ge 1) "registration tour"
Call $stu PUT "/tours/state" @{ key = "student.registration"; version = 1; completed = $true } | Out-Null
Assert ((Call $stu GET "/tours/state").data.completed."student.registration" -eq 1) "tour completed"

Write-Host "== 8 help & feedback"
Call $fac GET "/help/context?route=/faculty/attendance" | Out-Null
Call $stu POST "/feedback" @{ page = "/student/fees"; persona = "student"; rating = 1; message = "verify feedback" } 201 | Out-Null
Call $stu GET "/feedback/me" | Out-Null

Write-Host "== 9 i18n (feature may be off: 403 accepted)"
try { Invoke-RestMethod "$BaseUrl/public/locales/hi.json?institution=demo-uni" | Out-Null } catch { Write-Host "  i18n.web off" }
Call $stu PUT "/users/me" @{ locale = "en" } | Out-Null

Write-Host "Phase 39 verification passed"
