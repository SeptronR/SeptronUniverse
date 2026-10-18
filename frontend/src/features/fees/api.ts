import type { AxiosRequestConfig } from 'axios';
import { api } from '@/api/axios';
import type { Envelope } from '@/utils/types';
import type {
  DayBook,
  Discount,
  DiscountAssignment,
  Dues,
  FeeDashboard,
  FeeHead,
  FeeReport,
  FeeStructure,
  FineConfig,
  Invoice,
  NoDues,
  OnlineOrder,
  OrderStatus,
  Payment,
  Receipt,
  ReconcileRow,
  Refund,
  Scholarship,
  ScholarshipApplication,
  UpiQr,
} from './types';

type Params = Record<string, string | number | boolean | undefined | null>;
type Body = Record<string, unknown>;
const get = <T>(url: string, config?: AxiosRequestConfig) => api.get(url, config) as unknown as Promise<Envelope<T>>;
const once = { idempotent: false } as AxiosRequestConfig;
const post = <T>(url: string, body?: unknown, config: AxiosRequestConfig = once) =>
  api.post(url, body, config) as unknown as Promise<Envelope<T>>;
const put = <T>(url: string, body?: unknown) => api.put(url, body) as unknown as Promise<Envelope<T>>;
const del = <T>(url: string) => api.delete(url) as unknown as Promise<Envelope<T>>;
const blob = (url: string, params?: Params) => api.get(url, { params, responseType: 'blob' }) as unknown as Promise<Blob>;

/** Heads, structures, discounts, fines, invoices, collection, online / UPI, reconciliation, day-book, refunds,
 * reports (Prompts/12 §12.8). */
export const feesApi = {
  dashboard: () => get<FeeDashboard>('/fees/dashboard'),
  heads: () => get<FeeHead[]>('/fee-heads'),
  saveHead: (b: Body, id?: string) => (id ? put<FeeHead>(`/fee-heads/${id}`, b) : post<FeeHead>('/fee-heads', b)),
  deleteHead: (id: string) => del<null>(`/fee-heads/${id}`),
  structures: (p: Params = {}) => get<FeeStructure[]>('/fee-structures', { params: p }),
  structure: (id: string) => get<FeeStructure>(`/fee-structures/${id}`),
  createStructure: (b: Body) => post<FeeStructure>('/fee-structures', b),
  updateStructure: (id: string, b: Body) => put<FeeStructure>(`/fee-structures/${id}`, b),
  cloneStructure: (id: string, b: Body) => post<FeeStructure>(`/fee-structures/${id}/clone`, b),
  applicable: (p: Params) => get<{ structure: FeeStructure | null; matched_on: string[]; candidates: number }>('/fee-structures/applicable', { params: p }),
  assign: (id: string, b: Body) => post<Record<string, unknown>>(`/fee-structures/${id}/assign`, b),
  bulkInvoice: (b: Body) => post<Record<string, unknown>>('/fees/bulk-invoice', b),
  discounts: () => get<Discount[]>('/fee-discounts'),
  saveDiscount: (b: Body, id?: string) => (id ? put<Discount>(`/fee-discounts/${id}`, b) : post<Discount>('/fee-discounts', b)),
  assignDiscount: (id: string, b: Body) => post<DiscountAssignment>(`/fee-discounts/${id}/assign`, b),
  pendingDiscounts: () => get<DiscountAssignment[]>('/fee-discounts/assignments/pending'),
  decideDiscount: (id: string, decision: 'approve' | 'reject') => post<DiscountAssignment>(`/fee-discounts/assignments/${id}/${decision}`),
  fines: () => get<FineConfig[]>('/fine-configurations'),
  saveFines: (rows: FineConfig[]) => put<FineConfig[]>('/fine-configurations', rows),
  invoices: (p: Params = {}) => get<Invoice[]>('/fees/invoices', { params: p }),
  invoice: (id: string) => get<Invoice>(`/fees/invoices/${id}`),
  cancelInvoice: (id: string, reason: string) => post<Invoice>(`/fees/invoices/${id}/cancel`, { reason }),
  myDues: () => get<Dues>('/fees/me/dues'),
  myReceipts: () => get<Payment[]>('/fees/me/receipts'),
  wardDues: (studentId: string) => get<Dues>(`/fees/wards/${studentId}/dues`),
  enrolmentDues: (enrollmentId: string) => get<Dues>(`/fees/students/${enrollmentId}/dues`),
  /** Counter collection carries an Idempotency-Key (axios interceptor default). */
  collect: (b: Body) => api.post('/fees/collect', b) as unknown as Promise<Envelope<Receipt>>,
  payments: (p: Params = {}) => get<Payment[]>('/fees/payments', { params: p }),
  receiptPdf: (id: string) => blob(`/fees/payments/${id}/receipt.pdf`),
  thermal: (id: string) => get<{ receipt_number: string; text: string; commands: unknown[] }>(`/fees/payments/${id}/thermal`),
  cancelRequest: (id: string, reason: string) => post<Payment>(`/fees/payments/${id}/cancel-request`, { reason }),
  cancelQueue: () => get<Payment[]>('/fees/payments/cancel-requests'),
  decideCancel: (id: string, decision: 'approve' | 'reject', comment?: string) =>
    post<Payment>(`/fees/payments/${id}/cancel-request/${decision}`, { comment: comment ?? null }),
  bounce: (id: string, b: Body) => post<Payment>(`/fees/payments/${id}/bounce`, b),
  initiate: (b: Body) => post<OnlineOrder>('/fees/online/initiate', b),
  verify: (b: Body) => post<OrderStatus>('/fees/online/verify', b),
  orderStatus: (orderId: string) => get<OrderStatus>(`/fees/online/${orderId}/status`),
  devSign: (b: Body) => post<{ signature?: string }>('/_dev/fees/sign', b),
  upiQr: (b: Body) => post<UpiQr>('/fees/upi-qr', b),
  upiStatus: (ref: string) => get<OrderStatus>(`/fees/upi-qr/${ref}/status`),
  devUpiCallback: (ref: string) => post<OrderStatus>(`/_dev/fees/upi/${ref}/callback`),
  declare: (b: Body) => post<Payment>('/fees/offline/declare', b),
  reconcileUpload: (file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return api.post('/fees/reconcile/upload', fd, once) as unknown as Promise<Envelope<{ job_id: string; rows: number }>>;
  },
  reconcile: (p: Params = {}) => get<ReconcileRow[]>('/fees/reconcile', { params: p }),
  match: (id: string, b: Body) => post<ReconcileRow>(`/fees/reconcile/${id}/match`, b),
  ignore: (id: string) => post<ReconcileRow>(`/fees/reconcile/${id}/ignore`),
  dayBook: (p: Params = {}) => get<DayBook>('/fees/day-book', { params: p }),
  closeDay: (b: Body) => post<DayBook>('/fees/day-book/close', b),
  dayBookCsv: (p: Params) => blob('/fees/day-book/export', p),
  refunds: (p: Params = {}) => get<Refund[]>('/fees/refunds', { params: p }),
  myRefunds: () => get<Refund[]>('/fees/refunds/me'),
  requestRefund: (b: Body) => post<Refund>('/fees/refunds', b),
  decideRefund: (id: string, decision: 'approve' | 'reject', comment?: string) =>
    post<Refund>(`/fees/refunds/${id}/${decision}`, { comment: comment ?? null }),
  processRefund: (id: string, b: Body) => post<Refund>(`/fees/refunds/${id}/process`, b),
  report: (name: string, p: Params = {}) => get<FeeReport>(`/fees/reports/${name}`, { params: p }),
  reportExport: (name: string, p: Params = {}) => get<{ job_id: string }>(`/fees/reports/${name}`, { params: { ...p, format: 'csv' } }),
  accountingExport: (b: Body) => post<{ job_id: string }>('/fees/accounting-export', b),
};

export const scholarshipsApi = {
  schemes: (active = false) => get<Scholarship[]>('/scholarships', { params: { active } }),
  saveScheme: (b: Body, id?: string) => (id ? put<Scholarship>(`/scholarships/${id}`, b) : post<Scholarship>('/scholarships', b)),
  apply: (id: string, b: Body) => post<ScholarshipApplication>(`/scholarships/${id}/apply`, b),
  applications: (p: Params = {}) => get<ScholarshipApplication[]>('/scholarship-applications', { params: p }),
  mine: () => get<ScholarshipApplication[]>('/scholarship-applications/me'),
  act: (id: string, action: 'verify' | 'recommend' | 'sanction' | 'reject', b: Body = {}) =>
    post<ScholarshipApplication>(`/scholarship-applications/${id}/${action}`, b),
  disburse: (id: string, b: Body) => post<ScholarshipApplication>(`/scholarship-applications/${id}/disburse`, b),
};

export const noDuesApi = {
  create: (b: Body) => post<NoDues>('/no-dues', b),
  list: (p: Params = {}) => get<NoDues[]>('/no-dues', { params: p }),
  mine: () => get<NoDues[]>('/no-dues/me'),
  signoff: (id: string, b: Body) => post<NoDues>(`/no-dues/${id}/signoff`, b),
  certificate: (id: string) => blob(`/no-dues/${id}/certificate.pdf`),
};

/** Open a blob (PDF / CSV) in a new tab, or download it. */
export function openBlob(b: Blob, filename?: string) {
  const url = URL.createObjectURL(b);
  if (filename) {
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
  } else window.open(url, '_blank', 'noopener');
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
