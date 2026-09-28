import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { academicsApi } from './api';

type Params = Record<string, string | number | boolean | undefined | null>;

/** Query keys `[module, params]`; mutations invalidate whole modules (frontend coding standard 1). */
export const acKeys = {
  programs: (p: Params = {}) => ['programs', p] as const,
  regulations: (p: Params = {}) => ['regulations', p] as const,
  regulation: (id: string) => ['regulations', 'one', id] as const,
  rulesSchema: ['regulations', 'rules-schema'] as const,
  diff: (id: string) => ['regulations', 'diff', id] as const,
  programRegulations: (p: Params = {}) => ['program-regulations', p] as const,
  structure: (id: string) => ['program-regulations', 'structure', id] as const,
  courses: (p: Params = {}) => ['courses', p] as const,
  course: (id: string) => ['courses', 'one', id] as const,
  baskets: (p: Params = {}) => ['elective-baskets', p] as const,
  scales: (p: Params = {}) => ['grading-scales', p] as const,
  schemes: (p: Params = {}) => ['assessment-schemes', p] as const,
  batches: (p: Params = {}) => ['batches', p] as const,
  catalog: (p: Params = {}) => ['catalog', p] as const,
};

export const usePrograms = (p: Params = {}) =>
  useQuery({ queryKey: acKeys.programs(p), queryFn: () => academicsApi.programs(p), placeholderData: keepPreviousData });
export const useRegulations = (p: Params = {}) =>
  useQuery({ queryKey: acKeys.regulations(p), queryFn: () => academicsApi.regulations(p), placeholderData: keepPreviousData });
export const useRegulation = (id: string | undefined) =>
  useQuery({ queryKey: acKeys.regulation(id ?? ''), queryFn: () => academicsApi.regulation(id!), enabled: !!id });
export const useRulesSchema = () =>
  useQuery({ queryKey: acKeys.rulesSchema, queryFn: academicsApi.rulesSchema, staleTime: 3_600_000 });
export const useDiff = (id: string | undefined, enabled = true) =>
  useQuery({ queryKey: acKeys.diff(id ?? ''), queryFn: () => academicsApi.diff(id!), enabled: !!id && enabled });
export const useProgramRegulations = (p: Params = {}, enabled = true) =>
  useQuery({ queryKey: acKeys.programRegulations(p), queryFn: () => academicsApi.programRegulations(p), enabled });
export const useStructure = (id: string | undefined) =>
  useQuery({ queryKey: acKeys.structure(id ?? ''), queryFn: () => academicsApi.structure(id!), enabled: !!id });
export const useCourses = (p: Params = {}, enabled = true) =>
  useQuery({ queryKey: acKeys.courses(p), queryFn: () => academicsApi.courses(p), enabled, placeholderData: keepPreviousData });
export const useCourse = (id: string | undefined) =>
  useQuery({ queryKey: acKeys.course(id ?? ''), queryFn: () => academicsApi.course(id!), enabled: !!id });
export const useBaskets = (p: Params = {}, enabled = true) =>
  useQuery({ queryKey: acKeys.baskets(p), queryFn: () => academicsApi.baskets(p), enabled });
export const useScales = (p: Params = {}) => useQuery({ queryKey: acKeys.scales(p), queryFn: () => academicsApi.scales(p) });
export const useSchemes = (p: Params = {}, enabled = true) =>
  useQuery({ queryKey: acKeys.schemes(p), queryFn: () => academicsApi.schemes(p), enabled });
export const useBatches = (p: Params = {}) =>
  useQuery({ queryKey: acKeys.batches(p), queryFn: () => academicsApi.batches(p), placeholderData: keepPreviousData });
export const useCatalog = (p: Params = {}) =>
  useQuery({ queryKey: acKeys.catalog(p), queryFn: () => academicsApi.catalog(p), retry: false });

/** Mutation that invalidates the given module roots on success. */
export function useAcMutation<V, R>(fn: (v: V) => Promise<R>, roots: string[]) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => Promise.all(roots.map((r) => qc.invalidateQueries({ queryKey: [r] }))),
  });
}
