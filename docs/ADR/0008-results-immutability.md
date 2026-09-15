# ADR 0008 — Published results are versioned and immutable

**Status:** accepted (2026-09-13)

## Decision
`student_course_results` and `student_term_results` are versioned (`version`, `supersedes_id`, `is_current`). A DB trigger rejects UPDATEs on published rows except flipping `is_current`/`status→superseded`. Every change after publication (revaluation, grace, correction, malpractice) creates a new version through a request/workflow table. Each row carries a hash; each run a checksum; grade cards and degrees carry signed QR tokens resolving to `/verify/{token}`.

## Consequences
Full legal audit trail; reproducible runs from `config_snapshot`; ABC ledger revocations mirror versions.
