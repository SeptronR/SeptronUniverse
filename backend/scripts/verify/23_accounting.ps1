# Phase 23 — accounting & budget (Prompts/23 §23.11). Run after `seed_demo_institution.py --only accounting`.
param([Alias("BaseUrl")][string]$Base = "http://localhost:8000/api/v1")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1" -BaseUrl $Base

$acc = Login "accountant"; $hod = Login "hod.cse"; $hodE = Login "hod.ece"; $fac = Login "faculty.1"; $iqac = Login "iqac"
$cab = Login "college.admin.b"; $aud = Login "auditor.tmp"; $stu = Login "student.1"

Step "1 chart"
$tree = Api GET "/accounting/accounts/tree" $acc
Check ($tree.data.Count -ge 5) "chart tree"
ExpectStatus 403 { Api GET "/accounting/accounts/tree" $stu }
ExpectStatus 403 { Api GET "/accounting/accounts/tree" $hod }
$mine = Api GET "/accounting/budgets/me" $hod
Check ($mine.data.Count -ge 1) "HOD sees own department heads"

Step "2 chart edits"
$flat = Api GET "/accounting/accounts" $acc
$exp = $flat.data | Where-Object { $_.code -eq "5000" }
$sub = Api POST "/accounting/accounts" $acc @{ code = "59$(Get-Random -Minimum 50 -Maximum 99)"; name = "Verify sub-account"; parent_id = $exp.id }
Check ($sub.data.account_type -eq "expense") "type inherited from parent"
$used = $flat.data | Where-Object { $_.code -eq "5200" }
if ($used.debit_paise -gt 0) { ExpectStatus 409 { Api PUT "/accounting/accounts/$($used.id)" $acc @{ is_active = $false } } }

Step "3 postings"
$gaps = Api GET "/accounting/postings/gaps" $acc
Check ($null -ne $gaps.data) "gap check answers"

Step "4 expenses"
$heads = $mine.data | Where-Object { $_.status -eq "approved" -and $_.available_paise -gt 400000 } | Select-Object -First 1
$cons = $flat.data | Where-Object { $_.code -eq "5300" }
if ($heads) {
    $e = Api POST "/accounting/expenses" $hod @{ ledger_account_id = $cons.id; budget_head_id = $heads.id; amount_paise = 400000; spent_on = (Get-Date).ToString("yyyy-MM-dd"); payee = "Verify vendor"; description = "Verify consumables" }
    Check ($e.data.status -eq "recorded") "recorded"
    ExpectStatus 404 { Api GET "/accounting/expenses/$($e.data.id)" $hodE }
    Api POST "/accounting/expenses/$($e.data.id)/submit" $hod | Out-Null
    $d = Api POST "/accounting/expenses/$($e.data.id)/decide" $acc @{ action = "approve" }
    Check ($d.data.status -eq "approved") "approved below the threshold"
}
ExpectStatus 422 { Api POST "/accounting/expenses" $acc @{ ledger_account_id = $cons.id; amount_paise = 5000000; spent_on = (Get-Date).ToString("yyyy-MM-dd"); payee = "No doc"; description = "Large without attachment" } }

Step "6 grants"
$g = Api GET "/accounting/grants" $fac
Check ($g.data.Count -ge 1) "PI sees own grant"
ExpectStatus 404 { Api GET "/accounting/grants/$($g.data[0].id)" $hodE }

Step "7 reconciliation"
$r = Api GET "/accounting/reconciliations" $acc
$open = $r.data | Where-Object { $_.status -eq "open" } | Select-Object -First 1
if ($open) { ExpectStatus 409 { Api POST "/accounting/reconciliations/$($open.id)/close" $acc } }

Step "8 GST + statements"
$gst = Api GET "/accounting/gst/summary?period=$((Get-Date).ToString('yyyy-MM'))" $acc
Check ($null -ne $gst.data) "GST summary"
$from = (Get-Date).AddMonths(-12).ToString("yyyy-MM-dd"); $to = (Get-Date).ToString("yyyy-MM-dd")
$tb = Api GET "/accounting/trial-balance?from=$from&to=$to" $acc
Check ($tb.data.balanced) "trial balance debits = credits"
Api GET "/accounting/statements/receipts_payments?from=$from&to=$to" $iqac | Out-Null
Api GET "/accounting/statements/income_expenditure?from=$from&to=$to" $cab | Out-Null
ExpectStatus 403 { Api POST "/accounting/expenses" $aud @{ ledger_account_id = $cons.id; amount_paise = 100; spent_on = $to; payee = "x"; description = "xx" } }

Step "dashboard"
$db = Api GET "/accounting/dashboard" $acc
Check ($db.data.receivables_paise -ge 0) "dashboard"

Summary
