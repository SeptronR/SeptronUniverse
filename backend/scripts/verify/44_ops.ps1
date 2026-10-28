# Phase 44 — deployment, CI/CD & operations: API contract points (Prompts/44 §44.11). Pipeline, rollback, restore
# drill and chaos steps run on staging per docs/Runbooks/*. Written in the development-only run; not executed yet.
param([string]$BaseUrl = "http://localhost:8000/api/v1")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl
$root = $BaseUrl -replace "/api/v1$", ""
$sa = Login-SuperAdmin
$stu = Login "student.1" (Get-DemoPassword "student") @{ institution = "demo-uni" }

Write-Host "== 4 readiness"
Assert ((Invoke-WebRequest "$root/health").StatusCode -eq 200) "/health"
$r = Invoke-RestMethod "$root/ready"; Assert ($r.checks) "/ready checks"

Write-Host "== 7 metrics"
try { Invoke-WebRequest "$root/metrics" -Headers @{ Authorization = "Bearer wrong" } | Out-Null } catch { Assert ($_.Exception.Response.StatusCode.value__ -eq 401) "metrics bearer (when METRICS_TOKEN set)" }

Write-Host "== 8 status page"
$s = (Invoke-RestMethod "$BaseUrl/public/status").data
Assert ($s.components.Count -ge 10) "components"
$inc = (Call $sa POST "/platform/ops/incidents" @{ title = "Verify incident"; components = @("payments"); message = "investigating" } 201).data
Call $sa POST "/platform/ops/incidents/$($inc.id)/resolve" @{ state = "resolved"; message = "done" } | Out-Null
Assert ((Invoke-WebRequest "$BaseUrl/public/status/feed.rss").Content -match "<rss") "RSS"
Call $stu GET "/platform/ops/overview" $null 403 | Out-Null

Write-Host "== 9 ops console"
$o = (Call $sa GET "/platform/ops/overview").data
Assert ($o.migrations.head -and $o.queues.Count -eq 6) "overview"
$p = (Call $sa GET "/platform/ops/partitions").data
Assert ($p.Count -eq 6) "partitions"
$run = (Call $sa POST "/platform/ops/scripts/run" @{ script = "key_rotation"; params = @{ kind = "jwt" } }).data
Assert ($run.status -eq "pending_approval") "four-eyes"
Call $sa POST "/platform/ops/scripts/runs/$($run.id)/approve" @{} 409 | Out-Null   # same admin cannot approve

Write-Host "== 10 capacity / 13 releases"
Call $sa POST "/platform/ops/capacity/snapshot" @{} | Out-Null
Assert ((Call $sa GET "/platform/ops/capacity").data.snapshots.Count -ge 1) "capacity snapshot"
Call $sa POST "/platform/releases" @{ version = "0.44.0"; notes_md = "verify" } 201 | Out-Null
Call $sa POST "/platform/releases/0.44.0/announce" @{} | Out-Null

Write-Host "== 2 migration safety"
& (Get-VenvPython "$PSScriptRoot/../..") "$PSScriptRoot/../check_migration_safety.py" --all
Assert ($LASTEXITCODE -eq 0) "migration lint"
Summary "44"
