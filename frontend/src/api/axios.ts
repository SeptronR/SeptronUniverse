import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios';
import { useAuthStore } from '@/store/authStore';
import { useSessionStore } from '@/store/sessionStore';
import type { ApiErrorBody } from '@/utils/types';

/**
 * Axios instance — Prompts/00 §4.2. Callers receive the unwrapped envelope `{ success, data, message, meta }`.
 *  - tenant headers X-Institution-Id / X-College-Id from the session store
 *  - Idempotency-Key on every mutation unless `idempotent: false`
 *  - single-flight refresh on 401, IDEMPOTENT_REPLAY → stored response, READ_ONLY → session banner
 */
declare module 'axios' {
  export interface AxiosRequestConfig {
    idempotent?: boolean;
    _retry?: boolean;
  }
}

export const api = axios.create({ baseURL: import.meta.env.VITE_API_URL || '/api/v1', withCredentials: true });

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const { accessToken, currentUser } = useAuthStore.getState();
  const { institutionId, collegeId } = useSessionStore.getState();
  if (accessToken) config.headers.Authorization = `Bearer ${accessToken}`;
  const inst = institutionId || currentUser?.institution_id;
  if (inst) config.headers['X-Institution-Id'] = inst;
  if (collegeId) config.headers['X-College-Id'] = collegeId;
  if (
    ['post', 'put', 'patch', 'delete'].includes(config.method ?? '') &&
    config.idempotent !== false &&
    !config.headers['Idempotency-Key']
  ) {
    config.headers['Idempotency-Key'] = crypto.randomUUID();
  }
  return config;
});

let refreshing: Promise<string> | null = null;

api.interceptors.response.use(
  (res) => res.data, // unwrap envelope: callers receive { success, data, message, meta }
  async (err: AxiosError<ApiErrorBody>) => {
    const original = err.config;
    if (original && err.response?.status === 401 && !original._retry && !original.url?.includes('/auth/')) {
      original._retry = true;
      refreshing ??= api
        .post('/auth/refresh', undefined, { idempotent: false })
        .then((r: any) => {
          useAuthStore.getState().setAccessToken(r.data.access_token);
          return r.data.access_token as string;
        })
        .finally(() => {
          refreshing = null;
        });
      const token = await refreshing.catch(() => {
        useAuthStore.getState().logout();
        window.location.href = '/login';
        throw err;
      });
      original.headers.Authorization = `Bearer ${token}`;
      return api(original);
    }
    const body = err.response?.data;
    if (body?.error?.code === 'IDEMPOTENT_REPLAY') return (body.error.details as any).response;
    if (body?.error?.code === 'READ_ONLY') useSessionStore.getState().setReadOnly(true);
    return Promise.reject(err);
  },
);

export const getApiError = (e: any, fallback = 'Something went wrong'): string =>
  e?.response?.data?.error?.message ?? fallback;
export const getApiErrorCode = (e: any): string | undefined => e?.response?.data?.error?.code as string | undefined;
export const getApiErrorDetails = (e: any): Record<string, unknown> => e?.response?.data?.error?.details ?? {};
