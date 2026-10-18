import type { components } from '@/api/generated/openapi';

type S = components['schemas'];
export type Building = S['BuildingOut'];
export type Room = S['RoomOut'];
export type RoomAvailability = S['RoomAvailability'];
export type Slot = S['SlotOut'];
export type Timetable = S['TimetableResponse'];
export type Entry = S['EntryOut'];
export type EntryResult = S['EntryResult'];
export type ConflictReport = S['ConflictReport'];
export type PublishSummary = S['PublishSummary'];
export type WeeklyView = S['WeeklyView'];
export type Session = S['ClassSessionResponse'];
export type Substitution = S['SubstitutionResponse'];
export type Candidate = S['SubstituteCandidate'];
export type ICalToken = S['ICalToken'];

export const ROOM_TYPES = ['classroom', 'lab', 'seminar', 'auditorium', 'exam_hall', 'smart_class', 'sports', 'other'];
export const DAYS = ['', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
export const hhmm = (t?: string | null) => (t ? t.slice(0, 5) : '');
