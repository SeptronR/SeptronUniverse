"""Full tenant export (Phase 38 encrypted zip; password delivered separately).

python scripts/ops/tenant_export.py --institution demo-uni [--format csv]
"""

import argparse
import uuid

from _ops import run


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--institution", required=True)
    ap.add_argument("--format", default="csv")
    a = ap.parse_args()

    async def fn(db):  # type: ignore[no-untyped-def]
        from sqlalchemy import text

        from app.services.saas.institution_admin_service import InstitutionAdminService

        iid = (await db.execute(text("SELECT id FROM institutions WHERE slug = :s"), {"s": a.institution})).scalar_one()
        svc = InstitutionAdminService(db, None)
        return await svc.export_now(iid, uuid.uuid4().hex[:12], [], a.format)

    run(fn, platform=True)


if __name__ == "__main__":
    main()
