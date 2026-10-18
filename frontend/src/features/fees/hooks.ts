import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { feesApi, noDuesApi, scholarshipsApi } from './api';

type Params = Record<string, string | number | boolean | undefined | null>;

/** Query keys `['fees', …]`; mutations invalidate the module roots (`fees`, `scholarships`, `no-dues`). */
export const useFeeDashboard = (enabled = true) =>
  useQuery({ queryKey: ['fees', 'dashboard'], queryFn: feesApi.dashboard, enabled, retry: false });
export const useHeads = () => useQuery({ queryKey: ['fees', 'heads'], queryFn: feesApi.heads });
export const useStructures = (p: Params = {}) =>
  useQuery({ queryKey: ['fees', 'structures', p], queryFn: () => feesApi.structures(p), placeholderData: keepPreviousData });
export const useDiscounts = () => useQuery({ queryKey: ['fees', 'discounts'], queryFn: feesApi.discounts, retry: false });
export const usePendingDiscounts = (enabled = true) =>
  useQuery({ queryKey: ['fees', 'discounts', 'pending'], queryFn: feesApi.pendingDiscounts, enabled, retry: false });
export const useFines = () => useQuery({ queryKey: ['fees', 'fines'], queryFn: feesApi.fines, retry: false });
export const useInvoices = (p: Params, enabled = true) =>
  useQuery({ queryKey: ['fees', 'invoices', p], queryFn: () => feesApi.invoices(p), enabled, placeholderData: keepPreviousData });
export const useInvoice = (id?: string) =>
  useQuery({ queryKey: ['fees', 'invoice', id], queryFn: () => feesApi.invoice(id!), enabled: !!id });
export const useMyDues = (enabled = true) => useQuery({ queryKey: ['fees', 'me', 'dues'], queryFn: feesApi.myDues, enabled, retry: false });
export const useMyReceipts = (enabled = true) =>
  useQuery({ queryKey: ['fees', 'me', 'receipts'], queryFn: feesApi.myReceipts, enabled, retry: false });
export const useWardDues = (studentId?: string) =>
  useQuery({ queryKey: ['fees', 'ward', studentId], queryFn: () => feesApi.wardDues(studentId!), enabled: !!studentId, retry: false });
export const usePayments = (p: Params) =>
  useQuery({ queryKey: ['fees', 'payments', p], queryFn: () => feesApi.payments(p), placeholderData: keepPreviousData });
export const useCancelQueue = (enabled = true) =>
  useQuery({ queryKey: ['fees', 'cancel-queue'], queryFn: feesApi.cancelQueue, enabled, retry: false });
export const useReconcile = (p: Params) => useQuery({ queryKey: ['fees', 'reconcile', p], queryFn: () => feesApi.reconcile(p) });
export const useDayBook = (p: Params) => useQuery({ queryKey: ['fees', 'day-book', p], queryFn: () => feesApi.dayBook(p) });
export const useRefunds = (p: Params = {}) => useQuery({ queryKey: ['fees', 'refunds', p], queryFn: () => feesApi.refunds(p) });
export const useMyRefunds = (enabled = true) =>
  useQuery({ queryKey: ['fees', 'refunds', 'me'], queryFn: feesApi.myRefunds, enabled, retry: false });
export const useReport = (name: string, p: Params) =>
  useQuery({ queryKey: ['fees', 'report', name, p], queryFn: () => feesApi.report(name, p), retry: false });
export const useSchemes = (active = false) =>
  useQuery({ queryKey: ['scholarships', 'schemes', active], queryFn: () => scholarshipsApi.schemes(active), retry: false });
export const useApplications = (p: Params = {}, enabled = true) =>
  useQuery({ queryKey: ['scholarships', 'applications', p], queryFn: () => scholarshipsApi.applications(p), enabled, retry: false });
export const useMyApplications = (enabled = true) =>
  useQuery({ queryKey: ['scholarships', 'me'], queryFn: scholarshipsApi.mine, enabled, retry: false });
export const useNoDues = (p: Params = {}, enabled = true) =>
  useQuery({ queryKey: ['no-dues', p], queryFn: () => noDuesApi.list(p), enabled, retry: false });
export const useMyNoDues = (enabled = true) => useQuery({ queryKey: ['no-dues', 'me'], queryFn: noDuesApi.mine, enabled, retry: false });

export function useFeesMutation<V, R>(fn: (v: V) => Promise<R>, roots: string[] = ['fees', 'scholarships', 'no-dues']) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => roots.forEach((r) => qc.invalidateQueries({ queryKey: [r] })),
  });
}
