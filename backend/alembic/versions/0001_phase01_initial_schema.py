"""phase01 initial schema — applies the canonical Database_Schema.sql

Revision ID: 0001
Revises: None
Create Date: 2026-09-16

Schema-first (ADR 0001, Prompts/01 §01.2): the whole canonical DDL (extensions, helpers, 405 tables + 6 partition
defaults, deferred FKs/indexes, RLS policies, triggers, the ``search_documents`` materialized view and the §36 seed
rows) is applied statement by statement through ``alembic/sql_loader.py`` so that every later phase finds its tables in
place. Later revisions are delta-only (most phases: "expected delta migration: none").

The migrating role (``PLATFORM_DATABASE_URL`` → ``universe_platform``, BYPASSRLS) owns every object; the closing
``GRANTS_SQL`` block hands runtime privileges (tables, sequences, functions, default privileges for future objects) to
the *other* platform role so ``universe_app`` works under Row-Level Security as a non-owner — and the reverse when a
legacy install migrates as ``universe_app``.

Statements run through ``exec_driver_sql`` (no bind-parameter parsing: the DDL contains ``:`` inside string literals
and ``%`` inside ``LIKE`` patterns). ``downgrade()`` drops every object the DDL created — matviews, views, tables
(partition parents cascade to their children), functions — but keeps ``alembic_version`` and the schema itself, so
Alembic's own bookkeeping row and the role grants on ``public`` (docker/postgres/init/01_roles.sql) survive
``alembic downgrade base && alembic upgrade head``.
"""

import sys
from collections.abc import Sequence
from pathlib import Path

from alembic import op

# alembic/versions/0001_… → alembic/  (sql_loader lives next to env.py)
_ALEMBIC_DIR = str(Path(__file__).resolve().parents[1])
if _ALEMBIC_DIR not in sys.path:
    sys.path.insert(0, _ALEMBIC_DIR)

from sql_loader import load_statements  # noqa: E402

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRANTS_SQL = """
DO $$
DECLARE other TEXT;
BEGIN
  FOREACH other IN ARRAY ARRAY['universe_app', 'universe_platform'] LOOP
    IF other <> current_user AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = other) THEN
      EXECUTE format('GRANT USAGE ON SCHEMA public TO %I', other);
      EXECUTE format('GRANT ALL ON ALL TABLES IN SCHEMA public TO %I', other);
      EXECUTE format('GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO %I', other);
      EXECUTE format('GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO %I', other);
      EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO %I', other);
      EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO %I', other);
      EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO %I', other);
    END IF;
  END LOOP;
END $$;
"""

DROP_ALL_SQL = """
DO $$
DECLARE r RECORD;
BEGIN
  FOR r IN SELECT matviewname AS name FROM pg_matviews WHERE schemaname = 'public' LOOP
    EXECUTE format('DROP MATERIALIZED VIEW IF EXISTS %I CASCADE', r.name);
  END LOOP;
  FOR r IN SELECT viewname AS name FROM pg_views WHERE schemaname = 'public' LOOP
    EXECUTE format('DROP VIEW IF EXISTS %I CASCADE', r.name);
  END LOOP;
  -- partition parents first (children go with them), then everything else except Alembic's version table
  FOR r IN SELECT c.relname AS name FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'public' AND c.relkind = 'p' LOOP
    EXECUTE format('DROP TABLE IF EXISTS %I CASCADE', r.name);
  END LOOP;
  FOR r IN SELECT tablename AS name FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version' LOOP
    EXECUTE format('DROP TABLE IF EXISTS %I CASCADE', r.name);
  END LOOP;
  -- own functions only: extension members (pgcrypto, uuid-ossp, pg_trgm, btree_gin) stay with their extension
  FOR r IN SELECT p.oid::regprocedure AS sig FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
           WHERE n.nspname = 'public' AND p.prokind IN ('f', 'p')
             AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e') LOOP
    EXECUTE format('DROP FUNCTION IF EXISTS %s CASCADE', r.sig);
  END LOOP;
END $$;
"""


def upgrade() -> None:
    bind = op.get_bind()
    for stmt in load_statements():
        bind.exec_driver_sql(stmt)
    bind.exec_driver_sql(GRANTS_SQL)


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DROP_ALL_SQL)
