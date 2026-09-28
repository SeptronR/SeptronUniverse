import type { AxiosRequestConfig } from 'axios';
import { api } from '@/api/axios';
import type { Envelope } from '@/utils/types';
import type { Delegation, InboxItem, StepSpec, WorkflowDefinition, WorkflowInstance } from './types';

const get = <T>(url: string, config?: AxiosRequestConfig) => api.get(url, config) as unknown as Promise<Envelope<T>>;
const post = <T>(url: string, body?: unknown) =>
  api.post(url, body, { idempotent: false }) as unknown as Promise<Envelope<T>>;
const put = <T>(url: string, body?: unknown) => api.put(url, body) as unknown as Promise<Envelope<T>>;
const del = <T>(url: string) => api.delete(url) as unknown as Promise<Envelope<T>>;

/** Workflow engine API (Prompts/04 §04.8). */
export const workflowApi = {
  definitions: (module?: string) => get<WorkflowDefinition[]>('/workflow/definitions', { params: { module } }),
  saveDefinition: (id: string, body: { name?: string; description?: string; steps?: StepSpec[]; is_active?: boolean }) =>
    put<WorkflowDefinition>(`/workflow/definitions/${id}`, body),
  versions: (id: string) => get<WorkflowDefinition[]>(`/workflow/definitions/${id}/versions`),
  inbox: () => get<InboxItem[]>('/workflow/inbox'),
  instances: (params: Record<string, string | number | boolean | undefined> = {}) =>
    get<WorkflowInstance[]>('/workflow/instances', { params }),
  instance: (id: string) => get<WorkflowInstance>(`/workflow/instances/${id}`),
  act: (id: string, body: { decision: 'approve' | 'reject' | 'delegate'; comment?: string; delegate_to?: string }) =>
    post<WorkflowInstance>(`/workflow/instances/${id}/act`, body),
  cancel: (id: string, reason?: string) => post<WorkflowInstance>(`/workflow/instances/${id}/cancel`, { reason }),
  delegations: () => get<Delegation[]>('/workflow/delegations'),
  delegate: (body: { to_user_id: string; module?: string | null; from_on: string; to_on: string }) =>
    post<Delegation>('/workflow/delegations', body),
  revokeDelegation: (id: string) => del<null>(`/workflow/delegations/${id}`),
};
