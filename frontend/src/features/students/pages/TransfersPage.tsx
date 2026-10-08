import { useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { getApiError } from '@/api/axios';
import { DataTable } from '@/components/shared/DataTable';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input, Select } from '@/components/ui/Input';
import { toast } from '@/components/ui/Toaster';
import { usePermission } from '@/hooks/usePermission';
import { formatDate } from '@/utils/formatters';
import { studentsApi } from '../api';
import { StudentLink } from '../components/shared';
import { useStudentMutation, useTransfersQueue } from '../hooks';
import { TRANSFER_TYPES, label, type Transfer } from '../types';

/** /admin/students/transfers — transfer / migration requests; approve / reject at the caller's workflow step, then
 *  complete (assigns TC / migration certificate numbers and marks the student transferred). */
export default function TransfersPage() {
  const { can } = usePermission();
  const [params, setParams] = useState<Record<string, string | number | undefined>>({ page: 1, page_size: 25 });
  const list = useTransfersQueue(params);
  const act = useStudentMutation(
    (a: { id: string; action: 'approve' | 'reject' | 'complete' }) => studentsApi.transferAction(a.id, a.action),
    ['student-transfers', 'students'],
  );
  const set = (patch: Record<string, string | undefined>) => setParams((p) => ({ ...p, ...patch, page: 1 }));
  const go = (id: string, action: 'approve' | 'reject' | 'complete') =>
    act.mutate({ id, action }, { onSuccess: () => toast.success({ approve: 'Approved', reject: 'Rejected', complete: 'Transfer completed' }[action]), onError: (e) => toast.error(getApiError(e)) });
  const columns = useMemo<ColumnDef<Transfer, unknown>[]>(
    () => [
      { id: 'student', header: 'Student', cell: ({ row }) => <StudentLink id={row.original.student_id}><span className="font-mono text-xs">{row.original.registration_number}</span> {row.original.student_name}</StudentLink> },
      { accessorKey: 'transfer_type', header: 'Type', cell: ({ getValue }) => label(String(getValue())) },
      { id: 'to', header: 'To', enableSorting: false, cell: ({ row }) => String(row.original.to_ref?.name ?? row.original.to_ref?.institution ?? '—') },
      { accessorKey: 'requested_at', header: 'Requested', cell: ({ row }) => formatDate(row.original.requested_at) },
      { accessorKey: 'status', header: 'Status', cell: ({ row }) => <span><StatusBadge status={row.original.status} /> {row.original.current_step ? <span className="text-xs text-muted-foreground">step {row.original.current_step}</span> : null}</span> },
      { id: 'certs', header: 'TC / migration', enableSorting: false, cell: ({ row }) => [row.original.tc_no, row.original.migration_certificate_no].filter(Boolean).join(' · ') || '—' },
      {
        id: 'act',
        header: '',
        enableSorting: false,
        cell: ({ row }) => (
          <div className="flex gap-1">
            {row.original.can_act && <Button size="sm" onClick={() => go(row.original.id, 'approve')}>Approve</Button>}
            {row.original.can_act && <Button size="sm" variant="outline" onClick={() => go(row.original.id, 'reject')}>Reject</Button>}
            {row.original.status === 'approved' && can('students', 'transfer') && <Button size="sm" onClick={() => go(row.original.id, 'complete')}>Complete</Button>}
          </div>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  return (
    <div className="space-y-4">
      <PageHeader title="Transfers" description="Transfer and migration requests (registrar → dues check → principal)." />
      <div className="flex flex-wrap items-center gap-2">
        <Select className="w-36" aria-label="Status" placeholder="All statuses" options={['requested', 'dues_check', 'approved', 'rejected', 'completed'].map((s) => ({ value: s, label: label(s) }))} value={(params.status as string) ?? ''} onChange={(e) => set({ status: e.target.value || undefined })} />
        <Select className="w-44" aria-label="Type" placeholder="All types" options={TRANSFER_TYPES.map((t) => ({ value: t, label: label(t) }))} value={(params.transfer_type as string) ?? ''} onChange={(e) => set({ transfer_type: e.target.value || undefined })} />
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
        emptyTitle="No transfer requests"
      />
    </div>
  );
}
