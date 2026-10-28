// Shared helpers for the k6 scenarios (Prompts/43 §43.6 load_test_service). Run against **staging** only:
//   k6 run -e BASE=https://staging-api.example/api/v1 -e INSTITUTION=demo-uni -e TOKENS=tokens.json registration_rush.js
// tokens.json: {"students": ["<access token>", …], "staff": [...]} produced by load/make_tokens.py from the --load seed.
import http from 'k6/http';

export const BASE = __ENV.BASE || 'http://localhost:8000/api/v1';
export const INSTITUTION = __ENV.INSTITUTION || 'demo-uni';
export const TOKENS = JSON.parse(open(__ENV.TOKENS || './tokens.json'));

export function headers(token, extra = {}) {
  return { headers: { Authorization: `Bearer ${token}`, 'X-Institution-Slug': INSTITUTION, 'Content-Type': 'application/json', ...extra } };
}

export function pick(list) {
  return list[Math.floor(Math.random() * list.length)];
}

export function uuid() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

export function get(path, token) {
  return http.get(`${BASE}${path}`, headers(token));
}
