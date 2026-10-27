# Phase 37 — audit logs, security events & settings (Prompts/37 §37.11). Run after
# `seed_demo_institution.py --only audit` (demo-uni, APP_ENV=development). Written in the development-only run; not
# executed yet. Role names of the prompt map to the seeded users: principal = vice_chancellor, inst.admin = institution
# admin, security.off = security_officer, decoder = exam_decoder.
param([string]$BaseUrl = "http://localhost:8000/api/v1", [string]$Institution = "demo-uni")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl

$admin = Login "inst.admin" (Get-DemoPassword "institution_admin")
$prin = Login "principal" (Get-DemoPassword "vice_chancellor")
$reg = Login "registrar" (Get-DemoPassword "registrar")
$coe = Login "coe" (Get-DemoPassword "controller_of_examinations")
$cell = Login "exam.cell" (Get-DemoPassword "exam_cell")
$hod = Login "hod.cse" (Get-DemoPassword "hod")
$fac = Login "faculty.1" (Get-DemoPassword "faculty")
$acct = Login "accountant" (Get-DemoPassword "accountant")
$sec = Login "security.off" (Get-DemoPassword "security_officer")
$colB = Login "college.admin.b" (Get-DemoPassword "college_admin")
$iqac = Login "iqac" (Get-DemoPassword "iqac_coordinator")
$stu = Login "student.1" (Get-DemoPassword "student")
$aud = Login "auditor.tmp" (Get-DemoPassword "auditor")
$sa = Login "superadmin" (Get-DemoPassword "super_admin")

function Wait-Job($session, $jobId, [int]$seconds = 90) {
  for ($i = 0; $i -lt $seconds; $i += 2) {
    $r = Call $session GET "/jobs/$jobId"
    if ($r.data.status -in @("succeeded", "failed", "cancelled")) { return $r.data }
    Start-Sleep -Seconds 2
  }
  throw "job $jobId did not finish"
}
$from30 = (Get-Date).AddDays(-30).ToString("o")

Write-Host "== 1 explorer scopes"
$a = Call $admin GET "/audit-logs?from=$from30&page_size=50"
Assert ($a.data.total -gt 0) "admin: rows"
Assert ($a.meta.visibility.scopes -contains "all") "admin: All tab"
Assert (@($a.data.items | Where-Object { $_.summary }).Count -eq @($a.data.items).Count) "summaries rendered"
$fm = Call $fac GET "/audit-logs/me"
Assert (@($fm.data.items | Where-Object { $_.user.id -ne $fac.UserId }).Count -eq 0) "faculty /me: own rows only"
$fa = Call $fac GET "/audit-logs"
Assert (-not $fa.meta.visibility.scopes) "faculty: no ScopeTabs"
$h = Call $hod GET "/audit-logs?scope=department&record_type=student"
Assert ($h.meta.visibility.scopes -contains "department") "hod: department tab"
$cb = Call $colB GET "/audit-logs?scope=college"
Assert ($cb.meta.visibility.scopes -contains "college") "college admin B: college tab"
Call $stu GET "/audit-logs" $null 403 | Out-Null

Write-Host "== 2 diff & masking + timeline"
$st = (Call $reg GET "/students?size=1").data[0]
Call $reg PUT "/students/$($st.id)" @{ phone = "9876547890"; version = $st.version } | Out-Null
$row = (Call $reg GET "/audit-logs?record_type=student&record_id=$($st.id)&module=students&action=update").data.items[0]
$full = Call $reg GET "/audit-logs/$($row.id)"
Assert (@($full.data.masked_fields).Count -eq 0) "registrar: unmasked diff"
$masked = Call $hod GET "/audit-logs/$($row.id)" $null 200, 404
if ($masked.data) { Assert (@($masked.data.masked_fields).Count -ge 1) "hod: masked phone" }
$tl = Call $reg GET "/audit-logs/timeline?record_type=student&record_id=$($st.id)"
Assert (@($tl.data).Count -ge 1) "timeline merged"

Write-Host "== 3 who viewed"
Call $reg GET "/students/$($st.id)" | Out-Null
$wv = Call $reg GET "/audit-logs/who-viewed?record_type=student&record_id=$($st.id)"
Assert (@($wv.data | Where-Object { $_.fields_unmasked.Count -ge 1 }).Count -ge 1) "who-viewed lists the read"
Call $hod GET "/audit-logs/who-viewed?record_type=health_visit&record_id=$([guid]::NewGuid())" $null 403 | Out-Null

Write-Host "== 4 chain"
$v = Call $admin POST "/audit-logs/verify-chain" @{ from = (Get-Date).AddDays(-7).ToString("o") }
Assert ($v.data.ok -and $v.data.rows -gt 0) "chain ok"
$bad = Call $admin POST "/_dev/audit/corrupt-copy"
Assert (-not $bad.data.result.ok -and $bad.data.result.first_broken) "dev copy broken"
Call $admin POST "/_dev/audit/digest-daily" | Out-Null
$dg = Call $admin GET "/audit-logs/chain-digests"
Assert (@($dg.data | Where-Object { $_.signed }).Count -ge 1) "signed digests"
Call $admin POST "/_dev/audit/tamper-digest" | Out-Null
$v2 = Call $admin POST "/audit-logs/verify-chain" @{ from = (Get-Date).AddDays(-7).ToString("o") }
Assert (-not $v2.data.ok -and @($v2.data.digest_mismatches).Count -ge 1) "tampered digest reported"

Write-Host "== 5 coverage guard"
Push-Location "$PSScriptRoot/../.."
python scripts/check_audit_coverage.py
Assert ($LASTEXITCODE -eq 0) "check_audit_coverage.py: 0 unaudited"
Pop-Location

Write-Host "== 6 exam audit"
$S = (Call $coe GET "/exam-sessions?size=1").data[0].id
$m = Call $coe GET "/exams/$S/audit?section=marks"
Assert ($m.data.section -eq "marks") "marks section"
$c = Call $coe GET "/exams/$S/audit?section=custody"
Assert ($c.data.summary.gaps -ge 1) "custody gap flagged"
Call $coe GET "/exams/$S/audit?section=decode" | Out-Null
Call $cell GET "/exams/$S/audit?section=decode" $null 403 | Out-Null
Call $cell GET "/exams/$S/audit?section=runs" | Out-Null
foreach ($sec in @("marks", "qp_print", "custody", "valuation", "moderation", "decode", "runs", "publication", "post_result")) {
  Call $aud GET "/exams/$S/audit?section=$sec" | Out-Null
}
$ej = Call $coe POST "/exams/$S/audit/export" @{ format = "pdf" } 202
Assert ((Wait-Job $coe $ej.data.job_id).status -eq "succeeded") "exam audit report"

Write-Host "== 7 security"
$ev = Call $sec GET "/security/events?type=login_failed"
Assert (@($ev.data).Count -ge 5) "login failures"
Call $admin POST "/_dev/audit/anomaly-scan" | Out-Null
$an = Call $sec GET "/security/anomalies?active=true"
Assert (@($an.data | Where-Object { $_.rule -eq "login_failures_per_ip" }).Count -ge 1) "login_failures_per_ip alert"
Call $sec POST "/security/anomalies/$($an.data[0].id)/acknowledge" @{ note = "Blocked at the firewall" } | Out-Null
$acctUser = (Call $admin GET "/users?q=accountant&size=1").data[0].id
$rv = Call $admin POST "/security/sessions/revoke" @{ user_id = $acctUser; all = $true }
Assert ($rv.data.revoked -ge 1) "accountant sessions revoked"
Call $fac GET "/security/events" $null 403 | Out-Null

Write-Host "== 8 settings catalogue"
$cat = Call $admin GET "/settings/catalogue?q=late"
Assert (@($cat.data | Where-Object { $_.key -eq "fees.late_fee_grace_days" }).Count -eq 1) "catalogue search"
$colId = (Call $colB GET "/colleges?size=1").data[0].id
$eff = Call $admin GET "/settings/effective?college_id=$colId"
Assert (@($eff.data | Where-Object { $_.source -eq "college" }).Count -ge 5) "5 college overrides"
Call $admin PUT "/settings" @{ items = @(@{ category = "fees"; key = "late_fee_grace_days"; value = "x" }); reason = "test" } 422 | Out-Null
Call $colB PUT "/settings" @{ items = @(@{ category = "fees"; key = "late_fee_grace_days"; value = 5; college_id = $colId }); reason = "college grace" } | Out-Null
Call $colB PUT "/settings" @{ items = @(@{ category = "fees"; key = "late_fee_grace_days"; value = 3 }); reason = "x" } 403 | Out-Null
Call $admin PUT "/settings" @{ items = @(@{ category = "security"; key = "jwt_kid"; value = "k2" }); reason = "x" } 409 | Out-Null
Call $admin PUT "/settings" @{ items = @(@{ category = "security"; key = "mfa_required_roles"; value = @("registrar") }) } 422 | Out-Null
Call $admin PUT "/settings" @{ items = @(@{ category = "security"; key = "mfa_required_roles"; value = @("registrar") }); reason = "audit finding" } | Out-Null
$hist = Call $admin GET "/settings/history?key=fees.late_fee_grace_days"
Assert (@($hist.data).Count -ge 1) "history"
Call $admin POST "/settings/fees.late_fee_grace_days/reset?reason=revert" $null 200, 404 | Out-Null
Call $admin DELETE "/settings/fees.late_fee_grace_days/override?college_id=$colId&reason=revert" | Out-Null

Write-Host "== 9 import / export"
$ex = Call $admin GET "/settings/export"
$vals = $ex.data.values
$vals."fees.late_fee_grace_days" = 7; $vals."attendance.qr_ttl_seconds" = 150; $vals."security.jwt_kid" = "x"
$dry = Call $admin POST "/settings/import?dry_run=true" @{ json = @{ values = $vals }; reason = "import test" }
Assert (@($dry.data.applied).Count -eq 2 -and @($dry.data.skipped_locked).Count -eq 1) "dry run report"
Call $admin POST "/settings/import?dry_run=false" @{ json = @{ values = $vals }; reason = "import test" } | Out-Null

Write-Host "== 10 feature changes"
Call $admin GET "/settings/feature-changes" | Out-Null
Call $admin GET "/settings/platform-actions" | Out-Null
Call $hod GET "/settings/feature-changes" $null 403 | Out-Null

Write-Host "== 11 retention"
$pv = Call $admin GET "/retention/preview?data_class=login_history"
Assert ($pv.data.eligible -ge 20) "old login history counted"
Call $admin PUT "/retention/policies" @{ values = @{ login_history_days = 4000 } } 422 | Out-Null
Call $admin PUT "/retention/policies" @{ values = @{ login_history_days = 200 }; reason = "shorter" } | Out-Null
$pj = Call $admin POST "/retention/purge" @{ data_class = "message_logs" } 202
Assert ((Wait-Job $admin $pj.data.job_id).status -eq "succeeded") "purge job"
$mf = Call $admin GET "/retention/manifests"
Assert (@($mf.data).Count -ge 1) "manifest written"
$again = Call $admin POST "/_dev/audit/purge-daily"
Write-Host "   second purge rows: $($again.data.result)"

Write-Host "== 12 gating & scope"
Call $aud GET "/audit-logs" | Out-Null
Call $aud GET "/audit-logs/chain-digests" | Out-Null
Call $aud GET "/security/events" | Out-Null
Call $aud POST "/security/anomalies/$($an.data[0].id)/acknowledge" @{ note = "auditor" } 403 | Out-Null
Write-Host "Phase 37 verification finished"
