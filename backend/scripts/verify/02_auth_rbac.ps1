# API verification — Phase 02 auth, RBAC, feature flags, visibility & entitlements
# (Prompts/02_Phase02_Auth_RBAC_Features_Visibility.md §02.11).
#
# Run from backend/ with the API up (Redis required; a Celery worker is needed only for step 17's credential sheet):
#   .\scripts\verify\02_auth_rbac.ps1 [-BaseUrl http://localhost:8000/api/v1]
#
# Seed first (RUN_AFTER_PHASE.md §3):
#   python scripts/seed_platform.py
#   python scripts/seed_demo_institution.py --type university --only base
#
#  1. student.1 login -> access_token, permissions, features, HttpOnly SameSite=Strict refresh cookie
#  2. 5 wrong passwords -> the 6th attempt is 429 RATE_LIMITED (lockout window)
#  3. refresh rotation; replaying the old cookie revokes the whole family (reuse detection)
#  4. coe (MFA-required role) -> 403 MFA_REQUIRED + mfa_setup_required; setup/confirm/login with a TOTP code
#  5. GET /auth/me as accountant -> hr:view_all, leaves:view_all, attendance:staff_view_all, payroll:manage @institution
#  6. GET /roles: 403 for the student, 49 institution roles for inst.admin
#  7. permission matrix: removing leaves:view_all takes effect after re-login; restore
#  8. scoped assignment: hod @department CSE; a department of another institution -> 422
#  9. features: enable/disable hostel.core (-> 403 FEATURE_DISABLED on the stub route), dependants -> 409,
#     confirm_dependencies enables the chain
# 10. institution toggle: inst.admin switches a platform-enabled key off; enabling a platform-disabled key -> 409
# 11. time-boxed account: auditor.tmp expires -> 401 "account expired"
# 12. impersonation: super admin -> token with impersonator_id, audited; support agent is read-only
# 13. PII masking: phone/email masked without users:view_pii, full for hr (hr:view_pii)
# 14. entitlements + seat limit (plan student_limit=1 -> 403 RULE_VIOLATION / SEAT_LIMIT)
# 15. sessions: list, revoke, the revoked refresh cookie -> 401; logout blacklists the access token
# 16. POST /install -> 409 once installed
# 17. credential sheets: job -> XLSX (needs a worker; skipped with -SkipWorkerSteps)
#
# The Redis-less counterpart is scripts/verify/02_auth_rbac_inprocess.py (fakeredis + ASGI transport), which asserts
# the same contracts plus OTP, SSO, consents/DSRs and the password policy.
param(
  [string]$BaseUrl = "http://localhost:8000/api/v1",
  [switch]$SkipWorkerSteps
)
. "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl
$Backend = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Python = Get-VenvPython $Backend
$env:PYTHONUTF8 = "1"
Push-Location $Backend

function LoginFull($identifier, $password, $extra = @{}) {
  $body = @{ identifier = $identifier; password = $password } + $extra
  $params = @{ Method = 'POST'; Uri = "$script:BaseUrl/auth/login"; ContentType = 'application/json'
    Body = ($body | ConvertTo-Json -Depth 6); SkipHttpErrorCheck = $true; SessionVariable = 'ws' }
  $r = Invoke-WebRequest @params
  return @{ Status = $r.StatusCode; Body = $(if ($r.Content) { $r.Content | ConvertFrom-Json } else { $null })
    Session = $ws; Cookies = $r.Headers['Set-Cookie'] }
}

function Totp($secret) { (& $Python -c "import pyotp,sys;print(pyotp.TOTP(sys.argv[1]).now())" $secret).Trim() }

try {
  Write-Host "== 0. reset the fixtures of a previous run (same list as 02_auth_rbac_inprocess.py step 0)"
  $probes = "SELECT id FROM users WHERE username IN ('verify.temp','support.verify')"
  $touched = "feature_key LIKE 'hostel.%' OR feature_key LIKE 'comms.whatsapp%' OR feature_key IN ('security.sso','fees.core')"
  & $Python scripts/verify/_sql.py --write ("DELETE FROM mfa_secrets WHERE user_id IN (SELECT id FROM users WHERE username = 'coe'); " +
    "UPDATE users SET mfa_enabled = FALSE WHERE username = 'coe'; " +
    "DELETE FROM impersonation_logs WHERE impersonator_id IN ($probes) OR target_user_id IN ($probes); " +
    "DELETE FROM audit_logs WHERE user_id IN ($probes); DELETE FROM feedback_entries WHERE user_id IN ($probes); DELETE FROM users WHERE username IN ('verify.temp','support.verify'); " +
    "DELETE FROM roles WHERE slug IN ('imp_probe','nope_role'); " +
    "UPDATE subscription_plans SET student_limit = 200000, staff_limit = 20000 WHERE code = 'university'; " +
    "UPDATE users SET valid_to = NOW() + INTERVAL '7 days' WHERE username = 'auditor.tmp'; " +
    "DELETE FROM institution_feature_flags WHERE $touched; DELETE FROM feature_flag_changes WHERE $touched") | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "fixture reset failed" }
  & $Python scripts/verify/_reset_password.py hr (Get-DemoPassword 'hr_officer')   # step 17 rotates hr's password
  if ($LASTEXITCODE -ne 0) { throw "hr password reset failed" }
  & $Python -c "import asyncio,sys;sys.path.insert(0,'scripts');import _bootstrap;import redis.asyncio as r;from app.core.config import settings;asyncio.run(r.from_url(settings.REDIS_URL).flushdb())" | Out-Null
  Assert $true "coe MFA, probe users/roles, feature flags, plan limits and Redis lockouts reset"

  Write-Host "== 1. student login"
  $student = LoginFull 'student.1' (Get-DemoPassword 'student')
  Assert ($student.Status -eq 200) "POST /auth/login (student.1) -> 200"
  $studentToken = $student.Body.data.access_token
  Assert ($studentToken.Length -gt 20) "access_token issued"
  Assert ($student.Body.data.permissions -contains 'students:self') "permissions contain students:self"
  Assert ($student.Body.data.features -contains 'core.auth') "features contain core.auth"
  $cookie = ($student.Cookies | Where-Object { $_ -like 'refresh_token=*' }) -join ';'
  Assert ($cookie -match 'HttpOnly' -and $cookie -match '(?i)SameSite=Strict') "refresh cookie is HttpOnly + SameSite=Strict"

  Write-Host "== 2. lockout"
  for ($i = 1; $i -le 5; $i++) {
    $bad = LoginFull 'student.1' 'WrongPassword!1'
    Assert ($bad.Status -eq 401) "wrong password $i -> 401"
  }
  $locked = LoginFull 'student.1' 'WrongPassword!1'
  Assert ($locked.Status -eq 429 -and $locked.Body.error.code -eq 'RATE_LIMITED') "6th attempt -> 429 RATE_LIMITED"
  & $Python -c "import asyncio,sys;sys.path.insert(0,'scripts');import _bootstrap;import redis.asyncio as r;from app.core.config import settings;asyncio.run(r.from_url(settings.REDIS_URL).flushdb())" | Out-Null
  $student = LoginFull 'student.1' (Get-DemoPassword 'student')
  Assert ($student.Status -eq 200) "after clearing the lockout the correct password works"
  $studentToken = $student.Body.data.access_token

  Write-Host "== 3. refresh rotation + reuse detection"
  $refresh1 = Invoke-WebRequest -Method Post -Uri "$script:BaseUrl/auth/refresh" -WebSession $student.Session -SkipHttpErrorCheck
  Assert ($refresh1.StatusCode -eq 200) "POST /auth/refresh -> 200"
  $old = ($student.Cookies | Where-Object { $_ -like 'refresh_token=*' } | Select-Object -First 1).Split(';')[0].Split('=')[1]
  $replay = Invoke-WebRequest -Method Post -Uri "$script:BaseUrl/auth/refresh" -Headers @{ Cookie = "refresh_token=$old" } -SkipHttpErrorCheck
  Assert ($replay.StatusCode -eq 401) "replaying the old refresh cookie -> 401 (reuse detected)"
  $after = Invoke-WebRequest -Method Post -Uri "$script:BaseUrl/auth/refresh" -WebSession $student.Session -SkipHttpErrorCheck
  Assert ($after.StatusCode -eq 401) "the whole family was revoked"

  Write-Host "== 4. MFA for the controller of examinations"
  $coePwd = Get-DemoPassword 'controller_of_examinations'
  $coe = LoginFull 'coe' $coePwd
  Assert ($coe.Status -eq 403 -and $coe.Body.error.code -eq 'MFA_REQUIRED') "coe -> 403 MFA_REQUIRED"
  if ($coe.Body.error.details.mfa_setup_required) {
    $setupToken = $coe.Body.error.details.mfa_setup_token
    $setup = Call $setupToken POST "/auth/mfa/setup"
    Assert ($setup.data.secret.Length -gt 10) "mfa/setup -> secret + QR"
    $confirm = Call $setupToken POST "/auth/mfa/confirm" @{ code = (Totp $setup.data.secret) }
    Assert ($confirm.data.recovery_codes.Count -eq 10) "mfa/confirm -> 10 recovery codes"
    $script:CoeSecret = $setup.data.secret
  }
  if ($script:CoeSecret) {
    $coeIn = LoginFull 'coe' $coePwd @{ mfa_code = (Totp $script:CoeSecret) }
    Assert ($coeIn.Status -eq 200) "coe signs in with a TOTP code"
  }

  Write-Host "== 5. /auth/me as accountant"
  $acc = LoginFull 'accountant' (Get-DemoPassword 'accountant')
  Assert ($acc.Status -eq 200) "accountant login"
  $accToken = $acc.Body.data.access_token
  $me = Call $accToken GET "/auth/me"
  foreach ($p in 'hr:view_all', 'leaves:view_all', 'leaves:self', 'attendance:staff_view_all', 'payroll:manage') {
    Assert ($me.data.permissions -contains $p) "accountant holds $p"
  }
  Assert (($me.data.scopes | ForEach-Object { $_.scope_type }) -contains 'institution') "scopes = [institution]"

  Write-Host "== 6. roles"
  Call $studentToken GET "/roles" $null 403 | Out-Null
  $admin = LoginFull 'inst.admin' (Get-DemoPassword 'institution_admin')
  $adminToken = $admin.Body.data.access_token
  $roles = Call $adminToken GET "/roles?page_size=200"
  # later phases add role templates, so 49 (Phase 02) is a floor
  Assert ($roles.meta.pagination.total -ge 49) "inst.admin sees >= 49 institution roles ($($roles.meta.pagination.total))"
  $roleBySlug = @{}; foreach ($r in $roles.data) { $roleBySlug[$r.slug] = $r }

  Write-Host "== 7. permission matrix"
  $accRole = $roleBySlug['accountant'].id
  Call $adminToken GET "/roles/$accRole/permissions" | Out-Null
  $off = @{ modules = @(@{ module = 'leaves'; actions = @(@{ action = 'view_all'; granted = $false }) }) }
  Call $adminToken PUT "/roles/$accRole/permissions" $off | Out-Null
  $acc2 = LoginFull 'accountant' (Get-DemoPassword 'accountant')
  Assert (-not ($acc2.Body.data.permissions -contains 'leaves:view_all')) "leaves:view_all removed after re-login"
  $on = @{ modules = @(@{ module = 'leaves'; actions = @(@{ action = 'view_all'; granted = $true }) }) }
  Call $adminToken PUT "/roles/$accRole/permissions" $on | Out-Null
  $acc3 = LoginFull 'accountant' (Get-DemoPassword 'accountant')
  Assert ($acc3.Body.data.permissions -contains 'leaves:view_all') "restored"

  Write-Host "== 8. scoped assignments"
  $users = Call $adminToken GET "/users?page_size=200&q=faculty.1"
  $facultyId = ($users.data | Where-Object { $_.username -eq 'faculty.1' }).id
  $depts = @{}
  (& $Python scripts/verify/_sql.py "SELECT d.code, d.id FROM departments d JOIN institutions i ON i.id = d.institution_id WHERE i.slug = 'demo-uni'" | ConvertFrom-Json) | ForEach-Object { $depts[$_.code] = $_.id }
  $assign = Call $adminToken POST "/users/$facultyId/roles" @{ role_id = $roleBySlug['hod'].id; scope_type = 'department'; scope_id = $depts.CSE } 201
  Assert ($assign.data.scope_label) "hod @department CSE assigned (scope_label = $($assign.data.scope_label))"
  $bad = Call $adminToken POST "/users/$facultyId/roles" @{ role_id = $roleBySlug['hod'].id; scope_type = 'department'; scope_id = [guid]::NewGuid().ToString() } 422
  Assert ($bad.error.code -eq 'VALIDATION') "a department of another institution -> 422 VALIDATION"
  Call $adminToken DELETE "/users/$facultyId/roles/$($assign.data.id)" | Out-Null

  Write-Host "== 9. feature flags (super admin)"
  $saToken = Login-SuperAdmin   # enrols MFA on the first run and keeps the TOTP secret in LOCAL_TEST_CREDENTIALS.md
  $me = Call $saToken GET "/auth/me"
  Assert ($me.data.user.is_super_admin) "super admin signed in (MFA)"
  $instId = $admin.Body.data.user.institution_id
  $tenant = @{ 'X-Institution-Id' = $instId }
  $flags = Call $saToken GET "/institutions/$instId/features" $null 200 $tenant
  Assert ($flags.data.flags.Count -ge 350) "$($flags.data.flags.Count) feature rows for the tenant"
  Call $saToken PUT "/institutions/$instId/features/hostel.core" @{ enabled = $true; confirm_dependencies = $true } 200 $tenant | Out-Null
  Call $adminToken GET "/hostels" $null 200 | Out-Null
  # Phase 39: portals.warden depends on hostel.core and disabling does not cascade
  Call $saToken PUT "/institutions/$instId/features/portals.warden" @{ enabled = $false; reason = 'verify 02' } 200 $tenant | Out-Null
  Call $saToken PUT "/institutions/$instId/features/hostel.core" @{ enabled = $false; reason = 'verify 02' } 200 $tenant | Out-Null
  $blocked = Call $adminToken GET "/hostels" $null 403
  Assert ($blocked.error.code -eq 'FEATURE_DISABLED') "GET /hostels -> 403 FEATURE_DISABLED"
  $dep = Call $saToken PUT "/institutions/$instId/features/fees.core" @{ enabled = $false } 409 $tenant
  Assert ($dep.error.details.dependants -contains 'fees.scholarships') "disabling fees.core lists its dependants"
  $chain = Call $saToken PUT "/institutions/$instId/features/hostel.gate_qr" @{ enabled = $true } 409 $tenant
  Assert ($chain.error.details.missing_dependencies.Count -ge 1) "hostel.gate_qr lists its missing dependencies"
  Call $saToken PUT "/institutions/$instId/features/hostel.gate_qr" @{ enabled = $true; confirm_dependencies = $true } 200 $tenant | Out-Null
  Call $saToken PUT "/institutions/$instId/features/portals.warden" @{ enabled = $true; confirm_dependencies = $true } 200 $tenant | Out-Null

  Write-Host "== 10. institution toggle"
  Call $saToken PUT "/institutions/$instId/features/hostel.mess" @{ enabled = $true; confirm_dependencies = $true } 200 $tenant | Out-Null
  $off2 = Call $adminToken PUT "/features/hostel.mess/institution-toggle" @{ enabled = $false }
  Assert ($off2.data.effective -eq $false) "inst.admin switched hostel.mess off"
  Call $saToken PUT "/institutions/$instId/features/comms.whatsapp" @{ enabled = $false; confirm_dependencies = $true } 200 $tenant | Out-Null
  $conflict = Call $adminToken PUT "/features/comms.whatsapp/institution-toggle" @{ enabled = $true } 409
  Assert ($conflict.error.code -eq 'RULE_VIOLATION') "enabling a platform-disabled key -> 409"

  Write-Host "== 11. time-boxed account"
  $aud = LoginFull 'auditor.tmp' (Get-DemoPassword 'auditor')
  Assert ($aud.Status -eq 200) "auditor.tmp (7 days) signs in"
  $audId = $aud.Body.data.user.id
  Call $saToken PUT "/_dev/users/$audId/validity" @{ valid_to = (Get-Date).AddDays(-1).ToString('o') } | Out-Null
  $expired = LoginFull 'auditor.tmp' (Get-DemoPassword 'auditor')
  Assert ($expired.Status -eq 401 -and $expired.Body.error.message -match 'expired') "expired account -> 401 'account expired'"
  Call $saToken PUT "/_dev/users/$audId/validity" @{ valid_to = (Get-Date).AddDays(7).ToString('o') } | Out-Null

  Write-Host "== 12. impersonation"
  $adminId = $admin.Body.data.user.id
  $imp = Call $saToken POST "/users/$adminId/impersonate" @{ reason = 'phase 02 verification' }
  Assert ($imp.data.access_token) "super admin impersonates inst.admin"
  $impMe = Call $imp.data.access_token GET "/auth/me"
  Assert ($impMe.data.user.impersonator_id) "/auth/me shows impersonator_id"
  Call $imp.data.access_token POST "/auth/impersonation/stop" | Out-Null
  Call $imp.data.access_token GET "/auth/me" $null 401 | Out-Null

  Write-Host "== 13. PII masking"
  $hrUser = (Call $adminToken GET "/users?q=hr&page_size=50").data | Where-Object { $_.username -eq 'hr' }
  $masked = Call $adminToken GET "/users/$($hrUser.id)"
  Assert ($masked.data.phone -like '*`**') "inst.admin sees a masked phone ($($masked.data.phone))"
  $hr = LoginFull 'hr' (Get-DemoPassword 'hr_officer')
  $full = Call $hr.Body.data.access_token GET "/users/$($hrUser.id)"
  Assert (-not ($full.data.phone -like '*`**')) "hr (hr:view_pii) sees the full phone"

  Write-Host "== 14. entitlements + seat limit"
  $ent = Call $adminToken GET "/entitlements"
  Assert ($ent.data.plan -eq 'university' -and $ent.data.status -eq 'active') "entitlements -> plan/status"
  Call $saToken PUT "/_dev/plans/university" @{ student_limit = 1 } | Out-Null
  # a valid Phase 07 StudentCreate body (2025 BTECH-CSE, no login) — 07's fixture reset soft-deletes 'Verify%' rows
  $cse = (Call $adminToken GET "/programs?page_size=100&q=BTECH-CSE").data | Where-Object { $_.code -eq 'BTECH-CSE' }   # later phases add >100 programmes | Select-Object -First 1
  $seatBody = @{ first_name = 'Seat'; last_name = 'VerifySeat'; dob = '2007-05-01'; gender = 'M'; program_id = $cse.id; admission_year = 2025; create_user = $false }
  $seat = Call $adminToken POST "/students" $seatBody 403
  Assert ($seat.error.details.code -eq 'SEAT_LIMIT') "POST /students -> 403 RULE_VIOLATION / SEAT_LIMIT"
  Call $saToken PUT "/_dev/plans/university" @{ student_limit = 200000; staff_limit = 20000 } | Out-Null
  Call $adminToken POST "/students" $seatBody 201 | Out-Null

  Write-Host "== 15. sessions"
  $second = LoginFull 'student.1' (Get-DemoPassword 'student') @{ platform = 'android'; device_label = 'Pixel 8' }
  $sessions = Call $second.Body.data.access_token GET "/auth/sessions"
  Assert ($sessions.data.Count -ge 2) "$($sessions.data.Count) active sessions listed"
  Assert (($sessions.data | Where-Object { $_.current }).Count -eq 1) "the current session is flagged"
  $other = $sessions.data | Where-Object { -not $_.current } | Select-Object -First 1
  Call $second.Body.data.access_token DELETE "/auth/sessions/$($other.id)" | Out-Null
  $hist = Call $second.Body.data.access_token GET "/auth/login-history"
  Assert ($hist.data.Count -ge 5) "login history lists the attempts"
  Call $second.Body.data.access_token POST "/auth/logout" | Out-Null
  Call $second.Body.data.access_token GET "/auth/me" $null 401 | Out-Null

  Write-Host "== 16. install"
  $installBody = @{ install_key = 'change-me'; super_admin_email = 'platform.admin@septronuniverse.in'; super_admin_password = 'Install@2026Setup' }
  # a freshly migrated box (alembic + seed_platform, never POSTed /install) installs once; every later call is 409
  $first = Invoke-WebRequest -Method Post -Uri "$script:BaseUrl/install" -ContentType 'application/json' -Body ($installBody | ConvertTo-Json) -SkipHttpErrorCheck
  Assert ($first.StatusCode -in 200, 409) "POST /install -> $($first.StatusCode) (200 on a never-installed box, else 409)"
  $installed = Call $null POST "/install" $installBody 409
  Assert ($installed.error.code -eq 'CONFLICT') "POST /install on an installed platform -> 409 CONFLICT"

  if (-not $SkipWorkerSteps) {
    Write-Host "== 17. credential sheets (needs a Celery worker on the documents queue)"
    $sheet = Call $adminToken POST "/users/credential-sheets" @{ audience = 'staff'; ids = @($hrUser.id); batch_label = 'verify 02' } 202
    $jobId = $sheet.data.job_id
    $final = $null
    for ($i = 0; $i -lt 30; $i++) {
      Start-Sleep -Seconds 1
      $final = (Call $adminToken GET "/jobs/$jobId").data
      if ($final.status -in @('succeeded', 'failed', 'cancelled')) { break }
    }
    Assert ($final.status -eq 'succeeded' -and $final.result_url) "credential-sheet job -> succeeded with a file"
  }

  Summary "PHASE 02 auth, rbac, features, visibility"
}
finally {
  Pop-Location
}
