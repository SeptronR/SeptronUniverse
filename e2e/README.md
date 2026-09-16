# e2e - Playwright UI suites (one project per round)

No unit tests (ADR 0006): UI verification is functional. Each round gets a `tests/round<N>/` folder; Phase 43 adds the
per-role storage states (`.auth/`, git-ignored), the axe accessibility checks and the `run_all.ps1` runner.

```powershell
cd e2e
npm install
npm run install:browsers
$env:BASE_URL = "http://localhost:5173"; npx playwright test --project round0
```
