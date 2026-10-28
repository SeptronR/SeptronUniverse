# Runbook — Demo reset

The demo environment resets nightly (Phase 38 `demo.reset_nightly`): `seed_demo_institution.py --type <type> --all` on the demo tenant; credentials are regenerated into the (git-ignored) `LOCAL_TEST_CREDENTIALS.md` on the demo host. Manual reset: super admin → institution → *Reset demo data*.
