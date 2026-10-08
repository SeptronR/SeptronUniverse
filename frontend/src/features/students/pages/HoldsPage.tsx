import { useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { getApiError } from '@/api/axios';
import { DataTable } from '@/components/shared/DataTable';
import { PageHeader } from '@/components/shared/PageHeader';
import { ScopeTabs } from '@/components/shared/ScopeTabs';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input, Select, Textarea } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { formatDateTime } from '@/utils/formatters';
import { studentsApi } from '../api';
import { StudentLink } from '../components/shared';
import { useHoldsQueue, useStudentMutation } from '../hooks';
import { HOLD_TYPES, label, type Hold } from '../types';

/** /admin/students/holds — open / released holds queue; release needs a reason (library / hostel staff release their own types). */
export default function HoldsPage() {
  const [params, setParams] = useState<Record<string, string | number | undefined>>({ page: 1, page_size: 25, status: 'open' });
  const list = useHoldsQueue(params);
  const [release, setRelease] = useState<{ hold: Hold; reason: string } | null>(null);
  const mutation = useStudentMutation((r: { id: string; reason: string }) => studentsApi.releaseHold(r.id, r.reason), ['student-holds', 'students']);
  const set = (patch: Record<string, string | undefined>) => setParams((p) => ({ ...p, ...patch, page: 1 }));
  const columns = useMemo<ColumnDef<Hold, unknown>[]>(
    () => [
      { id: 'student', header: 'Student', cell: ({ row }) => <StudentLink id={row.original.student_id}><span className="font-mono text-xs">{row.original.registration_number}</span> {row.original.student_name}</StudentLink> },
      { accessorKey: 'hold_type', header: 'Type', cell: ({ getValue }) => <Badge variant="destructive">{label(String(getValue()))}</Badge> },
      { accessorKey: 'reason', header: 'Reason', enableSorting: false },
      { accessorKey: 'placed_at', header: 'Placed', cell: ({ row }) => `${formatDateTime(row.original.placed_at)} · ${row.original.placed_by_name ?? ''}` },
      { id: 'released', header: 'Released', enableSorting: false, cell: ({ row }) => (row.original.released_at ? `${formatDateTime(row.original.released_at)} — ${row.original.release_reason ?? ''}` : '—') },
      {
        id: 'act',
        header: '',
        enableSorting: false,
        cell: ({ row }) =>
          row.original.is_open && row.original.can_release ? (
            <Button size="sm" variant="outline" onClick={() => setRelease({ hold: row.original, reason: '' })}>Release</Button>
          ) : null,
      },
    ],
    [],
  );
  return (
    <div className="space-y-4">
      <PageHeader title="Holds" description="Holds block registration, exams, transcripts or graduation until released. Students and guardians are notified both ways." />
      <div className="flex flex-wrap items-center gap-2">
        <ScopeTabs visibility={list.data?.meta.visibility} value={params.scope as string | undefined} onChange={(scope) => set({ scope })} />
        <Select className="w-32" aria-label="Status" options={['open', 'released', 'all'].map((s) => ({ value: s, label: label(s) }))} value={String(params.status)} onChange={(e) => set({ status: e.target.value })} />
        <Select className="w-36" aria-label="Hold type" placeholder="All types" options={HOLD_TYPES.map((t) => ({ value: t, label: label(t) }))} value={(params.hold_type as string) ?? ''} onChange={(e) => set({ hold_type: e.target.value || undefined })} />
        <Input className="w-56" placeholder="Search student…" value={(params.q as string) ?? ''} onChange={(e) => set({ q: e.target.value || undefined })} />
      </div>
      <DataTable
        columns={columns}
        data={list.data?.data ?? []}
        isLoading={list.isLoading}
        pagination={list.data?.meta.pagination}
        onPageChange={(page) => setParams((p) => ({ ...p, page }))}
        onPageSizeChange={(page_size) => setParams((p) => ({ ...p, page_size, page: 1 }))}
        rowKey={(r) => r.id}
        emptyTitle="No holds"
      />
      <Modal
        open={release !== null}
        onOpenChange={(o) => !o && setRelease(null)}
        title={`Release ${label(release?.hold.hold_type)} hold — ${release?.hold.registration_number ?? ''}`}
        description={release?.hold.reason}
        footer={
          <Button
            loading={mutation.isPending}
            disabled={(release?.reason.trim().length ?? 0) < 3}
            onClick={() =>
              release &&
              mutation.mutate({ id: release.hold.id, reason: release.reason }, {
                onSuccess: () => { toast.success('Hold released'); setRelease(null); },
                onError: (e) => toast.error(getApiError(e)),
              })
            }
          >
            Release
          </Button>
        }
      >
        <Textarea aria-label="Release reason" placeholder="Why is it released?" value={release?.reason ?? ''} onChange={(e) => release && setRelease({ ...release, reason: e.target.value })} />
      </Modal>
    </div>
  );
}
