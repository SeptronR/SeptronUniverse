import type { AxiosRequestConfig } from 'axios';
import { api } from '@/api/axios';
import type { Envelope } from '@/utils/types';

type Params = Record<string, string | number | boolean | undefined | null>;
type Body = Record<string, unknown>;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const get = <T = Any>(url: string, config?: AxiosRequestConfig) => api.get(url, config) as unknown as Promise<Envelope<T>>;
const once = { idempotent: false } as AxiosRequestConfig;
const idem = { idempotent: true } as AxiosRequestConfig;
const post = <T = Any>(url: string, body?: unknown, config: AxiosRequestConfig = once) => api.post(url, body ?? {}, config) as unknown as Promise<Envelope<T>>;
const put = <T = Any>(url: string, body?: unknown) => api.put(url, body) as unknown as Promise<Envelope<T>>;
const blob = (url: string) => api.get(url, { responseType: 'blob' }) as unknown as Promise<Blob>;

/** Inventory, procurement & bills (Prompts/22 §22.8). */
export const inventoryApi = {
  departments: () => get('/departments', { params: { page_size: 200 } }),
  // masters
  suppliers: (p: Params = {}) => get('/inventory/suppliers', { params: p }),
  saveSupplier: (b: Body, id?: string) => (id ? put(`/inventory/suppliers/${id}`, b) : post('/inventory/suppliers', b)),
  verifySupplier: (id: string) => post(`/inventory/suppliers/${id}/verify`),
  blacklist: (id: string, reason: string) => post(`/inventory/suppliers/${id}/blacklist`, { reason }),
  statement: (id: string) => get(`/inventory/suppliers/${id}/statement`),
  stores: () => get('/inventory/stores'),
  saveStore: (b: Body, id?: string) => (id ? put(`/inventory/stores/${id}`, b) : post('/inventory/stores', b)),
  stock: (id: string, below_min?: boolean) => get(`/inventory/stores/${id}/stock`, { params: { below_min } }),
  categories: () => get('/inventory/categories'),
  addCategory: (b: Body) => post('/inventory/categories', b),
  items: (p: Params = {}) => get('/inventory/items', { params: p }),
  saveItem: (b: Body, id?: string) => (id ? put(`/inventory/items/${id}`, b) : post('/inventory/items', b)),
  importItems: (csv: string) => post('/inventory/items/import', { csv }),
  ledger: (id: string, store_id?: string) => get(`/inventory/items/${id}/ledger`, { params: { store_id } }),
  // stock
  move: (kind: 'issue' | 'return' | 'transfer' | 'adjust' | 'write-off', b: Body) => post(`/inventory/stock/${kind}`, b, idem),
  transactions: (p: Params = {}) => get('/inventory/stock/transactions', { params: p }),
  hazardous: () => get('/inventory/stock/hazardous-register'),
  // indents
  indents: (p: Params = {}) => get('/inventory/indents', { params: p }),
  myIndents: () => get('/inventory/indents/me'),
  createIndent: (b: Body) => post('/inventory/indents', b),
  updateIndent: (id: string, b: Body) => put(`/inventory/indents/${id}`, b),
  submitIndent: (id: string) => post(`/inventory/indents/${id}/submit`),
  fulfil: (id: string, b: Body) => post(`/inventory/indents/${id}/fulfil`, b),
  closeIndent: (id: string) => post(`/inventory/indents/${id}/close`),
  quotations: (id: string) => get(`/inventory/indents/${id}/quotations`),
  addQuotation: (id: string, b: Body) => post(`/inventory/indents/${id}/quotations`, b),
  comparative: (id: string) => get(`/inventory/indents/${id}/comparative-statement`),
  selectQuotation: (id: string) => post(`/inventory/quotations/${id}/select`),
  // POs / GRN
  pos: (p: Params = {}) => get('/inventory/purchase-orders', { params: p }),
  po: (id: string) => get(`/inventory/purchase-orders/${id}`),
  createPo: (b: Body) => post('/inventory/purchase-orders', b),
  poAction: (id: string, action: string, b: Body = {}) => post(`/inventory/purchase-orders/${id}/${action}`, b),
  poPdf: (id: string) => blob(`/inventory/purchase-orders/${id}.pdf`),
  grns: (p: Params = {}) => get('/inventory/goods-receipts', { params: p }),
  receive: (b: Body) => post('/inventory/goods-receipts', b),
  grnPdf: (id: string) => blob(`/inventory/goods-receipts/${id}.pdf`),
  // assets
  assets: (p: Params = {}) => get('/inventory/assets', { params: p }),
  myAssets: () => get('/inventory/assets/me'),
  asset: (id: string) => get(`/inventory/assets/${id}`),
  assetHistory: (id: string) => get(`/inventory/assets/${id}/history`),
  createAsset: (b: Body) => post('/inventory/assets', b),
  assetsFromGrn: (b: Body) => post('/inventory/assets/from-grn', b),
  transferAsset: (id: string, b: Body) => post(`/inventory/assets/${id}/transfer`, b),
  acceptCustody: (id: string) => post(`/inventory/assets/${id}/accept-custody`),
  assetStatus: (id: string, b: Body) => post(`/inventory/assets/${id}/status`, b),
  qrLabels: (b: Body) => post('/inventory/assets/qr-labels', b),
  lookup: (token: string) => get(`/inventory/assets/lookup/${token}`),
  depreciationPreview: (fy: string) => post('/inventory/assets/depreciation/run', { financial_year: fy, preview: true }),
  depreciationRun: (fy: string) => post('/inventory/assets/depreciation/run', { financial_year: fy }),
  depreciation: (fy: string) => get('/inventory/assets/depreciation', { params: { fy } }),
  audits: () => get('/inventory/asset-audits'),
  startAudit: (b: Body) => post('/inventory/asset-audits', b),
  scan: (id: string, scans: Body[]) => post(`/inventory/asset-audits/${id}/scan`, { scans }, idem),
  completeAudit: (id: string) => post(`/inventory/asset-audits/${id}/complete`),
  auditReport: (id: string) => get(`/inventory/asset-audits/${id}/report`),
  // bills
  bills: (p: Params = {}) => get('/inventory/vendor-bills', { params: p }),
  createBill: (b: Body) => post('/inventory/vendor-bills', b),
  verifyBill: (id: string) => post(`/inventory/vendor-bills/${id}/verify`),
  decideBill: (id: string, b: Body) => post(`/inventory/vendor-bills/${id}/decide`, b),
  payBill: (id: string, b: Body) => post(`/inventory/vendor-bills/${id}/pay`, b),
  ageing: () => get('/inventory/vendor-bills/ageing'),
  // vendor store
  sales: (date?: string) => get('/inventory/vendor-store/sales', { params: { date } }),
  sell: (b: Body) => post('/inventory/vendor-store/sales', b),
  salesReport: (date?: string) => get('/inventory/vendor-store/report', { params: { date } }),
  // reports
  report: (kind: string) => get(`/inventory/reports/${kind}`),
  exportReport: (kind: string) => get(`/inventory/reports/${kind}`, { params: { format: 'xlsx' } }),
  // vendor portal
  vendorRegister: (b: Body) => post('/vendor/register', b),
  vendorMe: () => get('/vendor/me'),
  vendorUpdate: (b: Body) => put('/vendor/me', b),
  rfqs: () => get('/vendor/rfqs'),
  vendorQuote: (indentId: string, b: Body) => post(`/vendor/rfqs/${indentId}/quotations`, b),
  vendorPos: () => get('/vendor/pos'),
  acknowledge: (id: string) => post(`/vendor/pos/${id}/acknowledge`),
  vendorGrns: () => get('/vendor/grns'),
  vendorBills: () => get('/vendor/bills'),
};
