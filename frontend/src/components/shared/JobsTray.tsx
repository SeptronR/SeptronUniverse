import { useEffect, useState } from 'react';
import * as Popover from '@radix-ui/react-popover';
import { Activity, CheckCircle2, Download, XCircle } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { wsClient } from '@/lib/ws';
import { cn } from '@/utils/cn';

export interface JobEvent {
  job_id: string;
  job_type?: string;
  status?: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';
  progress_pct?: number;
  message?: string | null;
  result_url?: string | null;
}

/**
 * Navbar jobs tray: listens on the WebSocket channel `jobs:{user}` and shows progress of background jobs
 * (Phase 01 adds the `/jobs` polling fallback and cancel action).
 */
export function JobsTray() {
  const [jobs, setJobs] = useState<Record<string, JobEvent>>({});

  useEffect(
    () =>
      wsClient.subscribe('jobs', (data) => {
        const ev = data as JobEvent;
        if (!ev?.job_id) return;
        setJobs((prev) => ({ ...prev, [ev.job_id]: { ...prev[ev.job_id], ...ev } }));
      }),
    [],
  );

  const list = Object.values(jobs);
  const active = list.filter((j) => !j.status || j.status === 'queued' || j.status === 'running').length;

  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <Button variant="ghost" size="icon" aria-label="Background jobs" className="relative">
          <Activity className={cn('h-5 w-5', active > 0 && 'animate-pulse text-primary')} />
          {active > 0 && (
            <span className="absolute -right-0.5 -top-0.5 rounded-full bg-primary px-1 text-[10px] font-semibold text-primary-foreground">
              {active}
            </span>
          )}
        </Button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content align="end" sideOffset={8} className="z-50 w-80 rounded-md border bg-popover p-3 text-sm shadow-md">
          <p className="mb-2 font-medium">Background jobs</p>
          {list.length === 0 ? (
            <p className="text-muted-foreground">No jobs in this session.</p>
          ) : (
            <ul className="max-h-72 space-y-2 overflow-y-auto">
              {list.map((j) => (
                <li key={j.job_id} className="rounded-md border p-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate font-medium">{j.job_type ?? j.job_id.slice(0, 8)}</span>
                    {j.status === 'succeeded' ? (
                      <CheckCircle2 className="h-4 w-4 text-status-approved" />
                    ) : j.status === 'failed' || j.status === 'cancelled' ? (
                      <XCircle className="h-4 w-4 text-status-rejected" />
                    ) : (
                      <span className="text-xs text-muted-foreground">{j.progress_pct ?? 0}%</span>
                    )}
                  </div>
                  <div className="mt-1 h-1.5 w-full rounded bg-muted">
                    <div className="h-1.5 rounded bg-primary transition-all" style={{ width: `${j.progress_pct ?? 0}%` }} />
                  </div>
                  {j.message && <p className="mt-1 truncate text-xs text-muted-foreground">{j.message}</p>}
                  {j.result_url && (
                    <a href={j.result_url} className="mt-1 inline-flex items-center gap-1 text-xs text-primary hover:underline">
                      <Download className="h-3 w-3" /> Download
                    </a>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
