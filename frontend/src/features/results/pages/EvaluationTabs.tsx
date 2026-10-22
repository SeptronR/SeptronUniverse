import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input, Select } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { SimpleTable } from '@/features/hr/components/shared';
import { examsApi, openBlob } from '@/features/exams/api';
import { usePermission } from '@/hooks/usePermission';
import { resultsApi } from '../api';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const fail = (e: unknown) => toast.error(getApiError(e));
const useQ = <T,>(key: unknown[], fn: () => Promise<T>, enabled = true) => useQuery({ queryKey: ['results', ...key], queryFn: fn, enabled, retry: false });
function useRun() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: () => qc.invalidateQueries({ queryKey: ['results'] }) });
}

function PaperPicker({ sessionId, value, onChange }: { sessionId: string; value: string; onChange: (v: string) => void }) {
  const papers = useQuery({ queryKey: ['exams', 'papers', sessionId], queryFn: () => examsApi.papers(sessionId), retry: false });
  return (
    <Select
      className="w-80"
      value={value}
      placeholder="Choose a paper"
      options={(papers.data?.data ?? []).map((p: Any) => ({ value: p.id, label: `${p.paper_code ?? ''} ${p.course_code ?? ''} · ${p.paper_type} · ${p.status}` }))}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

// ---- Coding ------------------------------------------------------------------------------------------------------------
export function CodingTab({ id }: { id: string }) {
  const [paper, setPaper] = useState('');
  const [size, setSize] = useState(30);
  const [timeline, setTimeline] = useState<string | null>(null);
  const bundles = useQ(['bundles', paper], () => resultsApi.bundles(paper), !!paper);
  const log = useQ(['custody', timeline], () => resultsApi.custody(timeline!), !!timeline);
  const run = useRun();
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <PaperPicker sessionId={id} value={paper} onChange={setPaper} />
        <Input type="number" className="w-24" value={size} onChange={(e) => setSize(Number(e.target.value) || 30)} />
        <Button disabled={!paper} onClick={() => run.mutate(() => resultsApi.createBundles(paper, size), { onSuccess: () => toast.success('Bundles created'), onError: fail })}>Create bundles</Button>
      </div>
      <SimpleTable
        head={['Bundle', 'Room', 'Scripts', 'Status', 'Rounds', '']}
        rows={(bundles.data?.data ?? []).map((b: Any) => [
          b.bundle_number,
          b.room_code ?? '—',
          b.script_count,
          <StatusBadge key="s" status={b.status} />,
          b.rounds.map((r: Any) => <Badge key={r.round} variant="outline" className="mr-1">R{r.round} {r.status}</Badge>),
          <div key="a" className="flex gap-1">
            {b.status === 'created' && <Button size="sm" onClick={() => run.mutate(() => resultsApi.code(b.id), { onSuccess: () => toast.success('Coded'), onError: fail })}>Code</Button>}
            {['coded', 'received'].includes(b.status) && <Button size="sm" variant="outline" onClick={() => run.mutate(() => resultsApi.logCustody(b.id, { action: 'dispatched', location: window.prompt('Location') ?? undefined }), { onError: fail })}>Dispatch</Button>}
            {b.status === 'dispatched' && <Button size="sm" variant="outline" onClick={() => run.mutate(() => resultsApi.logCustody(b.id, { action: 'received', location: window.prompt('Location') ?? undefined }), { onError: fail })}>Receive</Button>}
            <Button size="sm" variant="ghost" onClick={() => setTimeline(b.id)}>Custody</Button>
          </div>,
        ])}
      />
      <Modal open={!!timeline} onOpenChange={(o) => !o && setTimeline(null)} title="Custody timeline">
        <ol className="space-y-1 text-sm">
          {(log.data?.data ?? []).map((l: Any) => <li key={l.id}>{new Date(l.at).toLocaleString()} — <b>{l.action}</b>{l.location ? ` · ${l.location}` : ''}{l.remarks ? ` · ${l.remarks}` : ''}</li>)}
        </ol>
      </Modal>
    </div>
  );
}

// ---- Valuation ---------------------------------------------------------------------------------------------------------
export function ValuationTab({ id }: { id: string }) {
  const [paper, setPaper] = useState('');
  const [form, setForm] = useState({ round: '1', type: 'internal', staff: '', extName: '', extUser: '', due: '' });
  const status = useQ(['val-status', paper], () => resultsApi.valuationStatus(paper), !!paper);
  const bundles = useQ(['bundles', paper], () => resultsApi.bundles(paper), !!paper);
  const [rec, setRec] = useState<Any | null>(null);
  const run = useRun();
  const d = status.data?.data;
  const assign = () => {
    const ids = (bundles.data?.data ?? []).filter((b: Any) => !b.rounds.some((r: Any) => r.round === Number(form.round))).map((b: Any) => b.id);
    if (!ids.length) return toast.info('Every bundle already has this round');
    const body: Any = { bundle_ids: ids, round: Number(form.round), evaluator_type: form.type, due_at: form.due ? new Date(form.due).toISOString() : null };
    if (form.type === 'internal') body.evaluator_staff_id = form.staff;
    else body.external_evaluator = { name: form.extName, user_id: form.extUser || null };
    run.mutate(() => resultsApi.assign(paper, body), { onSuccess: () => toast.success('Assigned'), onError: fail });
  };
  return (
    <div className="space-y-3">
      <PaperPicker sessionId={id} value={paper} onChange={setPaper} />
      {paper && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <Select className="w-24" value={form.round} options={['1', '2'].map((r) => ({ value: r, label: `Round ${r}` }))} onChange={(e) => setForm({ ...form, round: e.target.value })} />
            <Select className="w-32" value={form.type} options={[{ value: 'internal', label: 'Internal' }, { value: 'external', label: 'External' }]} onChange={(e) => setForm({ ...form, type: e.target.value })} />
            {form.type === 'internal' ? (
              <Input className="w-72" placeholder="Evaluator staff id" value={form.staff} onChange={(e) => setForm({ ...form, staff: e.target.value })} />
            ) : (
              <>
                <Input className="w-48" placeholder="External name" value={form.extName} onChange={(e) => setForm({ ...form, extName: e.target.value })} />
                <Input className="w-72" placeholder="External examiner user id" value={form.extUser} onChange={(e) => setForm({ ...form, extUser: e.target.value })} />
              </>
            )}
            <Input type="datetime-local" className="w-56" value={form.due} onChange={(e) => setForm({ ...form, due: e.target.value })} />
            <Button onClick={assign}>Assign unassigned bundles</Button>
            <Button variant="outline" onClick={() => resultsApi.reconcile(paper).then((r: Any) => setRec(r.data)).catch(fail)}>Reconcile</Button>
          </div>
          <p className="text-sm text-muted-foreground">
            {d?.valuation_mode} valuation · {d?.bundles ?? 0} bundles · {d?.scripts ?? 0} scripts · final marks: {Object.entries(d?.final_marks ?? {}).map(([k, v]) => `${k} ${v}`).join(', ') || '—'}
          </p>
          <SimpleTable
            head={['Bundle', 'Round', 'Evaluator', 'Type', 'Progress', 'Due', 'Status']}
            rows={(d?.assignments ?? []).map((a: Any) => [
              a.bundle_number,
              a.valuation_round,
              a.evaluator_name ?? '—',
              a.evaluator_type,
              <div key="p" className="h-2 w-32 rounded bg-muted"><div className="h-2 rounded bg-primary" style={{ width: `${a.scripts ? (100 * a.valued) / a.scripts : 0}%` }} /></div>,
              a.due_at ? new Date(a.due_at).toLocaleDateString() : '—',
              <StatusBadge key="s" status={a.status} />,
            ])}
          />
          {rec && (
            <Card><CardContent className="space-y-2 p-3 text-sm">
              <p className="font-medium">Resolved {rec.resolved} · needs third {rec.needs_third} · rule {rec.rule} · tolerance {rec.tolerance} · mean discrepancy {rec.average_discrepancy ?? '—'}</p>
              {rec.discrepancies.slice(0, 30).map((x: Any) => <p key={x.answer_script_id}>{x.dummy_number}: V1 {x.v1} · V2 {x.v2} (Δ {x.discrepancy})</p>)}
              {rec.needs_third > 0 && (
                <Button size="sm" onClick={() => { const staff = window.prompt('Third evaluator staff id'); if (staff) run.mutate(() => resultsApi.thirdAssign(paper, { evaluator_staff_id: staff }), { onSuccess: () => toast.success('Third valuation assigned'), onError: fail }); }}>Assign third valuation</Button>
              )}
            </CardContent></Card>
          )}
        </>
      )}
    </div>
  );
}

// ---- Moderation ----------------------------------------------------------------------------------------------------------
export function ModerationTab({ id }: { id: string }) {
  const [paper, setPaper] = useState('');
  const [f, setF] = useState({ action_type: 'add_flat', rule: '{"marks": 2}', justification: '' });
  const list = useQ(['moderation', paper], () => resultsApi.moderation(paper), !!paper);
  const run = useRun();
  const propose = () => {
    let rule: Any;
    try { rule = JSON.parse(f.rule); } catch { return toast.error('Rule must be JSON'); }
    run.mutate(() => resultsApi.propose(paper, { action_type: f.action_type, rule, justification: f.justification }), { onSuccess: () => toast.success('Proposed'), onError: fail });
  };
  return (
    <div className="space-y-3">
      <PaperPicker sessionId={id} value={paper} onChange={setPaper} />
      {paper && (
        <div className="flex flex-wrap gap-2">
          <Select className="w-36" value={f.action_type} options={['scale_up', 'scale_down', 'add_flat', 'grace', 'normalize', 'cap'].map((x) => ({ value: x, label: x }))} onChange={(e) => setF({ ...f, action_type: e.target.value })} />
          <Input className="w-64 font-mono" value={f.rule} onChange={(e) => setF({ ...f, rule: e.target.value })} />
          <Input className="w-80" placeholder="Justification" value={f.justification} onChange={(e) => setF({ ...f, justification: e.target.value })} />
          <Button disabled={f.justification.length < 5} onClick={propose}>Propose</Button>
        </div>
      )}
      <SimpleTable
        head={['Action', 'Rule', 'Impact preview', 'Affected', 'Status', '']}
        rows={(list.data?.data ?? []).map((m: Any) => [
          m.action_type,
          <code key="r">{JSON.stringify(m.rule)}</code>,
          m.preview ? `${m.preview.affected}/${m.preview.scripts} scripts · mean ${m.preview.mean_before} → ${m.preview.mean_after}` : '—',
          m.affected_count ?? '—',
          <StatusBadge key="s" status={m.status} />,
          <div key="a" className="flex gap-1">
            {m.status === 'proposed' && <Button size="sm" onClick={() => run.mutate(() => resultsApi.moderationAction(m.id, 'approve'), { onError: fail })}>Approve (COE)</Button>}
            {m.status === 'approved' && <Button size="sm" onClick={() => run.mutate(() => resultsApi.moderationAction(m.id, 'apply'), { onError: fail })}>Apply</Button>}
            {m.status === 'applied' && <Button size="sm" variant="outline" onClick={() => run.mutate(() => resultsApi.moderationAction(m.id, 'revert'), { onError: fail })}>Revert</Button>}
          </div>,
        ])}
      />
    </div>
  );
}

// ---- Decode (decoder only) ----------------------------------------------------------------------------------------------
export function DecodeTab({ id }: { id: string }) {
  const [paper, setPaper] = useState('');
  const run = useRun();
  return (
    <Card><CardContent className="space-y-3 p-4">
      <p className="text-sm text-muted-foreground">Decoding joins dummy numbers to registrations and writes ESE marks. It is audited and, when the IP allow-list is on, only possible from allow-listed addresses. The mapping is never shown.</p>
      <div className="flex gap-2">
        <PaperPicker sessionId={id} value={paper} onChange={setPaper} />
        <Button disabled={!paper} variant="destructive" onClick={() => { if (window.confirm('Decode this paper? This cannot be undone.')) run.mutate(() => resultsApi.decode(paper).then((r: Any) => toast.success(`Decoded ${r.data.decoded_count} scripts`)), { onError: fail }); }}>Decode</Button>
      </div>
    </CardContent></Card>
  );
}

// ---- Result runs --------------------------------------------------------------------------------------------------------
export function ResultsRunTab({ id }: { id: string }) {
  const runs = useQ(['runs', id], () => resultsApi.runs({ exam_session_id: id }));
  const [sel, setSel] = useState<string | null>(null);
  const [type, setType] = useState('provisional');
  const run = useRun();
  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <Select className="w-44" value={type} options={['provisional', 'final', 'revaluation', 'supplementary_merge', 'correction'].map((x) => ({ value: x, label: x }))} onChange={(e) => setType(e.target.value)} />
        <Button onClick={() => run.mutate(() => resultsApi.createRun({ exam_session_id: id, run_type: type }), { onSuccess: () => toast.success('Run queued — compute job started'), onError: fail })}>Create run</Button>
      </div>
      <SimpleTable
        head={['Run', 'Type', 'Status', 'Rows', 'Anomalies', 'Checksum', '']}
        rows={(runs.data?.data ?? []).map((r: Any) => [
          new Date(r.created_at).toLocaleString(),
          r.run_type,
          <StatusBadge key="s" status={r.status} />,
          r.stats?.rows ?? '—',
          r.anomalies_count,
          <code key="c">{r.checksum?.slice(0, 12) ?? '—'}</code>,
          <Button key="o" size="sm" variant="outline" onClick={() => setSel(r.id)}>Open</Button>,
        ])}
      />
      {sel && <RunPanel runId={sel} />}
    </div>
  );
}

function RunPanel({ runId }: { runId: string }) {
  const r = useQ(['run', runId], () => resultsApi.run(runId));
  const an = useQ(['anomalies', runId], () => resultsApi.anomalies(runId));
  const rows = useQ(['rows', runId], () => resultsApi.rows(runId, { page_size: 50 }), ['verified', 'approved', 'published', 'computed'].includes(r.data?.data?.status));
  const [ack, setAck] = useState(false);
  const [pub, setPub] = useState({ open: false, audience: 'student', notify: true, withhold: '' });
  const run = useRun();
  const { can } = usePermission();
  const canPublish = can('results', 'publish');
  const d = r.data?.data;
  if (!d) return null;
  const groups: Record<string, Any[]> = {};
  (an.data?.data ?? []).forEach((a: Any) => (groups[a.code] = [...(groups[a.code] ?? []), a]));
  return (
    <Card><CardContent className="space-y-3 p-4">
      <p className="font-medium">{d.run_type} run · {d.status} · {d.stats?.rows ?? 0} rows · {d.stats?.students ?? 0} students</p>
      {Object.entries(groups).map(([code, items]) => (
        <details key={code} className="text-sm"><summary>{code} ({items.length})</summary>
          {items.slice(0, 40).map((a, i) => <p key={i}>{a.registration_number} · {a.course} — {a.detail}</p>)}
        </details>
      ))}
      <div className="flex flex-wrap items-center gap-2">
        {d.status === 'computed' && (
          <>
            <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> I reviewed {d.anomalies_count} anomalies</label>
            <Button onClick={() => run.mutate(() => resultsApi.runAction(runId, 'verify', { acknowledge_anomalies: ack }), { onSuccess: () => toast.success('Verified'), onError: fail })}>Verify</Button>
          </>
        )}
        {d.status === 'verified' && <Button onClick={() => run.mutate(() => resultsApi.runAction(runId, 'approve', { resolution_id: window.prompt('Governance resolution id (optional)') || null }), { onSuccess: () => toast.success('Approved'), onError: fail })}>Approve (COE)</Button>}
        {d.status === 'approved' && canPublish && <Button onClick={() => setPub({ ...pub, open: true })}>Publish…</Button>}
        {['computed', 'verified', 'approved'].includes(d.status) && <Button variant="outline" onClick={() => { if (window.confirm('Roll back this run? Its rows are deleted.')) run.mutate(() => resultsApi.runAction(runId, 'rollback'), { onError: fail }); }}>Roll back</Button>}
        {d.status === 'published' && <Button variant="outline" onClick={() => run.mutate(() => resultsApi.gradeCards(runId), { onSuccess: () => toast.success('Grade cards queued'), onError: fail })}>Generate grade cards</Button>}
        <Button variant="ghost" onClick={() => resultsApi.exportRun(runId).then((b) => openBlob(b, 'result-run.xlsx')).catch(fail)}><Download className="h-4 w-4" /> XLSX</Button>
      </div>
      <SimpleTable
        head={['Student', 'Course', 'Att.', 'CIA', 'ESE', 'Grace', 'Total', 'Grade', 'Status', 'v']}
        rows={(rows.data?.data ?? []).map((x: Any) => [`${x.registration_number ?? ''} ${x.student_name ?? ''}`, x.course_code, x.attempt_number, x.cia_marks ?? '—', x.ese_marks ?? '—', x.grace_marks, x.total_marks ?? '—', x.letter_grade ?? '—', x.result_status, x.version])}
      />
      <Modal open={pub.open} onOpenChange={(o) => setPub({ ...pub, open: o })} title="Publish results">
        <div className="space-y-2">
          <Select value={pub.audience} options={['student', 'college', 'public'].map((x) => ({ value: x, label: x }))} onChange={(e) => setPub({ ...pub, audience: e.target.value })} />
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={pub.notify} onChange={(e) => setPub({ ...pub, notify: e.target.checked })} /> Notify students (masked SMS: SGPA only)</label>
          <Input placeholder="Withhold enrolment ids (comma-separated)" value={pub.withhold} onChange={(e) => setPub({ ...pub, withhold: e.target.value })} />
          <Button onClick={() => run.mutate(() => resultsApi.publish(runId, { audience: pub.audience, notify: pub.notify, withhold_ids: pub.withhold.split(',').map((s) => s.trim()).filter(Boolean) }), { onSuccess: () => { setPub({ ...pub, open: false }); toast.success('Published'); }, onError: fail })}>Publish now</Button>
        </div>
      </Modal>
    </CardContent></Card>
  );
}

// ---- Custody & retention ---------------------------------------------------------------------------------------------------
export function CustodyTab({ id }: { id: string }) {
  const reg = useQ(['register', id], () => resultsApi.register(id));
  const run = useRun();
  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <Button variant="outline" onClick={() => run.mutate(() => resultsApi.archive(id), { onSuccess: () => toast.success('Archived'), onError: fail })}>Archive scripts</Button>
        <Button variant="destructive" onClick={() => { const note = window.prompt('Destruction approval note'); if (note) run.mutate(() => resultsApi.destroy(id, note), { onSuccess: () => toast.success('Destruction registered'), onError: fail }); }}>Destroy archived (COE)</Button>
      </div>
      <SimpleTable head={['Bundle', 'Paper', 'Scripts', 'Status', 'Last action', 'At']} rows={(reg.data?.data ?? []).map((b: Any) => [b.bundle_number, b.paper_code ?? '—', b.script_count, <StatusBadge key="s" status={b.status} />, b.last_action ?? '—', b.last_action_at ? new Date(b.last_action_at).toLocaleString() : '—'])} />
    </div>
  );
}
