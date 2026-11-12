# Phase 25 — calendar, events & facilities (Prompts/25 §25.11). Run after `seed_demo_institution.py --only facilities`.
param([Alias("BaseUrl")][string]$Base = "http://localhost:8000/api/v1")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1" -BaseUrl $Base

$reg = Login "registrar"; $hod = Login "hod.cse"; $stu = Login "student.1"; $stu2 = Login "student.2"; $fac = Login "faculty.1"

Step "1 calendar"
$c = Api GET "/calendar?scope=mine" $stu
Check ($c.data.items.Count -ge 1) "personal calendar merged"
$i = Api GET "/calendar?scope=institution" $reg
Check ($i.data.sources -contains "holidays") "source registry"
$t = Api POST "/calendar/feed-token" $stu
Check ($t.data.webcal_url -like "webcal://*") "webcal url"
$ics = Invoke-WebRequest -Uri $t.data.url -UseBasicParsing
Check ($ics.Content -like "BEGIN:VCALENDAR*") "personal ics"
Api DELETE "/calendar/feed-token" $stu | Out-Null
ExpectStatus 404 { Invoke-WebRequest -Uri $t.data.url -UseBasicParsing }

Step "2 events"
$from = (Get-Date).AddDays(30).ToString("yyyy-MM-dd")
$e = Api POST "/events" $fac @{ event_type = "fdp"; title = "Verify FDP"; from_on = $from; to_on = $from; budget_paise = 5000000; registration = @{ open = $true; fee_paise = 50000; capacity = 2 } }
Check ($e.data.naac_criterion -eq "6.3.3") "NAAC default"
$s = Api POST "/events/$($e.data.id)/action" $fac @{ action = "submit" }
Check ($s.data.workflow.status -eq "pending") "event.approval started"
ExpectStatus 403 { Api POST "/events" $stu @{ event_type = "fdp"; title = "x"; from_on = $from; to_on = $from } }

Step "3 bookings"
$rooms = Api GET "/facilities/rooms/availability?from_at=$((Get-Date).AddDays(3).ToString('s'))Z&to_at=$((Get-Date).AddDays(3).AddHours(2).ToString('s'))Z" $fac
Check ($rooms.data.rooms.Count -ge 1) "availability"
ExpectStatus 422 { Api POST "/facilities/room-bookings" $fac @{ room_id = $rooms.data.rooms[0].room_id; from_at = (Get-Date).AddHours(2).ToString("o"); to_at = (Get-Date).AddHours(3).ToString("o"); purpose = "Too soon" } }

Step "4 service desk"
$sr = Api POST "/facilities/service-requests" $stu @{ category = "it"; description = "Wi-Fi down in library"; priority = "normal" }
Check ($null -ne $sr.data.ticket_number) "ticket number"
ExpectStatus 404 { Api GET "/facilities/service-requests/$($sr.data.id)" $stu2 }
$d = Api GET "/facilities/service-desk/dashboard" $reg
Check ($d.data.open -ge 1) "dashboard"

Step "5 SOS / health / counselling / wallet gating"
$sos = Api POST "/emergency/sos" $stu @{ alert_type = "sos"; location = @{ text = "Library" }; drill = $true }
Check ($sos.data.status -eq "raised") "SOS raised"
ExpectStatus 404 { Api GET "/emergency/alerts/$($sos.data.id)" $stu2 }
ExpectStatus 403 { Api GET "/health/visits" $hod }
$hs = Api GET "/health/stats" $reg
Check ($hs.data.visits -ge 1) "health counts"
$w = Api GET "/wallet/me" $stu2
Check ($w.data.balance_paise -ge 0) "own wallet"

Done
