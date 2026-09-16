# API verification helper — Prompts/00_PREREQUISITE_Project_Setup.md §3.26
# Dot-source from a phase script:  . "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl
# Requires PowerShell 7+ (Invoke-WebRequest -SkipHttpErrorCheck).
param([string]$BaseUrl = "http://localhost:8000/api/v1")

$script:BaseUrl = $BaseUrl
$script:Checks = 0

function Login($identifier, $password) {
  $body = @{ identifier = $identifier; password = $password } | ConvertTo-Json
  (Invoke-RestMethod -Method Post -Uri "$script:BaseUrl/auth/login" -ContentType 'application/json' -Body $body).data.access_token
}

function Call($token, $method, $path, $body = $null, $expect = 200, $headers = @{}) {
  $h = @{}
  if ($token) { $h['Authorization'] = "Bearer $token" }
  foreach ($k in $headers.Keys) { $h[$k] = $headers[$k] }
  $params = @{ Method = $method; Uri = "$script:BaseUrl$path"; Headers = $h; SkipHttpErrorCheck = $true }
  if ($null -ne $body) {
    $params['ContentType'] = 'application/json'
    $params['Body'] = ($body | ConvertTo-Json -Depth 8)
  }
  try { $r = Invoke-WebRequest @params }
  catch { throw "$method $path failed: $_" }
  if ($r.StatusCode -ne $expect) { throw "$method $path expected $expect got $($r.StatusCode): $($r.Content)" }
  $script:Checks++
  Write-Host "OK $method $path -> $($r.StatusCode)"
  if ([string]::IsNullOrWhiteSpace($r.Content)) { return $null }
  return ($r.Content | ConvertFrom-Json)
}

function Assert($cond, $msg) {
  if (-not $cond) { throw "ASSERT FAILED: $msg" }
  $script:Checks++
  Write-Host "  assert: $msg"
}

function Get-DemoPassword($role) {
  # Demo credentials are written by scripts/seed_demo_institution.py to LOCAL_TEST_CREDENTIALS.md (git-ignored).
  $file = Join-Path $PSScriptRoot "../../../LOCAL_TEST_CREDENTIALS.md"
  if (-not (Test-Path $file)) { throw "LOCAL_TEST_CREDENTIALS.md not found - run scripts/seed_demo_institution.py --only base" }
  $line = Get-Content $file | Where-Object { $_ -match "^\|\s*$role\s*\|" } | Select-Object -Last 1
  if (-not $line) { throw "no credentials for role '$role' in LOCAL_TEST_CREDENTIALS.md" }
  return (($line -split '\|')[3].Trim() -replace '`', '')
}

function Summary($phase) {
  Write-Host ""
  Write-Host "$phase : PASS ($script:Checks checks)" -ForegroundColor Green
}
