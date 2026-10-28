// List / detail / search / dashboard latency with 200 concurrent staff users on 50 000-row tables.
// Pass: lists p95 < 300 ms, detail < 150 ms, search < 500 ms, dashboard < 300 ms.
import { check, group } from 'k6';
import http from 'k6/http';
import { BASE, TOKENS, headers, pick } from './lib.js';

export const options = {
  vus: 200,
  duration: '5m',
  thresholds: {
    'http_req_duration{kind:list}': ['p(95)<300'],
    'http_req_duration{kind:detail}': ['p(95)<150'],
    'http_req_duration{kind:search}': ['p(95)<500'],
    'http_req_duration{kind:dashboard}': ['p(95)<300'],
    http_req_failed: ['rate<0.005'],
  },
};

export default function () {
  const token = pick(TOKENS.staff);
  group('lists', () => {
    for (const path of ['/students?limit=50', '/fees/invoices?limit=50', '/attendance/summary?limit=50']) {
      const r = http.get(`${BASE}${path}`, { ...headers(token), tags: { kind: 'list' } });
      check(r, { ok: (x) => x.status === 200 });
      const first = r.json('data.0.id') || r.json('data.items.0.id');
      if (first && path.startsWith('/students')) http.get(`${BASE}/students/${first}`, { ...headers(token), tags: { kind: 'detail' } });
    }
  });
  http.get(`${BASE}/search?q=an`, { ...headers(token), tags: { kind: 'search' } });
  http.get(`${BASE}/dashboard`, { ...headers(token), tags: { kind: 'dashboard' } });
}
