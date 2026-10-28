import { api } from '@/api/axios';
import type { Envelope } from '@/utils/types';

type Params = Record<string, string | number | boolean | undefined | null>;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const get = <T = Any>(url: string, params?: Params) => api.get(url, { params }) as unknown as Promise<Envelope<T>>;
const post = <T = Any>(url: string, body?: unknown) => api.post(url, body ?? {}) as unknown as Promise<Envelope<T>>;
const put = <T = Any>(url: string, body?: unknown) => api.put(url, body) as unknown as Promise<Envelope<T>>;

export interface PortalNavEntry {
  key: string;
  label_key: string;
  route: string;
  icon: string;
  feature?: string | null;
}
export interface PortalShellConfig {
  persona: string | null;
  personas: string[];
  home: string | null;
  branding: { app_name: string; short_name: string; theme_color: string; background_color: string; logo_url?: string | null };
  tabs: PortalNavEntry[];
  more: PortalNavEntry[];
  home_widgets: string[];
  unified: string[];
  language: string;
  locales: string[];
  features_missing: string[];
  admin_switch: boolean;
  term?: { id: string; name: string } | null;
  ward_id?: string | null;
  tours_enabled: boolean;
  push_enabled: boolean;
}
export interface NotificationItem {
  id: string;
  title: string;
  body?: string | null;
  category?: string | null;
  route?: string | null;
  is_read: boolean;
  read_at?: string | null;
  created_at: string;
}
export interface TourDef {
  key: string;
  route: string;
  roles: string[];
  version: number;
  title?: string;
  steps: { target: string; title: string; body: string; placement?: string }[];
}
export interface PreferenceSet {
  categories: { category: string; channels: string[]; locked: string[]; available: string[] }[];
  quiet_hours?: { from: string; to: string } | null;
  digest: 'none' | 'daily' | 'weekly';
  push_subscribed: boolean;
  available_channels: string[];
}

/** Portals, notification centre, push, tours, contextual help — Prompts/39 §39.8. */
export const portalApi = {
  config: () => get<PortalShellConfig>('/portal/config'),
  wards: () => get('/portal/wards'),
  switchWard: (student_id: string) => post('/portal/wards/switch', { student_id }),
  requests: (p: Params = {}) => get('/portal/me/requests', p),
  documents: () => get('/portal/me/documents'),
  payments: (p: Params = {}) => get('/portal/me/payments', p),
  approvals: () => get('/portal/me/approvals'),
  calendar: (p: Params = {}) => get('/portal/me/calendar', p),
  timeline: (p: Params = {}) => get('/portal/me/timeline', p),
  updateMe: (b: { locale?: string; timezone?: string; theme?: string }) => put('/users/me', b),
  notifications: (p: Params = {}) => get<NotificationItem[]>('/notifications', p),
  counts: () => get('/notifications/counts'),
  open: (id: string) => get(`/notifications/${id}`),
  markRead: (b: { ids?: string[]; all?: boolean; category?: string }) => post('/notifications/mark-read', b),
  snooze: (category: string, hours: number) => post('/notifications/snooze', { category, hours }),
  preferences: () => get<PreferenceSet>('/notifications/preferences'),
  savePreferences: (b: Any) => put<PreferenceSet>('/notifications/preferences', b),
  testNotification: () => post('/notifications/test', { category: 'system', channels: ['in_app', 'push'] }),
  pendingAcks: () => get('/announcements/me', { pending_ack: true }),
  acknowledge: (id: string) => post(`/announcements/${id}/acknowledge`, { acknowledge: true }),
  vapidKey: () => get<{ public_key: string; configured: boolean }>('/public/push/vapid-key'),
  pwaConfig: () => get('/public/pwa-config'),
  subscribe: (b: Any) => post('/push/subscribe', b),
  unsubscribe: (endpoint: string) => api.delete('/push/subscribe', { data: { endpoint } }),
  testPush: () => post('/push/test', {}),
  installed: (outcome: string) => post('/pwa/installed', { platform: 'web', outcome }),
  tours: (route: string) => get<TourDef[]>('/tours/definitions', { route }),
  tourState: () => get<{ completed: Record<string, number>; dismissed: string[] }>('/tours/state'),
  saveTour: (b: { key: string; version: number; completed?: boolean; dismissed?: boolean; reset?: boolean }) => put('/tours/state', b),
  helpContext: (route: string) => get('/help/context', { route }),
  helpful: (slug: string, helpful: boolean) => post(`/help/helpful/${encodeURIComponent(slug)}`, { helpful }),
  feedback: (b: Any) => post('/feedback', b),
  myFeedback: () => get('/feedback/me'),
  localePack: (lng: string) => get<{ strings: Record<string, unknown> }>(`/public/locales/${lng}.json`),
};
