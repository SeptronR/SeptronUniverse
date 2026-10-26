"""Research & faculty development enums and shipped defaults (Prompts/30 §30.3 / §30.2)."""

from enum import StrEnum
from typing import Any


class PubType(StrEnum):
    JOURNAL = "journal"
    CONFERENCE = "conference"
    BOOK = "book"
    CHAPTER = "chapter"
    PATENT_PUB = "patent_pub"


class Indexing(StrEnum):
    SCI = "sci"
    SCIE = "scie"
    SCOPUS = "scopus"
    WOS = "wos"
    UGC_CARE = "ugc_care"
    OTHER = "other"
    NONE = "none"


class PatentStatus(StrEnum):
    FILED = "filed"
    PUBLISHED = "published"
    GRANTED = "granted"
    COMMERCIALISED = "commercialised"


class EthicsType(StrEnum):
    IEC = "iec"
    IAEC = "iaec"
    IBSC = "ibsc"


class EthicsDecision(StrEnum):
    APPROVED = "approved"
    REVISE = "revise"
    REJECTED = "rejected"


class EthicsCategory(StrEnum):
    EXEMPT = "exempt"
    EXPEDITED = "expedited"
    FULL_REVIEW = "full_review"


class ProjectStatus(StrEnum):
    APPLIED = "applied"
    SANCTIONED = "sanctioned"
    ONGOING = "ongoing"
    COMPLETED = "completed"
    CLOSED = "closed"


class ConsultancyStatus(StrEnum):
    ONGOING = "ongoing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class IncentiveType(StrEnum):
    SEED_GRANT = "seed_grant"
    PUBLICATION_INCENTIVE = "publication_incentive"
    TRAVEL_GRANT = "travel_grant"
    PATENT_FILING_SUPPORT = "patent_filing_support"


class IncentiveStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    DISBURSED = "disbursed"
    REJECTED = "rejected"


class FdpEventType(StrEnum):
    FDP = "fdp"
    WORKSHOP = "workshop"
    CONFERENCE = "conference"
    CERTIFICATION = "certification"
    MOOC = "mooc"
    INDUSTRY_TRAINING = "industry_training"


class FdpRole(StrEnum):
    ATTENDED = "attended"
    ORGANISED = "organised"
    RESOURCE_PERSON = "resource_person"


class AwardLevel(StrEnum):
    INSTITUTION = "institution"
    STATE = "state"
    NATIONAL = "national"
    INTERNATIONAL = "international"


class PartnerType(StrEnum):
    INDUSTRY = "industry"
    UNIVERSITY = "university"
    GOVERNMENT = "government"
    NGO = "ngo"


class MouType(StrEnum):
    ACADEMIC = "academic"
    RESEARCH = "research"
    PLACEMENT = "placement"
    EXCHANGE = "exchange"


class MouStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    ACTIVE = "active"
    EXPIRED = "expired"
    RENEWED = "renewed"
    REJECTED = "rejected"


class CollaborationType(StrEnum):
    JOINT_RESEARCH = "joint_research"
    EXCHANGE = "exchange"
    JOINT_DEGREE = "joint_degree"
    INTERNSHIP = "internship"


class StartupStage(StrEnum):
    IDEA = "idea"
    PROTOTYPE = "prototype"
    INCUBATED = "incubated"
    FUNDED = "funded"
    GRADUATED = "graduated"


PATENT_ORDER: tuple[str, ...] = tuple(s.value for s in PatentStatus)
STARTUP_ORDER: tuple[str, ...] = tuple(s.value for s in StartupStage)
PROJECT_ACTIONS: dict[str, tuple[tuple[str, ...], str]] = {
    # action: (allowed from, to)
    "submit": (("applied",), "applied"),
    "sanction": (("applied",), "sanctioned"),
    "start": (("sanctioned",), "ongoing"),
    "complete": (("ongoing",), "completed"),
    "close": (("completed",), "closed"),
}
INDEXED: frozenset[str] = frozenset({"sci", "scie", "scopus", "wos"})

# UGC (Minimum Qualifications …) Regulations 2018, Appendix II Table 2 — research score per item; the author share
# rule (first / corresponding 70 %, others 30 % split) is applied by ``api_score_service``.
DEFAULT_API_SCHEME: dict[str, Any] = {
    "name": "UGC_CAS_2018",
    "categories": {
        "teaching": {"label": "Teaching-learning", "max": 100, "per_hour": 0.5},
        "co_curricular": {"label": "Co-curricular / extension", "max": 30, "per_activity": 3},
        "publications": {
            "label": "Research papers",
            "points": {"sci": 10, "scie": 10, "wos": 10, "scopus": 10, "ugc_care": 5, "other": 2, "none": 0},
            "impact_factor_bonus": [[10, 15], [5, 10], [2, 5], [1, 0]],
            "max": None,
        },
        "books": {"label": "Books / chapters", "points": {"book": 12, "chapter": 5}, "max": None},
        "projects": {"label": "Sponsored projects", "per_project_lakh": [[10, 10], [0, 5]], "max": None},
        "consultancy": {"label": "Consultancy", "per_project": 3, "max": None},
        "patents": {"label": "Patents", "points": {"filed": 0, "published": 5, "granted": 10, "commercialised": 10}},
        "fdp": {"label": "FDP / MOOCs", "points": {"attended": 2, "organised": 4, "resource_person": 5}, "max": 20},
        "awards": {"label": "Awards", "points": {"international": 7, "national": 5, "state": 3, "institution": 2}},
    },
}
DEFAULT_INCENTIVE_SLABS: list[dict[str, Any]] = [
    # rupees (the setting is entered in rupees; the service converts to paise)
    {"indexing": "sci", "first_author": 25000, "co_author": 10000},
    {"indexing": "scie", "first_author": 20000, "co_author": 8000},
    {"indexing": "scopus", "first_author": 10000, "co_author": 5000},
    {"indexing": "wos", "first_author": 10000, "co_author": 5000},
    {"indexing": "ugc_care", "first_author": 3000, "co_author": 1000},
]
DEFAULT_SHARE: dict[str, int] = {"institution": 30, "faculty": 70}
AGENCIES: tuple[str, ...] = ("DST", "SERB", "AICTE", "UGC", "DBT", "ICSSR", "Industry")
