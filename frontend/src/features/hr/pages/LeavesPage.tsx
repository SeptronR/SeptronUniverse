import { useMemo, useState } from 'react';
import { InsightsPanel } from '@/features/analytics/components/InsightsPanel';
import { useQuery } from '@tanstack/react-query';
import type { ColumnDef } from '@tanstack/react-table';
import { CalendarDays, List, Plus } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { DataTable } from '@/components/shared/DataTable';
import { PageHeader } from '@/components/shared/PageHeader';
import { ScopeTabs } from '@/components/shared/ScopeTabs';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Select, Textarea } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { usePermission } from '@/hooks/usePermission';
import { useReportRun } from '@/features/reports/hooks';
import { hrApi } from '../api';
import { LeaveApplyModal, SimpleTable, WorkflowPanel } from '../components/shared';
import { useHrMutation, useLeaves } from '../hooks';
import { num, type Leave } from '../types';

/** /admin/hr/leaves — ScopeTabs Mine | Team | All driven by meta.visibility (accountant Mine | All, HOD Mine | Team,
 *  HR Mine | All + approvals); calendar view; approve / reject drawer with the workflow timeline. */
export default function LeavesPage() {
  const { can } = usePermission();
  const [params, setParams] = useState<Record<string, string | number | undefined | null>>({ page: 1, page_size: 25 });
  const [view, setView] = useState<'list' | 'calendar'>('list');
  const [applying, setApplying] = useState(false);
  const [open, setOpen] = useState<Leave | null>(null);
  const [comment, setComment] = useState('');
  const list = useLeaves(params);
  const report = useReportRun();
  const queue = useLeaves({ scope: 'all', status: 'pending', page_size: 100 });
  const calendar = useQuery({ queryKey: ['leaves', 'calendar'], queryFn: () => hrApi.calendar(), enabled: view === 'calendar' });
  const decide = useHrMutation(({ id, d }: { id: string; d: 'approve' | 'reject' }) => hrApi.decideLeave(id, d, comment || undefined), ['leaves', 'approvals']);
  const actionable = (queue.data?.data ?? []).filter((l) => l.can_act);
  const set = (patch: Record<string, string | undefined>) => setParams((p) => ({ ...p, ...patch, page: 1 }));
  const columns = useMemo<ColumnDef<Leave, unknown>[]>(
    () => [
      { id: 'who', header: 'Staff', enableSorting: false, cell: ({ row }) => <span>{row.original.staff_name} {row.original.is_mine && <Badge variant="outline">me</Badge>}</span> },
      { id: 'dept', header: 'Dept', enableSorting: false, cell: ({ row }) => row.original.department_code ?? '—' },
      { id: 'type', header: 'Type', enableSorting: false, cell: ({ row }) => row.original.leave_type_code },
      { accessorKey: 'from_date', header: 'From' },
      { accessorKey: 'to_date', header: 'To' },
      { accessorKey: 'days_count', header: 'Days', cell: ({ getValue }) => num(getValue() as string) },
      { accessorKey: 'status', header: 'Status', cell: ({ row }) => <span className="flex items-center gap-1"><StatusBadge status={row.original.status} />{row.original.status === 'pending' && row.original.current_step ? <span className="text-xs text-muted-foreground">step {row.original.current_step}</span> : null}</span> },
      { id: 'act', header: '', enableSorting: false, cell: ({ row }) => (row.original.can_act ? <Badge>awaiting you</Badge> : null) },
    ],
    [],
  );
  const act = (d: 'approve' | 'reject') =>
    open && decide.mutate({ id: open.id, d }, { onSuccess: (r) => { toast.success(`Leave ${r.data.status === 'pending' ? 'moved to the next step' : r.data.status}`); setOpen(null); setComment(''); }, onError: (e) => toast.error(getApiError(e)) });

  return (
    <div className="space-y-4">
      <PageHeader
        title="Leaves"
        description="Apply, track and approve leave. Approvals follow the leave.approval workflow (HOD, then HR)."
        actions={
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => setView(view === 'list' ? 'calendar' : 'list')}>
              {view === 'list' ? <CalendarDays className="h-4 w-4" /> : <List className="h-4 w-4" />} {view === 'list' ? 'Calendar' : 'List'}
            </Button>
            {can('leaves', 'create') && <Button onClick={() => setApplying(true)}><Plus className="h-4 w-4" /> Apply</Button>}
          </div>
        }
      />
      <InsightsPanel module="leaves" />
      {actionable.length > 0 && (
        <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm dark:bg-amber-950/30">
          <b>Approvals queue:</b> {actionable.length} leave(s) await your decision —{' '}
          {actionable.slice(0, 5).map((l) => (
            <button key={l.id} type="button" className="mr-2 text-primary underline" onClick={() => setOpen(l)}>{l.staff_name} ({l.leave_type_code} {num(l.days_count)}d)</button>
          ))}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <ScopeTabs visibility={list.data?.meta.visibility} value={params.scope as string | undefined} onChange={(scope) => set({ scope })} labels={{ department: 'Team', faculty: 'Team' }} />
        <Select className="w-36" placeholder="All statuses" options={['pending', 'approved', 'rejected', 'cancelled'].map((s) => ({ value: s, label: s }))} value={(params.status as string) ?? ''} onChange={(e) => set({ status: e.target.value || undefined })} />
      </div>
      {view === 'list' ? (
        <DataTable
          columns={columns}
          data={list.data?.data ?? []}
          isLoading={list.isLoading}
          pagination={list.data?.meta.pagination}
          onPageChange={(page) => setParams((p) => ({ ...p, page }))}
          onPageSizeChange={(page_size) => setParams((p) => ({ ...p, page_size, page: 1 }))}
          sort={params.sort as string | undefined}
          onSortChange={(sort) => setParams((p) => ({ ...p, sort }))}
          onRowClick={(r) => setOpen(r)}
          rowKey={(r) => r.id}
          // Phase 36: export = the leave register report with the current filters (job → JobsTray)
          onExport={() => void report.run('hr.leave_register', { ...params }, 'xlsx', ['status', 'college_id', 'department_id'])}
        />
      ) : (
        <SimpleTable head={['Staff', 'Dept', 'Type', 'From', 'To', 'Days', 'Status']} rows={(calendar.data?.data ?? []).map((c) => [c.staff_name, c.department_code, c.leave_type_code, c.from_date, c.to_date, num(c.days_count), <StatusBadge key={c.id} status={c.status} />])} empty="No leave in the next two months." />
      )}

      <Modal
        open={open !== null}
        onOpenChange={(o) => !o && setOpen(null)}
        title={open ? `${open.staff_name} · ${open.leave_type_name ?? open.leave_type_code}` : ''}
        description={open ? `${open.from_date} → ${open.to_date} · ${num(open.days_count)} day(s) · ${open.reason ?? ''}` : ''}
        size="lg"
        footer={
          open?.can_act && can('leaves', 'approve') ? (
            <div className="flex gap-2">
              <Button variant="destructive" loading={decide.isPending} onClick={() => act('reject')}>Reject</Button>
              <Button loading={decide.isPending} onClick={() => act('approve')}>Approve</Button>
            </div>
          ) : undefined
        }
      >
        <div className="space-y-3">
          <StatusBadge status={open?.status ?? ''} />
          <WorkflowPanel instanceId={open?.workflow_instance_id} />
          {open?.can_act && <Textarea aria-label="Comment" placeholder="Comment (optional)" value={comment} onChange={(e) => setComment(e.target.value)} />}
        </div>
      </Modal>
      <LeaveApplyModal open={applying} onOpenChange={setApplying} />
    </div>
  );
}
