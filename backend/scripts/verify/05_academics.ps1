# API verification — Phase 05 programmes, regulations & curriculum
# (Prompts/05_Phase05_Programmes_Regulations_Curriculum.md §05.11).
#
# Run from backend/ with the API up, Redis and a Celery worker + Beat (step 11's bulk import is a job; the outbox relay
# dispatches the workflow notifications and the catalogue-cache invalidation):
#   .\scripts\verify\05_academics.ps1 [-BaseUrl http://localhost:8000/api/v1]
#
# Seed first: python scripts/seed_demo_institution.py --type university --only academics   (runs base → communication)
#
# Roles: registrar (MFA in the demo tenant), hod.cse, dean.eng, faculty.1, student.1, unauthenticated
# (+ exam.cell for grading, ac.secretary for the BoS workflow's second step, inst.admin, superadmin for feature flags).
# Re-runnable: every run works on its own regulations V<run> / W<run> / X<run> and programme VP<run>.
#  1. seeded programmes readable by faculty.1 (200) — POST /programs as faculty.1 -> 403
#  2. registrar creates a draft regulation with attendance_min_pct=80 (201); rules ese_pass_min_pct="x" -> 422
#  3. hod.cse creates a CSE course (201); an ECE course -> 403 (scope); duplicate code -> 409
#  4. prerequisites VC201 -> VC101 (200); VC101 -> VC201 -> 422 RULE_VIOLATION (cycle)
#  5. structure with Σ credits ≠ required -> validate lists the issue; approve -> 409 with issues; fix -> clean;
#     hod.cse approve -> 403; dean.eng approve -> approved
#  6. activate -> active; PUT course -> 409 RECORD_LOCKED; clone -> draft, same codes, new ids; edit clone course 200;
#     activate clone -> source superseded (superseded_by_id); diff shows the changed course
#  7. BoS workflow on: approve -> regulation.approval pending for dean.eng -> ac.secretary -> approved via the hook
#  8. basket PE-III with a course of another regulation -> 422
#  9. grading scale with a gap -> 422; scheme components Σ scaled_to ≠ cia_max -> 422
# 10. batch 2026 with sections A/B; advisor faculty.1 on A -> class_advisor@offering:<section>
# 11. bulk import 20 CSV rows (2 bad) -> job succeeded 18 / failed 2 with reasons; export -> XLSX
# 12. public catalogue: programmes with public courses only, no internal ids; feature off -> 403
param([string]$BaseUrl = "http://localhost:8000/api/v1")
. "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl
$Backend = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Python = Get-VenvPython $Backend
$env:PYTHONUTF8 = "1"
Push-Location $Backend

function Sql($query) {
  $out = & $Python scripts/verify/_sql.py $query
  if ($LASTEXITCODE -ne 0) { throw "sql failed: $query" }
  return @($out | ConvertFrom-Json)
}
function WaitFor($label, [scriptblock]$probe, $seconds = 30) {
  for ($i = 0; $i -lt $seconds; $i++) { $v = & $probe; if ($v) { return $v }; Start-Sleep -Seconds 1 }
  throw "timed out waiting for: $label"
}
function Raw($token, $method, $path, $expect = 200) {
  # status + raw bytes (export / public routes)
  $h = @{}
  if ($token) { $h['Authorization'] = "Bearer $token" }
  $r = Invoke-WebRequest -Method $method -Uri "$script:BaseUrl$path" -Headers $h -SkipHttpErrorCheck
  if ($r.StatusCode -ne $expect) { throw "$method $path expected $expect got $($r.StatusCode): $($r.Content)" }
  $script:Checks++
  Write-Host "OK $method $path -> $($r.StatusCode)"
  return $r
}
function IdKeys($node) {
  # every property name that looks like an internal id, anywhere in a parsed JSON tree
  $found = @()
  if ($node -is [System.Collections.IEnumerable] -and $node -isnot [string]) { foreach ($x in $node) { $found += IdKeys $x } }
  elseif ($node -is [pscustomobject]) {
    foreach ($p in $node.PSObject.Properties) {
      if ($p.Name -eq 'id' -or $p.Name -like '*_id') { $found += $p.Name }
      $found += IdKeys $p.Value
    }
  }
  return $found
}

try {
  $run = Get-Random -Minimum 10000 -Maximum 99999
  # fixture: earlier phase scripts rotate demo passwords (02 password-policy checks) — restore the recorded one
  & $Python scripts/verify/_reset_password.py student.1 (Get-DemoPassword 'student') | Out-Null
  $registrar = Login-Mfa 'registrar' 'registrar'
  $hod = Login 'hod.cse' (Get-DemoPassword 'hod')
  $dean = Login 'dean.eng' (Get-DemoPassword 'dean')
  $faculty = Login 'faculty.1' (Get-DemoPassword 'faculty')
  $student = Login 'student.1' (Get-DemoPassword 'student')
  $admin = Login 'inst.admin' (Get-DemoPassword 'institution_admin')
  $examCell = Login-Mfa 'exam_cell' 'exam.cell'
  $secretary = Login 'ac.secretary' (Get-DemoPassword 'committee_secretary')
  $sa = Login-SuperAdmin
  $instId = (Call $admin GET "/auth/me").data.user.institution_id
  $tenant = @{ 'X-Institution-Id' = $instId }
  $facultyId = (Call $faculty GET "/auth/me").data.user.id
  # phase 34 affiliated colleges carry their own CSE / ECE departments: pin the demo college A
  $collegeA = ((Call $admin GET "/colleges?scope=all&page_size=200").data | Where-Object { $_.code -eq 'A' } | Select-Object -First 1).id
  $depts = (Call $admin GET "/departments?page_size=200&college_id=$collegeA").data | Where-Object { $_.college_id -eq $collegeA }
  $cse = ($depts | Where-Object { $_.code -eq 'CSE' } | Select-Object -First 1).id
  $ece = ($depts | Where-Object { $_.code -eq 'ECE' } | Select-Object -First 1).id
  function SetFlag($key, $on) {
    Call $sa PUT "/institutions/$instId/features/$key" @{ enabled = $on; confirm_dependencies = $true; reason = "verify 05" } 200 $tenant | Out-Null
  }
  SetFlag 'academics.bos_approval_workflow' $false
  SetFlag 'academics.public_catalog' $true
  Assert ($cse -and $ece) "fixtures: CSE and ECE departments (seed --only institution)"

  Write-Host "== 1. programmes are institution-wide readable"
  $progs = Call $faculty GET "/programs?page_size=200"
  Assert (($progs.data | Where-Object { $_.code -eq 'BTECH-CSE' }) -and ($progs.data | Where-Object { $_.code -eq 'MBA' })) "faculty.1 reads BTECH-CSE and MBA (seed --only academics)"
  Assert ($progs.meta.visibility.scopes -contains 'all') "meta.visibility offers the all tab"
  $newProg = @{ college_id = $collegeA; department_id = $cse; code = "VP$run"; name = "Verification Programme $run"; degree_name = 'B.Voc'; level = 'ug'; duration_years = 1; total_terms = 2 }
  Call $faculty POST "/programs" $newProg 403 | Out-Null
  $vp = (Call $registrar POST "/programs" $newProg 201).data
  Assert ($vp.exam_authority -eq 'autonomous_college') "exam_authority defaults from the institution type (university)"

  Write-Host "== 2. draft regulation with rules"
  $v = (Call $registrar POST "/regulations" @{ code = "V$run"; name = "Verify $run"; effective_from_admission_year = 2026; rules = @{ attendance_min_pct = 80 } } 201).data
  Assert ($v.status -eq 'draft' -and $v.rules.attendance_min_pct -eq 80 -and $v.rules.total_pass_min_pct -eq 50) "draft with attendance_min_pct=80 (other keys pre-filled)"
  Call $registrar PUT "/regulations/$($v.id)" @{ rules = @{ ese_pass_min_pct = 'x' } } 422 | Out-Null
  $schemes = (Call $registrar GET "/assessment-schemes?regulation_id=$($v.id)").data
  Assert (($schemes | Where-Object { $_.code -eq 'CIA40_SEE60' })) "pack scheme CIA40_SEE60 copied into the new regulation"

  Write-Host "== 3. courses (department scope)"
  $course = @{ regulation_id = $v.id; department_id = $cse; code = 'VC101'; title = 'Verification Course 101'; course_type = 'core'; lecture_hours = 3; tutorial_hours = 1; practical_hours = 0; credits = 4 }
  $c101 = (Call $hod POST "/courses" $course 201).data
  Assert ($c101.contact_hours_per_week -eq 4 -and $c101.status -eq 'draft' -and $c101.assessment_scheme_id) "L+T+P -> contact hours, draft, default scheme"
  Call $hod POST "/courses" $course 409 | Out-Null
  $eceCourse = $course.Clone(); $eceCourse.department_id = $ece; $eceCourse.code = 'VE101'
  Call $hod POST "/courses" $eceCourse 403 | Out-Null
  $c201 = (Call $hod POST "/courses" (@{ regulation_id = $v.id; department_id = $cse; code = 'VC201'; title = 'Verification Course 201'; course_type = 'core'; lecture_hours = 3; tutorial_hours = 1; credits = 4 }) 201).data
  $p301 = (Call $registrar POST "/courses" (@{ regulation_id = $v.id; department_id = $cse; code = 'VP301'; title = 'Elective A'; course_type = 'program_elective'; lecture_hours = 3; credits = 3 }) 201).data
  $p302 = (Call $registrar POST "/courses" (@{ regulation_id = $v.id; department_id = $cse; code = 'VP302'; title = 'Elective B'; course_type = 'program_elective'; lecture_hours = 3; credits = 3 }) 201).data

  Write-Host "== 4. prerequisite graph"
  $pre = Call $hod PUT "/courses/$($c201.id)/prerequisites" @{ items = @(@{ related_course_id = $c101.id; relation = 'prerequisite' }) }
  Assert ($pre.data.prerequisites.Count -eq 1 -and $pre.data.prerequisites[0].related_code -eq 'VC101') "VC201 requires VC101"
  $cycle = Call $hod PUT "/courses/$($c101.id)/prerequisites" @{ items = @(@{ related_course_id = $c201.id; relation = 'prerequisite' }) } 422
  Assert ($cycle.error.code -eq 'RULE_VIOLATION' -and $cycle.error.details.path -like '*VC101*VC201*') "cycle refused: $($cycle.error.details.path)"
  Call $hod PUT "/courses/$($c101.id)/prerequisites" @{ items = @(@{ related_course_id = $c101.id }) } 422 | Out-Null

  Write-Host "== 5. structure, validation, approval"
  Call $hod POST "/courses/$($c101.id)/status" @{ status = 'approved' } 403 | Out-Null   # hod drafts, dean approves
  foreach ($c in @($c101, $c201, $p301, $p302)) { Call $dean POST "/courses/$($c.id)/status" @{ status = 'approved' } | Out-Null }
  $pr = (Call $registrar POST "/program-regulations" @{ program_id = $vp.id; regulation_id = $v.id; total_credits_required = 14 } 201).data
  $structure = @{
    terms   = @(@{ term_number = 1; min_credits = 4; normal_credits = 4; max_credits = 8 }, @{ term_number = 2; min_credits = 4; normal_credits = 7; max_credits = 10 })
    courses = @(@{ term_number = 1; course_id = $c101.id; credit_bucket = 'PC' }, @{ term_number = 2; course_id = $c201.id; credit_bucket = 'PC' }, @{ term_number = 2; course_id = $p301.id; basket_code = 'PE-I' }, @{ term_number = 2; course_id = $p302.id; basket_code = 'PE-I' })
    baskets = @(@{ code = 'PE-I'; name = 'Programme Elective I'; basket_type = 'program_elective'; term_number = 2; min_choose = 1; max_choose = 1; credits_required = 3; course_ids = @($p301.id, $p302.id) })
  }
  $saved = Call $hod PUT "/program-regulations/$($pr.id)/structure" $structure
  Assert ($saved.data.terms.Count -eq 2 -and $saved.data.baskets.Count -eq 1 -and $saved.data.courses.Count -eq 4) "hod.cse saved 2 terms, 4 curriculum courses, 1 basket"
  $val = (Call $faculty POST "/program-regulations/$($pr.id)/structure/validate").data
  Assert ([decimal]$val.total -eq 11 -and [decimal]$val.required -eq 14 -and ($val.issues | Where-Object { $_.code -eq 'CREDIT_TOTAL_MISMATCH' -and $_.severity -eq 'warning' })) "validate: Σ 11 ≠ 14 listed (warning on a draft)"
  $blocked = Call $dean POST "/regulations/$($v.id)/approve" @{} 409
  Assert ($blocked.error.code -eq 'RULE_VIOLATION' -and ($blocked.error.details.issues | Where-Object { $_.code -eq 'CREDIT_TOTAL_MISMATCH' })) "approve -> 409 listing the credit mismatch"
  Call $registrar PUT "/program-regulations/$($pr.id)" @{ total_credits_required = 11 } | Out-Null
  $val = (Call $faculty POST "/program-regulations/$($pr.id)/structure/validate?for_approval=true").data
  Assert ($val.valid -and $val.issues.Count -eq 0) "validate after the fix: clean"
  Call $hod POST "/regulations/$($v.id)/approve" @{} 403 | Out-Null
  $appr = (Call $dean POST "/regulations/$($v.id)/approve" @{}).data
  Assert ($appr.regulation.status -eq 'approved' -and -not $appr.pending_workflow -and $appr.regulation.rules_locked) "dean.eng approved it directly (rules locked)"
  Call $registrar PUT "/regulations/$($v.id)" @{ rules = @{ attendance_min_pct = 70 } } 409 | Out-Null

  Write-Host "== 6. activate, lock, clone, supersede, diff"
  $act = (Call $registrar POST "/regulations/$($v.id)/activate").data
  Assert ($act.status -eq 'active' -and $act.locked_at -and $act.structure_locked) "active + locked_at"
  Assert ((Call $faculty GET "/courses/$($c101.id)").data.status -eq 'active') "its approved courses became active"
  $locked = Call $registrar PUT "/courses/$($c101.id)" @{ title = 'changed' } 409
  Assert ($locked.error.code -eq 'RECORD_LOCKED') "PUT course under an active regulation -> 409 RECORD_LOCKED"
  Call $hod PUT "/program-regulations/$($pr.id)/structure" $structure 409 | Out-Null
  $w = (Call $registrar POST "/regulations/$($v.id)/clone" @{ code = "W$run"; name = "Verify clone $run"; effective_from_admission_year = 2027 } 201).data
  Assert ($w.status -eq 'draft' -and $w.course_count -eq 4 -and $w.program_count -eq 1) "clone: draft with 4 courses and the programme binding"
  $wCourses = (Call $faculty GET "/courses?regulation_id=$($w.id)&page_size=50").data
  Assert ((($wCourses.code | Sort-Object) -join ',') -eq 'VC101,VC201,VP301,VP302' -and -not ($wCourses.id -contains $c101.id)) "same course codes, new ids"
  $w201 = $wCourses | Where-Object { $_.code -eq 'VC201' }
  $edited = (Call $hod PUT "/courses/$($w201.id)" @{ title = 'Verification Course 201 (revised)'; practical_hours = 2 }).data
  Assert ($edited.title -like '*revised*' -and $edited.contact_hours_per_week -eq 6) "edit a cloned course -> 200"
  $wPre = (Call $faculty GET "/courses/$($w201.id)").data.prerequisites
  Assert ($wPre.Count -eq 1 -and $wPre[0].related_code -eq 'VC101' -and $wPre[0].related_course_id -ne $c101.id) "prerequisites re-mapped to the cloned VC101"
  Call $dean POST "/regulations/$($w.id)/approve" @{} | Out-Null
  Call $registrar POST "/regulations/$($w.id)/activate" | Out-Null
  $src = (Call $faculty GET "/regulations/$($v.id)").data
  Assert ($src.status -eq 'superseded' -and $src.superseded_by_id -eq $w.id) "source superseded, superseded_by_id -> clone"
  $diff = (Call $faculty GET "/regulations/$($w.id)/diff").data
  Assert ($diff.predecessor_code -eq "V$run" -and ($diff.changed | Where-Object { $_.code -eq 'VC201' -and $_.fields.title })) "diff vs V$run shows VC201 changed"
  $eff = (Call $faculty GET "/regulations/$($w.id)/rules-effective?program_id=$($vp.id)").data
  Assert ($eff.rules.attendance_min_pct -eq 80 -and $eff.program_regulation_id) "rules-effective resolves through the programme binding"

  Write-Host "== 7. BoS approval workflow"
  SetFlag 'academics.bos_approval_workflow' $true
  $x = (Call $registrar POST "/regulations/$($w.id)/clone" @{ code = "X$run"; name = "Verify BoS $run"; effective_from_admission_year = 2028 } 201).data
  $sub = (Call $registrar POST "/regulations/$($x.id)/approve" @{}).data
  Assert ($sub.pending_workflow -and $sub.workflow_instance_id -and $sub.regulation.status -eq 'draft') "approve with BoS on -> submitted (still draft)"
  $wid = $sub.workflow_instance_id
  $inst = (Call $dean GET "/workflow/instances/$wid").data
  Assert ($inst.status -eq 'pending') "instance regulation.approval pending"
  Assert (((Call $dean GET "/workflow/inbox").data | Where-Object { $_.instance.id -eq $wid })) "dean.eng inbox shows it"
  Call $dean POST "/workflow/instances/$wid/act" @{ decision = 'approve'; comment = 'BoS recommends' } | Out-Null
  Assert ((Call $faculty GET "/regulations/$($x.id)").data.status -eq 'draft') "after the dean: still draft (academic council next)"
  Assert (((Call $secretary GET "/workflow/inbox").data | Where-Object { $_.instance.id -eq $wid })) "ac.secretary inbox shows step 2"
  Call $secretary POST "/workflow/instances/$wid/act" @{ decision = 'approve'; comment = 'Academic Council resolution' } | Out-Null
  $xr = (Call $faculty GET "/regulations/$($x.id)").data
  Assert ($xr.status -eq 'approved' -and $xr.approved_by) "workflow approved -> hook marked the regulation approved"
  SetFlag 'academics.bos_approval_workflow' $false

  Write-Host "== 8. elective baskets"
  $xpr = ((Call $faculty GET "/program-regulations?regulation_id=$($x.id)").data)[0]
  $xCourses = (Call $faculty GET "/courses?regulation_id=$($x.id)&page_size=50").data
  $bad = Call $registrar POST "/elective-baskets" @{ program_regulation_id = $xpr.id; code = 'PE-III'; name = 'Programme Elective III'; basket_type = 'program_elective'; term_number = 2; min_choose = 1; max_choose = 1; credits_required = 3; course_ids = @($c101.id) } 422
  Assert ($bad.error.details.field -eq 'course_ids') "courses of another regulation -> 422"
  $ok = Call $registrar POST "/elective-baskets" @{ program_regulation_id = $xpr.id; code = 'PE-III'; name = 'Programme Elective III'; basket_type = 'program_elective'; term_number = 2; min_choose = 1; max_choose = 1; credits_required = 3; course_ids = @(($xCourses | Where-Object { $_.code -like 'VP*' }).id) } 201
  Assert ($ok.data.courses.Count -eq 2) "PE-III with the regulation's own electives -> 201"

  Write-Host "== 9. grading scales and assessment schemes"
  $gap = @{ name = "Gap $run"; ranges = @(@{ grade = 'O'; min_pct = 90; max_pct = 100; points = 10 }, @{ grade = 'A'; min_pct = 80; max_pct = 89; points = 9 }, @{ grade = 'B'; min_pct = 70; max_pct = 78; points = 8 }, @{ grade = 'F'; min_pct = 0; max_pct = 69; points = 0 }) }
  $g = Call $examCell POST "/grading-scales" $gap 422
  Assert ($g.error.message -like '*Gap*78*') "range gap 79 -> 422 ($($g.error.message))"
  $gap.ranges[2].max_pct = 79
  Assert ((Call $examCell POST "/grading-scales" $gap 201).data.ranges.Count -eq 4) "contiguous ranges -> 201"
  $two = @{ name = "Two fails $run"; ranges = @(@{ grade = 'P'; min_pct = 40; points = 4 }, @{ grade = 'F'; min_pct = 20; points = 0 }, @{ grade = 'AB'; min_pct = 0; points = 0 }) }
  Call $examCell POST "/grading-scales" $two 422 | Out-Null
  $scheme = @{ regulation_id = $x.id; code = "S$run"; name = 'Bad weights'; cia_max = 40; ese_max = 60; components = @(@{ code = 'CAT1'; name = 'CAT 1'; category = 'cia'; max_marks = 50; scaled_to = 20 }, @{ code = 'CAT2'; name = 'CAT 2'; category = 'cia'; max_marks = 50; scaled_to = 10 }) }
  $s = Call $examCell POST "/assessment-schemes" $scheme 422
  Assert ($s.error.message -like '*cia_max*') "Σ scaled_to 30 ≠ cia_max 40 -> 422"
  $scheme.components[1].scaled_to = 20
  Assert ((Call $examCell POST "/assessment-schemes" $scheme 201).data.components.Count -eq 2) "Σ scaled_to = cia_max -> 201"
  Call $faculty POST "/grading-scales" $gap 403 | Out-Null

  Write-Host "== 10. batches, sections, class advisor"
  $wpr = ((Call $faculty GET "/program-regulations?regulation_id=$($w.id)").data)[0]
  $batch = (Call $registrar POST "/batches" @{ program_id = $vp.id; program_regulation_id = $wpr.id; admission_year = 2026; sections = @(@{ name = 'A'; capacity = 60 }, @{ name = 'B'; capacity = 60 }) } 201).data
  Assert ($batch.code -eq "2026-VP$run" -and (($batch.sections.name) -join ',') -eq 'A,B') "batch 2026 with sections A/B"
  Call $registrar POST "/batches" @{ program_id = $vp.id; program_regulation_id = $wpr.id; admission_year = 2026 } 409 | Out-Null
  $secA = $batch.sections | Where-Object { $_.name -eq 'A' }
  $adv = (Call $registrar PUT "/batches/$($batch.id)/sections/$($secA.id)/advisor" @{ user_id = $facultyId }).data
  Assert ((($adv.sections | Where-Object { $_.name -eq 'A' }).class_advisor_user_id) -eq $facultyId) "section A advisor = faculty.1"
  $roles = (Call $admin GET "/users/$facultyId/roles").data
  Assert (($roles | Where-Object { $_.role_slug -eq 'class_advisor' -and $_.scope_type -eq 'offering' -and $_.scope_id -eq $secA.id })) "faculty.1 holds class_advisor@offering:$($secA.id)"
  Call $faculty GET "/batches?page_size=5" | Out-Null

  Write-Host "== 11. bulk import + export"
  $lines = @('code,title,type,L,T,P,credits,department_code,scheme_code')
  for ($i = 1; $i -le 18; $i++) { $lines += ('B{0:D3},Imported course {0},core,3,0,0,3,CSE,' -f $i) }
  $lines += 'B901,Bad department,core,3,0,0,3,NOPE,'
  $lines += 'B902,Bad type,lecture,3,0,0,3,CSE,'
  $job = (Call $registrar POST "/courses/bulk-import" @{ regulation_id = $x.id; csv = ($lines -join "`n") } 202).data
  $final = WaitFor "bulk import job" { $j = (Call $registrar GET "/jobs/$($job.job_id)").data; if ($j.status -in @('succeeded', 'failed', 'cancelled')) { $j } } 60
  Assert ($final.status -eq 'succeeded' -and $final.result.succeeded -eq 18 -and $final.result.failed.Count -eq 2) "job succeeded: 18 imported, 2 failed"
  Assert (($final.result.failed | Where-Object { $_.message -like '*department_code*' }) -and ($final.result.failed | Where-Object { $_.message -like '*course type*' })) "failure reasons: unknown department / course type"
  $xlsx = Raw $registrar GET "/courses/export?regulation_id=$($x.id)"
  Assert ($xlsx.Headers['Content-Type'] -like '*spreadsheetml*' -and $xlsx.RawContentLength -gt 1000) "export -> XLSX ($($xlsx.RawContentLength) bytes)"

  Write-Host "== 12. public catalogue"
  $slug = (Call $admin GET "/institution/profile").data.slug
  $pub = (Raw $null GET "/public/catalog?institution=$slug").Content | ConvertFrom-Json
  $btech = $pub.data.programs | Where-Object { $_.code -eq 'BTECH-CSE' }
  Assert ($btech -and $btech.regulation -eq 'R2024' -and $btech.courses.Count -ge 30) "BTECH-CSE listed with its R2024 public courses ($($btech.courses.Count))"
  Assert (-not ($btech.courses | Where-Object { $_.code -eq 'MC101' })) "non-public MC101 (mandatory non-credit) is absent"
  $ids = IdKeys $pub.data
  Assert ($ids.Count -eq 0) "no internal ids in the public payload"
  $detail = (Raw $null GET "/public/catalog/courses/R2024/CS101?institution=$slug").Content | ConvertFrom-Json
  Assert ($detail.data.syllabus.Count -ge 1) "course page carries the syllabus"
  SetFlag 'website.course_catalog' $false   # dependant of academics.public_catalog (Phase 02: dependants -> 409)
  SetFlag 'academics.public_catalog' $false
  $off = WaitFor "catalogue disabled" { $r = Invoke-WebRequest -Uri "$script:BaseUrl/public/catalog?institution=$slug" -SkipHttpErrorCheck; if ($r.StatusCode -eq 403) { $r } } 90
  Assert (($off.Content | ConvertFrom-Json).error.code -eq 'FEATURE_DISABLED') "academics.public_catalog off -> 403 FEATURE_DISABLED"
  SetFlag 'academics.public_catalog' $true
  SetFlag 'website.course_catalog' $true
  Call $student GET "/programs" $null 403 | Out-Null   # students read their own curriculum through the enrolment (Phase 07)

  Summary "PHASE 05 programmes, regulations & curriculum"
}
finally {
  Pop-Location
}
