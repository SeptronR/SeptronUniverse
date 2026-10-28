"""Portal help articles seeded by revision ``0039`` — Prompts/39 §39.2 (one contextual article per portal page:
``help:/student/…``, ``help:/parent/…`` …, generated from the portal registry so every tab / More entry has one).
Slugs already seeded by Phase 38 are skipped by the migration (``WHERE NOT EXISTS``)."""

from typing import Any

from app.core.portals import PORTALS

PERSONA_TITLE = {
    "student": "Student",
    "parent": "Parent",
    "faculty": "Faculty",
    "alumni": "Alumni",
    "warden": "Warden",
    "gate": "Gate",
    "evaluator": "Evaluator",
    "scholar": "Scholar",
    "applicant": "Applicant",
    "recruiter": "Recruiter",
    "driver": "Driver",
}


def portal_articles() -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for persona, d in PORTALS.items():
        for e in (*d.tabs, *d.more):
            slug = f"help:{e.route.split('?')[0]}"
            if slug in seen:
                continue
            seen.add(slug)
            name = e.key.replace("_", " ")
            out.append(
                {
                    "slug": slug,
                    "title": f"{PERSONA_TITLE[persona]} portal — {name}",
                    "body": (
                        f"## {name.title()}\n\nThis page of the {persona} portal shows only your own records"
                        + (" (or your consented wards')" if persona == "parent" else "")
                        + ".\n\n* Use **?** for this help, **Restart tour** for a guided walk-through.\n"
                        "* Notifications for this area can be tuned under **Notification settings**.\n"
                        "* Something wrong? Send **Feedback** from the help drawer — the page is attached for you."
                    ),
                    "module": (e.feature or f"portals.{persona}").split(".")[0],
                    "audience": {"roles": [], "portals": [persona], "public": False},
                    "is_published": True,
                }
            )
    return out
