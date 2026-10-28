# Runbook — Migration failure / partial migration

1. The `migrate` service exits non-zero → the deploy stops before replacing the API (old code keeps serving the old schema).
2. Read the log (`docker compose logs migrate`); every revision runs in one transaction, so a failed revision leaves the previous head (`SELECT version_num FROM alembic_version`).
3. Fix forward with a new revision; never edit an applied revision. `CREATE INDEX CONCURRENTLY` failures leave an INVALID index — `DROP INDEX CONCURRENTLY` it and retry.
4. Contract steps (`# contract-of:`) only after the code that no longer needs the old shape has been live for a release. `scripts/check_migration_safety.py` enforces the markers in CI.
5. If the read-only window was opened for a `# risky` revision, close it only after `/ready` is green.
