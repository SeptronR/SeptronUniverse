import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Download, Plus, Send, Upload } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input, Select, Textarea } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs';
import { toast } from '@/components/ui/Toaster';
import { SimpleTable } from '@/features/hr/components/shared';
import { useMyOfferings } from '@/features/registration/hooks';
import { assessmentApi, lmsApi, openBlob } from '../api';
import { useAssessmentMutation, useQ } from '../hooks';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));
const STEPS = ['planned', 'marks_entry', 'submitted', 'verified', 'locked'];

function Stepper({ status }: { status: string }) {
  const at = Math.max(0, STEPS.indexOf(status === 'conducted' ? 'planned' : status));
  return (
    <div className="flex flex-wrap gap-1 text-xs">
      {STEPS.map((s, i) => (
        <Badge key={s} variant={i < at ? 'success' : i === at ? 'info' : 'outline'}>{s.replace('_', ' ')}</Badge>
      ))}
    </div>
  );
}

// ---- marks grid -----------------------------------------------------------------------------------------------------
function QuestionMapEditor({ a, cos, onClose }: { a: Any; cos: Any[]; onClose: () => void }) {
  const qs = useQ(['questions', a.id], () => assessmentApi.questions(a.id));
  const [rows, setRows] = useState<Any[]>([]);
  useEffect(() => setRows(qs.data?.data ?? []), [qs.data]);
  const save = useAssessmentMutation(() => assessmentApi.saveQuestions(a.id, rows.map((r) => ({ question_no: r.question_no, max_marks: Number(r.max_marks), co_id: r.co_id || null, bloom_level: r.bloom_level || null, part: r.part || null }))));
  const sum = rows.reduce((s, r) => s + Number(r.max_marks || 0), 0);
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`Question map — ${a.name}`} size="lg"
      footer={<Button disabled={sum !== Number(a.max_marks)} onClick={() => save.mutate(undefined, { onSuccess: () => { toast.success('Saved'); onClose(); }, onError: fail })}>Save ({sum}/{a.max_marks})</Button>}>
      <div className="space-y-2">
        {rows.map((r, i) => (
          <div key={i} className="flex flex-wrap gap-2">
            <Input className="w-16" placeholder="Part" value={r.part ?? ''} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, part: e.target.value } : x)))} />
            <Input className="w-20" placeholder="Q no." value={r.question_no} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, question_no: e.target.value } : x)))} />
            <Input className="w-20" type="number" placeholder="Max" value={r.max_marks} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, max_marks: e.target.value } : x)))} />
            <Select className="w-28" value={r.co_id ?? ''} placeholder="CO" options={cos.map((c) => ({ value: c.id, label: c.code }))} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, co_id: e.target.value } : x)))} />
            <Select className="w-32" value={r.bloom_level ?? ''} placeholder="Bloom" options={['remember', 'understand', 'apply', 'analyze', 'evaluate', 'create'].map((b) => ({ value: b, label: b }))} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, bloom_level: e.target.value } : x)))} />
            <Button size="sm" variant="ghost" onClick={() => setRows(rows.filter((_, j) => j !== i))}>Remove</Button>
          </div>
        ))}
        <Button size="sm" variant="outline" onClick={() => setRows([...rows, { question_no: `Q${rows.length + 1}`, max_marks: 0, part: 'A' }])}><Plus className="h-4 w-4" /> Question</Button>
      </div>
    </Modal>
  );
}

function MarksGrid({ a, courseId }: { a: Any; courseId?: string }) {
  const grid = useQ(['grid', a.id], () => assessmentApi.grid(a.id));
  const cos = useQ(['cos', courseId], () => assessmentApi.courseOutcomes(courseId!), !!courseId);
  const g = grid.data?.data;
  const [edits, setEdits] = useState<Record<string, Any>>({});
  const [qmap, setQmap] = useState(false);
  const [cr, setCr] = useState<Any | null>(null);
  const [crForm, setCrForm] = useState({ marks: '', reason: '' });
  const qmode = (g?.questions ?? []).length > 0;
  const save = useAssessmentMutation(() =>
    assessmentApi.saveMarks(a.id, Object.entries(edits).map(([id, e]) => ({ student_program_enrollment_id: id, ...e }))),
  );
  const submit = useAssessmentMutation(() => assessmentApi.submit(a.id));
  const requestChange = useAssessmentMutation(() => assessmentApi.requestChange({ target_id: cr.mark_id, new_value: { marks: Number(crForm.marks) }, reason: crForm.reason }));
  const [file, setFile] = useState<File | null>(null);
  const importJob = useAssessmentMutation(() => assessmentApi.importMarks(a.id, file!));
  const value = (r: Any, q?: string) => {
    const e = edits[r.student_program_enrollment_id];
    if (q) return e?.question_wise?.[q] ?? r.question_wise?.[q] ?? '';
    return e?.marks ?? r.marks ?? '';
  };
  const set = (r: Any, v: string, q?: string) => {
    const cur = edits[r.student_program_enrollment_id] ?? { question_wise: { ...(r.question_wise ?? {}) }, marks: r.marks };
    const next = q ? { ...cur, question_wise: { ...cur.question_wise, [q]: v === '' ? undefined : Number(v) }, marks: undefined } : { ...cur, marks: v === '' ? null : Number(v), question_wise: null };
    setEdits({ ...edits, [r.student_program_enrollment_id]: next });
  };
  const toggle = (r: Any, k: 'is_absent' | 'is_exempt') => setEdits({ ...edits, [r.student_program_enrollment_id]: { ...(edits[r.student_program_enrollment_id] ?? {}), [k]: !(edits[r.student_program_enrollment_id]?.[k] ?? r[k]) } });
  if (!g) return <p className="text-sm text-muted-foreground">{grid.error ? getApiError(grid.error) : 'Loading…'}</p>;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Stepper status={g.assessment.status} />
        {!g.read_only && <Button size="sm" variant="outline" onClick={() => setQmap(true)}>Question map</Button>}
        {!g.read_only && <Button size="sm" disabled={!Object.keys(edits).length} onClick={() => save.mutate(undefined, { onSuccess: (r: Any) => { setEdits({}); toast.success(`${r.data.saved} saved${r.data.rejected.length ? `, ${r.data.rejected.length} rejected` : ''}`); }, onError: fail })}>Save</Button>}
        {!g.read_only && <Button size="sm" onClick={() => submit.mutate(undefined, { onSuccess: () => toast.success('Submitted for verification'), onError: fail })}><Send className="h-4 w-4" /> Submit</Button>}
        {!g.read_only && (
          <>
            <input type="file" accept=".xlsx,.csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <Button size="sm" variant="outline" disabled={!file} onClick={() => importJob.mutate(undefined, { onSuccess: () => toast.success('Import queued — see Jobs'), onError: fail })}><Upload className="h-4 w-4" /> Import</Button>
          </>
        )}
        <Button size="sm" variant="ghost" onClick={() => assessmentApi.exportMarks(a.id).then(() => toast.success('Export queued — see Jobs')).catch(fail)}><Download className="h-4 w-4" /> Export</Button>
      </div>
      {Object.keys(g.co_summary ?? {}).length > 0 && (
        <div className="flex flex-wrap gap-2 text-xs">
          {Object.entries(g.co_summary).map(([co, pct]) => (
            <span key={co} className="rounded px-2 py-1" style={{ background: `hsl(${Math.min(120, Number(pct) * 1.2)} 70% 85%)` }}>{co}: {Number(pct).toFixed(0)}%</span>
          ))}
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left">
              <th className="p-1">Reg. no.</th>
              <th className="p-1">Name</th>
              {qmode && g.questions.map((q: Any) => <th key={q.question_no} className="p-1">{q.question_no}<span className="text-xs text-muted-foreground"> /{q.max_marks}{q.co_code ? ` ${q.co_code}` : ''}</span></th>)}
              <th className="p-1">Total /{g.assessment.max_marks}</th>
              <th className="p-1">AB</th>
              <th className="p-1">EX</th>
              {g.assessment.status === 'locked' && <th className="p-1" />}
            </tr>
          </thead>
          <tbody>
            {g.rows.map((r: Any) => {
              const e = edits[r.student_program_enrollment_id] ?? {};
              const total = qmode ? g.questions.reduce((s: number, q: Any) => s + Number(value(r, q.question_no) || 0), 0) : value(r);
              return (
                <tr key={r.student_program_enrollment_id} className="border-b">
                  <td className="p-1">{r.registration_number}</td>
                  <td className="p-1">{r.name}</td>
                  {qmode && g.questions.map((q: Any) => (
                    <td key={q.question_no} className="p-1">
                      <Input className="h-8 w-16" type="number" min={0} max={q.max_marks} step="0.5" disabled={g.read_only || (e.is_absent ?? r.is_absent)} value={value(r, q.question_no)} onChange={(ev) => set(r, ev.target.value, q.question_no)} />
                    </td>
                  ))}
                  <td className="p-1">
                    {qmode ? <span className="font-medium">{total}</span> : <Input className="h-8 w-20" type="number" min={0} max={g.assessment.max_marks} disabled={g.read_only || (e.is_absent ?? r.is_absent)} value={value(r)} onChange={(ev) => set(r, ev.target.value)} />}
                  </td>
                  <td className="p-1"><input type="checkbox" disabled={g.read_only} checked={e.is_absent ?? r.is_absent} onChange={() => toggle(r, 'is_absent')} /></td>
                  <td className="p-1"><input type="checkbox" disabled={g.read_only} checked={e.is_exempt ?? r.is_exempt} onChange={() => toggle(r, 'is_exempt')} /></td>
                  {g.assessment.status === 'locked' && <td className="p-1"><Button size="sm" variant="ghost" onClick={() => { setCr({ ...r, mark_id: r.mark_id }); setCrForm({ marks: String(r.marks ?? ''), reason: '' }); }}>Change…</Button></td>}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {qmap && <QuestionMapEditor a={g.assessment} cos={cos.data?.data?.cos ?? []} onClose={() => setQmap(false)} />}
      <Modal open={!!cr} onOpenChange={(o) => !o && setCr(null)} title={`Change request — ${cr?.name ?? ''}`}
        footer={<Button disabled={!crForm.reason || !cr?.mark_id} onClick={() => requestChange.mutate(undefined, { onSuccess: () => { toast.success('Requested — HOD → COE'); setCr(null); }, onError: fail })}>Request</Button>}>
        <Input placeholder="New marks" value={crForm.marks} onChange={(e) => setCrForm({ ...crForm, marks: e.target.value })} />
        <Textarea className="mt-2" placeholder="Reason / evidence" value={crForm.reason} onChange={(e) => setCrForm({ ...crForm, reason: e.target.value })} />
        {!cr?.mark_id && <p className="mt-2 text-xs text-muted-foreground">Open the change-request queue to raise it against the mark id.</p>}
      </Modal>
    </div>
  );
}

export function FacultyMarksPage() {
  const { offeringId } = useParams();
  useTitle('Internal marks');
  const list = useQ(['list', offeringId], () => assessmentApi.list(offeringId!), !!offeringId);
  const offerings = useMyOfferings();
  const off = (offerings.data?.data ?? []).find((o: Any) => o.id === offeringId) as Any;
  const inst = useAssessmentMutation(() => assessmentApi.instantiate(offeringId!));
  const rows: Any[] = list.data?.data ?? [];
  return (
    <div className="space-y-4">
      <PageHeader title={`Internal marks${off ? ` — ${off.course_code} ${off.section_code}` : ''}`} description="Per component: question map, marks grid, submit → HOD verify → exam-cell lock." />
      <div className="flex gap-2">
        <Button variant="outline" onClick={() => inst.mutate(undefined, { onSuccess: (r: Any) => toast.success(`${r.data.created} created`), onError: fail })}>Instantiate from scheme</Button>
        <Link className="self-center text-sm text-primary underline" to={`/faculty/offerings/${offeringId}/cia`}>CIA consolidation</Link>
      </div>
      {rows.length ? (
        <Tabs defaultValue={rows[0].id}>
          <TabsList>{rows.map((a) => <TabsTrigger key={a.id} value={a.id}>{a.name} <StatusBadge status={a.status} /></TabsTrigger>)}</TabsList>
          {rows.map((a) => <TabsContent key={a.id} value={a.id}><MarksGrid a={a} courseId={off?.course_id} /></TabsContent>)}
        </Tabs>
      ) : (
        <p className="text-sm text-muted-foreground">No assessments yet — instantiate them from the scheme.</p>
      )}
    </div>
  );
}

// ---- CIA ---------------------------------------------------------------------------------------------------------------
export function CiaPage() {
  const { id } = useParams();
  useTitle('CIA consolidation');
  const cia = useQ(['cia', id], () => assessmentApi.cia(id!), !!id);
  const run = useAssessmentMutation((fn: () => Promise<unknown>) => fn());
  const d = cia.data?.data;
  const codes = useMemo(() => Array.from(new Set((d?.rows ?? []).flatMap((r: Any) => Object.keys(r.component_breakdown ?? {}).filter((k) => !k.startsWith('_'))))) as string[], [d]);
  return (
    <div className="space-y-4">
      <PageHeader title="CIA consolidation" description={`Best-of and scaling to ${d?.cia_max ?? '…'}; HOD approve → lock → university submission (affiliated programmes).`} />
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => run.mutate(() => assessmentApi.consolidate(id!), { onSuccess: () => toast.success('Consolidated'), onError: fail })}>Recompute</Button>
        <Button variant="outline" onClick={() => run.mutate(() => assessmentApi.approveCia(id!), { onSuccess: () => toast.success('Approved'), onError: fail })}>HOD approve</Button>
        <Button variant="outline" onClick={() => run.mutate(() => assessmentApi.lockCia(id!), { onSuccess: () => toast.success('Locked'), onError: fail })}>Lock</Button>
        <Button variant="outline" onClick={() => run.mutate(() => assessmentApi.submitCia(id!), { onSuccess: () => toast.success('Submitted'), onError: fail })}>Submit to university</Button>
        {d?.status && <StatusBadge status={d.status} />}
      </div>
      <SimpleTable
        head={['Reg. no.', 'Name', ...codes, 'Total', `Scaled /${d?.cia_max ?? ''}`]}
        rows={(d?.rows ?? []).map((r: Any) => [
          r.registration_number,
          r.name,
          ...codes.map((c) => {
            const b = r.component_breakdown?.[c];
            return b ? <span key={c} className={b.counted === false ? 'text-muted-foreground line-through' : ''}>{b.absent ? 'AB' : b.exempt ? 'EX' : `${b.value}/${b.scaled_to}`}</span> : '—';
          }),
          r.cia_total,
          <strong key="s">{r.cia_scaled}</strong>,
        ])}
        empty="Not consolidated yet."
      />
    </div>
  );
}

// ---- LMS (faculty) ------------------------------------------------------------------------------------------------------
function ModulesTab({ offeringId }: { offeringId: string }) {
  const mods = useQ(['modules', offeringId], () => lmsApi.modules(offeringId));
  const [title, setTitle] = useState('');
  const [content, setContent] = useState<{ mid: string; type: string; title: string; url: string } | null>(null);
  const run = useAssessmentMutation((fn: () => Promise<unknown>) => fn());
  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <Input className="w-64" placeholder="Module title" value={title} onChange={(e) => setTitle(e.target.value)} />
        <Button disabled={!title} onClick={() => run.mutate(() => lmsApi.createModule(offeringId, { title, is_published: true, sequence: (mods.data?.data?.length ?? 0) + 1 }), { onSuccess: () => setTitle(''), onError: fail })}>Add module</Button>
      </div>
      {(mods.data?.data ?? []).map((m: Any) => (
        <div key={m.id} className="rounded border p-3">
          <div className="flex items-center justify-between">
            <p className="font-medium">{m.title} {!m.is_published && <Badge variant="outline">draft</Badge>}</p>
            <div className="flex gap-1">
              <Button size="sm" variant="outline" onClick={() => run.mutate(() => lmsApi.updateModule(m.id, { title: m.title, sequence: m.sequence, is_published: !m.is_published }), { onError: fail })}>{m.is_published ? 'Unpublish' : 'Publish'}</Button>
              <Button size="sm" variant="outline" onClick={() => setContent({ mid: m.id, type: 'file', title: '', url: '' })}>Add content</Button>
            </div>
          </div>
          <ul className="mt-2 space-y-1 text-sm">
            {m.contents.map((c: Any) => (
              <li key={c.id} className="flex items-center justify-between">
                <span><Badge variant="secondary">{c.content_type}</Badge> {c.title} <span className="text-xs text-muted-foreground">({c.view_count} views)</span></span>
                <Button size="sm" variant="ghost" onClick={() => run.mutate(() => lmsApi.deleteContent(c.id), { onError: fail })}>Delete</Button>
              </li>
            ))}
          </ul>
        </div>
      ))}
      <Modal open={!!content} onOpenChange={(o) => !o && setContent(null)} title="Add content"
        footer={<Button disabled={!content?.title} onClick={() => run.mutate(() => lmsApi.addContent(content!.mid, { content_type: content!.type, title: content!.title, file_url: content!.url || null, body: content!.type === 'text' ? content!.url : null }), { onSuccess: () => setContent(null), onError: fail })}>Add</Button>}>
        {content && (
          <div className="space-y-2">
            <Select value={content.type} options={['file', 'video', 'link', 'text', 'scorm', 'embed'].map((t) => ({ value: t, label: t }))} onChange={(e) => setContent({ ...content, type: e.target.value })} />
            <Input placeholder="Title" value={content.title} onChange={(e) => setContent({ ...content, title: e.target.value })} />
            <Input placeholder={content.type === 'text' ? 'Text' : 'URL'} value={content.url} onChange={(e) => setContent({ ...content, url: e.target.value })} />
          </div>
        )}
      </Modal>
    </div>
  );
}

function AssignmentsTab({ offeringId }: { offeringId: string }) {
  const list = useQ(['assignments', offeringId], () => lmsApi.assignments(offeringId));
  const [form, setForm] = useState({ title: '', due_at: '', max_marks: '10', late: '10' });
  const [open, setOpen] = useState<Any | null>(null);
  const subs = useQ(['subs', open?.id], () => lmsApi.submissions(open.id), !!open);
  const [grades, setGrades] = useState<Record<string, Any>>({});
  const run = useAssessmentMutation((fn: () => Promise<unknown>) => fn());
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Input className="w-64" placeholder="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
        <Input className="w-56" type="datetime-local" value={form.due_at} onChange={(e) => setForm({ ...form, due_at: e.target.value })} />
        <Input className="w-24" placeholder="Max" value={form.max_marks} onChange={(e) => setForm({ ...form, max_marks: e.target.value })} />
        <Input className="w-28" placeholder="Late %/day" value={form.late} onChange={(e) => setForm({ ...form, late: e.target.value })} />
        <Button disabled={!form.title} onClick={() => run.mutate(() => lmsApi.createAssignment(offeringId, { title: form.title, due_at: form.due_at ? new Date(form.due_at).toISOString() : null, max_marks: Number(form.max_marks), late_penalty_pct_per_day: Number(form.late), rubric: [{ criterion: 'quality', max: Number(form.max_marks) }] }), { onSuccess: () => toast.success('Draft created'), onError: fail })}>Create</Button>
      </div>
      <SimpleTable
        head={['Title', 'Due', 'Status', 'Submissions', '']}
        rows={(list.data?.data ?? []).map((a: Any) => [
          a.title,
          a.due_at ? new Date(a.due_at).toLocaleString() : '—',
          <StatusBadge key="s" status={a.status} />,
          a.submissions,
          <div key="b" className="flex gap-1">
            {a.status === 'draft' && <Button size="sm" onClick={() => run.mutate(() => lmsApi.assignmentStatus(a.id, 'publish'), { onError: fail })}>Publish</Button>}
            {a.status === 'published' && <Button size="sm" variant="outline" onClick={() => run.mutate(() => lmsApi.assignmentStatus(a.id, 'close'), { onError: fail })}>Close</Button>}
            <Button size="sm" variant="outline" onClick={() => setOpen(a)}>Grade</Button>
          </div>,
        ])}
      />
      <Modal open={!!open} onOpenChange={(o) => !o && setOpen(null)} title={`Grade — ${open?.title ?? ''}`} size="xl"
        footer={
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => run.mutate(() => lmsApi.similarity(open.id), { onSuccess: () => toast.success('Similarity check queued'), onError: fail })}>Similarity check</Button>
            <Button disabled={!Object.keys(grades).length} onClick={() => run.mutate(() => lmsApi.grade(open.id, Object.entries(grades).map(([submission_id, g]) => ({ submission_id, ...g }))), { onSuccess: () => { setGrades({}); toast.success('Graded'); }, onError: fail })}>Save grades</Button>
          </div>
        }>
        <SimpleTable
          head={['Student', 'Submitted', 'Late', 'Similarity', 'Marks', 'Feedback']}
          rows={(subs.data?.data ?? []).map((s: Any) => [
            `${s.student_name ?? ''} (${s.registration_number ?? ''})`,
            new Date(s.submitted_at).toLocaleString(),
            s.is_late ? <Badge key="l" variant="warning">late</Badge> : '—',
            s.similarity_pct != null ? `${s.similarity_pct}%` : '—',
            <Input key="m" className="h-8 w-20" defaultValue={s.marks ?? ''} onChange={(e) => setGrades({ ...grades, [s.id]: { ...(grades[s.id] ?? {}), marks: Number(e.target.value) } })} />,
            <Input key="f" className="h-8 w-48" defaultValue={s.feedback ?? ''} onChange={(e) => setGrades({ ...grades, [s.id]: { ...(grades[s.id] ?? {}), feedback: e.target.value } })} />,
          ])}
          empty="No submissions yet."
        />
      </Modal>
    </div>
  );
}

function QuizzesTab({ offeringId, courseId }: { offeringId: string; courseId?: string }) {
  const list = useQ(['quizzes', offeringId], () => lmsApi.quizzes(offeringId));
  const papers = useQ(['papers', courseId], () => lmsApi.blueprints({ course_id: courseId }), !!courseId);
  const [form, setForm] = useState({ title: '', paper: '', minutes: '15' });
  const [attempts, setAttempts] = useState<string | null>(null);
  const att = useQ(['attempts', attempts], () => lmsApi.attempts(attempts!), !!attempts);
  const run = useAssessmentMutation((fn: () => Promise<unknown>) => fn());
  void papers;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Input className="w-56" placeholder="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
        <Input className="w-72" placeholder="Frozen question paper id (Question bank)" value={form.paper} onChange={(e) => setForm({ ...form, paper: e.target.value })} />
        <Input className="w-20" placeholder="Min" value={form.minutes} onChange={(e) => setForm({ ...form, minutes: e.target.value })} />
        <Button disabled={!form.title || !form.paper} onClick={() => run.mutate(() => lmsApi.createQuiz(offeringId, { title: form.title, question_paper_id: form.paper, duration_minutes: Number(form.minutes) }), { onSuccess: () => toast.success('Draft created'), onError: fail })}>Create</Button>
      </div>
      <SimpleTable
        head={['Title', 'Duration', 'Status', '']}
        rows={(list.data?.data ?? []).map((q: Any) => [
          q.title,
          `${q.duration_minutes} min`,
          <StatusBadge key="s" status={q.status} />,
          <div key="b" className="flex gap-1">
            {q.status === 'draft' && <Button size="sm" onClick={() => run.mutate(() => lmsApi.quizStatus(q.id, 'publish'), { onError: fail })}>Publish</Button>}
            {q.status === 'published' && <Button size="sm" variant="outline" onClick={() => run.mutate(() => lmsApi.quizStatus(q.id, 'close'), { onError: fail })}>Close</Button>}
            <Button size="sm" variant="outline" onClick={() => setAttempts(q.id)}>Attempts</Button>
            <Button size="sm" variant="outline" onClick={() => run.mutate(() => lmsApi.pushToMarks(q.id), { onSuccess: () => toast.success('Pushed to marks'), onError: fail })}>Push to marks</Button>
          </div>,
        ])}
      />
      <Modal open={!!attempts} onOpenChange={(o) => !o && setAttempts(null)} title="Attempts" size="lg">
        <SimpleTable head={['Student', 'Attempt', 'Status', 'Auto', 'Total']} rows={(att.data?.data ?? []).map((a: Any) => [a.student_name, a.attempt_no, <StatusBadge key="s" status={a.status} />, a.auto_score ?? '—', a.total_score ?? '—'])} />
      </Modal>
    </div>
  );
}

function DiscussionsTab({ offeringId, faculty }: { offeringId: string; faculty: boolean }) {
  const threads = useQ(['threads', offeringId], () => lmsApi.threads(offeringId));
  const [open, setOpen] = useState<Any | null>(null);
  const posts = useQ(['posts', open?.id], () => lmsApi.posts(open.id), !!open);
  const [title, setTitle] = useState('');
  const [reply, setReply] = useState('');
  const run = useAssessmentMutation((fn: () => Promise<unknown>) => fn());
  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <Input className="w-80" placeholder="New thread title" value={title} onChange={(e) => setTitle(e.target.value)} />
        <Button disabled={!title} onClick={() => run.mutate(() => lmsApi.createThread(offeringId, { title }), { onSuccess: () => setTitle(''), onError: fail })}>Start thread</Button>
      </div>
      <SimpleTable
        head={['Thread', 'Posts', '', '']}
        rows={(threads.data?.data ?? []).map((t: Any) => [
          <span key="t">{t.is_pinned && '📌 '}{t.title} {t.is_locked && <Badge variant="outline">locked</Badge>}</span>,
          t.posts,
          <Button key="o" size="sm" variant="outline" onClick={() => setOpen(t)}>Open</Button>,
          faculty && <Button key="l" size="sm" variant="ghost" onClick={() => run.mutate(() => lmsApi.patchThread(t.id, { is_locked: !t.is_locked }), { onError: fail })}>{t.is_locked ? 'Unlock' : 'Lock'}</Button>,
        ])}
      />
      <Modal open={!!open} onOpenChange={(o) => !o && setOpen(null)} title={open?.title ?? ''} size="lg"
        footer={<div className="flex w-full gap-2"><Input placeholder="Reply" value={reply} onChange={(e) => setReply(e.target.value)} /><Button disabled={!reply} onClick={() => run.mutate(() => lmsApi.post(open.id, reply), { onSuccess: () => setReply(''), onError: fail })}>Post</Button></div>}>
        <div className="space-y-2">
          {(posts.data?.data ?? []).map((p: Any) => (
            <div key={p.id} className={`rounded border p-2 text-sm ${p.is_answer ? 'border-status-approved' : ''}`}>
              <p className="text-xs text-muted-foreground">{p.author_name} · {new Date(p.created_at).toLocaleString()}</p>
              <p>{p.body}</p>
              <div className="flex gap-1">
                <Button size="sm" variant="ghost" onClick={() => run.mutate(() => lmsApi.upvote(p.id), { onError: fail })}>▲ {p.upvotes}</Button>
                {faculty && !p.is_answer && <Button size="sm" variant="ghost" onClick={() => run.mutate(() => lmsApi.markAnswer(p.id), { onError: fail })}>Mark answer</Button>}
              </div>
            </div>
          ))}
        </div>
      </Modal>
    </div>
  );
}

function AnnouncementsTab({ offeringId, faculty }: { offeringId: string; faculty: boolean }) {
  const list = useQ(['ann', offeringId], () => lmsApi.announcements(offeringId));
  const [form, setForm] = useState({ title: '', body: '' });
  const [link, setLink] = useState('');
  const run = useAssessmentMutation((fn: () => Promise<unknown>) => fn());
  return (
    <div className="space-y-3">
      {faculty && (
        <div className="space-y-2">
          <Input placeholder="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          <Textarea placeholder="Message" value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} />
          <Button disabled={!form.title} onClick={() => run.mutate(() => lmsApi.announce(offeringId, form), { onSuccess: () => { setForm({ title: '', body: '' }); toast.success('Posted — students notified'); }, onError: fail })}>Post</Button>
          <div className="flex gap-2">
            <Input placeholder="Online class link (blank = create a meeting)" value={link} onChange={(e) => setLink(e.target.value)} />
            <Button variant="outline" onClick={() => run.mutate(() => lmsApi.onlineLink(offeringId, link || undefined), { onSuccess: () => toast.success('Link saved'), onError: fail })}>Save link</Button>
          </div>
        </div>
      )}
      {(list.data?.data ?? []).map((a: Any) => (
        <div key={a.id} className="rounded border p-3 text-sm">
          <p className="font-medium">{a.pinned && '📌 '}{a.title}</p>
          <p className="whitespace-pre-wrap">{a.body}</p>
          <p className="text-xs text-muted-foreground">{new Date(a.posted_at).toLocaleString()}</p>
        </div>
      ))}
    </div>
  );
}

export function OfferingLmsPage() {
  const { id } = useParams();
  useTitle('Course LMS');
  const offerings = useMyOfferings();
  const off = (offerings.data?.data ?? []).find((o: Any) => o.id === id) as Any;
  if (!id) return null;
  return (
    <div className="space-y-4">
      <PageHeader title={`LMS${off ? ` — ${off.course_code} ${off.section_code}` : ''}`} />
      <Tabs defaultValue="modules">
        <TabsList>
          <TabsTrigger value="modules">Modules</TabsTrigger>
          <TabsTrigger value="assignments">Assignments</TabsTrigger>
          <TabsTrigger value="quizzes">Quizzes</TabsTrigger>
          <TabsTrigger value="announcements">Announcements</TabsTrigger>
          <TabsTrigger value="discussions">Discussions</TabsTrigger>
        </TabsList>
        <TabsContent value="modules"><ModulesTab offeringId={id} /></TabsContent>
        <TabsContent value="assignments"><AssignmentsTab offeringId={id} /></TabsContent>
        <TabsContent value="quizzes"><QuizzesTab offeringId={id} courseId={off?.course_id} /></TabsContent>
        <TabsContent value="announcements"><AnnouncementsTab offeringId={id} faculty /></TabsContent>
        <TabsContent value="discussions"><DiscussionsTab offeringId={id} faculty /></TabsContent>
      </Tabs>
    </div>
  );
}

// ---- lesson plan / course file --------------------------------------------------------------------------------------------
export function LessonPlanPage() {
  const { id } = useParams();
  useTitle('Lesson plan');
  const plan = useQ(['plan', id], () => lmsApi.plan(id!), !!id);
  const dev = useQ(['deviation', id], () => lmsApi.deviation(id!), !!id);
  const file = useQ(['course-file', id], () => lmsApi.courseFile(id!), !!id);
  const [draft, setDraft] = useState('');
  const run = useAssessmentMutation((fn: () => Promise<unknown>) => fn());
  const f = file.data?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Lesson plan & course file" description="Plan unit-wise topics, tick delivery against sessions, track deviation; the course file fills itself as marks lock and the plan is delivered." />
      <Tabs defaultValue="plan">
        <TabsList>
          <TabsTrigger value="plan">Plan</TabsTrigger>
          <TabsTrigger value="deviation">Deviation</TabsTrigger>
          <TabsTrigger value="file">Course file ({f?.completion_pct ?? 0}%)</TabsTrigger>
        </TabsList>
        <TabsContent value="plan">
          <SimpleTable
            head={['#', 'Unit', 'Topic', 'Planned', 'Status', '']}
            rows={(plan.data?.data ?? []).map((r: Any) => [
              r.sequence,
              r.unit_no ?? '—',
              r.topic,
              r.planned_date ?? '—',
              <StatusBadge key="s" status={r.status} />,
              r.status !== 'delivered' && <Button key="d" size="sm" variant="outline" onClick={() => run.mutate(() => lmsApi.deliver(r.id, {}), { onSuccess: () => toast.success('Delivered'), onError: fail })}>Delivered today</Button>,
            ])}
            empty="No plan yet."
          />
          <p className="mt-3 text-sm">Replace the plan — one topic per line (<code>unit | topic | yyyy-mm-dd</code>):</p>
          <Textarea rows={6} value={draft} onChange={(e) => setDraft(e.target.value)} />
          <Button className="mt-2" disabled={!draft.trim()} onClick={() => run.mutate(() => lmsApi.savePlan(id!, draft.trim().split('\n').map((l, i) => { const [u, t, d] = l.split('|').map((x) => x.trim()); return { unit_no: Number(u) || null, topic: t || u, planned_date: d || null, sequence: i + 1, planned_hours: 1 }; })), { onSuccess: () => { setDraft(''); toast.success('Plan saved'); }, onError: fail })}>Save plan</Button>
        </TabsContent>
        <TabsContent value="deviation">
          <SimpleTable head={['#', 'Topic', 'Planned', 'Actual', 'Days late', 'Status']} rows={(dev.data?.data ?? []).map((r: Any) => [r.sequence, r.topic, r.planned_date ?? '—', r.actual_date ?? '—', r.days_late ?? '—', r.status])} />
        </TabsContent>
        <TabsContent value="file">
          <SimpleTable
            head={['Item', 'Done', 'Source']}
            rows={(f?.checklist ?? []).map((c: Any) => [
              c.label ?? c.key,
              <input key="d" type="checkbox" disabled={c.auto} checked={!!c.done} onChange={() => run.mutate(() => lmsApi.saveCourseFile(id!, [{ key: c.key, done: !c.done }]), { onError: fail })} />,
              c.auto ? 'automatic' : 'manual',
            ])}
          />
          {f?.audited_at && <p className="text-sm">Audited {new Date(f.audited_at).toLocaleDateString()} — {f.remarks}</p>}
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ---- projects ------------------------------------------------------------------------------------------------------------
export function FacultyProjectsPage() {
  useTitle('Projects');
  const offerings = useMyOfferings();
  const [off, setOff] = useState('');
  const list = useQ(['projects', off], () => lmsApi.projects(off), !!off);
  const [form, setForm] = useState({ title: '', members: '' });
  const [review, setReview] = useState<Any | null>(null);
  const [rv, setRv] = useState({ review_no: 1, problem: '', design: '', presentation: '', assessment: '' });
  const run = useAssessmentMutation((fn: () => Promise<unknown>) => fn());
  return (
    <div className="space-y-4">
      <PageHeader title="Projects & dissertations" description="Members from the offering's roster, guides, reviews with rubric → project_review marks." />
      <Select className="w-80" value={off} placeholder="Offering" options={(offerings.data?.data ?? []).map((o: Any) => ({ value: o.id, label: `${o.course_code} ${o.section_code}` }))} onChange={(e) => setOff(e.target.value)} />
      {off && (
        <div className="flex flex-wrap gap-2">
          <Input className="w-64" placeholder="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          <Input className="w-96" placeholder="Member enrolment ids (comma separated, leader first)" value={form.members} onChange={(e) => setForm({ ...form, members: e.target.value })} />
          <Button disabled={!form.title} onClick={() => run.mutate(() => lmsApi.createProject(off, { title: form.title, members: form.members.split(',').map((x) => x.trim()).filter(Boolean) }), { onSuccess: () => toast.success('Project created'), onError: fail })}>Create</Button>
        </div>
      )}
      <SimpleTable
        head={['Title', 'Type', 'Members', 'Reviews', 'Status', '']}
        rows={(list.data?.data ?? []).map((p: Any) => [
          p.title,
          p.project_type,
          p.members.map((m: Any) => m.registration_number).join(', '),
          p.reviews.map((r: Any) => `R${r.review_no}: ${r.marks ?? '—'}`).join(' · '),
          <StatusBadge key="s" status={p.status} />,
          <Button key="r" size="sm" variant="outline" onClick={() => setReview(p)}>Review</Button>,
        ])}
      />
      <Modal open={!!review} onOpenChange={(o) => !o && setReview(null)} title={`Review — ${review?.title ?? ''}`}
        footer={<Button onClick={() => run.mutate(() => lmsApi.review(review.id, { review_no: rv.review_no, rubric_scores: { problem: Number(rv.problem || 0), design: Number(rv.design || 0), presentation: Number(rv.presentation || 0) }, offering_assessment_id: rv.assessment || null }), { onSuccess: () => { toast.success('Review recorded'); setReview(null); }, onError: fail })}>Save</Button>}>
        <div className="grid grid-cols-2 gap-2">
          <Input type="number" placeholder="Review no." value={rv.review_no} onChange={(e) => setRv({ ...rv, review_no: Number(e.target.value) })} />
          <Input placeholder="Linked assessment id (project_review)" value={rv.assessment} onChange={(e) => setRv({ ...rv, assessment: e.target.value })} />
          <Input placeholder="Problem" value={rv.problem} onChange={(e) => setRv({ ...rv, problem: e.target.value })} />
          <Input placeholder="Design" value={rv.design} onChange={(e) => setRv({ ...rv, design: e.target.value })} />
          <Input placeholder="Presentation" value={rv.presentation} onChange={(e) => setRv({ ...rv, presentation: e.target.value })} />
        </div>
      </Modal>
    </div>
  );
}

// ---- question bank ---------------------------------------------------------------------------------------------------------
export function QuestionBankPage() {
  useTitle('Question bank');
  const [courseId, setCourseId] = useState('');
  const qs = useQ(['qbank', courseId], () => lmsApi.questions({ course_id: courseId || undefined }));
  const bps = useQ(['bps', courseId], () => lmsApi.blueprints({ course_id: courseId || undefined }));
  const [form, setForm] = useState({ body: '', body2: '', opts: 'A,B,C,D', correct: 'A', marks: '1', difficulty: 'medium' });
  const [bp, setBp] = useState({ name: '', count: '10', marks: '1' });
  const [paper, setPaper] = useState<Any | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const run = useAssessmentMutation((fn: () => Promise<unknown>) => fn());
  return (
    <div className="space-y-4">
      <PageHeader title="Question bank" description="Bilingual questions with CO / Bloom / difficulty, blueprints, generated papers (freeze → print)." />
      <Input className="w-96" placeholder="Course id (filter / new questions)" value={courseId} onChange={(e) => setCourseId(e.target.value)} />
      <Tabs defaultValue="questions">
        <TabsList>
          <TabsTrigger value="questions">Questions</TabsTrigger>
          <TabsTrigger value="blueprints">Blueprints & papers</TabsTrigger>
        </TabsList>
        <TabsContent value="questions">
          <div className="space-y-2 rounded border p-3">
            <Textarea placeholder="Question (primary language; $…$ for maths)" value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} />
            <Textarea placeholder="Question (second language, optional)" value={form.body2} onChange={(e) => setForm({ ...form, body2: e.target.value })} />
            <div className="flex flex-wrap gap-2">
              <Input className="w-64" placeholder="Options (comma separated)" value={form.opts} onChange={(e) => setForm({ ...form, opts: e.target.value })} />
              <Input className="w-24" placeholder="Correct" value={form.correct} onChange={(e) => setForm({ ...form, correct: e.target.value })} />
              <Input className="w-20" placeholder="Marks" value={form.marks} onChange={(e) => setForm({ ...form, marks: e.target.value })} />
              <Select className="w-28" value={form.difficulty} options={['easy', 'medium', 'hard'].map((d) => ({ value: d, label: d }))} onChange={(e) => setForm({ ...form, difficulty: e.target.value })} />
              <Button disabled={!form.body} onClick={() => run.mutate(() => lmsApi.createQuestion({ course_id: courseId || null, question_type: 'mcq', body_primary: form.body, body_secondary: form.body2 || null, marks: Number(form.marks), difficulty: form.difficulty, options: form.opts.split(',').map((o) => ({ body_primary: o.trim(), is_correct: o.trim() === form.correct.trim() })) }), { onSuccess: () => toast.success('Question saved'), onError: fail })}>Add MCQ</Button>
            </div>
            <div className="flex gap-2">
              <input type="file" accept=".csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              <Button size="sm" variant="outline" disabled={!file} onClick={() => run.mutate(() => lmsApi.importQuestions(file!, courseId || undefined), { onSuccess: (r: Any) => toast.success(`${r.data.created} imported, ${r.data.failed.length} failed`), onError: fail })}><Upload className="h-4 w-4" /> Import CSV</Button>
            </div>
          </div>
          <SimpleTable
            head={['Question', 'Type', 'Marks', 'Difficulty', 'Used', '']}
            rows={(qs.data?.data ?? []).map((q: Any) => [q.body_primary.slice(0, 80), q.question_type, q.marks, q.difficulty, q.usage_count, <Button key="d" size="sm" variant="ghost" onClick={() => run.mutate(() => lmsApi.deleteQuestion(q.id), { onError: fail })}>Delete</Button>])}
          />
        </TabsContent>
        <TabsContent value="blueprints">
          <div className="flex flex-wrap gap-2">
            <Input className="w-56" placeholder="Blueprint name" value={bp.name} onChange={(e) => setBp({ ...bp, name: e.target.value })} />
            <Input className="w-20" placeholder="Count" value={bp.count} onChange={(e) => setBp({ ...bp, count: e.target.value })} />
            <Input className="w-20" placeholder="Marks" value={bp.marks} onChange={(e) => setBp({ ...bp, marks: e.target.value })} />
            <Button disabled={!bp.name} onClick={() => run.mutate(() => lmsApi.createBlueprint({ course_id: courseId || null, name: bp.name, total_marks: Number(bp.count) * Number(bp.marks), duration_minutes: 30, pattern: { parts: [{ title: 'Part A', count: Number(bp.count), marks: Number(bp.marks) }] } }), { onSuccess: () => toast.success('Blueprint saved'), onError: fail })}>Create blueprint</Button>
          </div>
          <SimpleTable
            head={['Blueprint', 'Total', '']}
            rows={(bps.data?.data ?? []).map((b: Any) => [b.name, b.total_marks, <Button key="g" size="sm" onClick={() => run.mutate(() => lmsApi.generate({ blueprint_id: b.id }).then((r: Any) => setPaper(r.data)), { onError: fail })}>Generate paper</Button>])}
          />
          {paper && (
            <div className="space-y-2 rounded border p-3 text-sm">
              <p className="font-medium">{paper.title} · {paper.status} · id <code>{paper.id}</code></p>
              {paper.shortfall?.length > 0 && <p className="text-destructive">Shortfall: {paper.shortfall.map((s: Any) => `${s.part} ${s.found}/${s.wanted}`).join(', ')}</p>}
              <div className="flex gap-2">
                <Button size="sm" disabled={paper.status !== 'draft'} onClick={() => run.mutate(() => lmsApi.freeze(paper.id).then((r: Any) => setPaper(r.data)), { onError: fail })}>Freeze</Button>
                {['primary', 'secondary', 'both'].map((l) => <Button key={l} size="sm" variant="outline" onClick={() => lmsApi.printPaper(paper.id, l).then((b) => openBlob(b)).catch(fail)}>Print {l}</Button>)}
              </div>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ---- course outcomes ------------------------------------------------------------------------------------------------------
export function CourseOutcomesPage() {
  const { id } = useParams();
  useTitle('Course outcomes');
  const data = useQ(['cos', id], () => assessmentApi.courseOutcomes(id!), !!id);
  const d = data.data?.data;
  const [cos, setCos] = useState<Any[]>([]);
  const [cells, setCells] = useState<Record<string, number>>({});
  const [just, setJust] = useState<Record<string, string>>({});
  useEffect(() => {
    if (!d) return;
    setCos(d.cos);
    setCells(Object.fromEntries(d.matrix.map((c: Any) => [`${c.co_id}|${c.outcome_id}`, c.level])));
    setJust(Object.fromEntries(d.matrix.map((c: Any) => [`${c.co_id}|${c.outcome_id}`, c.justification ?? ''])));
  }, [d]);
  const run = useAssessmentMutation((fn: () => Promise<unknown>) => fn());
  if (!d) return <p className="text-sm text-muted-foreground">{data.error ? getApiError(data.error) : 'Loading…'}</p>;
  return (
    <div className="space-y-4">
      <PageHeader title="Course outcomes & CO-PO matrix" description="4–8 COs; every CO maps to at least one PO (levels 1–3 with justification)." />
      {d.warnings.map((w: string) => <p key={w} className="text-sm text-status-pending">{w}</p>)}
      {cos.map((c, i) => (
        <div key={i} className="flex gap-2">
          <Input className="w-20" value={c.code} disabled={!d.editable} onChange={(e) => setCos(cos.map((x, j) => (j === i ? { ...x, code: e.target.value } : x)))} />
          <Input value={c.statement} disabled={!d.editable} onChange={(e) => setCos(cos.map((x, j) => (j === i ? { ...x, statement: e.target.value } : x)))} />
          <Select className="w-32" value={c.bloom_level ?? ''} disabled={!d.editable} placeholder="Bloom" options={['remember', 'understand', 'apply', 'analyze', 'evaluate', 'create'].map((b) => ({ value: b, label: b }))} onChange={(e) => setCos(cos.map((x, j) => (j === i ? { ...x, bloom_level: e.target.value } : x)))} />
        </div>
      ))}
      {d.editable && (
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setCos([...cos, { code: `CO${cos.length + 1}`, statement: '', sequence: cos.length + 1 }])}><Plus className="h-4 w-4" /> CO</Button>
          <Button onClick={() => run.mutate(() => assessmentApi.saveCos(id!, cos.map((c, i) => ({ code: c.code, statement: c.statement, bloom_level: c.bloom_level || null, sequence: i + 1 }))), { onSuccess: () => toast.success('COs saved'), onError: fail })}>Save COs</Button>
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="text-sm">
          <thead><tr><th className="p-1 text-left">CO</th>{d.program_outcomes.map((p: Any) => <th key={p.id} className="p-1" title={p.statement}>{p.code}</th>)}</tr></thead>
          <tbody>
            {d.cos.map((c: Any) => (
              <tr key={c.id}>
                <td className="p-1 font-medium">{c.code}</td>
                {d.program_outcomes.map((p: Any) => {
                  const k = `${c.id}|${p.id}`;
                  return (
                    <td key={p.id} className="p-1">
                      <select className="rounded border bg-background p-1" disabled={!d.editable} value={cells[k] ?? ''} title={just[k] || 'Justification'} onChange={(e) => setCells({ ...cells, [k]: Number(e.target.value) })} onDoubleClick={() => { const j = window.prompt('Justification', just[k] ?? ''); if (j !== null) setJust({ ...just, [k]: j }); }}>
                        <option value="">–</option>
                        {[1, 2, 3].map((n) => <option key={n} value={n}>{n}</option>)}
                      </select>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex gap-2">
        {d.editable && <Button onClick={() => run.mutate(() => assessmentApi.saveMatrix(id!, Object.entries(cells).filter(([, v]) => v).map(([k, level]) => { const [co_id, outcome_id] = k.split('|'); return { co_id, outcome_id, level, justification: just[k] || null }; })), { onSuccess: () => toast.success('Matrix saved'), onError: fail })}>Save matrix</Button>}
        <Button variant="outline" onClick={() => assessmentApi.matrixCsv(id!).then((b) => openBlob(b, `co-po-${id}.csv`)).catch(fail)}><Download className="h-4 w-4" /> CSV</Button>
      </div>
      <p className="text-xs text-muted-foreground">Double-click a cell to add its justification.</p>
    </div>
  );
}

export { AnnouncementsTab, DiscussionsTab };
