import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Plus, Trash2 } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input, Select } from '@/components/ui/Input';
import { toast } from '@/components/ui/Toaster';
import { usePermission } from '@/hooks/usePermission';
import { useDepartments } from '@/features/institution/hooks';
import { academicsApi } from '@/features/academics/api';
import { hrApi } from '../api';
import { SimpleTable, WorkflowPanel } from '../components/shared';
import { useHrMutation, useStaffList } from '../hooks';
import { label } from '../types';

const LOAD: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = { over: 'destructive', within: 'default', under: 'secondary', no_norm: 'outline' };

/** /admin/hr/workload — department grid vs cadre norms; HOD course-allocation proposal → dean approval → apply. */
export default function WorkloadPage() {
  const { can } = usePermission();
  const departments = useDepartments({ page_size: 200 });
  const [dept, setDept] = useState('');
  const deptId = dept || departments.data?.data[0]?.id || '';
  const grid = useQuery({ queryKey: ['workload', deptId], queryFn: () => hrApi.workload(deptId), enabled: !!deptId, retry: false });
  const proposal = useQuery({ queryKey: ['workload', 'allocation', deptId], queryFn: () => hrApi.allocation(deptId), enabled: !!deptId && can('faculty', 'workload_manage'), retry: false });
  const courses = useQuery({ queryKey: ['courses', { department_id: deptId }], queryFn: () => academicsApi.courses({ department_id: deptId, page_size: 200 }), enabled: !!deptId });
  const staff = useStaffList({ scope: 'all', department_id: deptId, staff_category: 'teaching', page_size: 200 }, !!deptId);
  const [rows, setRows] = useState<{ course_id: string; staff_id: string; hours: number; role: string }[] | null>(null);
  const items = rows ?? proposal.data?.data.proposals ?? [];
  const save = useHrMutation(() => hrApi.saveAllocation(deptId, items), ['workload']);
  const act = useHrMutation(({ id, a }: { id: string; a: 'submit' | 'approve' | 'apply' }) => hrApi.allocationAction(id, a), ['workload', 'approvals']);
  const p = proposal.data?.data;
  const editable = !p || p.status === 'draft';

  return (
    <div className="space-y-4">
      <PageHeader title="Workload" description="Weekly teaching (from Phase 09 offerings) + admin hours against the cadre norm." />
      <Select aria-label="Department" className="w-60" options={(departments.data?.data ?? []).map((d) => ({ value: d.id, label: `${d.code} · ${d.name}` }))} value={deptId} onChange={(e) => { setDept(e.target.value); setRows(null); }} />
      {grid.error && <p className="text-sm text-muted-foreground">{getApiError(grid.error)}</p>}
      <SimpleTable
        head={['Staff', 'Cadre', 'Theory', 'Tutorial', 'Lab', 'Admin', 'Total', 'Norm', 'Load']}
        rows={(grid.data?.data ?? []).map((w) => [`${w.employee_id} · ${w.staff_name}`, label(w.cadre), w.theory_hours, w.tutorial_hours, w.lab_hours, w.admin_hours, <b key="t">{w.total_hours}</b>, w.norm_hours ?? '—', <Badge key="l" variant={LOAD[w.load_status]}>{w.load_status}</Badge>])}
      />
      {grid.data?.data[0]?.note && <p className="text-xs text-muted-foreground">{grid.data.data[0].note}</p>}

      {can('faculty', 'workload_manage') && p && (
        <div className="space-y-2">
          <h2 className="flex items-center gap-2 text-lg font-semibold">Course-allocation proposal <StatusBadge status={p.status} /></h2>
          {p.note && <p className="text-xs text-muted-foreground">{p.note}</p>}
          <SimpleTable
            head={['Course', 'Staff', 'Hours/week', 'Role', '']}
            rows={items.map((it, i) => [
              <Select key="c" aria-label="Course" disabled={!editable} placeholder="Course…" options={(courses.data?.data ?? []).map((c) => ({ value: c.id, label: `${c.code} · ${c.title}` }))} value={it.course_id} onChange={(e) => setRows(items.map((x, j) => (j === i ? { ...x, course_id: e.target.value } : x)))} />,
              <Select key="s" aria-label="Staff" disabled={!editable} placeholder="Staff…" options={(staff.data?.data ?? []).map((s) => ({ value: s.id, label: s.full_name }))} value={it.staff_id} onChange={(e) => setRows(items.map((x, j) => (j === i ? { ...x, staff_id: e.target.value } : x)))} />,
              <Input key="h" aria-label="Hours" disabled={!editable} type="number" className="w-20" value={it.hours} onChange={(e) => setRows(items.map((x, j) => (j === i ? { ...x, hours: Number(e.target.value) } : x)))} />,
              it.role,
              editable ? <Button key="d" size="icon" variant="ghost" aria-label="Remove" onClick={() => setRows(items.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></Button> : null,
            ])}
            empty="No allocations yet."
          />
          <div className="flex flex-wrap gap-2">
            {editable && <Button variant="outline" onClick={() => setRows([...items, { course_id: '', staff_id: '', hours: 3, role: 'instructor' }])}><Plus className="h-4 w-4" /> Row</Button>}
            {editable && <Button disabled={items.some((x) => !x.course_id || !x.staff_id)} onClick={() => save.mutate(undefined, { onSuccess: () => { toast.success('Saved'); setRows(null); }, onError: (e) => toast.error(getApiError(e)) })}>Save draft</Button>}
            {p.status === 'draft' && p.id !== '00000000-0000-0000-0000-000000000000' && <Button variant="outline" onClick={() => act.mutate({ id: p.id, a: 'submit' }, { onSuccess: () => toast.success('Submitted to the dean'), onError: (e) => toast.error(getApiError(e)) })}>Submit to dean</Button>}
            {p.status === 'submitted' && <Button onClick={() => act.mutate({ id: p.id, a: 'approve' }, { onSuccess: () => toast.success('Approved'), onError: (e) => toast.error(getApiError(e)) })}>Approve (dean)</Button>}
            {p.status === 'dean_approved' && <Button onClick={() => act.mutate({ id: p.id, a: 'apply' }, { onSuccess: () => toast.success('Applied'), onError: (e) => toast.error(getApiError(e)) })}>Apply to offerings</Button>}
          </div>
          {p.workflow_instance_id && <WorkflowPanel instanceId={p.workflow_instance_id} />}
        </div>
      )}
    </div>
  );
}
