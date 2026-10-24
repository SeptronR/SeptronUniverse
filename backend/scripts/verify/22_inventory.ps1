# Phase 22 — inventory, procurement & bills (Prompts/22 §22.11). Run after `seed_demo_institution.py --only inventory`.
param([string]$Base = "http://localhost:8000/api/v1")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1"

$mgr = Login "inv.mgr"; $central = Login "store.central"; $cse = Login "store.cse"; $hod = Login "hod.cse"
$fac = Login "faculty.1"; $acc = Login "accountant"; $va = Login "vendor.a"; $cab = Login "college.admin.b"; $aud = Login "auditor.tmp"

Step "1 catalogue + store scope"
$items = Api GET "/inventory/items" $fac
Check ($items.data.Count -ge 300) "faculty reads the catalogue"
Check ($null -eq $items.data[0].unit_cost_paise) "no costs for faculty"
$stores = Api GET "/inventory/stores" $mgr
$centralStore = $stores.data | Where-Object { $_.store_type -eq "central" } | Select-Object -First 1
ExpectStatus 403 { Api GET "/inventory/stores/$($centralStore.id)/stock" $cse }
$stock = Api GET "/inventory/stores/$($centralStore.id)/stock" $central
Check ($stock.data.Count -ge 1) "keeper sees own store stock"

Step "2 hazardous item needs safety data"
ExpectStatus 422 { Api POST "/inventory/items" $mgr @{ name = "Nitric acid verify"; unit = "l"; is_hazardous = $true } }

Step "3 stock"
$row = $stock.data | Where-Object { $_.quantity -ge 5 -and -not $_.is_hazardous } | Select-Object -First 1
$iss = Api POST "/inventory/stock/issue" $central @{ store_id = $centralStore.id; issued_to_type = "department"; items = @(@{ item_id = $row.item_id; quantity = 1 }) }
Check ($iss.data.transactions.Count -eq 1) "issue transaction"
ExpectStatus 409 { Api POST "/inventory/stock/issue" $central @{ store_id = $centralStore.id; issued_to_type = "department"; items = @(@{ item_id = $row.item_id; quantity = 100000 }) } }

Step "4 indents"
$ind = Api POST "/inventory/indents" $fac @{ purpose = "Verify indent"; items = @(@{ item_id = $row.item_id; qty = 2 }) }
$sub = Api POST "/inventory/indents/$($ind.data.id)/submit" $fac
Check ($sub.data.status -eq "submitted") "submitted to the workflow"
$h = Api GET "/inventory/indents?scope=department" $hod
Check ($h.meta.visibility.scopes -contains "department") "HOD scope tabs"

Step "6 POs"
$pos = Api GET "/inventory/purchase-orders" $mgr
Check ($pos.data.Count -ge 20) "seeded POs"
$vp = Api GET "/vendor/pos" $va
Check ($vp.data -ne $null) "vendor sees own POs"

Step "8 assets"
$a = Api GET "/inventory/assets" $mgr
Check ($a.data.Count -ge 400) "asset register"
Api GET "/inventory/assets/me" $fac | Out-Null
ExpectStatus 404 { Api GET "/inventory/assets/lookup/$('0' * 48)" $mgr }

Step "11 bills"
$b = Api GET "/inventory/vendor-bills" $acc
Check ($b.data.Count -ge 30) "bills"
$ag = Api GET "/inventory/vendor-bills/ageing" $acc
Check ($ag.data.buckets -ne $null) "ageing"
$vb = Api GET "/vendor/bills" $va
Check (@($vb.data | Where-Object { $_.supplier_id -ne $vb.data[0].supplier_id }).Count -eq 0) "vendor sees own bills only"

Step "14 visibility"
Api GET "/inventory/stores" $cab | Out-Null
Api GET "/inventory/assets" $aud | Out-Null
ExpectStatus 403 { Api POST "/inventory/stores" $aud @{ name = "nope" } }

Summary
