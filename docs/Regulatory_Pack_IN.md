# SeptronUniverse — Regulatory Pack: India (`IN`) and `GENERIC` stub

A **regulatory pack** is a code module (`app/core/packs/<code>/`) registered with `@register_pack("IN")` that supplies country-specific reference data, rules, metric definitions, document templates and statutory exports. `institutions.regulatory_pack` selects it; every pack exposes the same interface so the core never hard-codes a jurisdiction.

## 1. Pack interface

```python
class RegulatoryPack(Protocol):
    code: str                                  # "IN" | "GENERIC"
    categories: list[Category]                 # reservation categories
    quotas: list[Quota]
    id_formats: dict[str, IdFormat]            # apaar, aadhaar, pan, abc …
    default_grading_scales: list[GradingScale]
    default_assessment_schemes: list[AssessmentScheme]
    default_regulation_rules: dict             # attendance 75 %, pass %, exit points …
    default_outcomes: dict                     # NBA POs per discipline
    accreditation_frameworks: list[Framework]  # criteria trees + metric keys
    metric_definitions: list[MetricDef]        # computation keys
    statutory_reports: list[ReportDef]         # AISHE, NIRF, AICTE, UGC, NSP …
    document_templates: list[TemplateDef]      # bonafide, TC, migration, grade card, degree, hall ticket (bilingual variants)
    comms_compliance: CommsRules               # DLT, WhatsApp template policy, quiet hours
    privacy: PrivacyRules                      # DPDP consent texts, retention
    tax: TaxRules                              # GST applicability on fee heads
    phd_rules: PhdRules                        # UGC 2022 constraints
    validators: dict[str, Callable]            # e.g. validate_apaar(), validate_pan()
```

## 2. India pack (`IN`)

### 2.1 Reference data

| Item | Values |
|---|---|
| Categories | GEN, EWS, OBC-NCL, OBC-CL, SC, ST (+ sub-category free text; state lists configurable) |
| Horizontal reservations | PwD (with type & %), women, defence/ex-servicemen, sports, NCC, Kashmiri migrants, staff wards, minority (institution-specific) |
| Quotas | state, all-India, management, NRI/PIO/foreign, supernumerary (EWS vertical, PwD), lateral, sports |
| Identifiers | APAAR (12 digits, Luhn-style check), ABC id, Aadhaar (12 digits, Verhoeff; stored encrypted, masked), PAN (10 chars), DigiLocker id, AISHE code (institution), AICTE PID, NAAC id, UGC 2(f)/12(B) status |
| Domicile & languages | 28 states / 8 UTs; mother-tongue list; 11 UI locales (en, hi, bn, mr, te, ta, gu, kn, or, ml, as) |
| Boards / qualifying exams | CBSE, CISCE, state boards; JEE Main/Advanced, NEET, CUET, GATE, CAT, MAT, state CETs |
| Approving bodies | UGC, AICTE, NCTE, PCI, BCI, NMC, INC, COA, DEB (ODL) |

### 2.2 NEP 2020 / NCrF defaults

| Rule | Default |
|---|---|
| Credit definition | 1 credit = 15 lecture/tutorial hours or 30 practical hours per term |
| UG structure | 4-year multidisciplinary (8 semesters) with exits: certificate (after 1 yr / 40 cr), diploma (2 yr / 80 cr), degree (3 yr / 120 cr), honours/research (4 yr / 160 cr) — configurable per regulation |
| Credit buckets | Major, Minor, Multidisciplinary, AEC, SEC, VAC, Internship/Project, Research |
| MOOC credit cap | ≤ 40 % of programme credits via SWAYAM/NPTEL (configurable; default 12 credits per regulation rule) |
| ABC | every published credit-bearing result → `abc_credit_ledger` push; revisions revoke + re-push |
| APAAR | mandatory field with validation; DigiLocker linkage flag |
| Academic calendar | ~90 instructional days per semester; attendance threshold 75 % (condonable to 65 %) |

### 2.3 Grading & assessment defaults

| Item | Default |
|---|---|
| Letter grades (10-point) | O (≥90) 10 · A+ (80–89) 9 · A (70–79) 8 · B+ (60–69) 7 · B (55–59) 6 · C (50–54) 5 · P (45–49) 4 · F (<45) 0 · AB, WH, MP, W, I, AU special |
| Assessment schemes | THEORY 40/60, LAB 60/40 (or 50/50), PROJECT 100 internal reviews + viva, MOOC pass/fail mapping |
| Pass rules | ESE ≥ 45 % (theory), total ≥ 50 %; CIA minimum optional |
| SGPA/CGPA | Σ(C×GP)/ΣC; percentage = CGPA × 10 (or ×9.5 configurable) |
| Classes | Distinction ≥ 8.5 (first attempt), First ≥ 6.5, Second ≥ 5.0 |
| Grace | ≤ 5 marks per course, ≤ 2 courses per term |
| Double valuation | discrepancy 15 % → third valuation, average of closest two |
| Revaluation | apply only if |Δ| ≥ 5 marks; photocopy fee; challenge valuation optional |

### 2.4 UGC PhD Regulations 2022 (`phd_rules`)

| Rule | Default |
|---|---|
| Admission | entrance (or NET/JRF/GATE exemption) + interview; reservation applies |
| Guide load | Professor 8, Associate 6, Assistant 4 scholars (configurable) |
| Coursework | min 12 credits incl. research methodology; completed within 1 year (exemptions for M.Phil) |
| Progress | half-yearly report to DC/RAC; unsatisfactory twice → cancellation review |
| Duration | min 2 years (from registration), max 6 years (+ extensions up to 2 years; women/PwD relaxations) |
| Plagiarism | similarity ≤ 10 % (excluding references/quotes) via DrillBit/Urkund/Turnitin adapter; AI-generated content declaration |
| Examiners | ≥ 2 external examiners, at least one outside the state (or country per policy) |
| Viva | after examiner reports accept/minor revisions; open defence |
| ETD | Shodhganga upload within 30 days of award; INFLIBNET handle recorded |

### 2.5 Accreditation frameworks & metric definitions

| Framework | Criteria (top level) | Key computed metrics (`computation_key`) |
|---|---|---|
| NAAC (Revised Framework 2024) | 1 Curricular · 2 Teaching-Learning & Evaluation · 3 Research/Innovation/Extension · 4 Infrastructure · 5 Student Support & Progression · 6 Governance · 7 Institutional Values | `students.enrolment_by_category`, `students.seats_filled_vs_reserved`, `faculty.fsr`, `results.pass_pct_final_year`, `students.dropout_pct`, `placement.placed_pct`, `students.higher_studies_pct`, `students.qualifying_exams`, `scholarships.beneficiaries_pct`, `surveys.sss_score`, `faculty.phd_pct`, `research.publications_per_teacher`, `research.grants_amount`, `research.consultancy_revenue`, `research.patents`, `research.fdp_participation`, `academics.cbcs_pct`, `academics.value_added_courses`, `academics.internships_pct`, `finance.infra_spend_pct`, `library.spend`, `governance.grievance_sla_pct`, `events.count_by_type`, `values.gender_ratio` |
| NBA (GAPC v4, UG Engineering) | 1 Vision/Mission/PEO · 2 Programme Curriculum · 3 COs & POs · 4 Students' Performance · 5 Faculty Information · 6 Facilities · 7 Continuous Improvement · 8 First-Year · 9 Student Support · 10 Governance | `obe.co_attainment`, `obe.po_attainment`, `results.success_rate`, `results.academic_performance_index`, `faculty.cadre_ratio`, `faculty.fsr`, `faculty.fqi`, `research.publications`, `placement.placed_pct`, `students.professional_activities` |
| NIRF | TLR, RP, GO, OI, PR | `nirf.fsr`, `nirf.fqe`, `nirf.fru`, `nirf.pu`, `nirf.qp`, `nirf.ipr`, `nirf.gph`, `nirf.gue`, `nirf.gms`, `nirf.gphd`, `nirf.rd`, `nirf.wd`, `nirf.escs`, `nirf.pcs` |
| AISHE | institution, programmes, students (category/gender/state), staff, infrastructure, finance | `aishe.*` exports |
| AICTE approval / UGC annual | intake, faculty, infrastructure, finance | `aicte.*`, `ugc.*` |

### 2.6 Statutory reports (`statutory_reports`)
AISHE DCF, NIRF data capture (per discipline), AICTE EoA data, UGC annual report, NSP scholarship returns, State fee-regulatory committee returns, minority/SC-ST cell returns, anti-ragging compliance, RTI annual return, PhD awarded returns (UGC), placement statistics (NIRF format).

### 2.7 Document templates (`document_templates`, bilingual variants)
Bonafide, character, conduct, NOC, transfer certificate, migration certificate, course-completion, provisional degree, degree, consolidated marksheet, grade card, transcript, hall ticket, ID card, fee receipt (GST-aware), experience/service certificate, internship NOC, hostel allotment letter, event participation certificate.

### 2.8 Communication compliance
- **SMS DLT**: sender ids & template ids registered per institution (`dlt_templates`); messages must match approved templates; consent for promotional messages.
- **WhatsApp**: Meta template approval registry; 24-hour session rules; opt-in records.
- **Quiet hours** default 21:00–08:00 for non-critical notifications; emergency broadcast exempt.

### 2.9 Privacy & data protection (DPDP Act 2023)
- Consent records for data processing categories (academic, communication, marketing, health); guardian consent for minors.
- Data-subject requests (access/export/correction/erasure) with SLA; erasure limited by academic-record retention obligations.
- PII encryption at rest (Aadhaar, bank, PAN, health), masking by default, `view_pii` permission, PII-free logs.
- Retention: academic records permanent; attendance/logs per policy; applicant data 2 years after cycle.

### 2.10 Tax
GST applicability per fee head (education services exempt; hostel/mess/certain services taxable per current notifications) — configured, not hard-coded; GSTIN on institution/college profile; e-invoice fields on taxable receipts.

## 3. `GENERIC` pack (stub)
Categories: none (free-text equity groups); quotas: none; ids: national id (free format), passport; grading: 4.0 GPA scale (A 4.0 … F 0) or 10-point; assessment 40/60; pass 50 %; no NEP exits (configurable); frameworks: none (institution defines); reports: enrolment, completion, employment; templates: transcript, diploma, enrolment verification; privacy: GDPR-style consent/DSR; tax: VAT flag per fee head. Serves as the template for future country packs (e.g., `AE`, `NP`, `LK`).

## 4. Pack selection & overrides
- `institutions.regulatory_pack` set at onboarding; pack defaults are **copied** into institution-level tables (grading scales, schemes, frameworks, templates) so institutions can edit them; the pack version is recorded for upgrades.
- Rule keys in `regulations.rules` always win over pack defaults.

## 5. Verification (API + UI)
1. Onboard a demo institution with `IN`: grading scales, schemes, frameworks, templates and categories are present via their list endpoints and visible in Settings.
2. Create a student with an invalid APAAR → 422 with validation code; valid → stored and masked in list responses.
3. Compute NAAC metrics for a demo year → `metric_values` rows with numerator/denominator; IQAC grid shows them.
4. Onboard a `GENERIC` institution → no category field required on admission; 4.0 GPA scale seeded.
