import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { attendanceApi } from './api';

type Params = Record<string, string | number | boolean | undefined | null>;

/** Query keys `['attendance', …]`; mutations invalidate the module root (and the `timetable` sessions). */
export const useSheet = (sessionId?: string, refetchInterval?: number) =>
  useQuery({
    queryKey: ['attendance', 'sheet', sessionId],
    queryFn: () => attendanceApi.sheet(sessionId!),
    enabled: !!sessionId,
    retry: false,
    refetchInterval,
  });
export const useSummaries = (p: Params, enabled = true) =>
  useQuery({ queryKey: ['attendance', 'summaries', p], queryFn: () => attendanceApi.summaries(p), enabled, placeholderData: keepPreviousData });
export const useOfferingSummaries = (p: Params) =>
  useQuery({ queryKey: ['attendance', 'offerings', p], queryFn: () => attendanceApi.offerings(p), placeholderData: keepPreviousData });
export const useMySummary = (p: Params = {}, enabled = true) =>
  useQuery({ queryKey: ['attendance', 'me', p], queryFn: () => attendanceApi.me(p), enabled, retry: false });
export const useHistory = (p: Params = {}, enabled = true) =>
  useQuery({ queryKey: ['attendance', 'history', p], queryFn: () => attendanceApi.history(p), enabled, retry: false });
export const useRegister = (p: Params, enabled: boolean) =>
  useQuery({ queryKey: ['attendance', 'register', p], queryFn: () => attendanceApi.register(p), enabled, retry: false });
export const useMissing = (p: Params = {}) => useQuery({ queryKey: ['attendance', 'missing', p], queryFn: () => attendanceApi.missing(p) });
export const useUnmatched = (enabled = true) =>
  useQuery({ queryKey: ['attendance', 'unmatched'], queryFn: () => attendanceApi.unmatched(), enabled, retry: false });
export const useAlertConfig = (enabled = true) =>
  useQuery({ queryKey: ['attendance', 'alerts'], queryFn: () => attendanceApi.alertConfig(), enabled, retry: false });
export const useOds = (p: Params = {}) =>
  useQuery({ queryKey: ['attendance', 'od', p], queryFn: () => attendanceApi.ods(p), placeholderData: keepPreviousData });
export const useCondonations = (p: Params = {}) =>
  useQuery({ queryKey: ['attendance', 'condonations', p], queryFn: () => attendanceApi.condonations(p), placeholderData: keepPreviousData });
export const useMyCondonations = (enabled = true) =>
  useQuery({ queryKey: ['attendance', 'condonations', 'me'], queryFn: () => attendanceApi.myCondonations(), enabled, retry: false });
export const useVersions = (termId?: string) =>
  useQuery({ queryKey: ['attendance', 'versions', termId], queryFn: () => attendanceApi.versions(termId!), enabled: !!termId });
export const useEligibility = (termId: string | undefined, p: Params) =>
  useQuery({
    queryKey: ['attendance', 'eligibility', termId, p],
    queryFn: () => attendanceApi.eligibility(termId!, p),
    enabled: !!termId,
    placeholderData: keepPreviousData,
  });
export const useDetention = (termId: string | undefined, p: Params) =>
  useQuery({ queryKey: ['attendance', 'detention', termId, p], queryFn: () => attendanceApi.detention(termId!, p), enabled: !!termId });
export const useMyEligibility = (p: Params = {}, enabled = true) =>
  useQuery({ queryKey: ['attendance', 'elig-me', p], queryFn: () => attendanceApi.myEligibility(p), enabled, retry: false });

export function useAttendanceMutation<V, R>(fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['attendance'] });
      void qc.invalidateQueries({ queryKey: ['timetable'] });
    },
  });
}
