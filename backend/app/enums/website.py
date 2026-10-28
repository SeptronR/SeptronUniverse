"""Website enums and defaults — Prompts/40 §40.2 / §40.3."""

from typing import Literal

SslStatus = Literal["pending", "provisioning", "active", "failed", "disabled"]
EnquiryStatus = Literal["new", "contacted", "converted", "spam", "closed"]
ENQUIRY_STATUSES: tuple[str, ...] = ("new", "contacted", "converted", "spam", "closed")
# Phase 08 CRM stage → website enquiry status (status sync consumer)
STAGE_TO_STATUS: dict[str, str] = {
    "new": "new",
    "contacted": "contacted",
    "counselled": "contacted",
    "applied": "converted",
    "admitted": "converted",
    "lost": "closed",
}
SECTION_TYPES: tuple[str, ...] = (
    "hero",
    "about",
    "leadership",
    "programmes",
    "admissions_cta",
    "notices",
    "events",
    "gallery",
    "stats",
    "accreditation",
    "placements",
    "research",
    "departments",
    "colleges",
    "faculty_directory",
    "disclosures",
    "policies",
    "committees",
    "contact",
    "footer",
    "custom_html",
)
TEMPLATES: dict[str, tuple[str, ...]] = {
    "university": (
        "hero",
        "about",
        "leadership",
        "stats",
        "colleges",
        "programmes",
        "admissions_cta",
        "research",
        "notices",
        "events",
        "gallery",
        "accreditation",
        "disclosures",
        "contact",
        "footer",
    ),
    "autonomous_college": (
        "hero",
        "about",
        "leadership",
        "stats",
        "departments",
        "programmes",
        "admissions_cta",
        "placements",
        "notices",
        "events",
        "gallery",
        "accreditation",
        "disclosures",
        "contact",
        "footer",
    ),
    "affiliated_college": (
        "hero",
        "about",
        "leadership",
        "departments",
        "programmes",
        "admissions_cta",
        "notices",
        "events",
        "gallery",
        "disclosures",
        "contact",
        "footer",
    ),
}
RESERVED_HOSTS: tuple[str, ...] = ("app.", "api.", "admin.", "www.septron", "status.", "docs.")
ALLOWED_TAGS: frozenset[str] = frozenset(
    {
        "p",
        "br",
        "hr",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "strong",
        "b",
        "em",
        "i",
        "u",
        "s",
        "blockquote",
        "code",
        "pre",
        "ul",
        "ol",
        "li",
        "a",
        "img",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "figure",
        "figcaption",
        "span",
        "div",
        "iframe",
    }
)
EMBED_HOSTS: tuple[str, ...] = (
    "www.youtube.com",
    "youtube.com",
    "www.youtube-nocookie.com",
    "www.google.com",
    "maps.google.com",
)
DISPOSABLE_DOMAINS: frozenset[str] = frozenset(
    {"mailinator.com", "tempmail.com", "10minutemail.com", "guerrillamail.com"}
)
