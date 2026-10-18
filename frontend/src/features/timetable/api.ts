import type { AxiosRequestConfig } from 'axios';
import { api } from '@/api/axios';
import type { Envelope } from '@/utils/types';
import type {
  Building,
  Candidate,
  ConflictReport,
  EntryResult,
  ICalToken,
  PublishSummary,
  Room,
  RoomAvailability,
  Session,
  Slot,
  Substitution,
  Timetable,
  WeeklyView,
} from './types';

type Params = Record<string, string | number | boolean | undefined | null>;
type Body = Record<string, unknown>;
const get = <T>(url: string, config?: AxiosRequestConfig) => api.get(url, config) as unknown as Promise<Envelope<T>>;
const once = { idempotent: false } as AxiosRequestConfig;
const post = <T>(url: string, body?: unknown, config: AxiosRequestConfig = once) =>
  api.post(url, body, config) as unknown as Promise<Envelope<T>>;
const put = <T>(url: string, body?: unknown) => api.put(url, body) as unknown as Promise<Envelope<T>>;
const del = <T>(url: string) => api.delete(url) as unknown as Promise<Envelope<T>>;

/** Rooms, slots, timetables, views, substitutions, sessions, iCal (Prompts/10 §10.8). */
export const timetableApi = {
  buildings: (params: Params = {}) => get<Building[]>('/buildings', { params }),
  createBuilding: (b: Body) => post<Building>('/buildings', b),
  rooms: (params: Params = {}) => get<Room[]>('/rooms', { params }),
  createRoom: (b: Body) => post<Room>('/rooms', b),
  updateRoom: (id: string, b: Body) => put<Room>(`/rooms/${id}`, b),
  deleteRoom: (id: string) => del<null>(`/rooms/${id}`),
  availability: (params: Params) => get<RoomAvailability[]>('/rooms/availability', { params }),
  slots: (params: Params = {}) => get<Slot[]>('/time-slots', { params }),
  saveSlots: (b: Body) => put<Slot[]>('/time-slots', b),
  timetables: (params: Params = {}) => get<Timetable[]>('/timetables', { params }),
  timetable: (id: string) => get<Timetable>(`/timetables/${id}`),
  create: (b: Body) => post<Timetable>('/timetables', b),
  clone: (id: string) => post<Timetable>(`/timetables/${id}/clone`),
  remove: (id: string) => del<null>(`/timetables/${id}`),
  addEntry: (id: string, b: Body) => post<EntryResult>(`/timetables/${id}/entries`, b),
  updateEntry: (id: string, eid: string, b: Body) => put<EntryResult>(`/timetables/${id}/entries/${eid}`, b),
  deleteEntry: (id: string, eid: string) => del<null>(`/timetables/${id}/entries/${eid}`),
  check: (id: string, b?: Body) => post<ConflictReport>(`/timetables/${id}/check-conflicts`, b ?? null),
  publish: (id: string, b: Body) => post<PublishSummary>(`/timetables/${id}/publish`, b),
  archive: (id: string) => post<Timetable>(`/timetables/${id}/archive`),
  autoGenerate: (id: string, dry_run: boolean) =>
    post<Record<string, unknown>>(`/timetables/${id}/auto-generate`, {}, { params: { dry_run }, idempotent: false } as AxiosRequestConfig),
  exportCsv: (id: string) => get<{ job_id: string }>(`/timetables/${id}/export`),
  view: (params: Params) => get<WeeklyView>('/timetables/view', { params }),
  me: (params: Params = {}) => get<WeeklyView>('/timetables/me', { params }),
  icalToken: () => post<ICalToken>('/timetables/ical/token'),
  icalRevoke: () => del<ICalToken>('/timetables/ical/token'),
  substitutions: (params: Params = {}) => get<Substitution[]>('/substitutions', { params }),
  requestSub: (b: Body) => post<Substitution>('/substitutions', b),
  candidates: (id: string) => get<Candidate[]>(`/substitutions/${id}/candidates`),
  approveSub: (id: string, b: Body) => post<Substitution>(`/substitutions/${id}/approve`, b),
  rejectSub: (id: string, b: Body) => post<Substitution>(`/substitutions/${id}/reject`, b),
  withdrawSub: (id: string) => post<Substitution>(`/substitutions/${id}/withdraw`),
  sessions: (params: Params = {}) => get<Session[]>('/class-sessions', { params }),
  today: () => get<Session[]>('/class-sessions/today'),
  extra: (b: Body) => post<Session>('/class-sessions/extra', b),
  updateSession: (id: string, b: Body) => put<Session>(`/class-sessions/${id}`, b),
  cancel: (id: string, b: Body) => post<Session>(`/class-sessions/${id}/cancel`, b),
  reschedule: (id: string, b: Body) => post<Session>(`/class-sessions/${id}/reschedule`, b),
};
