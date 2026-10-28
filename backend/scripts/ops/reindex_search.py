"""Rebuild the global search index for one tenant (Phase 01 search) by re-emitting ``search.reindex`` for each entity.

python scripts/ops/reindex_search.py --institution demo-uni
"""

import argparse

from _ops import run, tenant_admin


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--institution", required=True)
    a = ap.parse_args()

    async def fn(db):  # type: ignore[no-untyped-def]
        from sqlalchemy import text

        iid, _ = await tenant_admin(db, a.institution)
        n = 0
        for table, etype in (
            ("students", "student.updated"),
            ("staff", "staff.updated"),
            ("courses", "course.updated"),
        ):
            rows = (await db.execute(text(f"SELECT id FROM {table} WHERE institution_id = :i"), {"i": iid})).all()  # noqa: S608
            for (rid,) in rows:
                await db.execute(
                    text(
                        "INSERT INTO domain_events (institution_id, event_type, aggregate_type, aggregate_id, payload) "
                        "VALUES (:i, :e, :t, :r, CAST(:p AS jsonb))"
                    ),
                    {"i": iid, "e": etype, "t": table[:-1], "r": rid, "p": '{"reindex": true}'},
                )
                n += 1
        return {"events": n}

    run(fn)


if __name__ == "__main__":
    main()
