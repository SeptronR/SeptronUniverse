"""Regulatory pack interface — docs/Regulatory_Pack_IN.md §1.

A pack supplies country-specific reference data, rules, metric definitions, document templates and statutory
exports; ``institutions.regulatory_pack`` selects it. Value objects are plain dataclasses so packs stay data-only;
``seed_institution_defaults(db, institution)`` (Phase 03) copies pack defaults into institution tables.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Category:
    code: str
    name: str
    is_reserved: bool = True


@dataclass(frozen=True)
class Quota:
    code: str
    name: str
    kind: str = "vertical"  # vertical | horizontal | supernumerary


@dataclass(frozen=True)
class IdFormat:
    key: str
    label: str
    pattern: str
    length: int | None = None
    masked: bool = False


@dataclass(frozen=True)
class GradingScale:
    code: str
    name: str
    bands: tuple[dict[str, Any], ...]  # ({"grade": "O", "min_pct": 90, "points": 10}, ...)


@dataclass(frozen=True)
class AssessmentScheme:
    code: str
    name: str
    internal_pct: int
    external_pct: int
    components: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class Framework:
    code: str
    name: str
    version: str


@dataclass(frozen=True)
class MetricDef:
    key: str
    name: str
    unit: str
    source_module: str


@dataclass(frozen=True)
class ReportDef:
    key: str
    name: str
    body: str  # AISHE | NIRF | AICTE | UGC | NSP …


@dataclass(frozen=True)
class TemplateDef:
    key: str
    name: str
    bilingual: bool = False


@dataclass(frozen=True)
class CommsRules:
    sms_requires_dlt: bool = False
    whatsapp_template_policy: str = "none"
    quiet_hours: tuple[int, int] | None = None  # (start_hour, end_hour) local


@dataclass(frozen=True)
class PrivacyRules:
    law: str = "GENERIC"
    consent_purposes: tuple[str, ...] = ("academic", "communication")
    retention_years: int = 7


@dataclass(frozen=True)
class TaxRules:
    tax_name: str = "none"
    default_rate_pct: float = 0.0
    taxable_fee_heads: tuple[str, ...] = ()


@dataclass(frozen=True)
class PhdRules:
    min_coursework_credits: int = 0
    max_scholars_per_guide: int | None = None
    min_duration_years: float = 3.0
    max_duration_years: float = 6.0


@dataclass
class RegulatoryPack:
    code: str
    name: str
    categories: list[Category] = field(default_factory=list)
    quotas: list[Quota] = field(default_factory=list)
    id_formats: dict[str, IdFormat] = field(default_factory=dict)
    default_grading_scales: list[GradingScale] = field(default_factory=list)
    default_assessment_schemes: list[AssessmentScheme] = field(default_factory=list)
    default_regulation_rules: dict[str, Any] = field(default_factory=dict)
    default_outcomes: dict[str, list[str]] = field(default_factory=dict)
    accreditation_frameworks: list[Framework] = field(default_factory=list)
    metric_definitions: list[MetricDef] = field(default_factory=list)
    statutory_reports: list[ReportDef] = field(default_factory=list)
    document_templates: list[TemplateDef] = field(default_factory=list)
    comms_compliance: CommsRules = field(default_factory=CommsRules)
    privacy: PrivacyRules = field(default_factory=PrivacyRules)
    tax: TaxRules = field(default_factory=TaxRules)
    phd_rules: PhdRules = field(default_factory=PhdRules)
    validators: dict[str, Callable[[str], bool]] = field(default_factory=dict)
    locales: list[str] = field(default_factory=lambda: ["en"])

    def public_config(self) -> dict[str, Any]:
        """The subset clients receive from ``GET /public/config`` (Phase 01)."""
        return {
            "code": self.code,
            "name": self.name,
            "categories": [c.__dict__ for c in self.categories],
            "quotas": [q.__dict__ for q in self.quotas],
            "id_formats": {
                k: {"label": v.label, "pattern": v.pattern, "masked": v.masked} for k, v in self.id_formats.items()
            },
            "locales": self.locales,
        }
