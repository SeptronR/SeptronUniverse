import { api } from '@/api/axios';
import type { Envelope } from '@/utils/types';

type Params = Record<string, string | number | boolean | undefined | null>;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const get = <T = Any>(url: string, params?: Params) => api.get(url, { params }) as unknown as Promise<Envelope<T>>;
const post = <T = Any>(url: string, body?: unknown) => api.post(url, body ?? {}) as unknown as Promise<Envelope<T>>;
const put = <T = Any>(url: string, body?: unknown) => api.put(url, body) as unknown as Promise<Envelope<T>>;
const del = (url: string) => api.delete(url);

/** Website administration + marketing — Prompts/40 §40.8. */
export const websiteApi = {
  config: () => get('/website/config'),
  saveConfig: (b: Any) => put('/website/config', b),
  publish: (notes?: string) => post('/website/config/publish', { notes }),
  versions: () => get('/website/config/versions'),
  rollback: (v: number) => post(`/website/config/rollback/${v}`),
  previewToken: () => post('/website/config/preview-token'),
  content: (section?: string) => get('/website/content', { section }),
  createContent: (b: Any) => post('/website/content', b),
  updateContent: (id: string, b: Any) => put(`/website/content/${id}`, b),
  deleteContent: (id: string) => del(`/website/content/${id}`),
  publishContent: (id: string, on: boolean) => post(`/website/content/${id}/${on ? 'publish' : 'unpublish'}`),
  notices: (p: Params = {}) => get('/website/notices', p),
  createNotice: (b: Any) => post('/website/notices', b),
  updateNotice: (id: string, b: Any) => put(`/website/notices/${id}`, b),
  bulkNotices: (ids: string[], action: string) => post('/website/notices/bulk', { ids, action }),
  announce: (id: string) => post(`/website/notices/${id}/announce`),
  events: () => get('/website/events'),
  createEvent: (b: Any) => post('/website/events', b),
  mirror: (event_ids: string[]) => post('/website/events/mirror', { event_ids, publish: true }),
  deleteEvent: (id: string) => del(`/website/events/${id}`),
  albums: () => get('/website/gallery/albums'),
  createAlbum: (b: Any) => post('/website/gallery/albums', b),
  addImage: (id: string, b: Any) => post(`/website/gallery/albums/${id}/images`, b),
  bulkUpload: (id: string, zip_url: string) => post(`/website/gallery/albums/${id}/bulk-upload`, { zip_url }),
  deleteAlbum: (id: string) => del(`/website/gallery/albums/${id}`),
  enquiries: (p: Params = {}) => get('/website/enquiries', p),
  enquiryStatus: (id: string, status: string) => put(`/website/enquiries/${id}/status`, { status }),
  linkCrm: (id: string) => post(`/website/enquiries/${id}/link-crm`),
  exportEnquiries: () => post('/website/enquiries/export'),
  catalogue: () => get('/website/catalogue/settings'),
  saveCatalogue: (b: Any) => put('/website/catalogue/settings', b),
  cataloguePreview: () => get('/website/catalogue/preview'),
  disclosures: () => get('/website/disclosures'),
  saveDisclosures: (b: Any) => put('/website/disclosures', b),
  directory: () => get('/website/faculty-directory/settings'),
  saveDirectory: (b: Any) => put('/website/faculty-directory/settings', b),
  domains: () => get('/website/domains'),
  addDomain: (hostname: string, make_primary: boolean) => post('/website/domains', { hostname, make_primary }),
  verifyDomain: (id: string) => post(`/website/domains/${id}/verify`),
  primaryDomain: (id: string) => post(`/website/domains/${id}/make-primary`),
  deleteDomain: (id: string) => del(`/website/domains/${id}`),
  analytics: (p: Params = {}) => get('/website/analytics', p),
  marketing: () => get('/platform/marketing'),
  saveMarketing: (b: Any) => put('/platform/marketing', b),
  publishMarketing: () => post('/platform/marketing/publish'),
};
