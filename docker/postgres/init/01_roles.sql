-- SeptronUniverse — PostgreSQL bootstrap (runs once from docker-entrypoint-initdb.d, or by hand: psql -U postgres -f docker/postgres/init/01_roles.sql)
-- Two login roles, exactly as Prompts/00_PREREQUISITE_Project_Setup.md §3.2/§8 and ADR 0002 require:
--   universe_app       — the API/worker role; NOT BYPASSRLS, so Row-Level Security is the backstop for every tenant query
--   universe_platform  — super-admin cross-tenant queries and ops scripts; BYPASSRLS
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

-- The compose file creates the database (POSTGRES_DB=universe) owned by POSTGRES_USER; hand it to the app role so
-- Alembic (0001 applies Database_Schema.sql) can create objects, and let the platform role read/write everything.
ALTER DATABASE universe OWNER TO universe_app;
GRANT ALL PRIVILEGES ON DATABASE universe TO universe_app;
GRANT ALL PRIVILEGES ON DATABASE universe TO universe_platform;

\connect universe
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
ALTER SCHEMA public OWNER TO universe_app;
GRANT ALL ON SCHEMA public TO universe_app;
GRANT USAGE ON SCHEMA public TO universe_platform;
ALTER DEFAULT PRIVILEGES FOR ROLE universe_app IN SCHEMA public GRANT ALL ON TABLES TO universe_platform;
ALTER DEFAULT PRIVILEGES FOR ROLE universe_app IN SCHEMA public GRANT ALL ON SEQUENCES TO universe_platform;
