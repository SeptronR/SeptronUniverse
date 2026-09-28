import type { AxiosRequestConfig } from 'axios';
import { api } from '@/api/axios';
import type { Envelope } from '@/utils/types';
import type {
  Announcement,
  AppNotification,
  DltTemplate,
  MessageLog,
  NotificationTemplate,
  PreferenceItem,
  TemplatePreview,
  WhatsappTemplate,
} from './types';

const get = <T>(url: string, config?: AxiosRequestConfig) => api.get(url, config) as unknown as Promise<Envelope<T>>;
const post = <T>(url: string, body?: unknown, config?: AxiosRequestConfig) =>
  api.post(url, body, config) as unknown as Promise<Envelope<T>>;
const put = <T>(url: string, body?: unknown) => api.put(url, body) as unknown as Promise<Envelope<T>>;
const del = <T>(url: string, config?: AxiosRequestConfig) => api.delete(url, config) as unknown as Promise<Envelope<T>>;
type Params = Record<string, string | number | boolean | undefined | null>;
const once = { idempotent: false };

/** Communication core API (Prompts/04 §04.8). */
export const commsApi = {
  templates: (params: Params = {}) => get<NotificationTemplate[]>('/communication/templates', { params }),
  createTemplate: (body: Record<string, unknown>) => post<NotificationTemplate>('/communication/templates', body, once),
  updateTemplate: (id: string, body: Record<string, unknown>) => put<NotificationTemplate>(`/communication/templates/${id}`, body),
  templateVersions: (id: string) => get<NotificationTemplate[]>(`/communication/templates/${id}/versions`),
  previewTemplate: (id: string, context: Record<string, unknown>) =>
    post<TemplatePreview>(`/communication/templates/${id}/preview`, { context }, once),
  activateTemplate: (id: string) => post<NotificationTemplate>(`/communication/templates/${id}/activate`, undefined, once),
  dlt: () => get<DltTemplate[]>('/communication/dlt-templates'),
  createDlt: (body: Record<string, unknown>) => post<DltTemplate>('/communication/dlt-templates', body, once),
  whatsapp: () => get<WhatsappTemplate[]>('/communication/whatsapp-templates'),
  createWhatsapp: (body: Record<string, unknown>) => post<WhatsappTemplate>('/communication/whatsapp-templates', body, once),
  syncWhatsapp: (id: string) => post<WhatsappTemplate>(`/communication/whatsapp-templates/${id}/sync-status`, undefined, once),
  send: (body: Record<string, unknown>) => post<{ event_id: string; event_type: string }>('/communication/send', body),
  logs: (params: Params = {}) => get<MessageLog[]>('/communication/logs', { params }),
  log: (id: string) => get<MessageLog>(`/communication/logs/${id}`),
  // notifications (self)
  notifications: (params: Params = {}) => get<AppNotification[]>('/notifications', { params }),
  unreadCount: () => get<{ unread: number }>('/notifications/unread-count'),
  markRead: (id: string) => post<{ unread: number }>(`/notifications/${id}/read`, undefined, once),
  readAll: () => post<{ unread: number }>('/notifications/read-all', undefined, once),
  preferences: () => get<{ items: PreferenceItem[]; available_channels: string[] }>('/notification-preferences/me'),
  savePreferences: (items: PreferenceItem[]) =>
    put<{ items: PreferenceItem[] }>('/notification-preferences/me', { items: items.map(({ mandatory: _m, ...rest }) => rest) }),
  registerDevice: (body: { provider: string; platform: string; token: string; topics?: string[] }) =>
    post<{ id: string }>('/devices', body, once),
  unregisterDevice: (provider: string, token: string) => del<null>('/devices', { params: { provider, token } }),
  // announcements
  announcements: (params: Params = {}) => get<Announcement[]>('/announcements', { params }),
  announcement: (id: string) => get<Announcement>(`/announcements/${id}`),
  createAnnouncement: (body: Record<string, unknown>) => post<Announcement>('/announcements', body, once),
  updateAnnouncement: (id: string, body: Record<string, unknown>) => put<Announcement>(`/announcements/${id}`, body),
  deleteAnnouncement: (id: string) => del<null>(`/announcements/${id}`),
  publishAnnouncement: (id: string, channels: string[]) => post<Announcement>(`/announcements/${id}/publish`, { channels }, once),
  announcementStats: (id: string) => get<{ total: number; read: number; acknowledged: number }>(`/announcements/${id}/stats`),
  acknowledge: (id: string) => post<Announcement>(`/announcements/${id}/acknowledge`, { acknowledge: true }, once),
};
