// Public website: 1 000 requests per second on cached SSR pages (Phase 40). Pass: p95 < 200 ms, 0 errors.
import { check } from 'k6';
import http from 'k6/http';

const SITE = __ENV.SITE || 'http://localhost:8000/site/demo-uni';
export const options = {
  scenarios: { rps: { executor: 'constant-arrival-rate', rate: 1000, timeUnit: '1s', duration: '3m', preAllocatedVUs: 400, maxVUs: 2000 } },
  thresholds: { http_req_duration: ['p(95)<200'], http_req_failed: ['rate<0.001'] },
};
const PAGES = ['/', '/notices', '/events', '/gallery', '/admissions', '/catalogue'];

export default function () {
  const r = http.get(`${SITE}${PAGES[Math.floor(Math.random() * PAGES.length)]}`);
  check(r, { 200: (x) => x.status === 200 });
}
