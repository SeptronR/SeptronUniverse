"""Demo seed for the platform module (Prompts/01 §01.2) — ``seed_demo_institution.py --only platform``.

Platform-level help articles (``help_articles.institution_id IS NULL`` → visible to every tenant) for the modules that
exist after Phase 01: getting started, background jobs, read-only mode, global search, feedback. No dependency on the
``base`` demo institution (Phase 02), so the help centre has content the moment the shell renders. Idempotent
(``get_or_create`` on ``slug`` with ``institution_id IS NULL``).
"""

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import select

from app.models.platform import HelpArticle

PLATFORM_ARTICLES: list[dict[str, str]] = [
    {
        "slug": "getting-started",
        "title": "Getting started with SeptronUniverse",
        "module": "dashboard",
        "body": (
            "## Welcome\n\nSeptronUniverse is your institution's operating system: academics, examinations, admissions, "
            "campus services and quality — one login, role-based.\n\n"
            "- **Sidebar**: groups appear as their modules are enabled for your institution and your roles allow them.\n"
            "- **Navbar**: switch college (when you have more than one), pick the academic year/term, search with "
            "`Ctrl+K`, watch background jobs in the tray and notifications in the bell.\n"
            "- **Mine | Department | College | All** tabs on every list follow your visibility scope.\n\n"
            "Use the feedback button (bottom of the help centre) to report a problem or suggest an improvement."
        ),
    },
    {
        "slug": "background-jobs",
        "title": "Background jobs and the jobs tray",
        "module": "jobs",
        "body": (
            "Long-running work — bulk PDFs, imports and exports, result runs, allocations — runs as a **background "
            "job**. You keep working; the tray in the navbar shows progress live and the **Jobs** page lists every job "
            "with its status, progress and result link.\n\n"
            "- `queued` → `running` → `succeeded` | `failed` | `cancelled`.\n"
            "- **Cancel** stops a job at its next checkpoint (partial output is discarded).\n"
            "- Result files stay available for 7 days, then they are cleaned up automatically."
        ),
    },
    {
        "slug": "read-only-mode",
        "title": "Read-only (maintenance) mode",
        "module": "settings",
        "body": (
            "During maintenance the platform — or a single institution — can be switched to **read-only**. A banner "
            "appears on every client and write actions answer `503 READ_ONLY`; reading, searching and exporting "
            "keep working.\n\n"
            "Institution admins (`settings:manage`) open or close a window under *Settings → Platform → Read-only*; "
            "platform-wide windows are set by the super admin. Windows may carry an end time and expire on their own."
        ),
    },
    {
        "slug": "global-search",
        "title": "Global search (Ctrl+K)",
        "module": "dashboard",
        "body": (
            "Press `Ctrl+K` (or click **Search** in the navbar) to jump to pages or find students, staff, courses and "
            "applicants by name, number or code. Results respect your permissions and visibility scope — you only see "
            "records you could open anyway."
        ),
    },
    {
        "slug": "feedback",
        "title": "Sending feedback",
        "module": "settings",
        "body": (
            "Found a bug, or an idea to make a screen better? Open **Help → Send feedback**, pick a category (bug, "
            "idea, question, praise), rate the page and describe what happened. The page you were on is attached "
            "automatically; your institution admin and the SeptronUniverse team see the entry."
        ),
    },
]


@seeder("platform")
async def seed_platform_help(ctx: SeedContext) -> None:
    for article in PLATFORM_ARTICLES:
        existing = (
            await ctx.db.execute(
                select(HelpArticle).where(HelpArticle.institution_id.is_(None), HelpArticle.slug == article["slug"])
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        ctx.db.add(
            HelpArticle(
                institution_id=None,
                slug=article["slug"],
                title=article["title"],
                body=article["body"],
                module=article["module"],
                audience=["all"],
                is_published=True,
            )
        )
        ctx.count("help_articles")
    await ctx.db.flush()
