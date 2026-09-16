# API verification — Phase 00 prerequisite skeleton (Prompts/00_PREREQUISITE_Project_Setup.md §9).
# Run from backend/ with the API up:  .\scripts\verify\00_prerequisite.ps1 [-BaseUrl http://localhost:8000/api/v1]
#
#  1. GET /health and /ready answer ok (DB + Redis reachable)
#  2. unknown /api/v1 route -> 404 with the error envelope (never {"detail": ...})
#  3. POST /auth/login placeholder -> 401 UNAUTHENTICATED envelope; Login helper surfaces the 401
#  4. validation error -> 422 VALIDATION envelope
#  5. write with READ_ONLY_MODE=false passes the gate (the 401 proves the gate let it through); X-Request-Id echoed
#  6. GET /api/v1/openapi.json lists the placeholder route; /metrics exposed
param([string]$BaseUrl = "http://localhost:8000/api/v1")
. "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl
$Root = $BaseUrl -replace '/api/v1$', ''

$health = Invoke-RestMethod "$Root/health"
Assert ($health.status -eq 'ok') "GET /health status ok (environment=$($health.environment))"
$ready = Invoke-RestMethod "$Root/ready"
Assert ($ready.status -eq 'ready') "GET /ready -> DB + Redis reachable"

$nf = Call $null GET "/does-not-exist" $null 404
Assert ($nf.success -eq $false -and $nf.error.code -eq 'NOT_FOUND') "404 uses the error envelope (NOT_FOUND)"
Assert ($null -ne $nf.request_id) "request_id present in error envelope"

$login = Call $null POST "/auth/login" @{ identifier = 'nobody'; password = 'x' } 401
Assert ($login.error.code -eq 'UNAUTHENTICATED') "login placeholder returns 401 UNAUTHENTICATED"
try { Login 'nobody' 'x'; throw "Login helper should have thrown" } catch { Assert ($_.ToString() -match '401') "Login helper surfaces the 401" }

$val = Call $null POST "/auth/login" @{ identifier = '' } 422
Assert ($val.error.code -eq 'VALIDATION' -and $val.error.details.errors.Count -ge 1) "422 VALIDATION with field errors"

$r = Invoke-WebRequest -Method Post -Uri "$BaseUrl/auth/login" -ContentType 'application/json' -Body '{"identifier":"a","password":"b"}' -Headers @{ 'X-Request-Id' = 'phase00-check' } -SkipHttpErrorCheck
Assert ($r.Headers['X-Request-Id'] -contains 'phase00-check') "X-Request-Id is echoed back"
Assert ($r.StatusCode -eq 401) "write passed the read-only gate (READ_ONLY_MODE=false) and reached the route"

$spec = Invoke-RestMethod "$BaseUrl/openapi.json"
Assert ($null -ne $spec.paths.'/api/v1/auth/login') "OpenAPI lists /api/v1/auth/login"
$metrics = Invoke-WebRequest "$Root/metrics" -SkipHttpErrorCheck
Assert ($metrics.StatusCode -eq 200 -and $metrics.Content -match 'http_request') "Prometheus /metrics exposed"

Summary "PHASE 00 prerequisite"
