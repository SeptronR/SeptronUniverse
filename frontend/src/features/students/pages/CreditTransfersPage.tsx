import { useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { getApiError } from '@/api/axios';
import { DataTable } from '@/components/shared/DataTable';
import { PageHeader } from '@/components/shared/PageHeader';
import { ScopeTabs } from '@/components/shared/ScopeTabs';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input, Select, Textarea } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { usePermission } from '@/hooks/usePermission';
import { useCourses } from '@/features/academics/hooks';
import { studentsApi } from '../api';
import { StudentLink } from '../components/shared';
import { useCreditTransfers, useStudentMutation } from '../hooks';
import { CT_SOURCES, label, type CreditTransfer } from '../types';

type Action = 'verify' | 'approve' | 'reject';

/** /admin/students/credit-transfers — verification queue: department verifies with the equivalent course, the
 *  registrar approves (MOOC credits are capped by the regulation; result rows arrive with Phase 15). */
export default function CreditTransfersPage() {
  const { can } = usePermission();
  const [params, setParams] = useState<Record<string, string | number | undefined>>({ page: 1, page_size: 25, status: 'submitted' });
  const list = useCreditTransfers(params);
  const [acting, setActing] = useState<{ ct: CreditTransfer; action: Action } | null>(null);
  const [courseQ, setCourseQ] = useState('');
  const [form, setForm] = useState({ equivalent_course_id: '', comment: '' });
  const courses = useCourses({ q: courseQ || undefined, page_size: 20 }, acting?.action === 'verify');
  const mutation = useStudentMutation(
    (a: { id: string; action: Action; body: Record<string, unknown> }) => studentsApi.creditTransferAction(a.id, a.action, a.body),
    ['credit-transfers', 'students'],
  );
  const set = (patch: Record<string, string | undefined>) => setParams((p) => ({ ...p, ...patch, page: 1 }));
  const open = (ct: CreditTransfer, action: Action) => {
    setForm({ equivalent_course_id: ct.equivalent_course_id ?? '', comment: '' });
    setCourseQ('');
    setActing({ ct, action });
  };
  const columns = useMemo<ColumnDef<CreditTransfer, unknown>[]>(
    () => [
      { id: 'student', header: 'Student', cell: ({ row }) => <StudentLink id={row.original.student_id}><span className="font-mono text-xs">{row.original.registration_number}</span> {row.original.student_name}</StudentLink> },
      { accessorKey: 'source', header: 'Source', cell: ({ getValue }) => label(String(getValue())) },
      { accessorKey: 'source_title', header: 'Course', cell: ({ row }) => `${row.original.source_course_code ?? ''} ${row.original.source_title}` },
      { accessorKey: 'credits', header: 'Credits' },
      { id: 'grade', header: 'Grade', enableSorting: false, cell: ({ row }) => `${row.original.source_grade ?? row.original.source_score_pct ?? '—'}${row.original.letter_grade ? ` → ${row.original.letter_grade}` : ''}` },
      { id: 'cert', header: 'Certificate', enableSorting: false, cell: ({ row }) => (row.original.certificate_url ? <a className="text-primary underline" href={row.original.certificate_url} target="_blank" rel="noreferrer">open</a> : '—') },
      { id: 'eq', header: 'Equivalent', enableSorting: false, cell: ({ row }) => row.original.equivalent_course ?? '—' },
      { accessorKey: 'status', header: 'Status', cell: ({ getValue }) => <StatusBadge status={String(getValue())} /> },
      {
        id: 'act',
        header: '',
        enableSorting: false,
        cell: ({ row }) => {
          const c = row.original;
          return (
            <div className="flex gap-1">
              {c.status === 'submitted' && can('credit_transfers', 'verify') && <Button size="sm" onClick={() => open(c, 'verify')}>Verify</Button>}
              {c.status === 'verified' && can('credit_transfers', 'approve') && <Button size="sm" onClick={() => open(c, 'approve')}>Approve</Button>}
              {['submitted', 'verified'].includes(c.status) && <Button size="sm" variant="outline" onClick={() => open(c, 'reject')}>Reject</Button>}
            </div>
          );
        },
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const submit = () =>
    acting &&
    mutation.mutate(
      { id: acting.ct.id, action: acting.action, body: { equivalent_course_id: form.equivalent_course_id || undefined, comment: form.comment || undefined } },
      { onSuccess: () => { toast.success(`${label(acting.action)} done`); setActing(null); }, onError: (e) => toast.error(getApiError(e)) },
    );

  return (
    <div className="space-y-4">
      <PageHeader title="Credit transfers" description="MOOC (SWAYAM / NPTEL), ABC and prior-institution credits awaiting verification and approval." />
      <div className="flex flex-wrap items-center gap-2">
        <ScopeTabs visibility={list.data?.meta.visibility} value={params.scope as string | undefined} onChange={(scope) => set({ scope })} />
        <Select className="w-36" aria-label="Status" placeholder="All statuses" options={['submitted', 'verified', 'approved', 'rejected', 'credited'].map((s) => ({ value: s, label: label(s) }))} value={(params.status as string) ?? ''} onChange={(e) => set({ status: e.target.value || undefined })} />
        <Select className="w-40" aria-label="Source" placeholder="All sources" options={CT_SOURCES.map((s) => ({ value: s, label: label(s) }))} value={(params.source as string) ?? ''} onChange={(e) => set({ source: e.target.value || undefined })} />
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
        emptyTitle="Nothing in the queue"
      />
      <Modal
        open={acting !== null}
        onOpenChange={(o) => !o && setActing(null)}
        title={`${label(acting?.action)} — ${acting?.ct.source_title ?? ''}`}
        description={acting ? `${acting.ct.registration_number} · ${acting.ct.credits} credits · ${label(acting.ct.source)}` : ''}
        footer={
          <Button
            variant={acting?.action === 'reject' ? 'destructive' : 'default'}
            loading={mutation.isPending}
            disabled={(acting?.action === 'verify' && !form.equivalent_course_id) || (acting?.action === 'reject' && form.comment.trim().length < 3)}
            onClick={submit}
          >
            {label(acting?.action)}
          </Button>
        }
      >
        <div className="space-y-3">
          {acting?.action === 'verify' && (
            <>
              <Input aria-label="Search courses" placeholder="Search equivalent course…" value={courseQ} onChange={(e) => setCourseQ(e.target.value)} />
              <Select aria-label="Equivalent course" placeholder="Choose the equivalent course" options={(courses.data?.data ?? []).map((c) => ({ value: c.id, label: `${c.code} · ${c.title} (${c.credits} cr${c.regulation_code ? ` · ${c.regulation_code}` : ''})` }))} value={form.equivalent_course_id} onChange={(e) => setForm({ ...form, equivalent_course_id: e.target.value })} />
            </>
          )}
          <Textarea aria-label="Comment" placeholder={acting?.action === 'reject' ? 'Reason (required)' : 'Comment (optional)'} value={form.comment} onChange={(e) => setForm({ ...form, comment: e.target.value })} />
        </div>
      </Modal>
    </div>
  );
}
