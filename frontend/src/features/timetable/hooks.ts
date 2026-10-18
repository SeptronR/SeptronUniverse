import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { timetableApi } from './api';

type Params = Record<string, string | number | boolean | undefined | null>;

/** Query keys `['timetable', …]`; mutations invalidate the module root. */
export const useRooms = (p: Params = {}) =>
  useQuery({ queryKey: ['timetable', 'rooms', p], queryFn: () => timetableApi.rooms(p), placeholderData: keepPreviousData });
export const useBuildings = () => useQuery({ queryKey: ['timetable', 'buildings'], queryFn: () => timetableApi.buildings() });
export const useSlots = (p: Params = {}) =>
  useQuery({ queryKey: ['timetable', 'slots', p], queryFn: () => timetableApi.slots(p) });
export const useTimetables = (p: Params = {}) =>
  useQuery({ queryKey: ['timetable', 'list', p], queryFn: () => timetableApi.timetables(p), placeholderData: keepPreviousData });
export const useTimetable = (id?: string) =>
  useQuery({ queryKey: ['timetable', 'one', id], queryFn: () => timetableApi.timetable(id!), enabled: !!id });
export const useWeekly = (p: Params, enabled = true) =>
  useQuery({ queryKey: ['timetable', 'view', p], queryFn: () => timetableApi.view(p), enabled, retry: false });
export const useMyWeek = (p: Params = {}) =>
  useQuery({ queryKey: ['timetable', 'me', p], queryFn: () => timetableApi.me(p), retry: false });
export const useSubstitutions = (p: Params = {}) =>
  useQuery({ queryKey: ['timetable', 'subs', p], queryFn: () => timetableApi.substitutions(p), placeholderData: keepPreviousData });
export const useCandidates = (id?: string) =>
  useQuery({ queryKey: ['timetable', 'cand', id], queryFn: () => timetableApi.candidates(id!), enabled: !!id });
export const useSessions = (p: Params = {}) =>
  useQuery({ queryKey: ['timetable', 'sessions', p], queryFn: () => timetableApi.sessions(p), placeholderData: keepPreviousData });
export const useToday = () => useQuery({ queryKey: ['timetable', 'today'], queryFn: () => timetableApi.today(), retry: false });

export function useTimetableMutation<V, R>(fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: ['timetable'] }) });
}
