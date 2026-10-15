# API verification — Phase 04 communication core & approval-workflow engine
# (Prompts/04_Phase04_Communication_Core_Workflow_Engine.md §04.11).
#
# Run from backend/ with the API up, Redis and a Celery worker + Beat (the outbox relay dispatches notifications):
#   .\scripts\verify\04_comms_workflow.ps1 [-BaseUrl http://localhost:8000/api/v1]
#
# Seed first: python scripts/seed_demo_institution.py --type university --only communication   (runs base + institution)
#
# Roles: inst.admin, hod.cse, hr, faculty.1, student.1, parent.1 (+ dean.eng for delegation, superadmin for step 10).
#  1. templates: platform auth.password_reset; institution override v1 → preview; a second active version wins
#  2. send announcement.published to role student (in_app + sms) → student.1 notification + in_app/sms(mock) logs sent;
#     unread-count 1 → read-all → 0
#  3. preferences: sms off for announcements → no SMS log; quiet hours around now → sms log 'deferred'
#  4. announcement requires_ack to college A → visible to a college-A member, not to college.admin.b; acknowledge → stats
#  5. device register (fcm) → 201; next announcement logs a push message (mock)
#  6. DLT: provider override sms=msg91 → a template without dlt id fails DLT_TEMPLATE_MISSING; with the DLT id → sent
#  7. workflow definitions: 18 shipped keys; PUT leave.approval → version +1
#  8. leave.approval dev run: hod.cse → hr → approved, hook marker, events dispatched, requester notified; student 403
#  9. delegation hod.cse → dean.eng (module leaves): dean.eng sees + approves; step acted_by dean, delegated_from hod
# 10. escalation: sla_hours 0.01 → escalate → step escalated with escalated_to
# 11. parallel no_dues.clearance: six parallel approvers; one reject → rejected
# 12. webhook: signed delivered callback → log delivered; bad signature → 401
param([string]$BaseUrl = "http://localhost:8000/api/v1")
. "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl
$Backend = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Python = Get-VenvPython $Backend
$env:PYTHONUTF8 = "1"
Push-Location $Backend

function Sql($query) {
  $out = & $Python scripts/verify/_sql.py $query
  if ($LASTEXITCODE -ne 0) { throw "sql failed: $query" }
  return @($out | ConvertFrom-Json)
}
function SqlWrite($query) { & $Python scripts/verify/_sql.py --write $query | Out-Null; if ($LASTEXITCODE -ne 0) { throw "sql failed: $query" } }
function WaitFor($label, [scriptblock]$probe, $seconds = 20) {
  for ($i = 0; $i -lt $seconds; $i++) { $v = & $probe; if ($v) { return $v }; Start-Sleep -Seconds 1 }
  throw "timed out waiting for: $label"
}

try {
  $run = Get-Random -Minimum 10000 -Maximum 99999
  $admin = Login 'inst.admin' (Get-DemoPassword 'institution_admin')
  $hod = Login 'hod.cse' (Get-DemoPassword 'hod')
  $hr = Login 'hr' (Get-DemoPassword 'hr_officer')
  $faculty = Login 'faculty.1' (Get-DemoPassword 'faculty')
  $student = Login 'student.1' (Get-DemoPassword 'student')
  $parent = Login 'parent.1' (Get-DemoPassword 'parent')
  $dean = Login 'dean.eng' (Get-DemoPassword 'dean')
  $collegeAdminB = Login 'college.admin.b' (Get-DemoPassword 'college_admin')
  $me = (Call $admin GET "/auth/me").data
  $instId = $me.user.institution_id
  $studentId = (Call $student GET "/auth/me").data.user.id
  $facultyId = (Call $faculty GET "/auth/me").data.user.id
  $hodId = (Call $hod GET "/auth/me").data.user.id
  $deanId = (Call $dean GET "/auth/me").data.user.id
  # fixtures of a previous run: preferences, devices, provider override, delegations, notifications of the student
  SqlWrite ("DELETE FROM notification_preferences WHERE user_id = '$studentId'; DELETE FROM device_tokens WHERE user_id = '$studentId'; " +
    "DELETE FROM notifications WHERE user_id = '$studentId'; UPDATE workflow_delegations SET is_active = FALSE WHERE institution_id = '$instId'; " +
    "DELETE FROM institution_settings WHERE institution_id = '$instId' AND category = 'integrations' AND key = 'provider_overrides'")
  Assert $true "fixtures reset"

  Write-Host "== 1. templates"
  $platform = Call $admin GET "/communication/templates?event_trigger=auth.password_reset"
  Assert (($platform.data | Where-Object { $_.is_platform }).Count -ge 1) "platform template for auth.password_reset (institution_id null)"
  $v1 = Call $admin POST "/communication/templates" @{ event_trigger = "custom.verify$run"; name = "Verify $run"; channels = @('in_app'); subject_template = 'Hi {{ name }}'; body_template = 'Hello {{ name }}, code {{ code }}'; variables = @('name', 'code') } 201
  $prev = Call $admin POST "/communication/templates/$($v1.data.id)/preview" @{ context = @{ name = 'Asha'; code = '42' } }
  Assert ($prev.data.body -eq 'Hello Asha, code 42') "preview renders v1"
  $v2 = Call $admin PUT "/communication/templates/$($v1.data.id)" @{ body_template = 'v2 {{ name }}' }
  Assert ($v2.data.version -eq 2 -and $v2.data.is_active) "edit writes version 2 (active)"
  $active = Call $admin GET "/communication/templates?event_trigger=custom.verify$run"
  Assert ((@($active.data | Where-Object { $_.is_active -and -not $_.is_platform })).version -eq 2) "resolver sees v2"

  Write-Host "== 2. ad-hoc send"
  $sent = Call $admin POST "/communication/send" @{ event_type = 'announcement.published'; audience = @{ roles = @('student') }; channels = @('in_app', 'sms'); context = @{ title = "Verify $run"; summary = 'check'; announcement_id = [guid]::NewGuid().ToString() } } 202
  $n = WaitFor "student notification" { (Call $student GET "/notifications?page_size=5").data | Where-Object { $_.title -eq "Verify $run" } }
  Assert ($n) "student.1 received the in-app notification"
  $logs = WaitFor "sms log" { $l = Sql "SELECT channel, status, provider FROM message_logs WHERE event_id = '$($sent.data.event_id)' AND user_id = '$studentId'"; if (($l | Where-Object { $_.channel -eq 'sms' -and $_.status -eq 'sent' })) { $l } }
  Assert (($logs | Where-Object { $_.channel -eq 'in_app' -and $_.status -eq 'sent' }) -and ($logs | Where-Object { $_.channel -eq 'sms' -and $_.provider -eq 'mock' })) "message_logs: in_app + sms(mock) sent"
  Assert ((Call $student GET "/notifications/unread-count").data.unread -ge 1) "unread-count >= 1"
  Call $student POST "/notifications/read-all" | Out-Null
  Assert ((Call $student GET "/notifications/unread-count").data.unread -eq 0) "read-all -> 0"

  Write-Host "== 3. preferences"
  Call $student PUT "/notification-preferences/me" @{ items = @(@{ category = 'announcements'; channels = @('in_app', 'push'); digest = 'none' }) } | Out-Null
  $s2 = Call $admin POST "/communication/send" @{ event_type = 'announcement.published'; audience = @{ user_ids = @($studentId) }; channels = @('in_app', 'sms'); context = @{ title = "Pref $run"; summary = 'x' } } 202
  WaitFor "pref notification" { (Call $student GET "/notifications?page_size=5").data | Where-Object { $_.title -eq "Pref $run" } } | Out-Null
  Assert (@(Sql "SELECT 1 AS x FROM message_logs WHERE event_id = '$($s2.data.event_id)' AND channel = 'sms'").Count -eq 0) "sms switched off -> no SMS log"
  $now = [DateTime]::UtcNow.AddHours(5.5)
  $from = $now.AddMinutes(-30).ToString('HH:mm'); $to = $now.AddMinutes(30).ToString('HH:mm')
  Call $student PUT "/notification-preferences/me" @{ items = @(@{ category = 'announcements'; channels = @('in_app', 'sms'); quiet_hours = @{ from = $from; to = $to }; digest = 'none' }) } | Out-Null
  $s3 = Call $admin POST "/communication/send" @{ event_type = 'announcement.published'; audience = @{ user_ids = @($studentId) }; channels = @('in_app', 'sms'); context = @{ title = "Quiet $run"; summary = 'x' } } 202
  $q = WaitFor "deferred sms" { Sql "SELECT status FROM message_logs WHERE event_id = '$($s3.data.event_id)' AND channel = 'sms'" }
  Assert ($q[0].status -eq 'deferred') "quiet hours -> sms log deferred (retry_failed delivers it after the window)"
  SqlWrite "DELETE FROM notification_preferences WHERE user_id = '$studentId'"

  Write-Host "== 4. announcement with acknowledgement (college A)"
  $colleges = (Call $admin GET "/colleges?scope=all&page_size=50").data
  $collegeA = ($colleges | Where-Object { $_.code -eq 'A' }).id
  $ann = Call $admin POST "/announcements" @{ title = "Ack $run"; body = 'Please acknowledge'; requires_ack = $true; college_id = $collegeA } 201
  Call $admin POST "/announcements/$($ann.data.id)/publish" @{ channels = @('in_app') } | Out-Null
  $hodList = (Call $hod GET "/announcements").data | Where-Object { $_.id -eq $ann.data.id }
  Assert ($hodList) "hod.cse (department CSE of college A) sees it"
  $bList = (Call $collegeAdminB GET "/announcements?scope=self").data | Where-Object { $_.id -eq $ann.data.id }
  Assert (-not $bList) "college.admin.b (college B) does not"
  Call $hod POST "/announcements/$($ann.data.id)/acknowledge" @{ acknowledge = $true } | Out-Null
  $stats = Call $admin GET "/announcements/$($ann.data.id)/stats"
  Assert ($stats.data.acknowledged -eq 1) "stats acknowledged = 1 (total $($stats.data.total))"

  Write-Host "== 5. devices"
  Call $student POST "/devices" @{ provider = 'fcm'; platform = 'android'; token = "t1-$run" } 201 | Out-Null
  $s5 = Call $admin POST "/communication/send" @{ event_type = 'announcement.published'; audience = @{ user_ids = @($studentId) }; channels = @('in_app', 'push'); context = @{ title = "Push $run"; summary = 'x' } } 202
  $p = WaitFor "push log" { Sql "SELECT status, provider FROM message_logs WHERE event_id = '$($s5.data.event_id)' AND channel = 'push' AND status = 'sent'" }
  Assert ($p[0].provider -eq 'mock') "push delivered to the mock provider"

  Write-Host "== 6. DLT compliance"
  Call $admin PUT "/settings" @{ items = @(@{ category = 'integrations'; key = 'provider_overrides'; value = @{ sms = 'msg91' } }) } | Out-Null
  $noDlt = Call $admin POST "/communication/templates" @{ event_trigger = "custom.dlt$run"; name = 'No DLT'; channels = @('sms'); body_template = 'Hi {{ name }}' } 201
  $s6 = Call $admin POST "/communication/send" @{ template_id = $noDlt.data.id; audience = @{ user_ids = @($studentId) }; channels = @('sms') } 202
  $f = WaitFor "dlt failure" { Sql "SELECT status, error FROM message_logs WHERE event_id = '$($s6.data.event_id)' AND channel = 'sms' AND status IN ('failed','sent')" }
  Assert ($f[0].status -eq 'failed' -and $f[0].error -like 'DLT_TEMPLATE_MISSING*') "no DLT id -> failed DLT_TEMPLATE_MISSING"
  $withDlt = Call $admin PUT "/communication/templates/$($noDlt.data.id)" @{ dlt_template_id = '1107000000000000001' }
  $s6b = Call $admin POST "/communication/send" @{ template_id = $withDlt.data.id; audience = @{ user_ids = @($studentId) }; channels = @('sms') } 202
  $ok6 = WaitFor "dlt sent" { Sql "SELECT status FROM message_logs WHERE event_id = '$($s6b.data.event_id)' AND channel = 'sms' AND status = 'sent'" }
  Assert ($ok6) "with the DLT id -> sent"
  SqlWrite "DELETE FROM institution_settings WHERE institution_id = '$instId' AND category = 'integrations' AND key = 'provider_overrides'"

  Write-Host "== 7. workflow definitions"
  $defs = Call $admin GET "/workflow/definitions"
  Assert ($defs.data.Count -ge 18) "$($defs.data.Count) definitions (18 shipped)"
  $leave = $defs.data | Where-Object { $_.key -eq 'leave.approval' }
  $steps = @(@{ order = 1; approver = @{ type = 'role'; value = 'hod' }; sla_hours = 24 }, @{ order = 2; approver = @{ type = 'role'; value = 'hr_officer' }; sla_hours = 24 })
  $leave2 = Call $admin PUT "/workflow/definitions/$($leave.id)" @{ steps = $steps }
  Assert ($leave2.data.version -eq $leave.version + 1) "PUT leave.approval -> version $($leave2.data.version)"

  Write-Host "== 8. leave.approval run"
  $depts = (Call $admin GET "/departments?page_size=200").data
  $cse = ($depts | Where-Object { $_.code -eq 'CSE' -and $_.college_code -eq 'A' }).id
  $wf = Call $admin POST "/_dev/workflow/start" @{ key = 'leave.approval'; context = @{ department_id = $cse }; requester = $facultyId; title = "Leave $run" } 201
  $wid = $wf.data.id
  Assert ($wf.data.status -eq 'pending' -and ($wf.data.steps[0].approver_user_id -eq $hodId)) "step 1 approver = hod.cse"
  Assert (((Call $hod GET "/workflow/inbox").data | Where-Object { $_.instance.id -eq $wid })) "hod.cse inbox shows it"
  Assert (-not ((Call $faculty GET "/workflow/inbox").data | Where-Object { $_.instance.id -eq $wid })) "faculty.1 inbox does not"
  Call $student POST "/workflow/instances/$wid/act" @{ decision = 'approve' } 403 | Out-Null
  $a1 = Call $hod POST "/workflow/instances/$wid/act" @{ decision = 'approve'; comment = 'ok' }
  Assert ($a1.data.current_step -eq 2) "hod approves -> step 2"
  Assert (((Call $hr GET "/workflow/inbox").data | Where-Object { $_.instance.id -eq $wid })) "hr inbox shows step 2"
  $a2 = Call $hr POST "/workflow/instances/$wid/act" @{ decision = 'approve' }
  Assert ($a2.data.status -eq 'approved') "hr approves -> approved"
  Assert ((Call $admin GET "/_dev/workflow/markers/$wid").data.marker -eq 'approved') "on_approved hook ran (marker)"
  WaitFor "approved event dispatched" { Sql "SELECT 1 AS x FROM domain_events WHERE aggregate_id = '$wid' AND event_type = 'workflow.approved' AND status = 'dispatched'" } | Out-Null
  WaitFor "requester notified" { (Call $faculty GET "/notifications?page_size=10").data | Where-Object { $_.event_type -eq 'workflow.approved' -and $_.title -like "*Leave $run*" } } | Out-Null
  Assert $true "workflow.acted/approved dispatched, faculty.1 notified"

  Write-Host "== 9. delegation"
  $today = (Get-Date).ToString('yyyy-MM-dd')
  Call $hod POST "/workflow/delegations" @{ to_user_id = $deanId; module = 'leaves'; from_on = $today; to_on = $today } 201 | Out-Null
  $wf2 = Call $admin POST "/_dev/workflow/start" @{ key = 'leave.approval'; context = @{ department_id = $cse }; requester = $facultyId; title = "Delegated $run" } 201
  Assert (((Call $dean GET "/workflow/inbox").data | Where-Object { $_.instance.id -eq $wf2.data.id -and $_.via -eq 'delegation' })) "dean.eng sees it via delegation"
  $d1 = Call $dean POST "/workflow/instances/$($wf2.data.id)/act" @{ decision = 'approve'; comment = 'on behalf of HOD' }
  $s1 = $d1.data.steps | Where-Object { $_.order -eq 1 -and $_.status -eq 'approved' }
  Assert ($s1.acted_by -eq $deanId -and $s1.delegated_from -eq $hodId) "acted_by = dean.eng, delegated_from = hod.cse"

  Write-Host "== 10. escalation"
  $sa = Login-SuperAdmin
  $esc = @(@{ order = 1; approver = @{ type = 'role'; value = 'hod' }; sla_hours = 0.01; escalate_to = @{ type = 'role'; value = 'registrar' } })
  $leave3 = Call $admin PUT "/workflow/definitions/$($leave.id)" @{ steps = $esc }
  $wf3 = Call $admin POST "/_dev/workflow/start" @{ key = 'leave.approval'; context = @{ department_id = $cse }; requester = $facultyId; title = "Escalate $run" } 201
  Start-Sleep -Seconds 40
  Call $sa POST "/_dev/workflow/escalate" $null 200 @{ 'X-Institution-Id' = $instId } | Out-Null
  $e = (Call $admin GET "/workflow/instances/$($wf3.data.id)").data
  Assert ($e.status -eq 'escalated' -and ($e.steps | Where-Object { $_.status -eq 'escalated' -and $_.escalated_to })) "step escalated to the registrar"
  Call $admin PUT "/workflow/definitions/$($leave.id)" @{ steps = $steps } | Out-Null

  Write-Host "== 11. parallel no-dues"
  $wf4 = Call $admin POST "/_dev/workflow/start" @{ key = 'no_dues.clearance'; context = @{ department_id = $cse }; requester = $studentId; title = "No dues $run" } 201
  Assert ((@($wf4.data.steps | Where-Object { $_.order -eq 1 })).Count -ge 6) "six parallel approvers"
  $librarian = Login 'librarian' (Get-DemoPassword 'librarian')   # one of the six parallel approvers
  $r = Call $librarian POST "/workflow/instances/$($wf4.data.id)/act" @{ decision = 'reject'; comment = 'library dues' }
  Assert ($r.data.status -eq 'rejected') "one reject -> rejected"

  Write-Host "== 12. webhook"
  $logRow = (Sql "SELECT id FROM message_logs WHERE institution_id = '$instId' AND channel = 'sms' AND status = 'sent' ORDER BY created_at DESC LIMIT 1")[0]
  $payload = (@{ message_id = $logRow.id; status = 'delivered' } | ConvertTo-Json -Compress)
  $sig = (& $Python -c "import sys,hmac,hashlib;sys.path.insert(0,'scripts');import _bootstrap;from app.core.config import settings;print(hmac.new((settings.SECRET_KEY+'mock').encode(),sys.argv[1].encode(),hashlib.sha256).hexdigest())" $payload).Trim()
  $bad = Invoke-WebRequest -Method Post -Uri "$script:BaseUrl/webhooks/mock/sms" -ContentType 'application/json' -Body $payload -Headers @{ 'X-Signature' = 'bad' } -SkipHttpErrorCheck
  Assert ($bad.StatusCode -eq 401) "invalid signature -> 401"
  $good = Invoke-WebRequest -Method Post -Uri "$script:BaseUrl/webhooks/mock/sms" -ContentType 'application/json' -Body $payload -Headers @{ 'X-Signature' = $sig } -SkipHttpErrorCheck
  Assert ($good.StatusCode -eq 200 -and ((Sql "SELECT status FROM message_logs WHERE id = '$($logRow.id)'")[0].status -eq 'delivered')) "signed callback -> delivered"

  Summary "PHASE 04 communication core & workflow engine"
}
finally {
  # this run's announcement ("Ack <run>") and custom templates (custom.verify<run> / custom.dlt<run>; no DELETE
  # endpoint — deactivating hides them) so the admin lists don't fill up with verification rows
  if ($ann) {
    try { Call $admin DELETE "/announcements/$($ann.data.id)" | Out-Null }
    catch { Write-Host "cleanup: $($_.Exception.Message)" -ForegroundColor Yellow }
  }
  # this run's dev workflow instances still open (delegated → waiting on HR, escalated, no-dues on a failed run) would
  # otherwise sit in the hod / registrar / hr inboxes; close them like engine.cancel does (open steps → skipped)
  $open = @($wf, $wf2, $wf3, $wf4) | Where-Object { $_ } | ForEach-Object { "'$($_.data.id)'" }
  if ($open) {
    $ids = $open -join ', '
    try {
      SqlWrite ("UPDATE workflow_steps SET status = 'skipped' WHERE instance_id IN ($ids) AND status IN ('pending', 'escalated'); " +
        "UPDATE workflow_instances SET status = 'cancelled', closed_at = now() WHERE id IN ($ids) AND status IN ('pending', 'escalated')")
    }
    catch { Write-Host "cleanup: $($_.Exception.Message)" -ForegroundColor Yellow }
  }
  if ($instId -and $run) {
    try { SqlWrite "UPDATE notification_templates SET is_active = FALSE WHERE institution_id = '$instId' AND event_trigger IN ('custom.verify$run', 'custom.dlt$run')" | Out-Null }
    catch { Write-Host "cleanup: $($_.Exception.Message)" -ForegroundColor Yellow }
  }
  Pop-Location
}
