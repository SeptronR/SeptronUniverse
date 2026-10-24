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
const post = <T = Any>(url: string, body?: unknown, config: AxiosRequestConfig = once) => api.post(url, body, config) as unknown as Promise<Envelope<T>>;
const put = <T = Any>(url: string, body?: unknown) => api.put(url, body) as unknown as Promise<Envelope<T>>;
const del = <T = Any>(url: string) => api.delete(url) as unknown as Promise<Envelope<T>>;
const blob = (url: string) => api.get(url, { responseType: 'blob' }) as unknown as Promise<Blob>;

/** Hostel, mess & staff accommodation (Prompts/20 §20.8). */
export const hostelApi = {
  colleges: () => get('/colleges', { params: { page_size: 100 } }),
  years: () => get('/academic-years'),
  // structure
  hostels: (p: Params = {}) => get('/hostels', { params: p }),
  createHostel: (b: Body) => post('/hostels', b),
  updateHostel: (id: string, b: Body) => put(`/hostels/${id}`, b),
  occupancy: (id: string) => get(`/hostels/${id}/occupancy`),
  blocks: (id: string) => get(`/hostels/${id}/blocks`),
  addBlock: (id: string, b: Body) => post(`/hostels/${id}/blocks`, b),
  bulkRooms: (id: string, b: Body) => post(`/hostels/${id}/rooms/bulk`, b),
  bedStatus: (id: string, status: string) => put(`/hostel-beds/${id}/status`, { status }),
  feePlans: (p: Params = {}) => get('/hostel-fee-plans', { params: p }),
  saveFeePlan: (b: Body) => post('/hostel-fee-plans', b),
  rulesPdf: (id: string) => blob(`/hostels/${id}/rules.pdf`),
  myRules: () => get('/hostels/me/rules'),
  // applications / allocations
  apply: (b: Body) => post('/hostel-applications', b, idem),
  myApplications: () => get('/hostel-applications/me'),
  cancelApplication: (id: string) => del(`/hostel-applications/${id}`),
  applications: (p: Params = {}) => get('/hostel-applications', { params: p }),
  allot: (b: Body) => post('/hostel-applications/allot', b),
  allotManual: (id: string, bed_id: string) => post(`/hostel-applications/${id}/allot-manual`, { bed_id }),
  decline: (id: string) => post(`/hostel-applications/${id}/decline`),
  allocations: (p: Params = {}) => get('/hostel-allocations', { params: p }),
  myAllocations: () => get('/hostel-allocations/me'),
  wardAllocations: () => get('/hostel-allocations/wards'),
  vacateRequest: () => post('/hostel-allocations/me/vacate-request'),
  checkIn: (id: string, b: Body) => post(`/hostel-allocations/${id}/check-in`, b),
  transfer: (id: string, b: Body) => post(`/hostel-allocations/${id}/transfer`, b),
  vacate: (id: string, b: Body) => post(`/hostel-allocations/${id}/vacate`, b),
  evict: (id: string, b: Body) => post(`/hostel-allocations/${id}/evict`, b),
  roomChanges: (p: Params = {}) => get('/room-change-requests', { params: p }),
  requestRoomChange: (b: Body) => post('/room-change-requests', b),
  decideRoomChange: (id: string, b: Body) => post(`/room-change-requests/${id}/decide`, b),
  // roll call
  rollCalls: (p: Params = {}) => get('/hostel-roll-calls', { params: p }),
  startRollCall: (b: Body) => post('/hostel-roll-calls', b),
  markRollCall: (id: string, entries: Body[]) => put(`/hostel-roll-calls/${id}/entries`, { entries }),
  // mess
  messPlans: (p: Params = {}) => get('/mess-plans', { params: p }),
  saveMessPlan: (b: Body, id?: string) => (id ? put(`/mess-plans/${id}`, b) : post('/mess-plans', b)),
  subscriptions: (p: Params = {}) => get('/mess-subscriptions', { params: p }),
  subscribe: (b: Body) => post('/mess-subscriptions', b),
  markMeal: (b: Body) => post('/mess-attendance', b),
  rebates: (p: Params = {}) => get('/mess-rebates', { params: p }),
  requestRebate: (b: Body) => post('/mess-rebates', b),
  decideRebate: (id: string, approve: boolean) => post(`/mess-rebates/${id}/decide`, { approve }),
  billRun: (b: Body) => post('/mess-bills/run', b),
  bills: (p: Params = {}) => get('/mess-bills', { params: p }),
  myBills: () => get('/mess-bills/me'),
  billPdf: (id: string) => blob(`/mess-bills/${id}.pdf`),
  // visitors
  visitors: (p: Params = {}) => get('/hostel-visitors', { params: p }),
  logVisitor: (b: Body) => post('/hostel-visitors', b),
  visitorOut: (id: string) => post(`/hostel-visitors/${id}/out`),
  // leaves & gate
  requestLeave: (b: Body) => post('/hostel-leaves', b, idem),
  myLeaves: () => get('/hostel-leaves/me'),
  wardLeaves: () => get('/hostel-leaves/wards'),
  leaves: (p: Params = {}) => get('/hostel-leaves', { params: p }),
  cancelLeave: (id: string) => del(`/hostel-leaves/${id}`),
  sendOtp: (id: string) => post(`/hostel-leaves/${id}/consent/send-otp`),
  verifyOtp: (id: string, otp: string) => post(`/hostel-leaves/${id}/consent/verify`, { otp }),
  parentApprove: (id: string) => post(`/hostel-leaves/${id}/consent/parent-approve`),
  decideLeave: (id: string, action: 'approve' | 'reject', remarks?: string) => post(`/hostel-leaves/${id}/decide`, { action, remarks }),
  markReturned: (id: string, remarks: string) => post(`/hostel-leaves/${id}/mark-returned`, { remarks }),
  gateScan: (qr_token: string, direction: 'out' | 'in') => post('/hostel-gate/scan', { qr_token, direction }),
  lateList: (p: Params = {}) => get('/hostel-gate/late-list', { params: p }),
  outNow: (p: Params = {}) => get('/hostel-gate/out-now', { params: p }),
  // complaints / discipline / quarters / reports
  complaints: (p: Params = {}) => get('/hostel-complaints', { params: p }),
  raiseComplaint: (b: Body) => post('/hostel-complaints', b),
  updateComplaint: (id: string, status: string) => put(`/hostel-complaints/${id}`, { status }),
  discipline: () => get('/hostel-discipline'),
  myDiscipline: () => get('/hostel-discipline/me'),
  recordDiscipline: (b: Body) => post('/hostel-discipline', b),
  quarters: () => get('/staff-quarters'),
  saveQuarter: (b: Body) => post('/staff-quarters', b),
  allocateQuarter: (id: string, b: Body) => post(`/staff-quarters/${id}/allocate`, b),
  vacateQuarter: (allocId: string) => post(`/staff-quarter-allocations/${allocId}/vacate`, {}),
  myQuarter: () => get('/staff-quarters/me'),
  report: (kind: string, hostel_id?: string) => get(`/hostels/reports/${kind}`, { params: { hostel_id } }),
};
