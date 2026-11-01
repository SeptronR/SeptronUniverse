# Phase 20 — hostel, mess & staff accommodation (Prompts/20 §20.11). Run after `seed_demo_institution.py --only hostel`.
param([Alias("BaseUrl")][string]$Base = "http://localhost:8000/api/v1")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1" -BaseUrl $Base

$reg = Login "registrar"; $warden = Login "warden.h1"; $gate = Login "gate.h1"; $hod = Login "hod.cse"; $aud = Login "auditor.tmp"; $par = Login "parent.1"

Step "1 visibility"
$all = Api GET "/hostels" $reg
Check ($all.data.Count -ge 4) "registrar sees all hostels"
$own = Api GET "/hostels" $warden
Check ($own.data.Count -eq 1) "warden sees own hostel"
$h = $own.data[0]
$occ = Api GET "/hostels/$($h.id)/occupancy" $warden
Check ($occ.data.totals.beds -ge 1) "occupancy totals"

Step "3 allotment dry run"
$dry = Api POST "/hostel-applications/allot" $reg @{ dry_run = $true }
Check ($dry.data.dry_run) "dry run answers inline"

Step "4 check-in ownership"
$other = $all.data | Where-Object { $_.id -ne $h.id } | Select-Object -First 1
$oa = Api GET "/hostel-allocations?hostel_id=$($other.id)&status=allotted" $reg
if ($oa.data.Count -ge 1) { ExpectStatus 404 { Api POST "/hostel-allocations/$($oa.data[0].id)/check-in" $warden @{ room_condition = @{}; inventory = @() } } }

Step "6 leaves queue"
$lv = Api GET "/hostel-leaves?status=requested" $warden
Check ($null -ne $lv.data) "leave queue"

Step "7 gate"
ExpectStatus 404 { Api POST "/hostel-gate/scan" $gate @{ qr_token = "hl$('0' * 48)"; direction = "out" } }

Step "9 roll-call duplicate"
$rc = Api GET "/hostel-roll-calls?hostel_id=$($h.id)" $warden
Check ($rc.data.Count -ge 1) "roll-call history"

Step "10 mess"
$bills = Api GET "/mess-bills" $warden
Check ($bills.data.Count -ge 1) "mess bills"

Step "15 quarters"
$q = Api GET "/staff-quarters" $reg
Check ($q.data.Count -ge 20) "quarters seeded"

Step "16 visibility"
Api GET "/hostel-allocations" $hod | Out-Null
Api GET "/hostel-leaves/wards" $par | Out-Null
Api GET "/hostel-allocations" $aud | Out-Null
ExpectStatus 403 { Api POST "/hostel-applications/allot" $aud @{ dry_run = $true } }

Summary
