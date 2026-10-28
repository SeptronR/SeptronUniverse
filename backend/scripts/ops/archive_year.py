"""Archive an academic year (lock it; Phase 37 retention archives the partitions older than the policy).

python scripts/ops/archive_year.py --institution demo-uni --year-id <uuid>      (four-eyes in the ops console)
"""

import argparse
import uuid

from _ops import run, tenant_admin


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--institution", required=True)
    ap.add_argument("--year-id", required=True)
    a = ap.parse_args()

    async def fn(db):  # type: ignore[no-untyped-def]
        from app.services.academic_session_service import AcademicSessionService

        _, principal = await tenant_admin(db, a.institution)
        out = await AcademicSessionService(db, principal).lock_year(uuid.UUID(a.year_id), True)
        return {
            "locked": out.model_dump(mode="json"),
            "note": "partition archival runs through the Phase 37 retention jobs",
        }

    run(fn)


if __name__ == "__main__":
    main()
