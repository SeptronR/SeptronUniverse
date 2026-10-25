import { useEffect, useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { SimpleTable } from '@/features/hr/components/shared';
import { postResultApi as pr } from '../api';

// Phase 16 web screens (Prompts/16 §16.9) — revaluation, malpractice, withheld, supplementary, transcripts, rank lists &
// medals, corrections, detained & readmission (admin) and the student revaluation / malpractice / transcript pages.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));
const useQ = <T,>(key: unknown[], fn: () => Promise<T>, enabled = true) => useQuery({ queryKey: ['post_result', ...key], queryFn: fn, enabled, retry: false });
function useRun() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: () => qc.invalidateQueries({ queryKey: ['post_result'] }) });
}
const rupees = (p: number | null | undefined) => `₹${((p ?? 0) / 100).toLocaleString('en-IN')}`;
const dt = (v?: string | null) => (v ? new Date(v).toLocaleString() : '—');
const list = (r: Any) => (Array.isArray(r?.data) ? r.data : r?.data?.items ?? r?.data?.entries ?? []);
const openBlob = (b: Blob, name: string) => { const u = URL.createObjectURL(b); const a = document.createElement('a'); a.href = u; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(u), 30000); };
const sel = 'h-9 rounded-md border bg-background px-2 text-sm';

function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <Card><CardContent className="space-y-3 p-4"><div className="flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">{title}</h2>{action}</div>{children}</CardContent></Card>;
}

function SessionPicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const q = useQ(['sessions'], () => pr.sessions());
  return <select className={sel} value={value} onChange={(e) => onChange(e.target.value)}><option value="">Exam session…</option>{list(q.data).map((s: Any) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>;
}
function TermPicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const q = useQ(['terms'], () => pr.terms());
  return <select className={sel} value={value} onChange={(e) => onChange(e.target.value)}><option value="">Term…</option>{list(q.data).map((t: Any) => <option key={t.id} value={t.id}>{t.name}</option>)}</select>;
}
function BatchPicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const q = useQ(['batches'], () => pr.batches());
  return <select className={sel} value={value} onChange={(e) => onChange(e.target.value)}><option value="">Batch…</option>{list(q.data).map((b: Any) => <option key={b.id} value={b.id}>{b.code ?? b.name}</option>)}</select>;
}

// ---- /admin/exams/revaluation ---------------------------------------------------------------------------------------------
export function RevaluationAdminPage() {
  useTitle('Revaluation');
  const [session, setSession] = useState('');
  const [f, setF] = useState({ type: '', status: '' });
  const q = useQ(['reval', session, f], () => pr.sessionReval(session, { type: f.type || undefined, status: f.status || undefined }), !!session);
  const [dlg, setDlg] = useState<Any | null>(null);
  const run = useRun();
  const act = (fn: () => Promise<unknown>, ok: string) => run.mutate(fn, { onSuccess: () => { toast.success(ok); setDlg(null); }, onError: fail });
  return (
    <div className="space-y-4">
      <PageHeader title="Revaluation" description="Retotaling, photocopies, revaluation and challenge requests; apply changed marks as a revaluation result run." actions={session ? <Button onClick={() => act(() => pr.applyReval(session), 'Revaluation run queued')}>Apply decided requests</Button> : undefined} />
      <div className="flex flex-wrap gap-2">
        <SessionPicker value={session} onChange={setSession} />
        <select className={sel} value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })}><option value="">All types</option>{['retotaling', 'photocopy', 'revaluation', 'challenge'].map((t) => <option key={t}>{t}</option>)}</select>
        <select className={sel} value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="">Any status</option>{['fee_pending', 'fee_paid', 'assigned', 'evaluated', 'marks_changed', 'no_change', 'rejected'].map((t) => <option key={t}>{t}</option>)}</select>
      </div>
      <SimpleTable
        head={['Student', 'Course', 'Type', 'Fee', 'Status', 'Original', 'Revised', 'Δ', '']}
        rows={list(q.data).map((r: Any) => [
          `${r.student_name ?? ''} ${r.registration_number ?? ''}`, r.course_code, <Badge key="t" variant="outline">{r.request_type}</Badge>, `${rupees(r.fee_paise)} · ${r.invoice_status ?? '—'}`, <StatusBadge key="s" status={r.status} />,
          r.original_marks ?? '—', r.revised_marks ?? '—', r.delta ?? '—',
          <div key="a" className="flex gap-1">
            {['fee_paid', 'assigned'].includes(r.status) && r.request_type !== 'retotaling' && <Button size="sm" variant="outline" onClick={() => setDlg({ kind: 'assign', r, evaluator_staff_id: '' })}>Assign</Button>}
            {r.request_type === 'retotaling' && r.status === 'fee_paid' && <Button size="sm" variant="outline" onClick={() => setDlg({ kind: 'retotal', r, revised_marks: r.original_marks ?? '' })}>Retotal</Button>}
            {!['marks_changed', 'no_change', 'rejected'].includes(r.status) && <Button size="sm" onClick={() => setDlg({ kind: 'decide', r, revised_marks: r.revised_marks ?? '', remarks: '' })}>Decide</Button>}
            {!['marks_changed', 'no_change', 'rejected'].includes(r.status) && <Button size="sm" variant="ghost" onClick={() => act(() => pr.reject(r.id, { remarks: 'rejected' }), 'Rejected')}>Reject</Button>}
          </div>,
        ])}
      />
      <Modal open={!!dlg} onOpenChange={(o) => !o && setDlg(null)} title={dlg?.kind === 'assign' ? 'Assign evaluator' : dlg?.kind === 'retotal' ? 'Retotal' : 'Decide'} footer={<Button onClick={() => {
        if (dlg.kind === 'assign') act(() => pr.assign(dlg.r.id, { evaluator_staff_id: dlg.evaluator_staff_id }), 'Assigned');
        else if (dlg.kind === 'retotal') act(() => pr.retotal(dlg.r.id, { revised_marks: Number(dlg.revised_marks) }), 'Retotalled');
        else act(() => pr.decide(dlg.r.id, { revised_marks: dlg.revised_marks === '' ? null : Number(dlg.revised_marks), remarks: dlg.remarks || null }), 'Decided');
      }}>Save</Button>}>
        {dlg && <div className="space-y-2 text-sm">
          <p>{dlg.r.course_code} · original {dlg.r.original_marks ?? '—'}{dlg.r.revised_marks != null ? ` · revised ${dlg.r.revised_marks}` : ''}</p>
          {dlg.kind === 'assign' && <Input placeholder="Evaluator staff id (not the original evaluator)" value={dlg.evaluator_staff_id} onChange={(e) => setDlg({ ...dlg, evaluator_staff_id: e.target.value.trim() })} />}
          {dlg.kind !== 'assign' && <Input type="number" placeholder="Revised marks" value={dlg.revised_marks} onChange={(e) => setDlg({ ...dlg, revised_marks: e.target.value })} />}
          {dlg.kind === 'decide' && <Input placeholder="Remarks" value={dlg.remarks} onChange={(e) => setDlg({ ...dlg, remarks: e.target.value })} />}
          {dlg.kind !== 'assign' && dlg.revised_marks !== '' && dlg.r.original_marks != null && <p className="text-xs text-muted-foreground">Δ {Number(dlg.revised_marks) - Number(dlg.r.original_marks)} — the minimum-delta rule decides whether marks change.</p>}
        </div>}
      </Modal>
    </div>
  );
}

// ---- /admin/exams/malpractice -------------------------------------------------------------------------------------------------
export function MalpracticeAdminPage() {
  useTitle('Malpractice');
  const [status, setStatus] = useState('');
  const q = useQ(['cases', status], () => pr.cases({ status: status || undefined }));
  const [cur, setCur] = useState<string>('');
  const c = useQ(['case', cur], () => pr.case(cur), !!cur);
  const [form, setForm] = useState<Any>({ punishment: 'warning', debar_terms: '', decision_text: '', hearing_at: '', committee_id: '', outcome: 'uphold' });
  const run = useRun();
  const act = (action: string, b: Any, ok: string) => run.mutate(() => pr.caseAction(cur, action, b), { onSuccess: () => toast.success(ok), onError: fail });
  const k = (c.data as Any)?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Malpractice cases" description="Report → inquiry → notice → statement → hearing → decision → appeal; results stay withheld until decided." />
      <select className={sel} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Any status</option>{['reported', 'inquiry', 'notice_sent', 'hearing', 'decided', 'appealed', 'closed'].map((s) => <option key={s}>{s}</option>)}</select>
      <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
        <SimpleTable head={['Case', 'Student', 'Course', 'Category', 'Status']} rows={list(q.data).map((m: Any) => [<button key="c" className="underline" onClick={() => setCur(m.id)}>{m.case_number}</button>, `${m.student_name ?? ''} ${m.registration_number ?? ''}`, m.course_code, m.category, <StatusBadge key="s" status={m.status} />])} />
        {k && <Section title={`${k.case_number} — ${k.student_name ?? ''}`} action={<StatusBadge status={k.status} />}>
          <p className="text-sm"><b>Report:</b> {k.invigilator_report}</p>
          {k.student_statement && <p className="text-sm"><b>Statement:</b> {k.student_statement}</p>}
          {(k.evidence ?? []).length > 0 && <div className="flex flex-wrap gap-1">{k.evidence.map((e: Any, i: number) => <Badge key={i} variant="outline">{e.label ?? e.kind ?? `evidence ${i + 1}`}</Badge>)}</div>}
          {k.punishment && <p className="text-sm"><b>Decision:</b> {k.punishment} — {k.decision_text}</p>}
          <div className="space-y-1 text-xs">{(k.timeline ?? []).map((t: Any, i: number) => <p key={i}>{dt(t.at)} · {t.event ?? t.action} {t.note ?? ''}</p>)}</div>
          <div className="grid grid-cols-2 gap-2 text-sm">
            <Input placeholder="Committee id" value={form.committee_id} onChange={(e) => setForm({ ...form, committee_id: e.target.value })} />
            <Button size="sm" variant="outline" onClick={() => act('inquiry', { committee_id: form.committee_id || null }, 'Inquiry opened')}>Open inquiry</Button>
            <Button size="sm" variant="outline" onClick={() => act('notice', {}, 'Notice sent')}>Send notice</Button>
            <div className="flex gap-1"><Input type="datetime-local" value={form.hearing_at} onChange={(e) => setForm({ ...form, hearing_at: e.target.value })} /><Button size="sm" variant="outline" disabled={!form.hearing_at} onClick={() => act('hearing', { hearing_at: new Date(form.hearing_at).toISOString() }, 'Hearing scheduled')}>Hearing</Button></div>
            <select className={sel} value={form.punishment} onChange={(e) => setForm({ ...form, punishment: e.target.value })}>{['none', 'warning', 'cancel_paper', 'cancel_session', 'debar_terms', 'expel'].map((p) => <option key={p}>{p}</option>)}</select>
            {form.punishment === 'debar_terms' && <Input type="number" placeholder="Terms" value={form.debar_terms} onChange={(e) => setForm({ ...form, debar_terms: e.target.value })} />}
            <textarea className="col-span-2 h-20 rounded-md border bg-background p-2" placeholder="Decision / appeal text" value={form.decision_text} onChange={(e) => setForm({ ...form, decision_text: e.target.value })} />
            <Button size="sm" disabled={form.decision_text.length < 3} onClick={() => act('decide', { punishment: form.punishment, debar_terms: form.debar_terms ? Number(form.debar_terms) : null, decision_text: form.decision_text }, 'Decided')}>Decide</Button>
            {k.status === 'appealed' && <div className="flex gap-1"><select className={sel} value={form.outcome} onChange={(e) => setForm({ ...form, outcome: e.target.value })}><option value="uphold">uphold</option><option value="modify">modify</option></select><Button size="sm" onClick={() => act('appeal/decide', { outcome: form.outcome, punishment: form.outcome === 'modify' ? form.punishment : null, debar_terms: form.debar_terms ? Number(form.debar_terms) : null, decision_text: form.decision_text }, 'Appeal decided')}>Appeal decision</Button></div>}
            <Button size="sm" variant="ghost" onClick={() => act('close', {}, 'Closed')}>Close case</Button>
          </div>
        </Section>}
      </div>
    </div>
  );
}

// ---- /admin/results/withheld ------------------------------------------------------------------------------------------------
export function WithheldPage() {
  useTitle('Withheld results');
  const [session, setSession] = useState('');
  const q = useQ(['withheld', session], () => pr.withheld(session || undefined));
  const [picked, setPicked] = useState<string[]>([]);
  const run = useRun();
  const rows = list(q.data);
  return (
    <div className="space-y-4">
      <PageHeader title="Withheld results" description="Rows held for malpractice, holds or dues; release the releasable ones (a correction run publishes them)." actions={<Button disabled={!picked.length} onClick={() => { const reason = window.prompt('Release reason'); if (reason) run.mutate(() => pr.release({ result_ids: picked, reason }), { onSuccess: () => { toast.success('Released'); setPicked([]); }, onError: fail }); }}>Release {picked.length || ''}</Button>} />
      <SessionPicker value={session} onChange={setSession} />
      <SimpleTable head={['', 'Student', 'Course', 'Reasons', 'Releasable']} rows={rows.map((r: Any) => [
        <input key="c" type="checkbox" disabled={!r.releasable} checked={picked.includes(r.result_id)} onChange={(e) => setPicked(e.target.checked ? [...picked, r.result_id] : picked.filter((x) => x !== r.result_id))} />,
        `${r.student_name ?? ''} ${r.registration_number ?? ''}`, r.course_code, <div key="r" className="flex flex-wrap gap-1">{r.reasons.map((x: string) => <Badge key={x} variant="outline">{x}</Badge>)}</div>, r.releasable ? 'yes' : 'no',
      ])} />
    </div>
  );
}

// ---- /admin/exams/supplementary -------------------------------------------------------------------------------------------------
export function SupplementaryPage() {
  useTitle('Supplementary exams');
  const [b, setB] = useState<Any>({ term_id: '', exam_kind: 'supplementary', from_session_id: '', name: '' });
  const [preview, setPreview] = useState<Any | null>(null);
  const run = useRun();
  const body = () => ({ term_id: b.term_id, exam_kind: b.exam_kind, from_session_id: b.from_session_id || null, name: b.name || null });
  return (
    <div className="space-y-4">
      <PageHeader title="Supplementary / arrear session" description="Preview students with open arrears, then create the session (registrations are built as arrear attempts)." />
      <div className="flex flex-wrap gap-2">
        <TermPicker value={b.term_id} onChange={(v) => setB({ ...b, term_id: v })} />
        <SessionPicker value={b.from_session_id} onChange={(v) => setB({ ...b, from_session_id: v })} />
        <select className={sel} value={b.exam_kind} onChange={(e) => setB({ ...b, exam_kind: e.target.value })}><option value="supplementary">supplementary</option><option value="arrear">arrear</option></select>
        <Input className="w-64" placeholder="Session name" value={b.name} onChange={(e) => setB({ ...b, name: e.target.value })} />
        <Button variant="outline" disabled={!b.term_id} onClick={() => run.mutate(() => pr.suppPreview(body()).then((r: Any) => setPreview(r.data)), { onError: fail })}>Preview</Button>
        <Button disabled={!preview} onClick={() => run.mutate(() => pr.suppCreate(body()), { onSuccess: () => toast.success('Session creation queued'), onError: fail })}>Create session</Button>
      </div>
      {preview && <Section title={`${preview.students} student(s), ${preview.papers.length} paper(s)`}><SimpleTable head={['Course', 'Students']} rows={preview.papers.map((p: Any) => [p.course_code ?? p.course_id, p.students ?? p.count ?? '—'])} /></Section>}
    </div>
  );
}

// ---- /admin/results/transcripts --------------------------------------------------------------------------------------------------
export function TranscriptsAdminPage() {
  useTitle('Transcripts');
  const [status, setStatus] = useState('');
  const q = useQ(['tr', status], () => pr.transcriptRequests(status || undefined));
  const [checks, setChecks] = useState<Any | null>(null);
  const run = useRun();
  const act = (id: string, a: string, b: Any = {}) => run.mutate(() => pr.transcriptAction(id, a, b), { onSuccess: () => toast.success(a), onError: fail });
  return (
    <div className="space-y-4">
      <PageHeader title="Transcript requests" description="Dues / hold checks, approve, generate, issue, reissue after a result revision." />
      <select className={sel} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Any status</option>{['requested', 'fee_pending', 'approved', 'generated', 'issued', 'cancelled'].map((s) => <option key={s}>{s}</option>)}</select>
      <SimpleTable head={['Student', 'Type', 'Copies', 'Fee', 'Requested', 'Status', '']} rows={list(q.data).map((t: Any) => [
        `${t.student_name ?? ''} ${t.registration_number ?? ''}`, t.transcript_type, t.copies, t.invoice_status ?? '—', dt(t.requested_at), <span key="s"><StatusBadge status={t.status} />{t.superseded && <Badge variant="warning">superseded</Badge>}</span>,
        <div key="a" className="flex flex-wrap gap-1">
          <Button size="sm" variant="ghost" onClick={() => pr.transcriptChecks(t.id).then((r: Any) => setChecks(r.data)).catch(fail)}>Checks</Button>
          <Button size="sm" variant="outline" onClick={() => act(t.id, 'approve')}>Approve</Button>
          <Button size="sm" variant="outline" onClick={() => act(t.id, 'generate')}>Generate</Button>
          <Button size="sm" onClick={() => act(t.id, 'issue', { delivery: 'digital' })}>Issue</Button>
          {t.superseded && <Button size="sm" variant="outline" onClick={() => act(t.id, 'reissue')}>Reissue</Button>}
          {['issued', 'generated'].includes(t.status) && <Button size="sm" variant="ghost" onClick={() => pr.downloadTranscript(t.id).then((b) => openBlob(b, `transcript-${t.document_number ?? t.id}.pdf`)).catch(fail)}>PDF</Button>}
        </div>,
      ])} />
      <Modal open={!!checks} onOpenChange={(o) => !o && setChecks(null)} title="Pre-issue checks"><pre className="whitespace-pre-wrap text-xs">{JSON.stringify(checks, null, 2)}</pre></Modal>
    </div>
  );
}

// ---- /admin/results/medals -----------------------------------------------------------------------------------------------------
export function RankMedalsPage() {
  useTitle('Rank lists & medals');
  const [f, setF] = useState<Any>({ batch_id: '', term_id: '', top_n: 10, public: false });
  const q = useQ(['ranks', f.batch_id, f.term_id], () => pr.rankLists({ batch_id: f.batch_id, term_id: f.term_id || undefined, cumulative: !f.term_id, top_n: f.top_n }), !!f.batch_id);
  const medals = useQ(['medals', f.batch_id], () => pr.medals({ batch_id: f.batch_id || undefined }));
  const run = useRun();
  const entries = (q.data as Any)?.data?.entries ?? [];
  return (
    <div className="space-y-4">
      <PageHeader title="Rank lists & medals" description="Ties broken by CGPA, then credits; publish (optionally public, masked) and award medals." />
      <div className="flex flex-wrap items-center gap-2">
        <BatchPicker value={f.batch_id} onChange={(v) => setF({ ...f, batch_id: v })} />
        <TermPicker value={f.term_id} onChange={(v) => setF({ ...f, term_id: v })} />
        <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={f.public} onChange={(e) => setF({ ...f, public: e.target.checked })} /> public</label>
        <Button disabled={!f.batch_id} onClick={() => run.mutate(() => pr.publishRank({ batch_id: f.batch_id, term_id: f.term_id || null, top_n: Number(f.top_n), public: f.public }), { onSuccess: () => toast.success('Published'), onError: fail })}>Publish</Button>
      </div>
      <SimpleTable head={['Rank', 'Student', 'SGPA', 'CGPA', 'Credits', 'Tie break', '']} rows={entries.map((e: Any) => [e.rank, `${e.student_masked} ${e.registration_number ?? ''}`, e.sgpa ?? '—', e.cgpa ?? '—', e.credits ?? '—', e.tie_break ?? '', e.rank <= 3 && e.student_program_enrollment_id ? <Button key="m" size="sm" variant="outline" onClick={() => run.mutate(() => pr.award({ batch_id: f.batch_id, medal: ['gold', 'silver', 'bronze'][e.rank - 1], student_program_enrollment_id: e.student_program_enrollment_id }), { onSuccess: () => toast.success('Medal awarded'), onError: fail })}>Award {['gold', 'silver', 'bronze'][e.rank - 1]}</Button> : null])} />
      <Section title="Medals"><SimpleTable head={['Medal', 'Student', 'Position', '']} rows={list(medals.data).map((m: Any) => [m.title, `${m.student_name ?? ''} ${m.registration_number ?? ''}`, m.position ?? '—', <Button key="r" size="sm" variant="ghost" onClick={() => run.mutate(() => pr.revokeMedal(m.id), { onSuccess: () => toast.success('Revoked'), onError: fail })}>Revoke</Button>])} /></Section>
    </div>
  );
}

// ---- /admin/results/corrections --------------------------------------------------------------------------------------------------
export function CorrectionsPage() {
  useTitle('Result corrections');
  const [status, setStatus] = useState('');
  const q = useQ(['corr', status], () => pr.corrections(status || undefined));
  const [form, setForm] = useState<Any | null>(null);
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Result corrections" description="Corrections on published rows go through HOD → COE and publish as a correction run." actions={<Button onClick={() => setForm({ result_id: '', reason: '', ese_delta: 0 })}>Raise correction</Button>} />
      <select className={sel} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Any status</option>{['pending', 'approved', 'rejected', 'applied'].map((s) => <option key={s}>{s}</option>)}</select>
      <SimpleTable head={['Result', 'Reason', 'ESE Δ', 'Raised', 'Status', '']} rows={list(q.data).map((c: Any) => [String(c.result_id ?? '').slice(0, 8), c.reason, c.ese_delta, dt(c.started_at), <StatusBadge key="s" status={c.status} />, c.status === 'pending' ? <div key="a" className="flex gap-1"><Button size="sm" onClick={() => run.mutate(() => pr.correctionDecide(c.id, 'approve'), { onError: fail })}>Approve</Button><Button size="sm" variant="ghost" onClick={() => run.mutate(() => pr.correctionDecide(c.id, 'reject'), { onError: fail })}>Reject</Button></div> : null])} />
      <Modal open={!!form} onOpenChange={(o) => !o && setForm(null)} title="Raise correction" footer={<Button disabled={!form?.result_id || (form?.reason ?? '').length < 5} onClick={() => run.mutate(() => pr.raiseCorrection({ ...form, ese_delta: Number(form.ese_delta) }), { onSuccess: () => { toast.success('Raised'); setForm(null); }, onError: fail })}>Raise</Button>}>
        {form && <div className="space-y-2 text-sm"><Input placeholder="Result id" value={form.result_id} onChange={(e) => setForm({ ...form, result_id: e.target.value.trim() })} /><Input placeholder="Reason" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} /><label>ESE marks change <Input type="number" value={form.ese_delta} onChange={(e) => setForm({ ...form, ese_delta: e.target.value })} /></label></div>}
      </Modal>
    </div>
  );
}

// ---- /admin/students/detained -----------------------------------------------------------------------------------------------------
export function DetainedPage() {
  useTitle('Detained & readmission');
  const [term, setTerm] = useState('');
  const q = useQ(['detained', term], () => pr.detained(term), !!term);
  const rq = useQ(['readmissions'], () => pr.readmissions());
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Detained & readmission" description="Students detained in a term and their readmission requests." />
      <TermPicker value={term} onChange={setTerm} />
      <SimpleTable head={['Student', 'Term', 'Attendance', 'Detained courses', 'Readmission', '']} rows={list(q.data).map((d: Any) => [`${d.student_name ?? ''} ${d.registration_number ?? ''}`, d.term_number, d.attendance_pct != null ? `${d.attendance_pct}%` : '—', d.detained_courses.join(', ') || '—', d.readmission?.status ?? '—', !d.readmission ? <Button key="r" size="sm" variant="outline" onClick={() => { const reason = window.prompt('Readmission reason'); if (reason) run.mutate(() => pr.readmit({ enrollment_id: d.student_program_enrollment_id, term_id: term, reason }), { onSuccess: () => toast.success('Requested'), onError: fail }); }}>Readmit</Button> : null])} />
      <Section title="Readmission requests"><SimpleTable head={['Enrolment', 'Reason', 'Started', 'Status', '']} rows={list(rq.data).map((r: Any) => [String(r.enrollment_id).slice(0, 8), r.reason ?? '—', dt(r.started_at), <StatusBadge key="s" status={r.status} />, r.status === 'pending' || r.status === 'in_progress' ? <div key="a" className="flex gap-1"><Button size="sm" onClick={() => run.mutate(() => pr.readmissionDecide(r.id, 'approve'), { onError: fail })}>Approve</Button><Button size="sm" variant="ghost" onClick={() => run.mutate(() => pr.readmissionDecide(r.id, 'reject'), { onError: fail })}>Reject</Button></div> : null])} /></Section>
    </div>
  );
}

// ---- student portal ----------------------------------------------------------------------------------------------------------------
export function StudentRevalPage() {
  useTitle('Revaluation');
  const [session, setSession] = useState('');
  const el = useQ(['elig', session], () => pr.eligibility(session), !!session);
  const mine = useQ(['myreval'], () => pr.myReval());
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Revaluation & photocopy" description="Request within the window; pay the fee from Fees; follow the status here." />
      <SessionPicker value={session} onChange={setSession} />
      {session && <SimpleTable head={['Course', 'Grade', 'Window ends', 'Request']} rows={((el.data as Any)?.data?.items ?? []).map((i: Any) => [i.course_code, i.letter_grade ?? '—', dt(i.window_ends_at), <div key="r" className="flex flex-wrap gap-1">{i.allowed_types.map((t: string) => <Button key={t} size="sm" variant="outline" disabled={!!i.existing?.[t]} onClick={() => run.mutate(() => pr.requestReval({ exam_registration_item_id: i.exam_registration_item_id, request_type: t }), { onSuccess: () => toast.success('Requested — pay the fee to proceed'), onError: fail })}>{t} {rupees(i.fees?.[t])}{i.existing?.[t] ? ` · ${i.existing[t]}` : ''}</Button>)}</div>])} />}
      <Section title="My requests"><SimpleTable head={['Course', 'Type', 'Fee', 'Status', 'Original', 'Revised', '']} rows={list(mine.data).map((r: Any) => [r.course_code, r.request_type, r.invoice_status ?? '—', <StatusBadge key="s" status={r.status} />, r.original_marks ?? '—', r.revised_marks ?? '—', r.photocopy_ready ? <Button key="p" size="sm" variant="ghost" onClick={() => pr.photocopy(r.id).then((b) => openBlob(b, `photocopy-${r.course_code}.pdf`)).catch(fail)}>Photocopy</Button> : null])} /></Section>
    </div>
  );
}

export function StudentMalpracticePage() {
  useTitle('Malpractice');
  const q = useQ(['mycases'], () => pr.myCases());
  const [text, setText] = useState<Record<string, string>>({});
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Malpractice" description="Notices, your statement, the decision and an appeal within the window." />
      {list(q.data).length === 0 && <p className="text-sm text-muted-foreground">No cases.</p>}
      {list(q.data).map((c: Any) => (
        <Section key={c.id} title={`${c.case_number} · ${c.course_code ?? ''}`} action={<StatusBadge status={c.status} />}>
          <p className="text-sm">Category: {c.category}{c.hearing_at ? ` · hearing ${dt(c.hearing_at)}` : ''}</p>
          {c.punishment && <p className="text-sm"><b>Decision:</b> {c.punishment} — {c.decision_text}</p>}
          <textarea className="h-20 w-full rounded-md border bg-background p-2 text-sm" placeholder={c.punishment ? 'Appeal grounds (min 10 characters)' : 'Your statement'} value={text[c.id] ?? ''} onChange={(e) => setText({ ...text, [c.id]: e.target.value })} />
          {!c.punishment && <Button size="sm" disabled={(text[c.id] ?? '').length < 3} onClick={() => run.mutate(() => pr.caseAction(c.id, 'statement', { text: text[c.id] }), { onSuccess: () => toast.success('Statement submitted'), onError: fail })}>Submit statement</Button>}
          {c.punishment && <Button size="sm" disabled={(text[c.id] ?? '').length < 10} onClick={() => run.mutate(() => pr.caseAction(c.id, 'appeal', { grounds: text[c.id] }), { onSuccess: () => toast.success('Appeal filed'), onError: fail })}>Appeal</Button>}
        </Section>
      ))}
    </div>
  );
}

export function StudentTranscriptsPage() {
  useTitle('Transcripts');
  const types = useQ(['trtypes'], () => pr.transcriptTypes());
  const mine = useQ(['mytr'], () => pr.myTranscripts());
  const [b, setB] = useState<Any>({ transcript_type: 'consolidated', copies: 1, delivery: 'digital', purpose: '' });
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Transcripts" description="Request, pay, download; each transcript carries a verification QR." />
      <Section title="New request">
        <div className="flex flex-wrap gap-2">
          <select className={sel} value={b.transcript_type} onChange={(e) => setB({ ...b, transcript_type: e.target.value })}>{list(types.data).map((t: Any) => <option key={t.transcript_type} value={t.transcript_type}>{t.transcript_type} — {rupees(t.fee_paise)}{t.requires_no_dues ? ' (no-dues)' : ''}</option>)}</select>
          <Input className="w-24" type="number" min={1} value={b.copies} onChange={(e) => setB({ ...b, copies: Number(e.target.value) })} />
          <select className={sel} value={b.delivery} onChange={(e) => setB({ ...b, delivery: e.target.value })}>{['digital', 'pickup', 'post'].map((d) => <option key={d}>{d}</option>)}</select>
          <Input className="w-56" placeholder="Purpose" value={b.purpose} onChange={(e) => setB({ ...b, purpose: e.target.value })} />
          <Button onClick={() => run.mutate(() => pr.requestTranscript({ ...b, purpose: b.purpose || null }), { onSuccess: () => toast.success('Requested — pay from Fees'), onError: fail })}>Request</Button>
        </div>
      </Section>
      <SimpleTable head={['Type', 'Copies', 'Fee', 'Requested', 'Status', '']} rows={list(mine.data).map((t: Any) => [t.transcript_type, t.copies, t.invoice_status ?? '—', dt(t.requested_at), <StatusBadge key="s" status={t.status} />, t.status === 'issued' ? <div key="d" className="flex gap-1"><Button size="sm" variant="outline" onClick={() => pr.downloadTranscript(t.id).then((x) => openBlob(x, `transcript-${t.document_number ?? t.id}.pdf`)).catch(fail)}>Download</Button>{t.verification_token && <a className="text-xs text-primary underline" href={`/verify/${t.verification_token}`} target="_blank" rel="noreferrer">Verify</a>}</div> : null])} />
    </div>
  );
}
