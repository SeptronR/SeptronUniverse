# Architecture Decision Records

| # | Decision | Status |
|---|---|---|
| [0001](0001-greenfield-same-architecture.md) | Greenfield repo mirroring SeptronOrbit's architecture | accepted |
| [0002](0002-tenancy-institution-college-rls.md) | Tenant = institution; colleges as sub-tenants; PostgreSQL RLS backstop | accepted |
| [0003](0003-feature-flag-registry.md) | Every feature is a registered, super-admin-controlled flag | accepted |
| [0004](0004-visibility-resolver.md) | Row-level visibility resolver (self / ownership / scoped / view_all) | accepted |
| [0005](0005-transactional-outbox.md) | Domain events via transactional outbox | accepted |
| [0006](0006-functional-verification.md) | Verification through API scripts and UI functional checks, not unit tests | accepted |
| [0007](0007-status-columns-and-enums.md) | Status columns as VARCHAR + Python enums | accepted |
| [0008](0008-results-immutability.md) | Published results are versioned and immutable | accepted |
