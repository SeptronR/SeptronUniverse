import type { AxiosRequestConfig } from 'axios';
import { api } from '@/api/axios';
import type { Envelope } from '@/utils/types';

type Params = Record<string, string | number | boolean | undefined | null>;
type Body = Record<string, unknown>;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const get = <T = Any>(url: string, config?: AxiosRequestConfig) => api.get(url, config) as unknown as Promise<Envelope<T>>;
const once = { idempotent: false } as AxiosRequestConfig;
const post = <T = Any>(url: string, body?: unknown) => api.post(url, body ?? {}, once) as unknown as Promise<Envelope<T>>;
const put = <T = Any>(url: string, body?: unknown) => api.put(url, body) as unknown as Promise<Envelope<T>>;
const blob = (url: string, params?: Params) => api.get(url, { responseType: 'blob', params }) as unknown as Promise<Blob>;

/** Accounting & budget (Prompts/23 §23.8). */
export const accountingApi = {
  years: () => get('/academic-years'),
  departments: () => get('/departments', { params: { page_size: 200 } }),
  // chart
  tree: (p: Params = {}) => get('/accounting/accounts/tree', { params: p }),
  accounts: () => get('/accounting/accounts'),
  saveAccount: (b: Body, id?: string) => (id ? put(`/accounting/accounts/${id}`, b) : post('/accounting/accounts', b)),
  importChart: (b: Body) => post('/accounting/accounts/import', b),
  mappings: () => get('/accounting/mappings'),
  saveMappings: (mappings: Body) => put('/accounting/mappings', { mappings }),
  ledger: (id: string, p: Params = {}) => get(`/accounting/ledger/${id}`, { params: p }),
  trialBalance: (p: Params) => get('/accounting/trial-balance', { params: p }),
  // records
  income: (p: Params = {}) => get('/accounting/income', { params: p }),
  addIncome: (b: Body) => post('/accounting/income', b),
  reverseIncome: (id: string, reason: string) => post(`/accounting/income/${id}/reverse`, { reason }),
  expenses: (p: Params = {}) => get('/accounting/expenses', { params: p }),
  addExpense: (b: Body) => post('/accounting/expenses', b),
  submitExpense: (id: string) => post(`/accounting/expenses/${id}/submit`),
  decideExpense: (id: string, b: Body) => post(`/accounting/expenses/${id}/decide`, b),
  payExpense: (id: string, b: Body) => post(`/accounting/expenses/${id}/pay`, b),
  replay: (p: Params) => api.post('/accounting/postings/replay', {}, { params: p, ...once }) as unknown as Promise<Envelope<Any>>,
  gaps: () => get('/accounting/postings/gaps'),
  // budgets
  budgets: (p: Params = {}) => get('/accounting/budgets', { params: p }),
  myBudgets: () => get('/accounting/budgets/me'),
  utilisation: (p: Params = {}) => get('/accounting/budgets/utilisation', { params: p }),
  addBudget: (b: Body) => post('/accounting/budgets', b),
  bulkBudgets: (b: Body) => post('/accounting/budgets/bulk', b),
  submitAll: (year?: string) => api.post('/accounting/budgets/submit', {}, { params: { year }, ...once }) as unknown as Promise<Envelope<Any>>,
  budgetAction: (id: string, action: 'submit' | 'approve' | 'freeze') => post(`/accounting/budgets/${id}/${action}`),
  revise: (id: string, b: Body) => post(`/accounting/budgets/${id}/revise`, b),
  transfer: (b: Body) => post('/accounting/budgets/transfer', b),
  // grants
  grants: () => get('/accounting/grants'),
  grant: (id: string) => get(`/accounting/grants/${id}`),
  addGrant: (b: Body) => post('/accounting/grants', b),
  grantReceipt: (id: string, b: Body) => post(`/accounting/grants/${id}/receipts`, b),
  grantExpense: (id: string, b: Body) => post(`/accounting/grants/${id}/expenses`, b),
  reallocate: (id: string, b: Body) => post(`/accounting/grants/${id}/reallocate`, b),
  closeGrant: (id: string, remark?: string) => post(`/accounting/grants/${id}/close`, { remark }),
  uc: (id: string, p: Params = {}) => blob(`/accounting/grants/${id}/uc.pdf`, p),
  soe: (id: string, p: Params = {}) => get(`/accounting/grants/${id}/soe`, { params: p }),
  // reconciliation
  recons: () => get('/accounting/reconciliations'),
  recon: (id: string) => get(`/accounting/reconciliations/${id}`),
  openRecon: (b: Body) => post('/accounting/reconciliations', b),
  importRecon: (id: string, csv: string) => post(`/accounting/reconciliations/${id}/import`, { csv }),
  matchRecon: (id: string, b: Body) => post(`/accounting/reconciliations/${id}/match`, b),
  unmatchRecon: (id: string, item_id: string) => post(`/accounting/reconciliations/${id}/unmatch`, { item_id }),
  addReconRecord: (id: string, b: Body) => post(`/accounting/reconciliations/${id}/add-record`, b),
  closeRecon: (id: string) => post(`/accounting/reconciliations/${id}/close`),
  // GST / exports / statements / periods
  gst: (period: string) => get('/accounting/gst/summary', { params: { period } }),
  gstExport: (period: string) => get('/accounting/gst/export', { params: { period } }),
  exports: () => get('/accounting/exports'),
  createExport: (b: Body) => post('/accounting/exports', b),
  statement: (kind: string, p: Params) => get(`/accounting/statements/${kind}`, { params: p }),
  statementFile: (kind: string, p: Params) => blob(`/accounting/statements/${kind}`, p),
  closePeriod: (upto_date: string) => post('/accounting/periods/close', { upto_date }),
  closeYear: (b: Body) => post('/accounting/years/close', b),
  dashboard: () => get('/accounting/dashboard'),
};
