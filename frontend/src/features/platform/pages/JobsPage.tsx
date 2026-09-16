import { useEffect, useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import type { ColumnDef } from '@tanstack/react-table';
import { Download, Play, XCircle } from 'lucide-react';
import { PageHeader } from '@/components/shared/PageHeader';
import { DataTable } from '@/components/shared/DataTable';
import { ScopeTabs } from '@/components/shared/ScopeTabs';
import { Button } from '@/components/ui/Button';
import { Select } from '@/components/ui/Input';
import { StatusBadge } from '@/components/ui/Badge';
import { toast } from '@/components/ui/Toaster';
import { getApiError } from '@/api/axios';
import { usePermission } from '@/hooks/usePermission';
import { wsClient } from '@/lib/ws';
import { formatDateTime, formatRelative } from '@/utils/formatters';
import { DEFAULT_PAGE_SIZE } from '@/utils/constants';
import type { ScopeName } from '@/utils/types';
import { jobKeys, useCancelJob, useDevSleepJob, useJobs, useReadOnly } from '../hooks';
import type { Job, JobStatus } from '../types';

const STATUSES: JobStatus[] = ['queued', 'running', 'succeeded', 'failed', 'cancelled'];
const ACTIVE: JobStatus[] = ['queued', 'running'];

/**
 * /jobs — background jobs of the signed-in user (Mine) or the institution (All with jobs:view_all).
 * Live updates: WebSocket `jobs:{user}` events patch the cached rows; polling every 5 s while a job is active
 * covers a dropped socket (Prompts/01 §01.9).
 */
export default function JobsPage() {
  const [params, setParams] = useSearchParams();
  const qc = useQueryClient();
  const { can } = usePermission();
  const readOnly = useReadOnly();
  const cancel = useCancelJob();
  const devSleep = useDevSleepJob();
  const [live, setLive] = useState<Record<string, Partial<Job>>>({});

  const page = Number(params.get('page') ?? 1);
  const pageSize = Number(params.get('page_size') ?? DEFAULT_PAGE_SIZE);
  const sort = params.get('sort');
  const scope = params.get('scope') ?? undefined;
  const status = (params.get('status') as JobStatus | null) ?? undefined;
  const query = useJobs(
    { page, page_size: pageSize, sort: sort ?? undefined, scope, status },
    { refetchInterval: 5_000 },
  );

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== 'page') next.delete('page');
    setParams(next, { replace: true });
  };

  useEffect(
    () =>
      wsClient.subscribe('jobs', (data) => {
        const ev = data as Partial<Job> & { job_id?: string };
        if (!ev?.job_id) return;
        setLive((prev) => ({ ...prev, [ev.job_id!]: { ...prev[ev.job_id!], ...ev } }));
        if (ev.status && !ACTIVE.includes(ev.status)) void qc.invalidateQueries({ queryKey: jobKeys.all });
      }),
    [qc],
  );

  const rows = useMemo(
    () => (query.data?.data ?? []).map((j) => ({ ...j, ...(live[j.id] ?? {}) })),
    [query.data, live],
  );
  const visibility = query.data?.meta.visibility;

  const columns = useMemo<ColumnDef<Job, unknown>[]>(
    () => [
      {
        accessorKey: 'job_type',
        header: 'Type',
        cell: ({ row }) => <span className="font-medium">{row.original.job_type}</span>,
      },
      { accessorKey: 'status', header: 'Status', cell: ({ row }) => <StatusBadge status={row.original.status} /> },
      {
        id: 'progress',
        header: 'Progress',
        enableSorting: false,
        cell: ({ row }) => (
          <div className="min-w-[10rem]">
            <div
              className="h-2 w-full rounded bg-muted"
              role="progressbar"
              aria-valuenow={row.original.progress_pct}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <div
                className="h-2 rounded bg-primary transition-all"
                style={{ width: `${row.original.progress_pct}%` }}
              />
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              {row.original.progress_pct}%{row.original.message ? ` · ${row.original.message}` : ''}
            </p>
          </div>
        ),
      },
      {
        accessorKey: 'created_at',
        header: 'Queued',
        cell: ({ row }) => (
          <span title={formatDateTime(row.original.created_at)}>{formatRelative(row.original.created_at)}</span>
        ),
      },
      {
        accessorKey: 'finished_at',
        header: 'Finished',
        cell: ({ row }) => (row.original.finished_at ? formatDateTime(row.original.finished_at) : '—'),
      },
      {
        id: 'result',
        header: 'Result',
        enableSorting: false,
        cell: ({ row }) =>
          row.original.result_url ? (
            <a href={row.original.result_url} className="inline-flex items-center gap-1 text-primary hover:underline">
              <Download className="h-3.5 w-3.5" /> Download
            </a>
          ) : row.original.error ? (
            <span className="text-xs text-destructive" title={row.original.error}>
              {row.original.error.slice(0, 60)}
            </span>
          ) : (
            '—'
          ),
      },
      {
        id: 'actions',
        header: '',
        enableSorting: false,
        cell: ({ row }) =>
          ACTIVE.includes(row.original.status) && can('jobs', 'cancel') ? (
            <Button
              variant="ghost"
              size="sm"
              data-write
              disabled={readOnly || row.original.cancel_requested}
              loading={cancel.isPending && cancel.variables === row.original.id}
              onClick={() =>
                cancel.mutate(row.original.id, {
                  onSuccess: () => toast.success('Cancellation requested'),
                  onError: (e) => toast.error(getApiError(e, 'Could not cancel the job')),
                })
              }
            >
              <XCircle className="h-4 w-4" /> Cancel
            </Button>
          ) : null,
      },
    ],
    [can, cancel, readOnly],
  );

  return (
    <div className="space-y-4">
      <PageHeader
        title="Background jobs"
        description="Bulk PDFs, imports, exports and computations run here; results stay for 7 days."
        actions={
          import.meta.env.DEV && can('jobs', 'view') ? (
            <Button
              variant="outline"
              size="sm"
              data-write
              disabled={readOnly}
              loading={devSleep.isPending}
              onClick={() =>
                devSleep.mutate(5, {
                  onSuccess: () => toast.success('Sleep job queued (dev)'),
                  onError: (e) => toast.error(getApiError(e, 'Could not queue the job')),
                })
              }
            >
              <Play className="h-4 w-4" /> Run test job
            </Button>
          ) : undefined
        }
      />
      <div className="flex flex-wrap items-center gap-3">
        <ScopeTabs visibility={visibility} value={scope} onChange={(s: ScopeName) => setParam('scope', s)} />
        <Select
          aria-label="Status"
          className="w-44"
          placeholder="All statuses"
          value={status ?? ''}
          onChange={(e) => setParam('status', e.target.value || null)}
          options={STATUSES.map((s) => ({ value: s, label: s }))}
        />
      </div>
      <DataTable
        columns={columns}
        data={rows}
        isLoading={query.isLoading}
        pagination={query.data?.meta.pagination}
        onPageChange={(p) => setParam('page', String(p))}
        onPageSizeChange={(s) => setParam('page_size', String(s))}
        sort={sort}
        onSortChange={(s) => setParam('sort', s)}
        rowKey={(r) => r.id}
        emptyTitle="No jobs yet"
        emptyDescription="Exports and bulk actions you start will appear here with live progress."
      />
    </div>
  );
}
