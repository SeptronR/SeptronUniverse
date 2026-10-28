"""Academic-year rollover (Phase 03 rule 4) for one tenant.

    python scripts/ops/rollover_academic_year.py --institution demo-uni --name 2027-28 --start 2027-06-01 --end 2028-05-31 \
        --terms '[{"name": "Odd", "start_date": "2027-06-01", "end_date": "2027-11-30"}, …]' [--promote-batches] [--lock-previous]
"""

import argparse
import json
from datetime import date

from _ops import run, tenant_admin


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--institution", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--terms", required=True, help="JSON list of RolloverTerm")
    ap.add_argument("--promote-batches", action="store_true")
    ap.add_argument("--lock-previous", action="store_true")
    a = ap.parse_args()

    async def fn(db):  # type: ignore[no-untyped-def]
        from app.schemas.academic_sessions import RolloverRequest
        from app.services.academic_session_service import AcademicSessionService

        _, principal = await tenant_admin(db, a.institution)
        body = RolloverRequest(
            new_year_name=a.name,
            start_date=date.fromisoformat(a.start),
            end_date=date.fromisoformat(a.end),
            terms=json.loads(a.terms),
            promote_batches=a.promote_batches,
            lock_previous=a.lock_previous,
        )
        return (await AcademicSessionService(db, principal).rollover(body)).model_dump(mode="json")

    run(fn)


if __name__ == "__main__":
    main()
