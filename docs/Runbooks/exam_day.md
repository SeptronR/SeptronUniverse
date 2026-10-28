# Runbook — Exam-day checklist

T-2 days: freeze deploys except hotfixes; confirm no `# risky` revision is pending; pre-scale `worker-documents` (hall tickets) and `worker-notifications` (result publish); verify IP allow-lists for `exam_decode` / `results_publish` (posture control `ip_allowlist_exam_ops` = pass); status page notice if relevant.
T-0: on-call named in the incident channel; Grafana *exam-day board* open; watch `queue_depth{queue="documents"}`, API p95, registration submit rate.
Decode / publish: COE follows the Phase 15 publish flow with MFA re-auth; publish fan-out is expected to reach ≥ 20 000 notifications/min — the `notifications` queue drains within minutes.
After: release the deploy freeze; record notes on the deploy / incident log.
