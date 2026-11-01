# Phase 17 — OBE attainment & CQI (Prompts/17 §17.11). Run after `seed_demo_institution.py --only attainment`.
param([Alias("BaseUrl")][string]$Base = "http://localhost:8000/api/v1")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1" -BaseUrl $Base

$obe = Login "obe"; $hod = Login "hod.cse"; $fac = Login "faculty.1"; $iqac = Login "iqac"; $stu = Login "student.1"; $aud = Login "auditor.tmp"

Step "1 configs"
$runs = Api GET "/cqi-actions" $obe
$progAction = $runs.data | Where-Object { $_.scope_type -eq "program" } | Select-Object -First 1
$progId = $progAction.scope_id
$eff = Api GET "/attainment-configs/effective?program_id=$progId" $obe
Check ($eff.data.levels.Count -ge 1) "effective config"
$bad = @{ scope_type = "program"; scope_id = $progId; levels = @(@{ level = 1; min_pct = 60 }, @{ level = 2; min_pct = 50 }) }
ExpectStatus 422 { Api PUT "/attainment-configs" $obe $bad }
$bad2 = @{ scope_type = "program"; scope_id = $progId; levels = @(@{ level = 1; min_pct = 40 }); direct_weight = 70; indirect_weight = 20 }
ExpectStatus 422 { Api PUT "/attainment-configs" $obe $bad2 }

Step "3 CO attainment (offering of a CQI action)"
$offAction = $runs.data | Where-Object { $_.scope_type -eq "offering" } | Select-Object -First 1
$oid = $offAction.scope_id
$co = Api GET "/course-offerings/$oid/attainment" $obe
Check ($co.data.cos.Count -ge 1) "CO rows"
$row = $co.data.cos[0]
if ($row.cia_level -ne $null -and $row.ese_level -ne $null -and $row.indirect_level -eq $null) {
  $expected = [math]::Round((0.3 * $row.cia_level + 0.7 * $row.ese_level), 2)
  Check ([math]::Abs($expected - $row.direct_level) -le 0.01) "direct = 0.3 cia + 0.7 ese"
}
if ($null -ne $row.final_level) { Check ([math]::Abs(($row.target - $row.final_level) - $row.gap) -le 0.01) "gap = target - final" }

Step "5 visibility"
Api GET "/course-offerings/$oid/attainment" $hod | Out-Null
ExpectStatus 403 { Api GET "/attainment/me?offering_id=$oid" $stu }

Step "6 PO run"
$batchRun = Api GET "/obe/gaps?program_id=$progId&threshold=0" $obe
Check ($null -ne $batchRun.data) "gap list"

Step "10 CQI"
$created = Api POST "/cqi-actions" $obe @{ scope_type = "program"; scope_id = $progId; action_text = "Verify script action"; due_on = (Get-Date).AddDays(30).ToString("yyyy-MM-dd") }
Check ($created.data.status -eq "planned") "planned"
ExpectStatus 404 { Api PUT "/cqi-actions/$($created.data.id)" $fac @{ action_text = "not mine" } }
Api POST "/cqi-actions/$($created.data.id)/status" $obe @{ status = "in_progress" } | Out-Null
Api POST "/cqi-actions/$($created.data.id)/status" $obe @{ status = "done"; evidence_url = "verify/evidence.pdf" } | Out-Null
$v = Api POST "/cqi-actions/$($created.data.id)/verify" $obe @{ approve = $true }
Check ($v.data.status -eq "verified") "verified"

Step "12 auditor"
ExpectStatus 403 { Api POST "/course-offerings/$oid/attainment/compute" $aud @{} }

Summary
