# API verification helper — Prompts/00_PREREQUISITE_Project_Setup.md §3.26
# Dot-source from a phase script:  . "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl
# Requires PowerShell 7+ (Invoke-WebRequest -SkipHttpErrorCheck).
param([string]$BaseUrl = "http://localhost:8000/api/v1")

$script:BaseUrl = $BaseUrl
$script:Checks = 0

function Login($identifier, $password, $extra = @{}) {
  # Phase 02: POST /auth/login answers the principal envelope; the refresh token is an httpOnly cookie (web) or the
  # body's refresh_token (platform=android|ios). Phase scripts that need the cookie use their own helper.
  $body = (@{ identifier = $identifier; password = $password } + $extra) | ConvertTo-Json -Depth 6
  # pwsh 7.6+ error text no longer carries the status code, so surface it explicitly
  $r = Invoke-WebRequest -Method Post -Uri "$script:BaseUrl/auth/login" -ContentType 'application/json' -Body $body -SkipHttpErrorCheck
  if ($r.StatusCode -ne 200) { throw "Login failed ($($r.StatusCode)): $($r.Content)" }
  ($r.Content | ConvertFrom-Json).data.access_token
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

function Get-DemoPassword($role, $identifier = $null) {
  # Demo credentials are written by scripts/seed_demo_institution.py (and seed_platform.py for super_admin) to
  # LOCAL_TEST_CREDENTIALS.md (git-ignored): | role | identifier | password |.
  $file = Join-Path $PSScriptRoot "../../../LOCAL_TEST_CREDENTIALS.md"
  if (-not (Test-Path $file)) { throw "LOCAL_TEST_CREDENTIALS.md not found - run scripts/seed_demo_institution.py --only base" }
  $rows = Get-Content $file | Where-Object { $_ -match "^\|\s*$role\s*\|" }
  # several accounts can share a role label (superadmin / superadmin.2): prefer the identifier's own row
  $line = $null
  if ($identifier) { $line = $rows | Where-Object { ($_ -split '\|')[2].Trim() -eq $identifier } | Select-Object -Last 1 }
  if (-not $line) { $line = $rows | Select-Object -Last 1 }
  if (-not $line) { throw "no credentials for role '$role' in LOCAL_TEST_CREDENTIALS.md" }
  return (($line -split '\|')[3].Trim() -replace '`', '')
}

function Summary($phase) {
  Write-Host ""
  Write-Host "$phase : PASS ($script:Checks checks)" -ForegroundColor Green
}

function Get-VenvPython($backend) {
  # backend/.venv on Windows (Scripts\python.exe) or Linux/macOS (bin/python); falls back to the PATH interpreter
  foreach ($rel in @(".venv\Scripts\python.exe", ".venv/bin/python")) {
    $p = Join-Path $backend $rel
    if (Test-Path $p) { return $p }
  }
  return "python"
}

function Get-CredentialsFile { Join-Path $PSScriptRoot "../../../LOCAL_TEST_CREDENTIALS.md" }

function Get-Totp($secret) {
  $py = Get-VenvPython (Resolve-Path (Join-Path $PSScriptRoot "../.."))
  (& $py -c "import pyotp,sys;print(pyotp.TOTP(sys.argv[1]).now())" $secret).Trim()
}

function Login-Mfa($role, $identifier) {
  # MFA-required roles (super admin; registrar / coe / decoder in the demo tenant). The first run enrols the account
  # (limited mfa_setup token -> setup -> confirm) and appends the TOTP secret to LOCAL_TEST_CREDENTIALS.md as role
  # "<role>_totp" (git-ignored), so later verification scripts sign in again without resetting MFA. A password-only
  # login (MFA not required) is returned as is. Returns the access token.
  $pwd = Get-DemoPassword $role $identifier
  $body = @{ identifier = $identifier; password = $pwd }
  $r = Invoke-WebRequest -Method Post -Uri "$script:BaseUrl/auth/login" -ContentType 'application/json' -Body ($body | ConvertTo-Json) -SkipHttpErrorCheck
  $j = $r.Content | ConvertFrom-Json
  if ($r.StatusCode -eq 200) { return $j.data.access_token }
  if ($r.StatusCode -ne 403 -or $j.error.code -ne 'MFA_REQUIRED') { throw "$identifier login failed: $($r.StatusCode) $($r.Content)" }
  if ($j.error.details.mfa_setup_required) {
    $h = @{ Authorization = "Bearer $($j.error.details.mfa_setup_token)" }
    $setup = (Invoke-RestMethod -Method Post -Uri "$script:BaseUrl/auth/mfa/setup" -Headers $h).data
    Invoke-RestMethod -Method Post -Uri "$script:BaseUrl/auth/mfa/confirm" -Headers $h -ContentType 'application/json' -Body (@{ code = (Get-Totp $setup.secret) } | ConvertTo-Json) | Out-Null
    Add-Content -Path (Get-CredentialsFile) -Value "`n| $($role)_totp | $identifier | ``$($setup.secret)`` |"
    $secret = $setup.secret
    Start-Sleep -Seconds 1
  } else {
    $secret = Get-DemoPassword "$($role)_totp"
  }
  $body['mfa_code'] = Get-Totp $secret
  $r = Invoke-WebRequest -Method Post -Uri "$script:BaseUrl/auth/login" -ContentType 'application/json' -Body ($body | ConvertTo-Json) -SkipHttpErrorCheck
  if ($r.StatusCode -ne 200) { throw "$identifier TOTP login failed: $($r.StatusCode) $($r.Content)" }
  return ($r.Content | ConvertFrom-Json).data.access_token
}

function Login-SuperAdmin { Login-Mfa 'super_admin' 'superadmin' }
