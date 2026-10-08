import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { studentsApi } from './api';

type Params = Record<string, string | number | boolean | undefined | null>;

/** Query keys `[module, params]`; mutations invalidate whole module roots (frontend coding standard 1). */
export const useStudents = (p: Params = {}, enabled = true) =>
  useQuery({ queryKey: ['students', p], queryFn: () => studentsApi.list(p), placeholderData: keepPreviousData, enabled });
export const useStudent = (id: string | undefined) =>
  useQuery({ queryKey: ['students', 'one', id], queryFn: () => studentsApi.one(id!), enabled: !!id });
export const useStudentStats = (enabled = true) =>
  useQuery({ queryKey: ['students', 'stats'], queryFn: studentsApi.stats, enabled, staleTime: 60_000 });
export const useHoldsQueue = (p: Params = {}) =>
  useQuery({ queryKey: ['student-holds', p], queryFn: () => studentsApi.holdsQueue(p), placeholderData: keepPreviousData });
export const useTransfersQueue = (p: Params = {}) =>
  useQuery({ queryKey: ['student-transfers', p], queryFn: () => studentsApi.transfersQueue(p), placeholderData: keepPreviousData });
export const useCreditTransfers = (p: Params = {}) =>
  useQuery({ queryKey: ['credit-transfers', p], queryFn: () => studentsApi.creditTransfers(p), placeholderData: keepPreviousData });
export const useMyStudent = (enabled = true) =>
  useQuery({ queryKey: ['students', 'me'], queryFn: studentsApi.me, enabled, retry: false });
export const useStudentDashboard = () =>
  useQuery({ queryKey: ['students', 'me', 'dashboard'], queryFn: studentsApi.dashboard, retry: false });
export const useWards = () => useQuery({ queryKey: ['students', 'wards'], queryFn: studentsApi.wards, retry: false });
export const useWardDashboard = (id: string | undefined) =>
  useQuery({ queryKey: ['students', 'wards', id], queryFn: () => studentsApi.wardDashboard(id!), enabled: !!id, retry: false });

/** Mutation that invalidates the given module roots on success. */
export function useStudentMutation<V, R>(fn: (v: V) => Promise<R>, roots: string[] = ['students']) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => Promise.all(roots.map((r) => qc.invalidateQueries({ queryKey: [r] }))),
  });
}
