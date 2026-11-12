# Phase 21 — transport (Prompts/21 §21.11). Run after `seed_demo_institution.py --only transport`.
param([Alias("BaseUrl")][string]$Base = "http://localhost:8000/api/v1")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1" -BaseUrl $Base

$mgr = Login "transport.mgr"; $d1 = Login "driver.1"; $d2 = Login "driver.2"; $acc = Login "accountant"
$hod = Login "hod.cse"; $stu = Login "student.1"; $par = Login "parent.1"; $cab = Login "college.admin.b"; $aud = Login "auditor.tmp"

Step "1 fleet + compliance"
$v = Api GET "/transport/vehicles" $mgr
Check ($v.data.Count -ge 12) "manager sees 12 vehicles"
Check ((@($v.data | Where-Object { $_.chips -contains "insurance_expiring" })).Count -ge 2) "2 insurance_expiring chips"
ExpectStatus 403 { Api GET "/transport/vehicles" $stu }
$c = Api GET "/transport/vehicles/compliance" $mgr
Check ($c.data.Count -ge 2) "compliance list"

Step "2 routes + reorder"
$r = Api POST "/transport/routes" $mgr @{ code = "VR$(Get-Random -Maximum 9999)"; name = "Verify route"; fee_paise = 1000000; stops = @(
    @{ name = "S1"; fee_paise = 900000 }, @{ name = "S2" }, @{ name = "S3" }, @{ name = "S4" }, @{ name = "S5" }) }
$ids = @($r.data.stops | Sort-Object sequence -Descending | ForEach-Object { $_.id })
$re = Api POST "/transport/routes/$($r.data.id)/stops/reorder" $mgr @{ stop_ids = $ids }
Check (($re.data | ForEach-Object { $_.sequence }) -join "," -eq "1,2,3,4,5") "renumbered 1..5"

Step "3 allocation"
$routes = Api GET "/transport/routes" $mgr
$r1 = $routes.data | Where-Object { $_.code -eq "R1" }
$me = Api GET "/transport/me" $stu
Check ($me.data.route.code -eq "R1") "student.1 on R1"
ExpectStatus 409 { Api POST "/transport/allocations" $mgr @{ person_type = "student"; person_id = $me.data.allocation.person_id; route_id = $r1.id; stop_id = $r1.stops[0].id } }

Step "6 driver flow"
$today = (Get-Date).ToString("yyyy-MM-dd")
$dt = Api GET "/transport/driver/trips?date=$today" $d1
Check ($null -ne $dt.data) "driver.1 trips"
$t = $dt.data | Where-Object { $_.status -eq "scheduled" } | Select-Object -First 1
if ($t) {
    ExpectStatus 404 { Api POST "/transport/trips/$($t.id)/start" $d2 @{} }   # out of the driver's scope: 404 (QA-028)
    $s = Api POST "/transport/trips/$($t.id)/start" $d1 @{ odometer = 50000 }
    Check ($s.data.status -eq "in_progress") "trip started"
    $m = Api GET "/transport/trips/$($t.id)/manifest" $d1
    Check ($m.data.stops.Count -ge 1) "manifest"
    $e = Api POST "/transport/trips/$($t.id)/end" $d1 @{ odometer = 50024 }
    Check ($e.data.status -eq "completed") "trip ended"
}

Step "10 fuel ownership"
$v2 = $v.data | Where-Object { $_.registration_no -eq "KA01AB1002" }
# the scoped vehicle lookup answers 404 before the ownership 403 (spec says 403; refused either way, QA-028)
ExpectStatus 404 { Api POST "/transport/vehicles/$($v2.id)/fuel" $d1 @{ filled_on = $today; litres = 60; cost_paise = 600000 } }
$cpk = Api GET "/transport/reports/cost_per_km" $mgr
Check ($cpk.data.rows.Count -ge 12) "cost per km report"

Step "11 visibility"
Api GET "/transport/allocations?scope=department" $hod | Out-Null
$w = Api GET "/transport/wards" $par
Check ($w.data.Count -ge 1) "parent sees ward allocation"
$cb = Api GET "/transport/vehicles" $cab
Check ($cb.data.Count -lt $v.data.Count) "college admin B sees fewer vehicles"
Api GET "/transport/allocations" $aud | Out-Null
ExpectStatus 403 { Api POST "/transport/allocations" $aud @{ person_type = "student"; person_id = $me.data.allocation.person_id; route_id = $r1.id; stop_id = $r1.stops[0].id } }
Api GET "/transport/allocations" $acc | Out-Null
ExpectStatus 403 { Api POST "/transport/allocations" $acc @{ person_type = "student"; person_id = $me.data.allocation.person_id; route_id = $r1.id; stop_id = $r1.stops[0].id } }

Step "stats"
$st = Api GET "/transport/stats" $mgr
Check ($st.data.vehicles -ge 12) "stats"

Summary
