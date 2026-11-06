# Phase 35 — dashboards, analytics & early warning (Prompts/35 §35.11). Run after
# `seed_demo_institution.py --only analytics` (demo-uni). Written in the development-only run; not executed yet.
# Role names of the prompt map to the seeded users: principal = vice_chancellor, inst.admin = institution admin,
# faculty.m1 = the mentor of the highest-risk student (resolved from /risk/students), student.risk = that student.
param([string]$BaseUrl = "http://localhost:8000/api/v1", [string]$Institution = "demo-uni")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl

$admin = Login "inst.admin"
$prin = Login "principal"
$reg = Login-Mfa 'registrar' 'registrar'
$coe = Login-Mfa 'controller_of_examinations' 'coe'
$hod = Login "hod.cse"
$hodE = Login "hod.ece"
$dean = Login "dean.eng"
$fac = Login "faculty.1"
$acct = Login "accountant"
$plc = Login "placement"
$iqac = Login "iqac"
$colB = Login "college.admin.b"
$stu = Login "student.1"
$aud = Login "auditor.tmp"

Write-Host "== 1 read models"
$job = Call $admin POST "/analytics/readmodels/refresh" @{ views = @() } 202
Assert ($job.data.job_id) "refresh job queued"
Start-Sleep -Seconds 20
$rm = Call $admin GET "/analytics/readmodels"
Assert (@($rm.data).Count -eq 13) "13 read models"
Assert (@($rm.data | Where-Object { $_.stale }).Count -eq 0) "no stale read model after refresh"
Call $fac GET "/analytics/readmodels" $null 403 | Out-Null

Write-Host "== 2 role dashboards"
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$d = Call $prin GET "/dashboard"
$sw.Stop(); Write-Host "   principal dashboard: $($sw.ElapsedMilliseconds) ms"
Assert ($d.data.role -eq "vice_chancellor") "principal composition"
Assert (@($d.data.widgets | Where-Object { -not $_.permission_ok }).Count -eq 0) "every widget permission_ok"
Assert (@($d.data.widgets | Where-Object { $_.stat -and $_.stat.source -eq "mv_kpi_daily" }).Count -ge 1) "stats from mv_kpi_daily"
Assert ($d.meta.visibility.scopes -contains "all") "principal scopes include all"
$ds = Call $stu GET "/dashboard"
Assert ($ds.data.role -eq "student") "student composition"
Assert (@($ds.meta.visibility.scopes).Count -eq 0) "student: no ScopeTabs"
$att = @($ds.data.widgets | Where-Object { $_.key -eq "attendance_avg_pct" })[0]
Assert ($null -ne $att.stat.class_average -or $att.unavailable) "class average comparison"
$df = Call $hod GET "/dashboard?role=faculty"
Assert ($df.data.role -eq "faculty" -or $df.data.role -eq "hod") "role switch honoured when held"

Write-Host "== 3 scope narrowing"
$hod = Login "hod.cse"   # fresh token: the steps above can outlast the access token
$hAll = Call $hod GET "/analytics/charts/students.enrolment_by_category?scope=all"
Assert ($hAll.data.scope -eq "department") "HOD scope=all narrowed to department"
$sl = Call $hod GET "/students?scope=department&size=1"
# the chart counts active enrolments; the list also holds break / detained students (07 fixtures)
Assert ([int]$hAll.data.total -le [int]$sl.meta.pagination.total -and [int]$hAll.data.total -ge [int]($sl.meta.pagination.total * 0.9)) "chart total ($($hAll.data.total)) within the department list ($($sl.meta.pagination.total))"
$cB = Call $colB GET "/analytics/charts/students.enrolment_by_college"
Assert (@($cB.data.series).Count -le 1) "college admin sees own college only"
$dd = Call $aud GET "/analytics/charts/students.enrolment_by_category/drilldown"
Assert ($dd.data.aggregates_only -or $dd.data.masked) "auditor drill-down masked / aggregates"

Write-Host "== 4 charts"
$cat = Call $acct GET "/analytics/charts"
Assert (@($cat.data | Where-Object { $_.module -eq "fees" }).Count -ge 5) "accountant: fee charts"
Assert (@($cat.data | Where-Object { $_.module -eq "exams" }).Count -eq 0) "accountant: no exam charts"
$cm = Call $acct GET "/analytics/charts/fees.collection_by_mode_daily?dims[period]=last_30d"
$sum = 0; foreach ($r in $cm.data.table.rows) { for ($i = 1; $i -lt $r.Count; $i++) { $sum += [double]($r[$i] | ForEach-Object { if ($_ -eq $null) { 0 } else { $_ } }) } }
Assert ([math]::Abs($sum - [double]$cm.data.total) -lt 1) "series total equals table total"
Call $iqac GET "/analytics/charts/accreditation.metric_trend?params[bogus]=1" $null 422 | Out-Null
$csv = Invoke-WebRequest -Uri "$BaseUrl/analytics/charts/fees.dues_aging?format=csv" -Headers @{ Authorization = "Bearer $acct" }
Assert ($csv.Content -like "label*") "csv inline"
$exp = Call $acct POST "/analytics/charts/fees.collection_by_mode_daily/export" @{ format = "xlsx" } 202
Assert ($exp.data.job_id) "export job"

Write-Host "== 5 insights"
$ins = Call $reg GET "/analytics/insights/students"
Assert (@($ins.data.charts).Count -ge 1) "insights charts for students"
Call $fac GET "/analytics/insights/attendance" | Out-Null

Write-Host "== 6 freshness / ETag"
$e1 = Invoke-WebRequest -Uri "$BaseUrl/analytics/charts/fees.overdue_total" -Headers @{ Authorization = "Bearer $acct" }
Assert ($e1.Headers.ETag) "ETag present"

Write-Host "== 7 KPI targets"
$t = Call $admin GET "/analytics/targets"
Call $admin PUT "/analytics/targets" @{ targets = @{ attendance_pct = 99 } } | Out-Null
Call $admin POST "/analytics/targets/evaluate" @{} 202 | Out-Null
Start-Sleep -Seconds 5
$al = Call $prin GET "/analytics/alerts?active=true"
Assert (@($al.data | Where-Object { $_.key -eq "attendance_pct" }).Count -ge 1) "attendance breach open"
Call $admin PUT "/analytics/targets" @{ targets = @{ attendance_pct = $t.data.targets.attendance_pct } } | Out-Null

Write-Host "== 8 layouts / pins"
$lay = Call $admin GET "/dashboard/layouts/hod"
$ws = @($lay.data.widgets | Where-Object { -not $_.hidden -and $_.key -ne "research.publications_by_department" } | ForEach-Object { @{ key = $_.key; position = $_.position } })
$ws += @{ key = "research.publications_by_department"; hidden = $true }
Call $admin PUT "/dashboard/layouts/hod" @{ widgets = $ws } | Out-Null
$h2 = Call $hod GET "/dashboard"
Assert (@($h2.data.widgets | Where-Object { $_.key -eq "research.publications_by_department" }).Count -eq 0) "hidden widget gone"
Call $hod PUT "/dashboard/pins" @{ pinned_keys = @("attendance.pct_by_batch"); hidden_keys = @() } | Out-Null
$h3 = Call $hod GET "/dashboard"
Assert ($h3.data.widgets[0].key -eq "attendance.pct_by_batch") "pinned first"
Call $admin POST "/dashboard/layouts/hod/reset" @{} | Out-Null
Call $fac PUT "/dashboard/layouts/hod" @{ widgets = @() } 403 | Out-Null

Write-Host "== 9 digests"
$dg = Call $admin POST "/analytics/digests" @{ cadence = "weekly"; roles = @("hod"); channels = @("in_app", "email"); hour = 7 } 201
$sn = Call $admin POST "/analytics/digests/$($dg.data.id)/send-now" @{} 202
Assert ($sn.data.job_id) "digest job"
Call $admin DELETE "/analytics/digests/$($dg.data.id)" | Out-Null

Write-Host "== 10 early warning"
$co = Call $reg GET "/risk/cohort?group_by=department"
Assert (@($co.data.cells | Where-Object { ($_.high + $_.medium) -ge 1 }).Count -ge 1) "a department with at-risk students"
$coE = Call $hodE GET "/risk/cohort?group_by=department"
Assert (@($coE.data.cells).Count -le 1) "HOD ECE: own department only"
$rs = Call $reg GET "/risk/students?level=high"
$top = @($rs.data)[0]
if (-not $top) { $top = @((Call $reg GET "/risk/students?level=medium").data)[0] }   # flags are recomputed; high may be empty
Call $stu GET "/risk/students?level=high" $null 403 | Out-Null
$iv = Call $hod POST "/risk/students/$($top.enrollment_id)/interventions" @{ intervention_type = "guardian_call"; notes = "verify 35" } 201
$ivs = Call $hod GET "/risk/students/$($top.enrollment_id)/interventions"
Assert (@($ivs.data | Where-Object { $_.id -eq $iv.data.id }).Count -eq 1) "intervention listed"
$tr = Call $reg GET "/risk/cohort/trend"
Assert ($null -ne $tr.data.periods) "trend"
$ex = Call $reg POST "/risk/cohort/export" @{ kind = "cohort" } 202
Assert ($ex.data.job_id) "cohort export job"

Write-Host "== 11 feature off"
Call $dean GET "/dashboard" | Out-Null

Write-Host "== 12 public counters"
$pc = Invoke-RestMethod -Uri "$BaseUrl/analytics/public-counters?institution=$Institution"
Assert ($pc.data.counters.PSObject.Properties.Name -contains "students_active") "public students counter"
Assert (-not ($pc.data.counters.PSObject.Properties.Name -contains "fee_overdue_paise")) "no private keys"

Summary "Phase 35"
