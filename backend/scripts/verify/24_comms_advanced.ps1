# Phase 24 — communication advanced (Prompts/24 §24.11). Run after `seed_demo_institution.py --only comms_advanced`.
param([string]$Base = "http://localhost:8000/api/v1")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1"

$reg = Login "registrar"; $hod = Login "hod.cse"; $stu = Login "student.1"; $par = Login "parent.1"

Step "1 segments"
$f = Api GET "/comms/segments/fields" $reg
Check ($f.data -ne $null) "segment fields"
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
$s = Api POST "/comms/campaigns/$($c.data.id)/action" $reg @{ action = "send_now" }
Check ($s.data.status -in @("sending", "sent", "pending_approval")) "send accepted"
$r = Api GET "/comms/campaigns/$($c.data.id)/report" $reg
Check ($r.data -ne $null) "report"
ExpectStatus 403 { Api POST "/comms/campaigns" $stu @{ name = "x"; channels = @("sms") } }

Step "3 HOD department limits"
ExpectStatus 403 { Api POST "/comms/campaigns" $hod @{ name = "HOD SMS"; channels = @("sms"); audience_rules = @{ person_types = @("student") } } }

Step "4 emergency"
$log = Api GET "/comms/emergency/log" $reg
Check ($log.data.Count -ge 1) "emergency log"
ExpectStatus 403 { Api POST "/comms/emergency/broadcast" $stu @{ message = "Not allowed"; audience = "all" } }

Step "5 bot"
$fl = Api GET "/comms/bot/flows" $reg
Check ($fl.data.flows.Count -ge 3) "bot flows"
$sim = Api POST "/comms/simulator/inbound-whatsapp" $reg @{ from = "+919000000101"; text = "hi" }
Check ($sim.data -ne $null) "simulator replies"

Step "6 assistant"
$me = Api GET "/assistant/me" $stu
Check ($me.data -ne $null) "assistant status"

Step "7 analytics + my messages"
$d = Api GET "/comms/analytics/delivery" $reg
Check ($d.data -ne $null) "delivery analytics"
ExpectStatus 403 { Api GET "/comms/analytics/delivery" $stu }
$mm = Api GET "/comms/me/messages" $par
Check ($mm.data -ne $null) "my messages"

Summary
