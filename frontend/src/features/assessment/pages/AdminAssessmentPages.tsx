import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input, Select } from '@/components/ui/Input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs';
import { toast } from '@/components/ui/Toaster';
import { SimpleTable, WorkflowPanel } from '@/features/hr/components/shared';
import { assessmentApi } from '../api';
import { useAssessmentMutation, useQ } from '../hooks';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));

function ChangeRequests({ applyAllowed }: { applyAllowed: boolean }) {
  const list = useQ(['changes'], () => assessmentApi.changes());
  const run = useAssessmentMutation((fn: () => Promise<unknown>) => fn());
  return (
    <SimpleTable
      head={['Student', 'Assessment', 'Old → new', 'Reason', 'Status', 'Workflow', '']}
      rows={(list.data?.data ?? []).map((r: Any) => [
        r.student_name,
        r.assessment_name,
        `${r.old_value?.marks ?? '—'} → ${r.new_value?.marks ?? '—'}`,
        r.reason,
        <StatusBadge key="s" status={r.status} />,
        <WorkflowPanel key="w" instanceId={r.workflow_instance_id} />,
        <div key="b" className="flex gap-1">
          {r.can_act && ['requested', 'hod_approved'].includes(r.status) && (
            <>
              <Button size="sm" onClick={() => run.mutate(() => assessmentApi.decideChange(r.id, 'approve'), { onSuccess: () => toast.success('Approved'), onError: fail })}>Approve</Button>
              <Button size="sm" variant="outline" onClick={() => run.mutate(() => assessmentApi.decideChange(r.id, 'reject'), { onError: fail })}>Reject</Button>
            </>
          )}
          {applyAllowed && r.status === 'coe_approved' && <Button size="sm" onClick={() => run.mutate(() => assessmentApi.applyChange(r.id), { onSuccess: () => toast.success('Applied'), onError: fail })}>Apply</Button>}
        </div>,
      ])}
      empty="No change requests."
    />
  );
}

/** `/admin/assessment/verification` — the HOD queue of submitted assessments + CIA approvals + change requests. */
export function MarksVerificationPage() {
  useTitle('Marks verification');
  const queue = useQ(['queue', 'submitted'], () => assessmentApi.queue({ status: 'submitted' }));
  const [comment, setComment] = useState('');
  const run = useAssessmentMutation((fn: () => Promise<unknown>) => fn());
  return (
    <div className="space-y-4">
      <PageHeader title="Marks verification" description="Submitted assessments of your department; reject returns them for correction with your comment." />
      <Tabs defaultValue="queue">
        <TabsList>
          <TabsTrigger value="queue">Submitted ({queue.data?.data?.length ?? 0})</TabsTrigger>
          <TabsTrigger value="changes">Change requests</TabsTrigger>
        </TabsList>
        <TabsContent value="queue">
          <Input className="mb-2 w-96" placeholder="Comment for rejections" value={comment} onChange={(e) => setComment(e.target.value)} />
          <SimpleTable
            head={['Course', 'Assessment', 'Marked', 'Submitted', '']}
            rows={(queue.data?.data ?? []).map((a: Any) => [
              `${a.course_code} ${a.section_code}`,
              a.name,
              `${a.marks_entered}`,
              a.submitted_at ? new Date(a.submitted_at).toLocaleString() : '—',
              <div key="b" className="flex gap-1">
                <Button size="sm" onClick={() => run.mutate(() => assessmentApi.verify(a.id, 'approve'), { onSuccess: () => toast.success('Verified'), onError: fail })}>Verify</Button>
                <Button size="sm" variant="outline" disabled={!comment} onClick={() => run.mutate(() => assessmentApi.verify(a.id, 'reject', comment), { onSuccess: () => toast.success('Returned'), onError: fail })}>Reject</Button>
                <Button size="sm" variant="ghost" onClick={() => run.mutate(() => assessmentApi.approveCia(a.offering_id), { onSuccess: () => toast.success('CIA approved'), onError: fail })}>Approve CIA</Button>
              </div>,
            ])}
            empty="Nothing waiting for verification."
          />
        </TabsContent>
        <TabsContent value="changes"><ChangeRequests applyAllowed={false} /></TabsContent>
      </Tabs>
    </div>
  );
}

/** `/admin/assessment/locks` — exam cell: lock verified assessments, reopen, apply change requests. */
export function MarksLocksPage() {
  useTitle('Marks locks');
  const [status, setStatus] = useState('verified');
  const queue = useQ(['queue', status], () => assessmentApi.queue({ status }));
  const [reason, setReason] = useState('');
  const run = useAssessmentMutation((fn: () => Promise<unknown>) => fn());
  return (
    <div className="space-y-4">
      <PageHeader title="Marks locks" description="Lock verified marks (they feed eligibility and attainment); reopen with a reason; university CIA submission per offering." />
      <Tabs defaultValue="locks">
        <TabsList>
          <TabsTrigger value="locks">Assessments</TabsTrigger>
          <TabsTrigger value="changes">Change requests</TabsTrigger>
        </TabsList>
        <TabsContent value="locks">
          <div className="mb-2 flex gap-2">
            <Select className="w-40" value={status} options={['verified', 'locked', 'submitted', 'marks_entry'].map((s) => ({ value: s, label: s }))} onChange={(e) => setStatus(e.target.value)} />
            <Input className="w-80" placeholder="Reopen reason" value={reason} onChange={(e) => setReason(e.target.value)} />
          </div>
          <SimpleTable
            head={['Course', 'Assessment', 'Status', '']}
            rows={(queue.data?.data ?? []).map((a: Any) => [
              `${a.course_code} ${a.section_code}`,
              a.name,
              <StatusBadge key="s" status={a.status} />,
              <div key="b" className="flex gap-1">
                {a.status === 'verified' && <Button size="sm" onClick={() => run.mutate(() => assessmentApi.lock(a.id), { onSuccess: () => toast.success('Locked'), onError: fail })}>Lock</Button>}
                {['locked', 'verified', 'submitted'].includes(a.status) && <Button size="sm" variant="outline" disabled={!reason} onClick={() => run.mutate(() => assessmentApi.reopen(a.id, reason), { onSuccess: () => toast.success('Reopened'), onError: fail })}>Reopen</Button>}
                <Button size="sm" variant="ghost" onClick={() => run.mutate(() => assessmentApi.lockCia(a.offering_id), { onSuccess: () => toast.success('CIA locked'), onError: fail })}>Lock CIA</Button>
                <Button size="sm" variant="ghost" onClick={() => run.mutate(() => assessmentApi.submitCia(a.offering_id), { onSuccess: () => toast.success('Submitted to the university'), onError: fail })}>Submit CIA</Button>
              </div>,
            ])}
            empty="Nothing in this state."
          />
        </TabsContent>
        <TabsContent value="changes"><ChangeRequests applyAllowed /></TabsContent>
      </Tabs>
    </div>
  );
}

/** `/admin/obe/programs/:id` — PEO / PO / PSO, PEO-PO matrix, template import. */
export function ProgramOutcomesPage() {
  const { id } = useParams();
  useTitle('Programme outcomes');
  const data = useQ(['program-outcomes', id], () => assessmentApi.programOutcomes(id!), !!id);
  const d = data.data?.data;
  const [rows, setRows] = useState<Any[]>([]);
  const [cells, setCells] = useState<Record<string, number>>({});
  useEffect(() => {
    if (!d) return;
    setRows(d.outcomes);
    setCells(Object.fromEntries(d.peo_po.map((c: Any) => [`${c.peo_id}|${c.po_id}`, c.level])));
  }, [d]);
  const run = useAssessmentMutation((fn: () => Promise<unknown>) => fn());
  const peos = (d?.outcomes ?? []).filter((o: Any) => o.outcome_type === 'PEO');
  const pos = (d?.outcomes ?? []).filter((o: Any) => o.outcome_type !== 'PEO');
  return (
    <div className="space-y-4">
      <PageHeader title="Programme outcomes" description="PEO / PO / PSO with the NBA (engineering) or generic template; PEO-PO matrix." />
      <div className="flex gap-2">
        <Button variant="outline" onClick={() => run.mutate(() => assessmentApi.importTemplate(id!), { onSuccess: () => toast.success('Template imported'), onError: fail })}>Import template</Button>
        <Button variant="outline" onClick={() => setRows([...rows, { outcome_type: 'PEO', code: `PEO${peos.length + 1}`, statement: '', sequence: peos.length + 1 }])}>Add PEO</Button>
        <Button onClick={() => run.mutate(() => assessmentApi.saveProgramOutcomes(id!, rows.map((o) => ({ outcome_type: o.outcome_type, code: o.code, statement: o.statement, framework: o.framework ?? null, sequence: o.sequence }))), { onSuccess: () => toast.success('Saved'), onError: fail })}>Save outcomes</Button>
      </div>
      {rows.map((o, i) => (
        <div key={i} className="flex gap-2">
          <span className="w-12 text-sm font-medium">{o.outcome_type}</span>
          <Input className="w-20" value={o.code} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, code: e.target.value } : x)))} />
          <Input value={o.statement} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, statement: e.target.value } : x)))} />
        </div>
      ))}
      {peos.length > 0 && (
        <>
          <h3 className="font-medium">PEO-PO matrix</h3>
          <table className="text-sm">
            <thead><tr><th />{pos.map((p: Any) => <th key={p.id} className="p-1">{p.code}</th>)}</tr></thead>
            <tbody>
              {peos.map((e: Any) => (
                <tr key={e.id}>
                  <td className="p-1 font-medium">{e.code}</td>
                  {pos.map((p: Any) => (
                    <td key={p.id} className="p-1">
                      <select className="rounded border bg-background p-1" value={cells[`${e.id}|${p.id}`] ?? ''} onChange={(ev) => setCells({ ...cells, [`${e.id}|${p.id}`]: Number(ev.target.value) })}>
                        <option value="">–</option>
                        {[1, 2, 3].map((n) => <option key={n} value={n}>{n}</option>)}
                      </select>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <Button onClick={() => run.mutate(() => assessmentApi.savePeoPo(id!, Object.entries(cells).filter(([, v]) => v).map(([k, level]) => { const [peo_id, po_id] = k.split('|'); return { peo_id, po_id, level }; })), { onSuccess: () => toast.success('Matrix saved'), onError: fail })}>Save matrix</Button>
        </>
      )}
    </div>
  );
}

/** `/admin/obe/programs` — pick a programme to edit its outcomes. */
export function ObeProgramsPage() {
  useTitle('OBE definitions');
  const programs = useQ(['programs'], () => import('@/features/academics/api').then((m) => m.academicsApi.programs({ page_size: 200 })));
  return (
    <div className="space-y-4">
      <PageHeader title="OBE definitions" description="Programme outcomes (PEO / PO / PSO); course outcomes are edited from each course." />
      <SimpleTable
        head={['Programme', 'Name', '']}
        rows={((programs.data as Any)?.data ?? []).map((p: Any) => [p.code, p.name, <a key="o" className="text-primary underline" href={`/admin/obe/programs/${p.id}`}>Outcomes</a>])}
      />
    </div>
  );
}
