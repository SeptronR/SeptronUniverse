"""Close an academic term (Phase 03 status machine; close checks must pass).

python scripts/ops/close_term.py --institution demo-uni --term-id <uuid>
"""

import argparse
import uuid

from _ops import run, tenant_admin


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--institution", required=True)
    ap.add_argument("--term-id", required=True)
    a = ap.parse_args()

    async def fn(db):  # type: ignore[no-untyped-def]
        from app.schemas.academic_sessions import TermStatusChange
        from app.services.academic_session_service import AcademicSessionService

        _, principal = await tenant_admin(db, a.institution)
        out = await AcademicSessionService(db, principal).change_status(
            uuid.UUID(a.term_id), TermStatusChange(status="closed")
        )
        return out.model_dump(mode="json")

    run(fn)


if __name__ == "__main__":
    main()
