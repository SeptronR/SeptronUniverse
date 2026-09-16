-- SeptronUniverse — PostgreSQL bootstrap (runs once from docker-entrypoint-initdb.d, or by hand: psql -U postgres -f docker/postgres/init/01_roles.sql)
-- Two login roles, exactly as Prompts/00_PREREQUISITE_Project_Setup.md §3.2/§8 and ADR 0002 require:
--   universe_app       — the API/worker runtime role; NOT BYPASSRLS, so Row-Level Security is the backstop for every tenant query
--   universe_platform  — owns the schema (Alembic migrates with PLATFORM_DATABASE_URL), super-admin cross-tenant queries,
--                        outbox relay / partition maintenance / search_documents refresh; BYPASSRLS
-- Phase 01 decision (PROGRESS.md 2026-09-16): DDL is owned by the platform role so RLS applies to the app role as a
-- non-owner and the materialized-view refresh sees every tenant. Revision 0001 grants the app role its runtime privileges
-- (tables, sequences, functions + default privileges for later revisions).
-- Passwords here are dev defaults (they match backend/.env.example); production sets them from the host vault.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'universe_app') THEN
    CREATE ROLE universe_app LOGIN PASSWORD 'pass' NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'universe_platform') THEN
    CREATE ROLE universe_platform LOGIN PASSWORD 'pass' BYPASSRLS;
  END IF;
END
$$;

-- The compose file creates the database (POSTGRES_DB=universe) owned by POSTGRES_USER; hand it to the platform role so
-- Alembic (0001 applies Database_Schema.sql) owns every object, and let the app role connect.
ALTER DATABASE universe OWNER TO universe_platform;
GRANT ALL PRIVILEGES ON DATABASE universe TO universe_platform;
GRANT CONNECT, TEMPORARY ON DATABASE universe TO universe_app;

\connect universe
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
ALTER SCHEMA public OWNER TO universe_platform;
GRANT ALL ON SCHEMA public TO universe_platform;
GRANT USAGE ON SCHEMA public TO universe_app;
ALTER DEFAULT PRIVILEGES FOR ROLE universe_platform IN SCHEMA public GRANT ALL ON TABLES TO universe_app;
ALTER DEFAULT PRIVILEGES FOR ROLE universe_platform IN SCHEMA public GRANT ALL ON SEQUENCES TO universe_app;
ALTER DEFAULT PRIVILEGES FOR ROLE universe_platform IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO universe_app;
