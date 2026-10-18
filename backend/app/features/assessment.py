"""Feature keys registered by Phase 13 (docs/Feature_Flags.md assessment / lms groups + ``obe.definitions``).

``obe.attainment`` / ``obe.cqi`` / ``obe.nba_export`` / ``obe.indirect_surveys`` belong to Phase 17. Dependencies on
keys of later phases (``integrations.video_conf`` / ``integrations.plagiarism`` / ``integrations.lti``) are listed as
documented.
"""

from app.core.features import register_feature

_KEYS: tuple[tuple[str, str, str, str, bool, str, tuple[str, ...]], ...] = (
    (
        "assessment",
        "assessment.internal_marks",
        "Internal assessment",
        "schemes, components, marks",
        True,
        "starter",
        ("registration.core",),
    ),
    (
        "assessment",
        "assessment.question_wise_co",
        "Question-wise CO marks",
        "question map, question-wise entry",
        True,
        "standard",
        ("obe.definitions",),
    ),
    (
        "assessment",
        "assessment.marks_workflow",
        "Marks workflow",
        "submit/verify/lock chain",
        True,
        "starter",
        ("assessment.internal_marks",),
    ),
    (
        "assessment",
        "assessment.marks_change_requests",
        "Marks change requests",
        "post-lock corrections",
        True,
        "standard",
        ("workflow.engine",),
    ),
    (
        "assessment",
        "assessment.projects",
        "Projects & dissertations",
        "project groups, reviews",
        True,
        "standard",
        ("assessment.internal_marks",),
    ),
    ("lms", "lms.content", "Course content", "modules, contents, views", True, "standard", ("registration.core",)),
    ("lms", "lms.assignments", "Assignments", "assignments & submissions", True, "standard", ("lms.content",)),
    (
        "lms",
        "lms.similarity_check",
        "Similarity check",
        "plagiarism on submissions",
        False,
        "professional",
        ("integrations.plagiarism",),
    ),
    ("lms", "lms.quizzes", "Quizzes", "quizzes/attempts", True, "standard", ("lms.question_bank",)),
    ("lms", "lms.question_bank", "Question bank", "questions, tags, syllabus topics", True, "standard", ()),
    (
        "lms",
        "lms.blueprints_paper_builder",
        "Blueprints & paper builder",
        "QP generation",
        True,
        "standard",
        ("lms.question_bank",),
    ),
    ("lms", "lms.study_materials", "Study materials", "publishable materials", True, "standard", ("lms.content",)),
    ("lms", "lms.discussions", "Discussions", "threads & posts", True, "standard", ("lms.content",)),
    (
        "lms",
        "lms.lesson_plans",
        "Lesson plans",
        "lesson plans & delivery tick-off",
        True,
        "standard",
        ("timetable.core",),
    ),
    ("lms", "lms.course_files", "Course files", "checklist & audit", True, "standard", ("lms.lesson_plans",)),
    (
        "lms",
        "lms.online_class_links",
        "Online class links",
        "Zoom/Meet links on sessions",
        True,
        "standard",
        ("integrations.video_conf",),
    ),
    ("lms", "lms.lti_moodle", "LTI / Moodle", "external LMS sync", False, "professional", ("integrations.lti",)),
    (
        "obe",
        "obe.definitions",
        "OBE definitions",
        "PEO/PO/PSO/CO, CO-PO matrix",
        True,
        "standard",
        ("academics.curriculum",),
    ),
)

for _group, _key, _name, _desc, _on, _tier, _deps in _KEYS:
    register_feature(
        key=_key,
        group=_group,
        name=_name,
        description=_desc,
        default_enabled=_on,
        min_plan_tier=_tier,
        depends_on=_deps,
    )
