import { api } from '@/api/axios';
import type { Envelope } from '@/utils/types';

type Params = Record<string, string | number | boolean | undefined | null>;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const get = <T = Any>(url: string, params?: Params) => api.get(url, { params }) as unknown as Promise<Envelope<T>>;
const post = <T = Any>(url: string, body?: unknown) => api.post(url, body ?? {}) as unknown as Promise<Envelope<T>>;
const put = <T = Any>(url: string, body?: unknown) => api.put(url, body) as unknown as Promise<Envelope<T>>;
const del = (url: string) => api.delete(url);

/** Integrations hub, API keys, webhooks, migration toolkit, exports — Prompts/41 §41.9. */
export const integrationsApi = {
  providers: () => get('/integrations/providers'),
  capabilities: () => get('/integrations/capabilities'),
  connections: () => get('/integrations/connections'),
  createConnection: (b: Any) => post('/integrations/connections', b),
  updateConnection: (id: string, b: Any) => put(`/integrations/connections/${id}`, b),
  deleteConnection: (id: string) => del(`/integrations/connections/${id}`),
  test: (id: string, action = 'ping') => post(`/integrations/connections/${id}/test`, { action }),
  toggle: (id: string, on: boolean) => post(`/integrations/connections/${id}/${on ? 'enable' : 'disable'}`),
  health: (id: string) => get(`/integrations/connections/${id}/health`),
  inbound: (p: Params = {}) => get('/integrations/inbound', p),
  replayInbound: (id: string) => post(`/integrations/inbound/${id}/replay`),
  changelog: () => get('/integrations/api-changelog'),
  apiKeys: () => get('/integrations/api-keys'),
  createKey: (b: Any) => post('/integrations/api-keys', b),
  rotateKey: (id: string) => post(`/integrations/api-keys/${id}/rotate`),
  revokeKey: (id: string) => del(`/integrations/api-keys/${id}`),
  webhooks: () => get('/integrations/webhooks'),
  createWebhook: (b: Any) => post('/integrations/webhooks', b),
  updateWebhook: (id: string, b: Any) => put(`/integrations/webhooks/${id}`, b),
  deleteWebhook: (id: string) => del(`/integrations/webhooks/${id}`),
  testWebhook: (id: string) => post(`/integrations/webhooks/${id}/test`, { event_type: 'ping' }),
  rotateWebhook: (id: string) => post(`/integrations/webhooks/${id}/rotate-secret`),
  deliveries: (p: Params = {}) => get('/integrations/deliveries', p),
  retry: (ids: string[]) => post('/integrations/deliveries/retry', { ids }),
  deadLetters: (kind: string) => get('/integrations/dead-letters', { kind }),
  replayDead: (kind: string, ids: string[]) => post('/integrations/dead-letters/replay', { kind, ids }),
  discardDead: (kind: string, ids: string[], reason: string) => post('/integrations/dead-letters/discard', { kind, ids, reason }),
  templates: () => get('/imports/templates'),
  imports: (p: Params = {}) => get('/imports', p),
  createImport: (b: Any) => post('/imports', b),
  validate: (id: string) => post(`/imports/${id}/validate`),
  apply: (id: string, confirm_valid_rows: number) => post(`/imports/${id}/apply`, { confirm_valid_rows, on_conflict: 'skip' }),
  rollback: (id: string) => post(`/imports/${id}/rollback`),
  deleteImport: (id: string) => del(`/imports/${id}`),
  workbook: () => get('/imports/workbook'),
  startWorkbook: () => post('/imports/workbook/start'),
  exportMe: () => post('/exports/users/me', { include: [] }),
  exportTenant: () => post('/exports/tenant', {}),
  exportStatus: (id: string) => get(`/exports/${id}`),
};
