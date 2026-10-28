// Attendance fan-in: 2 000 faculty devices flush offline queues (one session of 60 marks each) within 5 minutes,
// each with an Idempotency-Key replayed once. Pass: all flushed, replays answered 200/409 IDEMPOTENT_REPLAY, p95 < 800 ms.
import { check } from 'k6';
import http from 'k6/http';
import { BASE, TOKENS, headers, uuid } from './lib.js';

export const options = {
  scenarios: { fanin: { executor: 'shared-iterations', vus: 400, iterations: 2000, maxDuration: '5m' } },
  thresholds: { 'http_req_duration{name:flush}': ['p(95)<800'], checks: ['rate>0.99'] },
};
const SESSIONS = JSON.parse(open(__ENV.SESSIONS || './sessions.json')); // [{session_id, token, marks: [...]}, …]

export default function () {
  const s = SESSIONS[__ITER % SESSIONS.length];
  const key = uuid();
  const body = JSON.stringify({ marks: s.marks });
  const p = { ...headers(s.token || TOKENS.staff[0], { 'Idempotency-Key': key }), tags: { name: 'flush' } };
  const first = http.post(`${BASE}/class-sessions/${s.session_id}/attendance`, body, p);
  const replay = http.post(`${BASE}/class-sessions/${s.session_id}/attendance`, body, p);
  check(first, { flushed: (x) => x.status < 300 || x.status === 409 });
  check(replay, { replay: (x) => x.status < 300 || x.status === 409 });
}
