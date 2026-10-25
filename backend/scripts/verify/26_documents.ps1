# Phase 26 — document templates, certificates & requests (Prompts/26 §26.11). Run after `seed_demo_institution.py --only documents`.
param([string]$Base = "http://localhost:8000/api/v1")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_common.ps1"

$reg = Login "registrar"; $office = Login "office.1"; $hod = Login "hod.cse"; $stu = Login "student.1"
$hr = Login "hr"; $coe = Login "coe"; $staff = Login "staff.1"; $aud = Login "auditor.tmp"; $par = Login "parent.1"

Step "1 back-fill + unified verify"
$gc = Api GET "/documents/issued?template_type=grade_card&limit=1" $reg
Check ($gc.data.Count -ge 1) "grade cards back-filled"
$v = Invoke-RestMethod "$Base/verify/$($gc.data[0].verification_token)"
Check ($v.data.valid -and $v.data.template_type -eq "grade_card") "unified verify"

Step "2 templates"
$t = Api GET "/documents/templates?template_type=bonafide" $reg
Check ($t.data.Count -ge 2) "platform default + override"
$plat = $t.data | Where-Object { $_.source -eq "platform" } | Select-Object -First 1
$c = Api POST "/documents/templates" $reg @{ template_type = "bonafide"; name = "Verify bonafide"; from_template_id = $plat.id }
$bad = Api PUT "/documents/templates/$($c.data.id)" $reg @{ html_template = "<p>{{ student.unknown_var }}</p>"; layout = @{ mode = "html" } }
ExpectStatus 422 { Api POST "/documents/templates/$($c.data.id)/publish" $reg @{ change_note = "should fail" } }
Api PUT "/documents/templates/$($c.data.id)" $reg @{ html_template = "<p>{{ student.registration_number }}</p>"; layout = @{ mode = "html" } } | Out-Null
$p = Api POST "/documents/templates/$($c.data.id)/publish" $reg @{ change_note = "verify" }
Check ($p.data.status -eq "published") "published"
ExpectStatus 403 { Api POST "/documents/templates" $reg @{ template_type = "bonafide"; name = "bi"; is_bilingual = $true } }

Step "3 render API"
$me = Api GET "/students/me" $stu
$r1 = Api POST "/documents/render" $office @{ template_type = "bonafide"; entity_type = "student_program_enrollment"; entity_id = $me.data.enrollments[0].id; register = "bonafide" }
$r2 = Api POST "/documents/render" $office @{ template_type = "bonafide"; entity_type = "student_program_enrollment"; entity_id = $me.data.enrollments[0].id; register = "bonafide" }
Check ($r1.data.issued_document_id -eq $r2.data.issued_document_id) "idempotent"
ExpectStatus 403 { Api POST "/documents/render" $stu @{ template_type = "bonafide"; entity_type = "student"; entity_id = $me.data.id } }

Step "4 issued + signed links"
$mine = Api GET "/documents/me" $stu
Check ($mine.data.Count -ge 1) "my documents"
$l = Api POST "/documents/issued/$($mine.data[0].id)/signed-link" $stu @{}
Check ($l.data.url -like "/api/v1/documents/download/*") "signed link"
ExpectStatus 403 { Api GET ($l.data.url -replace "^/api/v1", "") $reg }
ExpectStatus 403 { Api GET "/documents/issued?template_type=transcript" $hod }
ExpectStatus 403 { Api POST "/documents/issued/$($mine.data[0].id)/revoke" $aud @{ reason = "x" } }

Step "5 revoke / reissue"
ExpectStatus 403 { Api POST "/documents/issued/$($r1.data.issued_document_id)/revoke" $office @{ reason = "test" } }
$rv = Api POST "/documents/issued/$($r1.data.issued_document_id)/reissue" $reg @{ reason = "name correction" }
$old = Invoke-RestMethod "$Base/verify/$($r1.data.verification_token)"
Check ($old.data.revoked -and $old.data.superseded_by) "old superseded"

Step "6 serial registers"
$res = Api POST "/documents/registers/provisional/reserve" $office @{ count = 5 }
Check ($res.data.Count -eq 5) "reserved"
$rc = Api GET "/documents/registers/provisional/reconcile" $reg
Check ($rc.data.reserved -ge 5) "reconcile"

Step "8 requests"
$types = Api GET "/certificate-requests/types" $stu
Check (($types.data | Where-Object { $_.template_type -eq "bonafide" }).allowed) "bonafide allowed"
$q = Api POST "/certificate-requests" $stu @{ template_type = "conduct"; copies = 2; purpose = "verify" }
Check ($q.data.status -eq "fee_pending") "fee pending"
ExpectStatus 409 { Api POST "/certificate-requests" $stu @{ template_type = "conduct" } }
ExpectStatus 422 { Api POST "/certificate-requests" $stu @{ template_type = "tc" } }
$x = Api POST "/certificate-requests" $staff @{ template_type = "experience" }
$hq = Api GET "/certificate-requests?template_type=experience" $hr
Check ($hq.data.id -contains $x.data.id) "hr queue"

Step "11 verification"
ExpectStatus 404 { Invoke-RestMethod "$Base/verify/deadbeef" }
Done
