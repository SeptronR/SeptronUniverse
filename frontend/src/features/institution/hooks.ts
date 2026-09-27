import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { institutionApi } from './api';

type Params = Record<string, string | number | boolean | undefined | null>;

/** Query keys `[module, params]`; mutations invalidate the whole module (frontend coding standard 1). */
export const instKeys = {
  profile: ['institution', 'profile'] as const,
  colleges: (p: Params = {}) => ['colleges', p] as const,
  faculties: (p: Params = {}) => ['faculties', p] as const,
  departments: (p: Params = {}) => ['departments', p] as const,
  years: (p: Params = {}) => ['academic-years', p] as const,
  terms: (p: Params = {}) => ['academic-terms', p] as const,
  term: (id: string) => ['academic-terms', 'one', id] as const,
  holidays: (p: Params = {}) => ['holidays', p] as const,
  sequences: (p: Params = {}) => ['number-sequences', p] as const,
  settings: ['settings'] as const,
  platform: (p: Params = {}) => ['platform-institutions', p] as const,
};

export const useProfile = () => useQuery({ queryKey: instKeys.profile, queryFn: institutionApi.profile });
export const useColleges = (p: Params = {}, enabled = true) =>
  useQuery({ queryKey: instKeys.colleges(p), queryFn: () => institutionApi.colleges(p), enabled, placeholderData: keepPreviousData });
export const useFaculties = (p: Params = {}, enabled = true) =>
  useQuery({ queryKey: instKeys.faculties(p), queryFn: () => institutionApi.faculties(p), enabled });
export const useDepartments = (p: Params = {}) =>
  useQuery({ queryKey: instKeys.departments(p), queryFn: () => institutionApi.departments(p), placeholderData: keepPreviousData });
export const useYears = (p: Params = {}, enabled = true) =>
  useQuery({ queryKey: instKeys.years(p), queryFn: () => institutionApi.years(p), enabled });
export const useTerms = (p: Params = {}, enabled = true) =>
  useQuery({ queryKey: instKeys.terms(p), queryFn: () => institutionApi.terms(p), enabled });
export const useTerm = (id: string | undefined) =>
  useQuery({ queryKey: instKeys.term(id ?? ''), queryFn: () => institutionApi.term(id!), enabled: !!id });
export const useHolidays = (p: Params = {}) =>
  useQuery({ queryKey: instKeys.holidays(p), queryFn: () => institutionApi.holidays(p), placeholderData: keepPreviousData });
export const useSequences = (p: Params = {}) =>
  useQuery({ queryKey: instKeys.sequences(p), queryFn: () => institutionApi.sequences(p) });
export const useSettings = () => useQuery({ queryKey: instKeys.settings, queryFn: () => institutionApi.settings() });
export const usePlatformInstitutions = (p: Params = {}) =>
  useQuery({ queryKey: instKeys.platform(p), queryFn: () => institutionApi.platformInstitutions(p), placeholderData: keepPreviousData });

/** Mutation that invalidates the given module roots on success. */
export function useInstMutation<V, R>(fn: (v: V) => Promise<R>, roots: string[]) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => Promise.all(roots.map((r) => qc.invalidateQueries({ queryKey: [r] }))),
  });
}
