import type { AxiosRequestConfig } from 'axios';
import { api } from '@/api/axios';
import type { Envelope } from '@/utils/types';

type Params = Record<string, string | number | boolean | undefined | null>;
type Body = Record<string, unknown>;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const get = <T = Any>(url: string, params?: Params) => api.get(url, { params }) as unknown as Promise<Envelope<T>>;
const once = { idempotent: false } as AxiosRequestConfig;
const post = <T = Any>(url: string, body?: unknown) => api.post(url, body ?? {}, once) as unknown as Promise<Envelope<T>>;
const put = <T = Any>(url: string, body?: unknown) => api.put(url, body) as unknown as Promise<Envelope<T>>;
const del = <T = Any>(url: string) => api.delete(url) as unknown as Promise<Envelope<T>>;

/** Mentoring, early warning, grievances, discipline, surveys, clubs (Prompts/27 §27.8; the committees stub moved to features/governance). */
export const ssApi = {
  // mentoring
  assignments: (p: Params = {}) => get('/mentoring/assignments', p),
  assign: (b: Body) => post('/mentoring/assignments', b),
  bulkAssign: (b: Body) => post('/mentoring/assignments/bulk', b),
  reassign: (id: string, b: Body) => put(`/mentoring/assignments/${id}/reassign`, b),
  load: (p: Params = {}) => get('/mentoring/load', p),
  myMentor: () => get('/mentoring/me'),
  wardMentors: () => get('/mentoring/wards'),
  mentees: (p: Params = {}) => get('/mentoring/mentees', p),
  mentee360: (enrollmentId: string) => get(`/mentoring/mentees/${enrollmentId}/360`),
  mySlots: () => get('/mentoring/slots'),
  publishSlots: (b: Body) => post('/mentoring/slots', b),
  deleteSlot: (id: string) => del(`/mentoring/slots/${id}`),
  availableSlots: (p: Params = {}) => get('/mentoring/slots/available', p),
  bookSlot: (id: string, b: Body = {}) => post(`/mentoring/slots/${id}/book`, b),
  bookingAction: (id: string, action: 'cancel' | 'attended' | 'no-show') => post(`/mentoring/bookings/${id}/${action}`),
  sessions: (p: Params = {}) => get('/mentoring/sessions', p),
  logSession: (b: Body) => post('/mentoring/sessions', b),
  mySessions: () => get('/mentoring/sessions/me'),
  updateSession: (id: string, b: Body) => put(`/mentoring/sessions/${id}`, b),
  tickAction: (id: string, idx: number, done: boolean) => put(`/mentoring/sessions/${id}/action-items/${idx}`, { done }),
  refer: (b: Body) => post('/mentoring/referrals', b),
  referrals: (p: Params = {}) => get('/mentoring/referrals', p),
  updateReferral: (id: string, b: Body) => put(`/mentoring/referrals/${id}`, b),
  // risk
  riskCompute: (b: Body = {}) => post('/risk/compute', b),
  riskFlags: (p: Params = {}) => get('/risk/flags', p),
  riskHeatmap: (p: Params = {}) => get('/risk/heatmap', p),
  riskMe: () => get('/risk/flags/me'),
  riskAck: (id: string, action: string) => post(`/risk/flags/${id}/acknowledge`, { action }),
  // grievances
  raiseGrievance: (b: Body) => post('/grievances', b),
  myGrievances: () => get('/grievances/me'),
  wardGrievances: () => get('/grievances/wards'),
  grievances: (p: Params = {}) => get('/grievances', p),
  grievance: (id: string) => get(`/grievances/${id}`),
  grievanceUpdate: (id: string, b: Body) => post(`/grievances/${id}/updates`, b),
  grievanceTriage: (id: string, b: Body) => post(`/grievances/${id}/triage`, b),
  grievanceResolve: (id: string, resolution: string) => post(`/grievances/${id}/resolve`, { resolution }),
  grievanceClose: (id: string) => post(`/grievances/${id}/close`),
  grievanceEscalate: (id: string, reason: string) => post(`/grievances/${id}/escalate`, { reason }),
  grievanceRate: (id: string, rating: number, comment?: string) => post(`/grievances/${id}/rate`, { rating, comment }),
  grievanceReopen: (id: string, reason: string) => post(`/grievances/${id}/reopen`, { reason }),
  grievanceRegister: (kind: string, p: Params = {}) => get(`/grievances/registers/${kind}`, p),
  anonymousGrievance: (institution: string, b: Body) => post(`/grievances/anonymous?institution=${encodeURIComponent(institution)}`, b),
  trackGrievance: (p: Params) => get('/grievances/track', p),
  // discipline
  cases: (p: Params = {}) => get('/discipline/cases', p),
  reportCase: (b: Body) => post('/discipline/cases', b),
  myCases: () => get('/discipline/cases/me'),
  caseFile: (id: string) => get(`/discipline/cases/${id}`),
  inquiry: (id: string, b: Body) => post(`/discipline/cases/${id}/inquiry`, b),
  notice: (id: string, b: Body) => post(`/discipline/cases/${id}/notice`, b),
  hearing: (id: string, b: Body) => post(`/discipline/cases/${id}/hearing`, b),
  decide: (id: string, b: Body) => post(`/discipline/cases/${id}/decide`, b),
  closeCase: (id: string) => post(`/discipline/cases/${id}/close`),
  statement: (id: string, b: Body) => post(`/discipline/cases/${id}/statement`, b),
  appeal: (id: string, b: Body) => post(`/discipline/cases/${id}/appeal`, b),
  appealDecide: (id: string, b: Body) => post(`/discipline/cases/${id}/appeal/decide`, b),
  disciplineRegister: (p: Params = {}) => get('/discipline/register', p),
  // surveys
  surveys: (p: Params = {}) => get('/surveys', p),
  createSurvey: (b: Body) => post('/surveys', b),
  survey: (id: string) => get(`/surveys/${id}`),
  updateSurvey: (id: string, b: Body) => put(`/surveys/${id}`, b),
  surveyAction: (id: string, action: 'open' | 'close' | 'analyse' | 'remind') => post(`/surveys/${id}/${action}`),
  completion: (id: string) => get(`/surveys/${id}/completion`),
  pendingSurveys: () => get('/surveys/me/pending'),
  surveyForm: (id: string, p: Params = {}) => get(`/surveys/${id}/form`, p),
  respond: (id: string, b: Body) => post(`/surveys/${id}/respond`, b),
  analytics: (id: string, p: Params = {}) => get(`/surveys/${id}/analytics`, p),
  compare: (id: string, p: Params = {}) => get(`/surveys/${id}/compare`, p),
  sssScore: (p: Params = {}) => get('/surveys/sss/score', p),
  exportSurvey: (id: string) => get(`/surveys/${id}/export`),
  externalLinks: (id: string, b: Body) => post(`/surveys/${id}/external-links`, b),
  // clubs / hours / achievements
  clubs: (p: Params = {}) => get('/clubs', p),
  createClub: (b: Body) => post('/clubs', b),
  updateClub: (id: string, b: Body) => put(`/clubs/${id}`, b),
  members: (id: string) => get(`/clubs/${id}/members`),
  addMember: (id: string, b: Body) => post(`/clubs/${id}/members`, b),
  join: (id: string) => post(`/clubs/${id}/join`),
  decideMember: (id: string, mid: string, approve: boolean) => post(`/clubs/${id}/members/${mid}/decide`, { approve }),
  setRole: (id: string, mid: string, role: string) => post(`/clubs/${id}/members/${mid}/role`, { role }),
  clubEvents: (id: string) => get(`/clubs/${id}/events`),
  addClubEvent: (id: string, b: Body) => post(`/clubs/${id}/events`, b),
  hours: (p: Params = {}) => get('/activity-hours', p),
  logHours: (b: Body) => post('/activity-hours', b),
  myHours: () => get('/activity-hours/me'),
  verifyHours: (b: Body) => post('/activity-hours/verify', b),
  ledger: (p: Params = {}) => get('/activity-hours/ledger', p),
  creditEligible: (p: Params = {}) => get('/activity-hours/credit-eligible', p),
  achievements: (p: Params = {}) => get('/achievements', p),
  submitAchievement: (b: Body) => post('/achievements', b),
  myAchievements: () => get('/achievements/me'),
  verifyAchievement: (id: string, approve = true) => post(`/achievements/${id}/verify`, { approve }),
  // committees (Phase 33 governance list, used to pick the inquiry committee) + stats
  committees: (p: Params = {}) => get('/governance/committees', p),
  stats: (p: Params = {}) => get('/student-support/stats', p),
};
