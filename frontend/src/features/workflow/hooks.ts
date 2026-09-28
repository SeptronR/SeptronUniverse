import { useEffect } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { wsClient } from '@/lib/ws';
import { useFeature } from '@/hooks/useFeature';
import { workflowApi } from './api';

export const wfKeys = {
  inbox: ['workflow', 'inbox'] as const,
  definitions: ['workflow', 'definitions'] as const,
  instances: (p: object) => ['workflow', 'instances', p] as const,
  instance: (id: string) => ['workflow', 'instance', id] as const,
  delegations: ['workflow', 'delegations'] as const,
};

/** Approvals inbox; refreshed by the `approvals.changed` WebSocket signal (consumer notifications.workflow). */
export function useInbox() {
  const enabled = useFeature('workflow.engine');
  const qc = useQueryClient();
  useEffect(
    () =>
      wsClient.subscribe('notifications', (data) => {
        if ((data as { type?: string })?.type === 'approvals.changed') qc.invalidateQueries({ queryKey: ['workflow'] });
      }),
    [qc],
  );
  return useQuery({ queryKey: wfKeys.inbox, queryFn: workflowApi.inbox, enabled, refetchInterval: 120_000 });
}

export const useDefinitions = () => useQuery({ queryKey: wfKeys.definitions, queryFn: () => workflowApi.definitions() });
export const useInstances = (p: Record<string, string | number | boolean | undefined>) =>
  useQuery({ queryKey: wfKeys.instances(p), queryFn: () => workflowApi.instances(p) });
export const useInstance = (id: string | undefined) =>
  useQuery({ queryKey: wfKeys.instance(id ?? ''), queryFn: () => workflowApi.instance(id!), enabled: !!id });
export const useDelegations = () =>
  useQuery({ queryKey: wfKeys.delegations, queryFn: workflowApi.delegations, enabled: useFeature('workflow.delegation') });

export function useWorkflowMutation<V, R>(fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: ['workflow'] }) });
}
