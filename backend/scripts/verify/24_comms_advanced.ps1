# Phase 24 — communication advanced (Prompts/24 §24.11). Run after `seed_demo_institution.py --only comms_advanced`.
param([Alias("BaseUrl")][string]$Base = "http://localhost:8000/api/v1")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1" -BaseUrl $Base

$reg = Login "registrar"; $hod = Login "hod.cse"; $stu = Login "student.1"; $par = Login "parent.1"

Step "1 segments"
$f = Api GET "/comms/segments/fields" $reg
Check ($null -ne $f.data) "segment fields"
$p = Api POST "/comms/segments/preview" $reg @{ person_types = @("student") }
Check ($p.data.count -ge 1) "preview counts students"
ExpectStatus 403 { Api POST "/comms/segments/preview" $stu @{ person_types = @("student") } }
$saved = Api GET "/comms/segments" $reg
Check ($saved.data.Count -ge 2) "saved segments"

Step "2 campaigns"
$c = Api POST "/comms/campaigns" $reg @{ name = "Verify campaign"; channels = @("in_app"); audience_rules = @{ person_types = @("student") }; body_override = @{ in_app = "Verify message" } }
Check ($c.data.status -eq "draft") "draft"
$chk = Api POST "/comms/campaigns/$($c.data.id)/compliance-check" $reg
Check ($chk.data.ok) "compliance ok for in-app"
$sb = Api POST "/comms/campaigns/$($c.data.id)/action" $reg @{ action = "submit" }
if ($sb.data.status -eq "pending_approval") { Api POST "/comms/campaigns/$($c.data.id)/action" $reg @{ action = "approve" } | Out-Null }
$s = Api POST "/comms/campaigns/$($c.data.id)/action" $reg @{ action = "send_now" }
Check ($s.data.status -in @("sending", "sent", "pending_approval")) "send accepted"
$r = Api GET "/comms/campaigns/$($c.data.id)/report" $reg
Check ($null -ne $r.data) "report"
ExpectStatus 403 { Api POST "/comms/campaigns" $stu @{ name = "x"; channels = @("sms") } }

Step "3 HOD department limits"
ExpectStatus 403 { Api POST "/comms/campaigns" $hod @{ name = "HOD SMS"; channels = @("sms"); audience_rules = @{ person_types = @("student") } } }

Step "4 emergency"
$log = Api GET "/comms/emergency/log" $reg
Check ($log.data.Count -ge 1) "emergency log"
ExpectStatus 403 { Api POST "/comms/emergency/broadcast" $stu @{ message = "Not allowed"; audience = "all" } }

# 02 cascades comms.whatsapp off with its dependants
$saT = Login-SuperAdmin; $instId = (Api GET "/auth/me" $reg).data.user.institution_id
foreach ($k in "comms.whatsapp", "comms.whatsapp_bot") { Api PUT "/institutions/$instId/features/$k" $saT @{ enabled = $true; confirm_dependencies = $true; reason = "verify 24" } @{ "X-Institution" = "demo-uni" } | Out-Null }
Start-Sleep -Seconds 8   # feature cache invalidates through the outbox
Step "5 bot"
$fl = Api GET "/comms/bot/flows" $reg
Check ($fl.data.flows.Count -ge 3) "bot flows"
$sim = Api POST "/comms/simulator/inbound-whatsapp" $reg @{ phone = "+919000000101"; text = "hi" }
Check ($null -ne $sim.data) "simulator replies"

Step "6 assistant"
$me = Api GET "/assistant/me" $stu
Check ($null -ne $me.data) "assistant status"

Step "7 analytics + my messages"
$d = Api GET "/comms/analytics/delivery" $reg
Check ($null -ne $d.data) "delivery analytics"
ExpectStatus 403 { Api GET "/comms/analytics/delivery" $stu }
$mm = Api GET "/comms/me/messages" $par
Check ($null -ne $mm.data) "my messages"

Summary
