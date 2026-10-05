import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { hrApi } from './api';

type Params = Record<string, string | number | boolean | undefined | null>;

/** Query keys `[module, params]`; mutations invalidate whole module roots (frontend coding standard 1). */
export const useStaffList = (p: Params = {}, enabled = true) =>
  useQuery({ queryKey: ['staff', p], queryFn: () => hrApi.staff(p), placeholderData: keepPreviousData, enabled });
export const useStaff = (id: string | undefined) =>
  useQuery({ queryKey: ['staff', 'one', id], queryFn: () => hrApi.staffOne(id!), enabled: !!id });
export const useMyStaff = () => useQuery({ queryKey: ['staff', 'me'], queryFn: hrApi.me, retry: false });
export const useDesignations = () => useQuery({ queryKey: ['designations'], queryFn: hrApi.designations, staleTime: 300_000 });
export const useLeaveTypes = () => useQuery({ queryKey: ['leave-types'], queryFn: hrApi.leaveTypes, staleTime: 300_000 });
export const useLeaves = (p: Params = {}) =>
  useQuery({ queryKey: ['leaves', p], queryFn: () => hrApi.leaves(p), placeholderData: keepPreviousData });
export const useMyBalance = () => useQuery({ queryKey: ['leaves', 'balance'], queryFn: () => hrApi.myBalance() });
export const useAttendance = (p: Params = {}) =>
  useQuery({ queryKey: ['staff-attendance', p], queryFn: () => hrApi.attendance(p), placeholderData: keepPreviousData });
export const usePayroll = (p: Params = {}) =>
  useQuery({ queryKey: ['payroll', p], queryFn: () => hrApi.payroll(p), placeholderData: keepPreviousData });
export const useMyPayslips = () => useQuery({ queryKey: ['payroll', 'me'], queryFn: () => hrApi.myPayslips() });

/** Mutation that invalidates the given module roots on success. */
export function useHrMutation<V, R>(fn: (v: V) => Promise<R>, roots: string[]) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => Promise.all(roots.map((r) => qc.invalidateQueries({ queryKey: [r] }))),
  });
}
