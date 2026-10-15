import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { admissionsApi } from './api';

type Params = Record<string, string | number | boolean | undefined | null>;

/** Query keys `['admissions', …]`; mutations invalidate the module root (frontend coding standard 1). */
export const useCycles = (p: Params = {}) =>
  useQuery({ queryKey: ['admissions', 'cycles', p], queryFn: () => admissionsApi.cycles(p) });
export const useCycle = (id: string | undefined) =>
  useQuery({ queryKey: ['admissions', 'cycle', id], queryFn: () => admissionsApi.cycle(id!), enabled: !!id });
export const useCyclePrograms = (id: string | undefined) =>
  useQuery({ queryKey: ['admissions', 'programs', id], queryFn: () => admissionsApi.programs(id!), enabled: !!id });
export const useSeatStatus = (id: string | undefined) =>
  useQuery({ queryKey: ['admissions', 'seats', id], queryFn: () => admissionsApi.seatStatus(id!), enabled: !!id });
export const useApplicants = (p: Params = {}, enabled = true) =>
  useQuery({ queryKey: ['admissions', 'applicants', p], queryFn: () => admissionsApi.applicants(p), placeholderData: keepPreviousData, enabled });
export const useApplicant = (id: string | undefined) =>
  useQuery({ queryKey: ['admissions', 'applicant', id], queryFn: () => admissionsApi.applicant(id!), enabled: !!id });
export const useApplicantTimeline = (id: string | undefined) =>
  useQuery({ queryKey: ['admissions', 'timeline', id], queryFn: () => admissionsApi.timeline(id!), enabled: !!id });
export const useVerificationQueue = (p: Params = {}) =>
  useQuery({ queryKey: ['admissions', 'queue', p], queryFn: () => admissionsApi.verificationQueue(p), placeholderData: keepPreviousData });
export const useMeritLists = (cycleId: string | undefined) =>
  useQuery({ queryKey: ['admissions', 'merit', cycleId], queryFn: () => admissionsApi.meritLists({ cycle_id: cycleId }), enabled: !!cycleId, refetchInterval: 5000 });
export const useMeritList = (id: string | undefined) =>
  useQuery({ queryKey: ['admissions', 'merit-list', id], queryFn: () => admissionsApi.meritList(id!), enabled: !!id });
export const useRounds = (cycleId: string | undefined) =>
  useQuery({ queryKey: ['admissions', 'rounds', cycleId], queryFn: () => admissionsApi.rounds(cycleId!), enabled: !!cycleId });
export const useAllotments = (roundId: string | undefined) =>
  useQuery({ queryKey: ['admissions', 'allotments', roundId], queryFn: () => admissionsApi.allotments(roundId!), enabled: !!roundId });
export const useOffers = (cycleId: string | undefined) =>
  useQuery({ queryKey: ['admissions', 'offers', cycleId], queryFn: () => admissionsApi.offers({ cycle_id: cycleId }), enabled: !!cycleId });
export const useEnquiries = (p: Params = {}) =>
  useQuery({ queryKey: ['admissions', 'enquiries', p], queryFn: () => admissionsApi.enquiries(p), placeholderData: keepPreviousData });
export const useEnquiryStats = () =>
  useQuery({ queryKey: ['admissions', 'enquiry-stats'], queryFn: admissionsApi.enquiryStats });
export const useMyApplication = (enabled = true) =>
  useQuery({ queryKey: ['admissions', 'me'], queryFn: admissionsApi.me, enabled, retry: false });
export const useMyTimeline = (enabled = true) =>
  useQuery({ queryKey: ['admissions', 'me', 'timeline'], queryFn: admissionsApi.myTimeline, enabled, retry: false });

/** Mutation that invalidates every admissions query on success. */
export function useAdmissionsMutation<V, R>(fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: ['admissions'] }) });
}
