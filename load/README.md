# Load tests (k6) — staging only

Prompts/43 §43.6. Fixtures come from `seed_demo_institution.py --type university --all --load` (5 000 students in one
registration window, 20 000 exam registrations, 10 000 hall tickets). `make_tokens.py` signs in the seeded users and
writes `tokens.json` / `offerings.json` / `sessions.json` (git-ignored).

| Scenario | Script | Thresholds |
|---|---|---|
| Registration rush | `registration_rush.js` + `check_allocation.sql` | p95 < 1 s, < 1 % errors, 0 over-allocations |
| Lists / detail / search / dashboard | `lists_dashboard.js` | 300 / 150 / 500 / 300 ms p95 |
| Result publish fan-out | `result_publish.js` | ≥ 20 000 notifications / min, outbox lag < 30 s |
| Attendance fan-in | `attendance_fan_in.js` | 2 000 queues < 5 min, p95 < 800 ms |
| Public website | `website.js` | 1 000 rps, p95 < 200 ms |
| Hall-ticket bulk | `POST /exam-sessions/{id}/hall-tickets` job, timed by the job row | 10 000 PDFs < 15 min |

Results: `k6 run --summary-export=out/<scenario>.json …`, then publish into `platform_settings['qa.load_results']`
(shown at `GET /api/v1/qa/load-results` and on `/admin/qa`).
