import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';
import { useSessionStore } from '@/store/sessionStore';
import { useAuthStore } from '@/store/authStore';
import { platformApi } from './api';
import type { FeedbackCreate, JobListParams, ReadOnlyModeRequest } from './types';

/** Query keys follow `[module, params]`; invalidate by `[module]` (frontend coding standard 1). */
export const jobKeys = {
  all: ['jobs'] as const,
  list: (p: JobListParams) => ['jobs', p] as const,
  one: (id: string) => ['jobs', 'one', id] as const,
};
export const helpKeys = {
  all: ['help'] as const,
  list: (p: object) => ['help', p] as const,
  one: (slug: string) => ['help', 'one', slug] as const,
};

export const usePublicConfig = (institution?: string) =>
  useQuery({
    queryKey: ['platform', 'public-config', institution ?? null],
    queryFn: () => platformApi.publicConfig(institution),
    staleTime: 5 * 60_000,
  });

/** Polls the public read-only state and mirrors it into the session store (banner + disabled writes). */
export const useReadOnlyPoll = (intervalMs = 60_000) => {
  const setReadOnly = useSessionStore((s) => s.setReadOnly);
  const query = useQuery({
    queryKey: ['platform', 'read-only'],
    queryFn: platformApi.readOnly,
    refetchInterval: intervalMs,
    staleTime: intervalMs,
  });
  useEffect(() => {
    if (query.data) setReadOnly(!!(query.data.data.platform || query.data.data.institution));
  }, [query.data, setReadOnly]);
  return query;
};

export const useReadOnly = () => useSessionStore((s) => s.readOnly);

export const useSetReadOnly = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ReadOnlyModeRequest) => platformApi.setReadOnly(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['platform', 'read-only'] }),
  });
};

export const useJobs = (params: JobListParams, options: { refetchInterval?: number | false } = {}) =>
  useQuery({
    queryKey: jobKeys.list(params),
    queryFn: () => platformApi.listJobs(params),
    placeholderData: keepPreviousData,
    ...options,
  });

export const useJob = (id: string | undefined) =>
  useQuery({ queryKey: jobKeys.one(id ?? ''), queryFn: () => platformApi.getJob(id!), enabled: !!id });

export const useCancelJob = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => platformApi.cancelJob(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: jobKeys.all }),
  });
};

export const useDevSleepJob = () => {
  const qc = useQueryClient();
  return useMutation({
    // inline=true runs the body inside the API when no worker is around (dev launcher); a worker skips started rows
    mutationFn: (seconds: number) => platformApi.devSleepJob(seconds, true),
    onSuccess: () => qc.invalidateQueries({ queryKey: jobKeys.all }),
  });
};

export const useSearch = (q: string, types?: string[]) => {
  const enabled = useAuthStore((s) => s.isAuthenticated) && q.trim().length >= 2;
  return useQuery({
    queryKey: ['search', q.trim(), types ?? null],
    queryFn: () => platformApi.search(q.trim(), types),
    enabled,
    staleTime: 15_000,
  });
};

export const useHelpArticles = (params: { module?: string; q?: string } = {}) =>
  useQuery({
    queryKey: helpKeys.list(params),
    queryFn: () => platformApi.listHelp(params),
    placeholderData: keepPreviousData,
  });

export const useHelpArticle = (slug: string | undefined) =>
  useQuery({ queryKey: helpKeys.one(slug ?? ''), queryFn: () => platformApi.getHelp(slug!), enabled: !!slug });

export const useSubmitFeedback = () =>
  useMutation({ mutationFn: (body: FeedbackCreate) => platformApi.submitFeedback(body) });
