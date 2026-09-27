import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { commsApi } from './api';

type Params = Record<string, string | number | boolean | undefined | null>;

export const commsKeys = {
  templates: (p: Params = {}) => ['comm-templates', p] as const,
  logs: (p: Params = {}) => ['comm-logs', p] as const,
  notifications: (p: Params = {}) => ['notifications', p] as const,
  unread: ['notifications', 'unread'] as const,
  preferences: ['notification-preferences'] as const,
  announcements: (p: Params = {}) => ['announcements', p] as const,
  announcement: (id: string) => ['announcements', 'one', id] as const,
};

export const useTemplates = (p: Params = {}) => useQuery({ queryKey: commsKeys.templates(p), queryFn: () => commsApi.templates(p) });
export const useLogs = (p: Params = {}) =>
  useQuery({ queryKey: commsKeys.logs(p), queryFn: () => commsApi.logs(p), placeholderData: keepPreviousData });
export const useMyNotifications = (p: Params = {}) =>
  useQuery({ queryKey: commsKeys.notifications(p), queryFn: () => commsApi.notifications(p), placeholderData: keepPreviousData });
export const useUnreadCount = (enabled = true) =>
  useQuery({ queryKey: commsKeys.unread, queryFn: commsApi.unreadCount, enabled, refetchInterval: 60_000 });
export const usePreferences = () => useQuery({ queryKey: commsKeys.preferences, queryFn: commsApi.preferences });
export const useAnnouncements = (p: Params = {}) =>
  useQuery({ queryKey: commsKeys.announcements(p), queryFn: () => commsApi.announcements(p), placeholderData: keepPreviousData });
export const useAnnouncement = (id: string | undefined) =>
  useQuery({ queryKey: commsKeys.announcement(id ?? ''), queryFn: () => commsApi.announcement(id!), enabled: !!id });

export function useCommsMutation<V, R>(fn: (v: V) => Promise<R>, roots: string[]) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => Promise.all(roots.map((r) => qc.invalidateQueries({ queryKey: [r] }))),
  });
}
