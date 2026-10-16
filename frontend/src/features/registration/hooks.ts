import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { institutionApi } from '@/features/institution/api';
import { registrationApi } from './api';

type Params = Record<string, string | number | boolean | undefined | null>;

/** Query keys `['registration', …]`; mutations invalidate the module root. */
export const useOfferings = (p: Params = {}) =>
  useQuery({
    queryKey: ['registration', 'offerings', p],
    queryFn: () => registrationApi.offerings(p),
    placeholderData: keepPreviousData,
  });
export const useMyOfferings = (p: Params = {}) =>
  useQuery({ queryKey: ['registration', 'my-offerings', p], queryFn: () => registrationApi.myOfferings(p) });
export const useRoster = (id: string | undefined, waitlist = false) =>
  useQuery({
    queryKey: ['registration', 'roster', id, waitlist],
    queryFn: () => registrationApi.roster(id!, waitlist),
    enabled: !!id,
  });
export const useWindows = (p: Params = {}) =>
  useQuery({ queryKey: ['registration', 'windows', p], queryFn: () => registrationApi.windows(p) });
export const useCatalog = () =>
  useQuery({ queryKey: ['registration', 'catalog'], queryFn: () => registrationApi.catalog(), retry: false });
export const useMyRegistration = () =>
  useQuery({ queryKey: ['registration', 'mine'], queryFn: () => registrationApi.mine() });
export const useMyHistory = () =>
  useQuery({ queryKey: ['registration', 'history'], queryFn: () => registrationApi.myHistory() });
export const useRegistrations = (p: Params = {}) =>
  useQuery({
    queryKey: ['registration', 'list', p],
    queryFn: () => registrationApi.list(p),
    placeholderData: keepPreviousData,
  });
export const useRegistration = (id: string | undefined) =>
  useQuery({ queryKey: ['registration', 'one', id], queryFn: () => registrationApi.get(id!), enabled: !!id });
export const useArrears = (p: Params = {}) =>
  useQuery({
    queryKey: ['registration', 'arrears', p],
    queryFn: () => registrationApi.arrears(p),
    placeholderData: keepPreviousData,
  });
export const useTerms = () =>
  useQuery({ queryKey: ['academic-terms', 'all'], queryFn: () => institutionApi.terms({ page_size: 100 }) });
export const useCurrentTerm = () =>
  useQuery({ queryKey: ['academic-terms', 'current'], queryFn: () => institutionApi.currentTerm() });

export function useRegistrationMutation<V, R>(fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: ['registration'] }) });
}
