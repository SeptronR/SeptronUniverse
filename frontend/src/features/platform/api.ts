import type { AxiosRequestConfig } from 'axios';
import { api } from '@/api/axios';
import type { Envelope } from '@/utils/types';
import type {
  FeedbackCreate,
  FeedbackResponse,
  HelpArticle,
  HelpArticleSummary,
  Job,
  JobListParams,
  PublicConfig,
  ReadOnlyModeRequest,
  ReadOnlyState,
  SearchResponse,
} from './types';

// The axios response interceptor unwraps to the envelope, so the resolved value is `Envelope<T>` (not AxiosResponse).
const get = <T>(url: string, config?: AxiosRequestConfig) => api.get(url, config) as unknown as Promise<Envelope<T>>;
const post = <T>(url: string, body?: unknown, config?: AxiosRequestConfig) =>
  api.post(url, body, config) as unknown as Promise<Envelope<T>>;

/**
 * Platform API (Prompts/01 §01.8) — the only place these routes are called from (frontend coding standard 1).
 */
export const platformApi = {
  publicConfig: (institution?: string) =>
    get<PublicConfig>('/public/config', { params: institution ? { institution } : undefined }),
  readOnly: () => get<ReadOnlyState>('/platform/read-only'),
  setReadOnly: (body: ReadOnlyModeRequest) => post<ReadOnlyState>('/platform/read-only', body, { idempotent: false }),

  listJobs: (params: JobListParams = {}) => get<Job[]>('/jobs', { params }),
  getJob: (id: string) => get<Job>(`/jobs/${id}`),
  cancelJob: (id: string) => post<Job>(`/jobs/${id}/cancel`, undefined, { idempotent: false }),
  /** Dev-only route (APP_ENV=development) used by the UI checklist to watch the tray update live. */
  devSleepJob: (seconds = 5, inline = false) =>
    post<Job>('/_dev/jobs/sleep', undefined, { params: { seconds, inline: inline || undefined }, idempotent: false }),

  search: (q: string, types?: string[]) =>
    get<SearchResponse>('/search', { params: { q, types: types?.join(',') || undefined } }),

  listHelp: (params: { module?: string; q?: string } = {}) => get<HelpArticleSummary[]>('/help/articles', { params }),
  getHelp: (slug: string) => get<HelpArticle>(`/help/articles/${slug}`),

  submitFeedback: (body: FeedbackCreate) => post<FeedbackResponse>('/feedback', body),
};
