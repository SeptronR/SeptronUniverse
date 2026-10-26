"""Accreditation & compliance (IQAC) enums and IN-pack defaults — Prompts/32 §32.2 / §32.3.

* ``FRAMEWORK_TREES`` — the complete criteria trees seeded by revision ``0032`` under the six §36 frameworks (NAAC 2024
  key indicators / metrics with ``metric_type`` / ``max_score`` / ``metric_key``; NBA GAPC v4 criteria 1–10 with
  sub-criteria and marks; NIRF TLR / RP / GO / OI / PR parameters; AISHE DCF sections; AICTE / UGC data packs). Codes
  are dotted paths — the parent of ``2.3.1`` is ``2.3`` and of ``2.3`` is ``2``.
* ``METRIC_DEFINITIONS`` — every ``metric_definitions`` row beyond the 30 seeded by §36.5 (``0001``) with its
  ``computation_key``, ``source_module``, ``params_schema`` and ``depends_on``. ``computation_key`` is a function
  registered in ``app/core/metrics.py``; ``published:<key>`` keys are pushed by module events (``*.stats_published``,
  ``metrics.publish``) and ``manual.input`` keys are non-computable (manual input with verification).
"""

from enum import StrEnum
from typing import Any


class MetricType(StrEnum):
    QUANTITATIVE = "quantitative"
    QUALITATIVE = "qualitative"
    QN_QL = "qn_ql"


class PeriodType(StrEnum):
    ACADEMIC_YEAR = "academic_year"
    CALENDAR_YEAR = "calendar_year"
    FINANCIAL_YEAR = "financial_year"
    FIVE_YEAR = "five_year"


class ValueSource(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"
    OVERRIDE = "override"


class CycleStatus(StrEnum):
    PLANNING = "planning"
    DATA_COLLECTION = "data_collection"
    DRAFTING = "drafting"
    INTERNAL_REVIEW = "internal_review"
    SUBMITTED = "submitted"
    PEER_VISIT = "peer_visit"
    RESULT = "result"


class ResponseStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    FINAL = "final"


class SubmissionType(StrEnum):
    AQAR = "aqar"
    NIRF_DATA = "nirf_data"
    AISHE = "aishe"
    AICTE_APPROVAL = "aicte_approval"
    UGC_ANNUAL = "ugc_annual"
    NSP_RETURN = "nsp_return"


class SubmissionStatus(StrEnum):
    DRAFT = "draft"
    GENERATED = "generated"
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"


class AuditType(StrEnum):
    ACADEMIC = "academic"
    ADMINISTRATIVE = "administrative"
    GREEN = "green"
    ENERGY = "energy"
    GENDER = "gender"
    FINANCIAL_STATUTORY = "financial_statutory"
    AG = "ag"


class AuditStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"


class ExportFormat(StrEnum):
    NAAC_SSR = "naac_ssr"
    NAAC_AQAR = "naac_aqar"
    NBA_SAR = "nba_sar"
    NIRF_DCF = "nirf_dcf"
    AISHE_DCF = "aishe_dcf"
    AICTE = "aicte"
    UGC_ANNUAL = "ugc_annual"
    DOCX = "docx"
    PDF = "pdf"
    XLSX = "xlsx"


# forward-only cycle machine (``result`` records score / grade)
CYCLE_FLOW: tuple[str, ...] = tuple(s.value for s in CycleStatus)

# framework code → the feature key that activates it per institution
FRAMEWORK_FEATURES: dict[str, str] = {
    "NAAC_2024": "accreditation.naac",
    "NBA_UG_ENGG": "accreditation.nba",
    "NIRF": "accreditation.nirf",
    "AISHE": "accreditation.aishe",
    "AICTE_APPROVAL": "accreditation.aicte_ugc",
    "UGC_12B": "accreditation.aicte_ugc",
}

# submission type → (framework code, feature key)
SUBMISSION_FRAMEWORK: dict[str, tuple[str, str]] = {
    "aqar": ("NAAC_2024", "accreditation.naac"),
    "nirf_data": ("NIRF", "accreditation.nirf"),
    "aishe": ("AISHE", "accreditation.aishe"),
    "aicte_approval": ("AICTE_APPROVAL", "accreditation.aicte_ugc"),
    "ugc_annual": ("UGC_12B", "accreditation.aicte_ugc"),
    "nsp_return": ("AISHE", "accreditation.aishe"),
}

# narrative word limits per framework (criterion responses)
WORD_LIMITS: dict[str, int] = {"NAAC_2024": 500, "NBA_UG_ENGG": 1000, "NIRF": 300, "AISHE": 300}

# NAAC benchmark bands for the score simulation (fraction of max_score earned at a normalised metric value)
BENCHMARK_BANDS: tuple[tuple[float, float], ...] = ((0.8, 1.0), (0.6, 0.75), (0.4, 0.5), (0.2, 0.25), (0.0, 0.0))

C = tuple[str, str, str, float | None, str | None, str]  # code, title, metric_type, max_score, metric_key, period


def _naac() -> list[C]:
    q, ql, ay, fy = "quantitative", "qualitative", "academic_year", "five_year"
    return [
        ("1.1", "Curriculum Design and Development", "qn_ql", 20, None, ay),
        (
            "1.1.1",
            "Curricula developed and implemented have relevance to local / national / global needs",
            ql,
            20,
            None,
            ay,
        ),
        ("1.2", "Academic Flexibility", "qn_ql", 30, None, ay),
        ("1.2.1", "Programmes with CBCS / elective course system", q, 15, "academics.cbcs_pct", ay),
        ("1.2.2", "Value-added courses / add-on certificate programmes", q, 15, "academics.value_added_courses", fy),
        ("1.3", "Curriculum Enrichment", "qn_ql", 30, None, ay),
        (
            "1.3.1",
            "Cross-cutting issues (gender, environment, values) integrated into the curriculum",
            ql,
            10,
            None,
            ay,
        ),
        ("1.3.2", "Students undertaking projects / field work / internships", q, 20, "academics.internships_pct", ay),
        ("1.4", "Feedback System", q, 20, None, ay),
        ("1.4.1", "Structured feedback on curriculum collected and analysed", q, 20, "surveys.sss_score", ay),
        ("2.1", "Student Enrolment and Profile", q, 30, None, ay),
        ("2.1.1", "Enrolment percentage", q, 10, "students.enrolment_by_category", fy),
        ("2.1.2", "Seats filled against reserved categories", q, 20, "students.seats_filled_vs_reserved", fy),
        ("2.2", "Student-Teacher Ratio", q, 30, None, ay),
        ("2.2.1", "Student - full-time teacher ratio", q, 30, "faculty.fsr", ay),
        ("2.3", "Teaching-Learning Process", "qn_ql", 40, None, ay),
        ("2.3.1", "Student-centric methods (experiential, participative, problem solving)", ql, 20, None, ay),
        ("2.3.2", "Mentor - mentee ratio", q, 20, "mentoring.ratio", ay),
        ("2.4", "Teacher Profile and Quality", q, 60, None, ay),
        ("2.4.1", "Full-time teachers against sanctioned posts", q, 20, "faculty.cadre_ratio", fy),
        ("2.4.2", "Full-time teachers with PhD", q, 20, "faculty.phd_pct", fy),
        ("2.4.3", "Teaching experience of full-time teachers", q, 20, "faculty.fqi", ay),
        ("2.5", "Evaluation Process and Reforms", "qn_ql", 40, None, ay),
        ("2.5.1", "Transparent and robust internal assessment", ql, 40, None, ay),
        ("2.6", "Student Performance and Learning Outcomes", "qn_ql", 90, None, ay),
        ("2.6.1", "Programme and course outcomes are stated and communicated", ql, 10, None, ay),
        ("2.6.2", "Attainment of POs and COs", q, 30, "obe.po_attainment", ay),
        ("2.6.3", "Pass percentage of students (final year)", q, 50, "results.pass_pct_final_year", fy),
        ("2.7", "Student Satisfaction Survey", q, 60, None, ay),
        ("2.7.1", "Online student satisfaction survey", q, 60, "surveys.sss_score", ay),
        ("3.1", "Resource Mobilisation for Research", q, 10, None, fy),
        ("3.1.1", "Grants received for research projects", q, 10, "research.grants_amount", fy),
        ("3.2", "Innovation Ecosystem", "qn_ql", 15, None, fy),
        ("3.2.1", "Ecosystem for innovation and transfer of knowledge", ql, 5, None, ay),
        (
            "3.2.2",
            "Workshops / seminars on research methodology, IPR, entrepreneurship",
            q,
            10,
            "events.count_by_type",
            fy,
        ),
        ("3.3", "Research Publications and Awards", q, 25, None, fy),
        (
            "3.3.1",
            "Research papers per teacher in UGC CARE / indexed journals",
            q,
            15,
            "research.publications_per_teacher",
            fy,
        ),
        ("3.3.2", "Books / chapters / conference papers per teacher", q, 10, "nirf.pu", fy),
        ("3.4", "Extension Activities", "qn_ql", 40, None, fy),
        ("3.4.1", "Extension activities in the neighbourhood community", ql, 10, None, ay),
        ("3.4.2", "Extension and outreach programmes", q, 30, "events.extension_activities", fy),
        ("3.5", "Collaboration", q, 20, None, fy),
        ("3.5.1", "Functional MoUs / collaborations", q, 20, "research.mous_functional", fy),
        ("3.6", "Patents, Consultancy and PhDs", q, 20, None, fy),
        ("3.6.1", "Patents published / granted", q, 5, "research.patents", fy),
        ("3.6.2", "Revenue from consultancy and corporate training", q, 5, "research.consultancy_revenue", fy),
        ("3.6.3", "PhDs awarded per recognised guide", q, 10, "research.phd_awarded", fy),
        ("4.1", "Physical Facilities", "qn_ql", 30, None, fy),
        ("4.1.1", "Adequate infrastructure for teaching-learning", ql, 15, None, ay),
        ("4.1.2", "Expenditure for infrastructure augmentation excluding salary", q, 15, "finance.infra_spend_pct", fy),
        ("4.2", "Library as a Learning Resource", "qn_ql", 20, None, fy),
        ("4.2.1", "Library automated with ILMS and e-resources", ql, 5, "library.eresources_count", ay),
        ("4.2.2", "Expenditure for purchase of books / journals", q, 15, "library.spend", fy),
        ("4.3", "IT Infrastructure", "qn_ql", 30, None, ay),
        ("4.3.1", "IT facilities including Wi-Fi updated", ql, 30, None, ay),
        ("4.4", "Maintenance of Campus Infrastructure", q, 20, None, fy),
        ("4.4.1", "Expenditure on maintenance of infrastructure", q, 20, "finance.opex", fy),
        ("5.1", "Student Support", q, 40, None, fy),
        ("5.1.1", "Students benefited by scholarships and freeships", q, 20, "scholarships.beneficiaries_pct", fy),
        (
            "5.1.2",
            "Capacity building and skills enhancement initiatives",
            q,
            10,
            "students.professional_activities",
            fy,
        ),
        (
            "5.1.3",
            "Redressal of student grievances including sexual harassment and ragging",
            q,
            10,
            "governance.grievance_sla_pct",
            ay,
        ),
        ("5.2", "Student Progression", q, 50, None, fy),
        ("5.2.1", "Placement of outgoing students", q, 20, "placement.placed_pct", fy),
        ("5.2.2", "Students progressing to higher education", q, 15, "students.higher_studies_pct", ay),
        (
            "5.2.3",
            "Students qualifying in state / national / international exams",
            q,
            15,
            "students.qualifying_exams",
            fy,
        ),
        ("5.3", "Student Participation and Activities", q, 30, None, fy),
        (
            "5.3.1",
            "Awards / medals for outstanding performance in sports / cultural activities",
            q,
            15,
            "students.professional_activities",
            fy,
        ),
        ("5.3.2", "Sports and cultural events organised", q, 15, "events.count_by_type", fy),
        ("5.4", "Alumni Engagement", "qn_ql", 20, None, ay),
        ("5.4.1", "Alumni association contributes significantly", ql, 20, "alumni.donations_total_paise", ay),
        ("6.1", "Institutional Vision and Leadership", ql, 10, None, ay),
        ("6.1.1", "Governance reflective of the vision and mission", ql, 10, None, ay),
        ("6.2", "Strategy Development and Deployment", "qn_ql", 10, None, ay),
        ("6.2.1", "Strategic plan deployed; policies and administrative setup", ql, 5, None, ay),
        ("6.2.2", "e-governance in areas of operation", q, 5, None, ay),
        ("6.3", "Faculty Empowerment Strategies", q, 30, None, fy),
        ("6.3.1", "Welfare measures for teaching and non-teaching staff", ql, 10, None, ay),
        ("6.3.2", "Teachers provided financial support for conferences / FDP", q, 10, "research.fdp_participation", fy),
        ("6.3.3", "Teachers undergoing online / face-to-face FDPs", q, 10, "research.fdp_participation", fy),
        ("6.4", "Financial Management and Resource Mobilisation", "qn_ql", 20, None, fy),
        ("6.4.1", "Internal and external financial audits", ql, 10, None, ay),
        ("6.4.2", "Funds / grants received from non-government bodies", q, 10, "alumni.donations_total_paise", fy),
        ("6.5", "Internal Quality Assurance System", "qn_ql", 30, None, ay),
        ("6.5.1", "IQAC contribution to institutionalising quality assurance", ql, 15, None, ay),
        (
            "6.5.2",
            "Quality assurance initiatives (AQAR, NIRF, ISO, audits)",
            q,
            15,
            "governance.quality_initiatives",
            ay,
        ),
        ("7.1", "Institutional Values and Social Responsibilities", "qn_ql", 50, None, ay),
        ("7.1.1", "Measures initiated for the promotion of gender equity", ql, 10, "values.gender_ratio", ay),
        (
            "7.1.2",
            "Facilities for alternate sources of energy and energy conservation",
            q,
            10,
            "values.energy_audit_score",
            ay,
        ),
        ("7.1.3", "Quality audits on environment and energy", q, 10, "values.green_audit_score", ay),
        ("7.1.4", "Disabled-friendly, barrier-free environment", q, 10, "values.pwd_ratio", ay),
        ("7.1.5", "Code of conduct and inclusive environment", ql, 10, None, ay),
        ("7.2", "Best Practices", ql, 30, None, ay),
        ("7.2.1", "Two best practices successfully implemented", ql, 30, None, ay),
        ("7.3", "Institutional Distinctiveness", ql, 20, None, ay),
        (
            "7.3.1",
            "Performance of the institution in one area distinctive to its priority and thrust",
            ql,
            20,
            None,
            ay,
        ),
    ]


def _nba() -> list[C]:
    q, ql, ay = "quantitative", "qualitative", "academic_year"
    return [
        ("1.1", "State the Vision and Mission of the department and institute", ql, 5, None, ay),
        ("1.2", "State the Programme Educational Objectives (PEOs)", ql, 5, None, ay),
        ("1.3", "Dissemination of Vision, Mission and PEOs", ql, 15, None, ay),
        ("1.4", "Process for defining Vision, Mission and PEOs", ql, 15, None, ay),
        ("1.5", "Consistency of PEOs with the Mission", ql, 10, None, ay),
        ("2.1", "Programme curriculum", "qn_ql", 50, "academics.cbcs_pct", ay),
        ("2.2", "Teaching-learning processes", "qn_ql", 50, None, ay),
        ("3.1", "Course Outcomes and their mapping with POs / PSOs", "qn_ql", 25, None, ay),
        ("3.2", "Attainment of Course Outcomes", q, 75, "obe.co_attainment", ay),
        ("3.3", "Attainment of Programme Outcomes / PSOs", q, 75, "obe.po_attainment", ay),
        ("4.1", "Enrolment ratio", q, 20, "students.seats_filled_vs_reserved", ay),
        ("4.2", "Success rate in the stipulated period", q, 20, "results.success_rate", ay),
        ("4.3", "Academic performance in the first year", q, 10, "results.academic_performance_index", ay),
        ("4.4", "Academic performance in the second year", q, 10, "results.academic_performance_index", ay),
        ("4.5", "Placement, higher studies and entrepreneurship", q, 30, "placement.placed_pct", ay),
        ("4.6", "Professional activities", q, 10, "students.professional_activities", ay),
        ("5.1", "Student-Faculty Ratio (SFR)", q, 20, "faculty.fsr", ay),
        ("5.2", "Faculty cadre proportion", q, 20, "faculty.cadre_ratio", ay),
        ("5.3", "Faculty qualification", q, 20, "faculty.fqi", ay),
        ("5.4", "Faculty retention", q, 10, None, ay),
        ("5.5", "Innovations by the faculty in teaching and learning", ql, 10, None, ay),
        ("5.6", "Faculty as participants in FDPs / STTPs", q, 15, "research.fdp_participation", ay),
        ("5.7", "Research and development", q, 75, "research.publications_per_teacher", ay),
        ("5.8", "Faculty performance appraisal and development system", ql, 20, None, ay),
        ("5.9", "Visiting / adjunct / emeritus faculty", q, 10, None, ay),
        ("6.1", "Adequate and well-equipped laboratories and technical manpower", "qn_ql", 40, None, ay),
        ("6.2", "Additional facilities created for improving quality of learning", ql, 25, None, ay),
        ("6.3", "Laboratories: maintenance and overall ambience", ql, 10, None, ay),
        ("6.4", "Project laboratory", ql, 5, None, ay),
        (
            "7.1",
            "Actions taken based on the results of evaluation of each PO / PSO",
            "qn_ql",
            20,
            "obe.attainment_gap_pct",
            ay,
        ),
        ("7.2", "Academic audit and actions taken", ql, 10, None, ay),
        ("7.3", "Improvement in placement, higher studies and entrepreneurship", q, 10, None, ay),
        ("7.4", "Improvement in the quality of students admitted", q, 10, None, ay),
        ("8.1", "First-year student-faculty ratio", q, 5, None, ay),
        ("8.2", "Qualification of faculty teaching first-year common courses", q, 5, None, ay),
        ("8.3", "First-year academic performance", q, 10, "results.academic_performance_index", ay),
        ("8.4", "Attainment of COs of first-year courses", q, 10, "obe.co_attainment", ay),
        ("8.5", "Attainment of POs / PSOs from first-year courses", q, 20, "obe.po_attainment", ay),
        ("9.1", "Mentoring system", ql, 5, "mentoring.ratio", ay),
        ("9.2", "Feedback analysis and reward / corrective measures", ql, 10, "surveys.sss_score", ay),
        ("9.3", "Feedback on facilities", ql, 5, None, ay),
        ("9.4", "Self-learning", ql, 5, "students.mooc_completions", ay),
        ("9.5", "Career guidance, training, placement", ql, 10, None, ay),
        ("9.6", "Entrepreneurship cell", ql, 5, None, ay),
        ("9.7", "Co-curricular and extra-curricular activities", ql, 10, "events.count_by_type", ay),
        ("10.1", "Organisation, governance and transparency", "qn_ql", 40, None, ay),
        ("10.2", "Budget allocation, utilisation and public accounting at institute level", q, 30, "finance.capex", ay),
        ("10.3", "Programme-specific budget allocation, utilisation", q, 30, "finance.opex", ay),
        ("10.4", "Library and Internet", "qn_ql", 20, "library.books_added", ay),
    ]


def _nirf() -> list[C]:
    q, ay, fy = "quantitative", "academic_year", "financial_year"
    return [
        ("TLR", "Teaching, Learning & Resources", q, 100, None, ay),
        ("TLR.SS", "Student strength including doctoral students", q, 20, "students.enrolment_by_category", ay),
        ("TLR.FSR", "Faculty-student ratio with emphasis on permanent faculty", q, 30, "nirf.fsr", ay),
        ("TLR.FQE", "Combined metric for faculty with PhD and experience", q, 20, "nirf.fqe", ay),
        ("TLR.FRU", "Financial resources and their utilisation", q, 30, "nirf.fru", fy),
        ("RP", "Research and Professional Practice", q, 100, None, ay),
        ("RP.PU", "Combined metric for publications", q, 35, "nirf.pu", "calendar_year"),
        ("RP.QP", "Combined metric for quality of publications", q, 35, "nirf.qp", "calendar_year"),
        ("RP.IPR", "IPR and patents: published and granted", q, 15, "nirf.ipr", "calendar_year"),
        ("RP.FPPP", "Footprint of projects and professional practice", q, 15, "nirf.fppp", fy),
        ("GO", "Graduation Outcomes", q, 100, None, ay),
        ("GO.GPH", "Metric for university examinations", q, 40, "nirf.gph", ay),
        ("GO.GUE", "Metric for number of graduating students (placement & higher studies)", q, 15, "nirf.gue", ay),
        ("GO.MS", "Median salary", q, 25, "nirf.gms", ay),
        ("GO.GPHD", "Metric for number of PhD students graduated", q, 20, "nirf.gphd", ay),
        ("OI", "Outreach and Inclusivity", q, 100, None, ay),
        ("OI.RD", "Percentage of students from other states / countries", q, 30, "nirf.rd", ay),
        ("OI.WD", "Percentage of women", q, 30, "nirf.wd", ay),
        ("OI.ESCS", "Economically and socially challenged students", q, 20, "nirf.escs", ay),
        ("OI.PCS", "Facilities for physically challenged students", q, 20, "nirf.pcs", ay),
        ("PR", "Perception", q, 100, None, ay),
        ("PR.PR", "Peer perception: academic peers and employers", "qualitative", 100, None, ay),
    ]


def _aishe() -> list[C]:
    q, ay = "quantitative", "academic_year"
    return [
        ("A", "Basic details of the institution", "qualitative", None, None, ay),
        ("B", "Departments and programmes", q, None, "academics.programs_count", ay),
        ("C", "Student enrolment (programme × category × gender)", q, None, "students.enrolment_by_category", ay),
        ("D", "Examination results (pass-outs)", q, None, "results.pass_pct_final_year", ay),
        ("E", "Teaching staff (designation × category × gender)", q, None, "faculty.fsr", ay),
        ("F", "Non-teaching staff", q, None, "faculty.non_teaching_count", ay),
        ("G", "Financial information (income / expenditure)", q, None, "finance.opex", "financial_year"),
        ("H", "Infrastructure (hostel, library, labs)", q, None, "hostel.occupancy_pct", ay),
        ("I", "Scholarships", q, None, "scholarships.beneficiaries_pct", ay),
        ("J", "PwD and minority students", q, None, "values.pwd_ratio", ay),
    ]


def _aicte() -> list[C]:
    q, ay = "quantitative", "academic_year"
    return [
        ("EOA.1", "Approved intake and admitted students", q, None, "students.seats_filled_vs_reserved", ay),
        ("EOA.2", "Faculty cadre and student-faculty ratio", q, None, "faculty.cadre_ratio", ay),
        ("EOA.3", "Faculty qualification (PhD)", q, None, "faculty.phd_pct", ay),
        ("EOA.4", "Fee structure and mandatory disclosure", "qualitative", None, None, ay),
        ("EOA.5", "Grievance redressal and anti-ragging", q, None, "governance.grievance_sla_pct", ay),
        ("EOA.6", "Library (titles, volumes, e-resources)", q, None, "library.books_added", ay),
        ("EOA.7", "Placement statistics", q, None, "placement.placed_pct", ay),
    ]


def _ugc() -> list[C]:
    q, ay = "quantitative", "academic_year"
    return [
        ("UGC.1", "Status under 2(f) / 12(B) and governance", "qualitative", None, None, ay),
        ("UGC.2", "Programmes offered and enrolment", q, None, "students.enrolment_by_category", ay),
        ("UGC.3", "Teachers (sanctioned / filled / PhD)", q, None, "faculty.phd_pct", ay),
        ("UGC.4", "Research output and PhDs awarded", q, None, "research.phd_awarded", ay),
        ("UGC.5", "Finance (grants received and utilised)", q, None, "finance.capex", "financial_year"),
        ("UGC.6", "Affiliated colleges", q, None, "affiliation.colleges_count", ay),
    ]


FRAMEWORK_TREES: dict[str, list[C]] = {
    "NAAC_2024": _naac(),
    "NBA_UG_ENGG": _nba(),
    "NIRF": _nirf(),
    "AISHE": _aishe(),
    "AICTE_APPROVAL": _aicte(),
    "UGC_12B": _ugc(),
}


def parent_code(code: str) -> str | None:
    """``2.3.1`` → ``2.3``; ``2.3`` → ``2``; ``TLR.FSR`` → ``TLR``; top level → None."""
    return code.rsplit(".", 1)[0] if "." in code else None


# key, name, unit, source_module, computation_key, params_schema, depends_on
MD = tuple[str, str, str, str, str, dict[str, Any] | None, list[str] | None]
_MIN_CTC = {"type": "object", "properties": {"min_ctc_paise": {"type": "integer", "minimum": 0}}}
_INDEX = {"type": "object", "properties": {"indexing_set": {"type": "array", "items": {"type": "string"}}}}

METRIC_DEFINITIONS: tuple[MD, ...] = (
    (
        "results.success_rate",
        "Success rate in the stipulated period",
        "pct",
        "results",
        "results.success_rate",
        None,
        None,
    ),
    (
        "results.academic_performance_index",
        "Academic performance index (mean CGPA × success)",
        "score",
        "results",
        "results.academic_performance_index",
        None,
        None,
    ),
    (
        "faculty.cadre_ratio",
        "Faculty cadre proportion (professor : associate : assistant)",
        "ratio",
        "hr",
        "faculty.cadre_ratio",
        None,
        None,
    ),
    ("faculty.fqi", "Faculty qualification index", "score", "hr", "faculty.fqi", None, None),
    ("faculty.phd_guides", "Recognised PhD guides", "count", "phd", "published:faculty.phd_guides", None, None),
    ("faculty.non_teaching_count", "Non-teaching staff", "count", "hr", "faculty.non_teaching_count", None, None),
    ("nirf.fsr", "NIRF faculty-student ratio score", "score", "hr", "nirf.fsr", None, ["faculty.fsr"]),
    (
        "nirf.fqe",
        "NIRF faculty qualification & experience",
        "score",
        "hr",
        "nirf.fqe",
        None,
        ["faculty.phd_pct", "faculty.fqi"],
    ),
    (
        "nirf.fru",
        "NIRF financial resources & utilisation",
        "paise",
        "accounting",
        "nirf.fru",
        None,
        ["finance.capex", "finance.opex"],
    ),
    ("nirf.pu", "NIRF publications per faculty", "ratio", "research", "published:nirf.pu", _INDEX, None),
    ("nirf.qp", "NIRF quality of publications (indexed)", "count", "research", "published:nirf.qp", _INDEX, None),
    ("nirf.ipr", "NIRF IPR (patents granted)", "count", "research", "published:nirf.ipr", None, None),
    ("nirf.fppp", "NIRF footprint of projects & practice", "paise", "research", "published:nirf.fppp", None, None),
    (
        "nirf.gue",
        "NIRF graduating students in placement + higher studies",
        "pct",
        "placement",
        "nirf.gue",
        None,
        ["placement.placed_pct", "students.higher_studies_pct"],
    ),
    ("nirf.rd", "NIRF regional diversity (other states / countries)", "pct", "students", "nirf.rd", None, None),
    ("nirf.wd", "NIRF women diversity", "pct", "students", "nirf.wd", None, None),
    ("nirf.escs", "NIRF economically & socially challenged students", "pct", "fees", "nirf.escs", None, None),
    ("nirf.pcs", "NIRF facilities for physically challenged students", "score", "students", "manual.input", None, None),
    (
        "students.professional_activities",
        "Student professional activities / awards",
        "count",
        "clubs",
        "students.professional_activities",
        None,
        None,
    ),
    ("students.mooc_completions", "Students completing MOOCs", "count", "lms", "manual.input", None, None),
    ("academics.programs_count", "Programmes offered", "count", "academics", "academics.programs_count", None, None),
    (
        "academics.new_courses_pct",
        "New courses introduced",
        "pct",
        "academics",
        "academics.new_courses_pct",
        None,
        None,
    ),
    ("alumni.total", "Registered alumni", "count", "alumni", "published:alumni.total", None, None),
    ("alumni.verified_pct", "Verified alumni", "pct", "alumni", "published:alumni.verified_pct", None, None),
    ("alumni.employed_pct", "Alumni employed", "pct", "alumni", "published:alumni.employed_pct", None, None),
    (
        "alumni.higher_studies_pct",
        "Alumni in higher studies",
        "pct",
        "alumni",
        "published:alumni.higher_studies_pct",
        None,
        None,
    ),
    ("alumni.mentors", "Alumni mentors", "count", "alumni", "published:alumni.mentors", None, None),
    ("alumni.events", "Alumni events", "count", "alumni", "published:alumni.events", None, None),
    (
        "alumni.event_participation",
        "Alumni event participation",
        "count",
        "alumni",
        "published:alumni.event_participation",
        None,
        None,
    ),
    (
        "alumni.donations_total_paise",
        "Alumni contributions",
        "paise",
        "alumni",
        "published:alumni.donations_total_paise",
        None,
        None,
    ),
    ("hostel.occupancy_pct", "Hostel occupancy", "pct", "hostel", "hostel.occupancy_pct", None, None),
    ("library.books_added", "Library books added", "count", "library", "published:library.books_added", None, None),
    (
        "library.eresources_count",
        "Library e-resources",
        "count",
        "library",
        "published:library.eresources_count",
        None,
        None,
    ),
    ("transport.routes", "Transport routes", "count", "transport", "transport.routes", None, None),
    (
        "transport.students_using_pct",
        "Students using institution transport",
        "pct",
        "transport",
        "manual.input",
        None,
        None,
    ),
    ("values.pwd_ratio", "Students with disabilities", "pct", "students", "values.pwd_ratio", None, None),
    ("values.green_audit_score", "Green audit outcome", "score", "accreditation", "manual.input", None, None),
    ("values.energy_audit_score", "Energy audit outcome", "score", "accreditation", "manual.input", None, None),
    ("finance.capex", "Capital expenditure", "paise", "accounting", "finance.capex", None, None),
    ("finance.opex", "Operational expenditure (excluding salary)", "paise", "accounting", "finance.opex", None, None),
    ("research.phd_awarded", "PhDs awarded", "count", "phd", "published:research.phd_awarded", None, None),
    ("research.mous_functional", "Functional MoUs", "count", "research", "research.mous_functional", None, None),
    ("mentoring.ratio", "Mentor-mentee ratio", "ratio", "mentoring", "mentoring.ratio", None, None),
    (
        "events.extension_activities",
        "Extension & outreach activities",
        "count",
        "events",
        "events.extension_activities",
        None,
        None,
    ),
    (
        "obe.attainment_gap_pct",
        "POs below target attainment",
        "pct",
        "obe",
        "obe.attainment_gap_pct",
        None,
        ["obe.po_attainment"],
    ),
    (
        "governance.quality_initiatives",
        "Quality assurance initiatives",
        "count",
        "accreditation",
        "governance.quality_initiatives",
        None,
        None,
    ),
    ("placement.offers", "Placement offers", "count", "placement", "placement.offers", _MIN_CTC, None),
    # Phase 34: affiliation portfolio keys pushed through ``metrics.publish`` (source ``affiliation``)
    (
        "affiliation.sanctioned_intake",
        "Sanctioned intake (affiliated colleges)",
        "count",
        "affiliation",
        "published:affiliation.sanctioned_intake",
        None,
        None,
    ),
    (
        "affiliation.programs_approved",
        "Programmes approved for affiliated colleges",
        "count",
        "affiliation",
        "published:affiliation.programs_approved",
        None,
        None,
    ),
    (
        "affiliation.autonomous_colleges",
        "Autonomous colleges",
        "count",
        "affiliation",
        "published:affiliation.autonomous_colleges",
        None,
        None,
    ),
    (
        "affiliation.submission_compliance_pct",
        "College data submissions accepted",
        "pct",
        "affiliation",
        "published:affiliation.submission_compliance_pct",
        None,
        None,
    ),
)

# §36.5 seed keys (``0001``) whose computation function is event-fed rather than computed here
PUBLISHED_SEED_KEYS: frozenset[str] = frozenset(
    {
        "research.publications_per_teacher",
        "research.grants_amount",
        "research.consultancy_revenue",
        "research.patents",
        "research.fdp_participation",
        "nirf.gphd",
        "placement.placed_pct",
        "nirf.gms",
        "students.higher_studies_pct",
        "academics.internships_pct",
    }
)

# metric keys a pushed event may carry that are not defined (ignored with a log line)
EVENT_SOURCES: dict[str, str] = {
    "research.stats_published": "research",
    "phd.stats_published": "phd",
    "placement.stats_published": "placement",
    "alumni.stats_published": "alumni",
    "metrics.publish": "module",
}

DEFAULT_DISCLOSURE_ITEMS: list[dict[str, Any]] = [
    {
        "key": "sanctioned_intake",
        "title": "Sanctioned intake and admitted students",
        "metric_key": "students.seats_filled_vs_reserved",
    },
    {"key": "faculty_list", "title": "Faculty strength and qualification", "metric_key": "faculty.phd_pct"},
    {"key": "fsr", "title": "Student-faculty ratio", "metric_key": "faculty.fsr"},
    {"key": "fee_structure", "title": "Fee structure", "metric_key": None},
    {
        "key": "results_summary",
        "title": "Results summary (final year pass %)",
        "metric_key": "results.pass_pct_final_year",
    },
    {"key": "placement_stats", "title": "Placement statistics", "metric_key": "placement.placed_pct"},
    {"key": "median_salary", "title": "Median salary of placed graduates", "metric_key": "nirf.gms"},
    {
        "key": "grievance_committees",
        "title": "Grievance redressal (resolved within SLA)",
        "metric_key": "governance.grievance_sla_pct",
    },
    {"key": "anti_ragging", "title": "Anti-ragging committee and squad", "metric_key": None},
    {"key": "iqac_minutes", "title": "IQAC minutes and action taken", "metric_key": None},
    {"key": "aqar_links", "title": "AQAR / SSR submissions", "metric_key": None},
]

DEFAULT_ACCREDITATION_SETTINGS: dict[str, Any] = {
    "period_type_default": "academic_year",
    "compute_schedule": "weekly",
    "override_requires_verification": True,
    "evidence_max_mb": 25,
    "disclosure_items": DEFAULT_DISCLOSURE_ITEMS,
}
