# Runbook — Tenant suspend / export / restore / reset / erase

* Suspend / archive / reactivate: `/super-admin/institutions/{id}` (Phase 38) — archive needs a finished export.
* Export: Phase 38 encrypted zip (password delivered separately) or `ops scripts → tenant_export`.
* Restore (four-eyes): `ops scripts → tenant_restore` loads an export into a **scratch** database for review; copy-back is a reviewed, scripted operation per table — never an in-place restore over live data. See `tenant_restore.md`.
* Reset (demo only): `seed_demo_institution.py --type <t> --all` via the Phase 38 reset.
* Erase: four-eyes `erase_request`, audit chain kept, DPDP manifest stored.
