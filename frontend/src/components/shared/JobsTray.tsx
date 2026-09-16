import { useEffect, useMemo, useState } from 'react';
import * as Popover from '@radix-ui/react-popover';
import { Link } from 'react-router-dom';
import { Activity, CheckCircle2, Download, XCircle } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { toast } from '@/components/ui/Toaster';
import { getApiError } from '@/api/axios';
import { useCancelJob, useJobs, useReadOnly } from '@/features/platform/hooks';
import type { Job, JobStatus } from '@/features/platform/types';
import { usePermission } from '@/hooks/usePermission';
import { useFeature } from '@/hooks/useFeature';
import { wsClient } from '@/lib/ws';
import { useNotificationStore } from '@/store/notificationStore';
import { cn } from '@/utils/cn';

export interface JobEvent {
  job_id: string;
  job_type?: string;
  status?: JobStatus;
  progress_pct?: number | null;
  message?: string | null;
  result_url?: string | null;
  cancel_requested?: boolean;
}

type TrayJob = JobEvent & { id: string; created_at?: string };
const ACTIVE = new Set<JobStatus>(['queued', 'running']);

/**
 * Navbar jobs tray (Prompts/01 §01.9): WebSocket `jobs:{user}` events update rows instantly; `GET /jobs` is polled
 * every 10 s (5 s while a job is active or the socket is down) as the fallback, and queued/running jobs can be cancelled.
 */
export function JobsTray() {
  const enabled = useFeature('core.background_jobs');
  const { can } = usePermission();
  const connected = useNotificationStore((s) => s.connected);
  const readOnly = useReadOnly();
  const cancel = useCancelJob();
  const [live, setLive] = useState<Record<string, JobEvent>>({});
  const hasActive = Object.values(live).some((j) => j.status && ACTIVE.has(j.status));
  const poll = useJobs(
    { page_size: 8, sort: '-created_at' },
    { refetchInterval: hasActive || !connected ? 5_000 : 10_000 },
  );

  useEffect(
    () =>
      wsClient.subscribe('jobs', (data) => {
        const ev = data as JobEvent;
        if (!ev?.job_id) return;
        setLive((prev) => ({ ...prev, [ev.job_id]: { ...prev[ev.job_id], ...ev } }));
      }),
    [],
  );

  const list = useMemo<TrayJob[]>(() => {
    const byId = new Map<string, TrayJob>();
    (poll.data?.data ?? []).forEach((j: Job) => byId.set(j.id, { ...j, job_id: j.id }));
    Object.values(live).forEach((ev) =>
      byId.set(ev.job_id, { ...(byId.get(ev.job_id) ?? { id: ev.job_id }), ...ev, id: ev.job_id }),
    );
    return Array.from(byId.values()).sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''));
  }, [poll.data, live]);
  const active = list.filter((j) => !j.status || ACTIVE.has(j.status)).length;

  if (!enabled || !can('jobs', 'view')) return null;

  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label={`Background jobs${active ? `, ${active} active` : ''}`}
          className="relative"
        >
          <Activity className={cn('h-5 w-5', active > 0 && 'animate-pulse text-primary')} />
          {active > 0 && (
            <span className="absolute -right-0.5 -top-0.5 rounded-full bg-primary px-1 text-[10px] font-semibold text-primary-foreground">
              {active}
            </span>
          )}
        </Button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={8}
          className="z-50 w-80 rounded-md border bg-popover p-3 text-sm shadow-md"
        >
          <div className="mb-2 flex items-center justify-between">
            <p className="font-medium">Background jobs</p>
            <span className="text-xs text-muted-foreground" title={connected ? 'Live updates' : 'Polling every 5 s'}>
              {connected ? '● live' : '○ polling'}
            </span>
          </div>
          {list.length === 0 ? (
            <p className="text-muted-foreground">No jobs yet.</p>
          ) : (
            <ul className="max-h-72 space-y-2 overflow-y-auto">
              {list.slice(0, 8).map((j) => (
                <li key={j.id} className="rounded-md border p-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate font-medium">{j.job_type ?? j.id.slice(0, 8)}</span>
                    {j.status === 'succeeded' ? (
                      <CheckCircle2 className="h-4 w-4 text-status-approved" aria-label="succeeded" />
                    ) : j.status === 'failed' || j.status === 'cancelled' ? (
                      <XCircle className="h-4 w-4 text-status-rejected" aria-label={j.status} />
                    ) : (
                      <span className="text-xs text-muted-foreground">{j.progress_pct ?? 0}%</span>
                    )}
                  </div>
                  <div className="mt-1 h-1.5 w-full rounded bg-muted">
                    <div
                      className="h-1.5 rounded bg-primary transition-all"
                      style={{ width: `${j.progress_pct ?? 0}%` }}
                    />
                  </div>
                  <div className="mt-1 flex items-center justify-between gap-2">
                    <p className="truncate text-xs text-muted-foreground">{j.message ?? j.status}</p>
                    {j.result_url ? (
                      <a
                        href={j.result_url}
                        className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                      >
                        <Download className="h-3 w-3" /> Download
                      </a>
                    ) : j.status && ACTIVE.has(j.status) && can('jobs', 'cancel') ? (
                      <button
                        type="button"
                        data-write
                        disabled={readOnly || j.cancel_requested}
                        className="text-xs text-muted-foreground hover:text-destructive disabled:opacity-50"
                        onClick={() =>
                          cancel.mutate(j.id, {
                            onSuccess: () => toast.success('Cancellation requested'),
                            onError: (e) => toast.error(getApiError(e, 'Could not cancel the job')),
                          })
                        }
                      >
                        {j.cancel_requested ? 'Cancelling…' : 'Cancel'}
                      </button>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          )}
          <Link to="/jobs" className="mt-2 block text-xs text-primary hover:underline">
            All jobs →
          </Link>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
