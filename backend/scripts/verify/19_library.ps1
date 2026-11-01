# Phase 19 — library (Prompts/19 §19.11). Run after `seed_demo_institution.py --only library`.
param([Alias("BaseUrl")][string]$Base = "http://localhost:8000/api/v1")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1" -BaseUrl $Base

$lib = Login "librarian"; $hod = Login "hod.cse"; $acc = Login "accountant"; $stu = Login "student.1"; $fac = Login "faculty.1"; $par = Login "parent.1"; $aud = Login "auditor.tmp"

Step "1 stats & visibility"
$s = Api GET "/library/stats" $lib
Check ($s.data.books -ge 1000) "books seeded"
ExpectStatus 403 { Api GET "/library/stats" $stu }
$b = Api GET "/library/books?page_size=5" $lib
Check ($b.meta.visibility.scopes -contains "all") "librarian sees all"

Step "2 catalogue"
$nb = Api POST "/library/books" $lib @{ title = "Verify Book"; isbn = "0-306-40615-2"; authors = @("V. Script") }
Check ($nb.data.isbn -eq "9780306406157") "ISBN-10 normalised"
$dup = Api POST "/library/books" $lib @{ title = "Verify Book 2"; isbn = "9780306406157" }
Check ($dup.data.warnings.Count -ge 1) "duplicate ISBN warns"
$cp = Api POST "/library/books/$($nb.data.id)/copies/bulk" $lib @{ count = 5; location = "Stack V" }
Check ($cp.data.Count -eq 5) "5 copies"
Check ($cp.data[0].barcode -eq $cp.data[0].accession_number) "barcode = accession"

Step "3 members"
$me = Api GET "/library/members/me" $stu
Check ($me.data.max_books_allowed -ge 1) "limits from rules"

Step "4 issue"
$copy = $cp.data[0]
$iss = Api POST "/library/circulation/issue" $lib @{ member_code = $me.data.member_code; barcode = $copy.barcode }
Check ($iss.data.status -eq "issued") "issued"
ExpectStatus 403 { Api POST "/library/circulation/issue" $stu @{ member_code = $me.data.member_code; barcode = $cp.data[1].barcode } }

Step "6 renew"
$rn = Api POST "/library/circulation/self-renew" $stu @{ issue_id = $iss.data.id }
Check ($rn.data.renewals -eq 1) "renewed once"

Step "7 return & fines"
$ret = Api POST "/library/circulation/return" $lib @{ barcode = $copy.barcode }
Check ($ret.data.issue.status -eq "returned") "returned"
$f = Api GET "/library/fines?status=outstanding" $lib
if ($f.data.Count -ge 1) { ExpectStatus 403 { Api POST "/library/fines/$($f.data[0].issue_id)/waive" $acc @{ reason = "accountant cannot waive" } } }

Step "10 visibility"
$od = Api GET "/library/issues?overdue=true" $hod
Check ($od.meta.visibility.scopes -contains "department") "HOD department scope"
Api GET "/library/members/wards" $par | Out-Null
Api GET "/library/issues" $fac | Out-Null
ExpectStatus 403 { Api POST "/library/circulation/issue" $aud @{ member_code = $me.data.member_code; barcode = $cp.data[2].barcode } }

Step "11 OPAC"
$o = Api GET "/opac/search?q=algor&institution=$Institution" $null
Check ($o.data.total -ge 1) "OPAC finds algorithms"

Summary
