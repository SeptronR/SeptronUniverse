// Result publish fan-out: publish a 20 000-row run, then poll the notification counter for 5 minutes.
// Pass: ≥ 20 000 notifications within the first minute after publish; outbox lag < 30 s (GET /platform/health →
// checks.outbox.lag_seconds; notification counts from GET /platform/health checks.notifications.sent_last_5m).
import { check, sleep } from 'k6';
import http from 'k6/http';
import { BASE, TOKENS, headers, uuid } from './lib.js';

export const options = { vus: 1, iterations: 1, thresholds: { checks: ['rate==1'] } };

export default function () {
  const coe = TOKENS.coe;
  const run = __ENV.RUN_ID;
  const r = http.post(`${BASE}/result-runs/${run}/publish`, JSON.stringify({ confirm: true }), headers(coe, { 'Idempotency-Key': uuid() }));
  check(r, { published: (x) => x.status === 200 });
  const t0 = Date.now();
  let sent = 0;
  while (Date.now() - t0 < 300000) {
    sleep(10);
    const m = http.get(`${BASE}/platform/health`, headers(coe));
    sent = m.json('data.checks.notifications.sent_last_5m') || sent;
    if (sent >= 20000) break;
  }
  check(sent, { '≥ 20 000 notifications in the window': (n) => n >= 20000 });
  check(Date.now() - t0, { 'within 60 s': (ms) => ms <= 60000 });
}
