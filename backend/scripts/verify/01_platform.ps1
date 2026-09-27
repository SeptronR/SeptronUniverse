# API verification — Phase 01 infrastructure & platform services (Prompts/01_Phase01_Infrastructure_Platform_Services.md §01.11).
# Run from backend/ with the API, a Celery worker and Beat up (Redis required):
#   .\scripts\verify\01_platform.ps1 [-BaseUrl http://localhost:8000/api/v1]
#
#  1. GET /health -> {status:"ok"}; GET /ready -> 200 {status:"ready"} with db/redis/storage/migrations/outbox checks
#  2. GET /api/v1/public/config -> envelope {packs:{IN:{categories}}, themes:[5], min_app_versions}
#  3. GET /platform/read-only -> platform:false; super admin opens a platform window -> POST /feedback 503 READ_ONLY; revert
#  4. alembic single head; 411 base tables; check_schema_drift.py --phase 01 -> 0 diffs
#  5. outbox: test.ping dispatched + consumed (event_consumptions); test.fail re-armed (attempts, next_attempt_at)
#  6. WebSocket: no token -> 4401; forged token -> 4401
#  7. jobs: POST /_dev/jobs/sleep -> queued -> running -> succeeded; progress events on jobs:{user}
#  8. file service: PNG stored under {institution}/…, renamed .exe rejected, signed URL works and expires
#  9. partitions: beat.partitions.ensure_next_month -> >= 2 partitions per partitioned table
# Until Phase 02 ships /auth/login, protected routes use a token minted by scripts/dev_token.py (super admin).
param([string]$BaseUrl = "http://localhost:8000/api/v1")
. "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl
$Root = $BaseUrl -replace '/api/v1$', ''
$WsUrl = ($Root -replace '^http', 'ws') + '/ws'
$Backend = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Python = Get-VenvPython $Backend
$env:PYTHONUTF8 = "1"
Push-Location $Backend

function Run-Py([string]$script, [string[]]$scriptArgs = @()) {
  & $Python $script @scriptArgs
  if ($LASTEXITCODE -ne 0) { throw "$script $($scriptArgs -join ' ') failed (exit $LASTEXITCODE)" }
  $script:Checks++
}

try {
  Write-Host "== 1. health / ready"
  $health = Invoke-RestMethod "$Root/health"
  Assert ($health.status -eq 'ok') "GET /health status ok (environment=$($health.environment))"
  $ready = Invoke-RestMethod "$Root/ready"
  Assert ($ready.status -eq 'ready') "GET /ready -> ready (db, redis, storage, migrations, outbox)"
  Assert ($ready.checks.migrations.ok -and $ready.checks.redis.ok) "migrations at head + Redis reachable"

  Write-Host "== 2. public config"
  $cfg = Call $null GET "/public/config"
  Assert ($cfg.success -eq $true) "envelope success"
  Assert ($cfg.data.packs.IN.categories.Count -ge 1) "packs.IN.categories present ($($cfg.data.packs.IN.categories.Count))"
  Assert ($cfg.data.themes.Count -eq 5) "5 themes"
  Assert ($null -ne $cfg.data.min_app_versions.android) "min_app_versions present"
  $mobile = Call $null POST "/mobile/config" @{ platform = 'android'; app_version = '0.0.1' }
  Assert ($mobile.data.update_available -eq $true) "POST /mobile/config compares versions"

  Write-Host "== 3. read-only mode"
  $token = (& $Python scripts/dev_token.py --minutes 30 | Select-Object -Last 1).Trim()
  if (-not $token) { throw "dev_token.py returned no token (run scripts/seed_platform.py first)" }
  $ro = Call $null GET "/platform/read-only"
  Assert ($ro.data.platform -eq $false) "GET /platform/read-only -> platform:false"
  $set = Call $token POST "/platform/read-only" @{ scope = 'platform'; enabled = $true; reason = 'verify 01' }
  Assert ($set.data.platform -eq $true) "super admin opened a platform read-only window"
  $blocked = Call $token POST "/feedback" @{ message = 'blocked during read-only' } 503
  Assert ($blocked.error.code -eq 'READ_ONLY') "POST /feedback during the window -> 503 READ_ONLY"
  $revert = Call $token POST "/platform/read-only" @{ scope = 'platform'; enabled = $false }
  Assert ($revert.data.platform -eq $false) "window closed (the switch itself is exempt from the gate)"
  $fb = Call $token POST "/feedback" @{ message = 'phase 01 verification feedback'; category = 'praise'; rating = 5; page = '/help' } 201
  Assert ($fb.data.status -eq 'new') "POST /feedback -> 201 after revert"
  $help = Call $token GET "/help/articles"
  Assert ($help.data.Count -ge 5) "GET /help/articles -> $($help.data.Count) platform articles (seed --only platform)"
  $search = Call $token GET "/search?q=nobody"
  Assert ($search.data.results.Count -eq 0) "GET /search returns gracefully with no data"

  Write-Host "== 4. schema"
  $heads = (& $Python -m alembic heads) | Where-Object { $_ -match '\(head\)' }
  Assert (@($heads).Count -eq 1) "alembic heads -> exactly one head"
  Run-Py "scripts/verify/01_platform_db.py" @("tables")
  Run-Py "scripts/check_schema_drift.py" @("--phase", "01")

  Write-Host "== 5. outbox (worker + Beat must be running)"
  Run-Py "scripts/verify/01_platform_db.py" @("outbox", "--wait", "30")

  Write-Host "== 6. WebSocket handshakes"
  Run-Py "scripts/verify/ws_check.py" @("--url", $WsUrl)

  Write-Host "== 7. jobs + tray channel"
  $watch = Start-Job -ScriptBlock {
    param($py, $script, $url, $tok, $cwd)
    Set-Location $cwd
    $env:PYTHONUTF8 = "1"
    & $py $script --url $url --token $tok --watch-job 40 2>&1
    "EXIT:$LASTEXITCODE"
  } -ArgumentList $Python, (Join-Path $Backend "scripts\verify\ws_check.py"), $WsUrl, $token, $Backend
  Start-Sleep -Seconds 2
  $job = Call $token POST "/_dev/jobs/sleep?seconds=5" $null 202
  Assert ($job.data.status -eq 'queued') "POST /_dev/jobs/sleep -> 202 queued"
  $jobId = $job.data.id
  $final = $null
  for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 1
    $final = (Call $token GET "/jobs/$jobId").data
    if ($final.status -in @('succeeded', 'failed', 'cancelled')) { break }
  }
  Assert ($final.status -eq 'succeeded' -and $final.progress_pct -eq 100) "job queued -> running -> succeeded (progress 100)"
  $out = Receive-Job -Job $watch -Wait -AutoRemoveJob
  $out | ForEach-Object { Write-Host "   $_" }
  Assert (($out | Select-Object -Last 1) -eq 'EXIT:0') "progress events received on jobs:{user}"
  $mine = Call $token GET "/jobs?page_size=5"
  Assert ($null -ne $mine.meta.visibility) "GET /jobs carries meta.visibility"
  $cancel = Call $token POST "/jobs/$jobId/cancel" $null 409
  Assert ($cancel.error.code -eq 'CONFLICT') "cancel of a finished job -> 409 CONFLICT"

  Write-Host "== 8. file service"
  Run-Py "scripts/verify/file_service_check.py" @("--base-url", $Root)

  Write-Host "== 9. partitions"
  Run-Py "scripts/verify/01_platform_db.py" @("partitions")

  Summary "PHASE 01 platform"
}
finally {
  Pop-Location
}
