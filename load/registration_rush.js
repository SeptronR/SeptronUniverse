// Registration rush: 5 000 students submit carts within 10 minutes on 20 capped offerings.
// Pass: p95 submit < 1 s, no 5xx; afterwards `SELECT offering_id, count(*) … ≤ capacity` (load/check_allocation.sql).
import { check } from 'k6';
import http from 'k6/http';
import { BASE, TOKENS, headers, pick, uuid } from './lib.js';

export const options = {
  scenarios: { rush: { executor: 'ramping-arrival-rate', startRate: 5, timeUnit: '1s', preAllocatedVUs: 300, maxVUs: 1500,
    stages: [{ target: 20, duration: '2m' }, { target: 12, duration: '6m' }, { target: 0, duration: '2m' }] } },
  thresholds: { 'http_req_duration{name:submit}': ['p(95)<1000'], 'http_req_failed{name:submit}': ['rate<0.01'], checks: ['rate>0.99'] },
};

export default function () {
  const token = pick(TOKENS.students);
  const body = JSON.stringify({}); // carts were filled by the --load seed on the 20 capped offerings
  const r = http.post(`${BASE}/registration/me/submit`, body, { ...headers(token, { 'Idempotency-Key': uuid() }), tags: { name: 'submit' } });
  check(r, { 'no 5xx': (x) => x.status < 500, 'accepted or seat rule': (x) => [200, 201, 409, 422].includes(x.status) });
}
