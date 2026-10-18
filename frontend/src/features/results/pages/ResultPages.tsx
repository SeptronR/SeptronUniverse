import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { toast } from '@/components/ui/Toaster';
import { SimpleTable } from '@/features/hr/components/shared';
import { openBlob } from '@/features/exams/api';
import { resultsApi } from '../api';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));
const useQ = <T,>(key: unknown[], fn: () => Promise<T>, enabled = true) => useQuery({ queryKey: ['results', ...key], queryFn: fn, enabled, retry: false });
function useRun() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: () => qc.invalidateQueries({ queryKey: ['results'] }) });
}
const CHIP: Record<string, 'destructive' | 'outline' | 'secondary'> = { W: 'secondary', AB: 'destructive', WH: 'destructive', MP: 'destructive', I: 'secondary', F: 'destructive' };

// ---- /faculty/evaluation — evaluator portal (dummy numbers only) --------------------------------------------------------
export function EvaluatorPortalPage() {
  useTitle('Evaluation');
  const mine = useQ(['my-bundles'], () => resultsApi.myBundles());
  const [sel, setSel] = useState<Any | null>(null);
  return (
    <div className="space-y-4">
      <PageHeader title="Evaluation" description="Assigned bundles — scripts are identified by dummy numbers only." />
      <SimpleTable
        head={['Bundle', 'Paper', 'Round', 'Progress', 'Due', 'Status', '']}
        rows={(mine.data?.data ?? []).map((b: Any) => [
          b.bundle_number,
          `${b.paper_code ?? ''} ${b.course_title ?? ''}`,
          b.valuation_round,
          `${b.valued}/${b.scripts}`,
          b.due_at ? new Date(b.due_at).toLocaleDateString() : '—',
          <StatusBadge key="s" status={b.status} />,
          <Button key="o" size="sm" variant="outline" onClick={() => setSel(b)}>Open</Button>,
        ])}
      />
      {sel && <BundleEntry bundle={sel} />}
    </div>
  );
}

function BundleEntry({ bundle }: { bundle: Any }) {
  const scripts = useQ(['bundle-scripts', bundle.bundle_id], () => resultsApi.bundleScripts(bundle.bundle_id));
  const questions: { q: string; max: number }[] = Array.isArray(bundle.qp_pattern?.questions)
    ? bundle.qp_pattern.questions.map((q: Any, i: number) => ({ q: String(q.q ?? q.id ?? i + 1), max: Number(q.max ?? q.max_marks ?? 0) }))
    : Object.entries(bundle.qp_pattern ?? {}).filter(([k]) => k !== 'total').map(([q, m]) => ({ q, max: Number(m) }));
  const [qw, setQw] = useState<Record<string, Record<string, string>>>({});
  const [tot, setTot] = useState<Record<string, string>>({});
  const run = useRun();
  const locked = ['submitted', 'verified'].includes(bundle.status);
  const save = (s: Any) => {
    const parts = qw[s.id] ?? {};
    const question_wise = questions.length ? Object.fromEntries(Object.entries(parts).filter(([, v]) => v !== '').map(([k, v]) => [k, Number(v)])) : undefined;
    const marks = question_wise && Object.keys(question_wise).length ? Object.values(question_wise).reduce((a, b) => a + b, 0) : Number(tot[s.id] ?? s.marks ?? 0);
    if (marks > Number(bundle.max_marks)) return toast.error(`Exceeds the maximum ${bundle.max_marks}`);
    run.mutate(() => resultsApi.submitMarks(s.id, bundle.valuation_round, { marks, question_wise }), { onSuccess: () => toast.success(`${s.dummy_number} saved`), onError: fail });
  };
  return (
    <Card><CardContent className="space-y-3 p-4">
      <div className="flex items-center justify-between">
        <p className="font-medium">Bundle {bundle.bundle_number} · round {bundle.valuation_round} · max {bundle.max_marks}</p>
        {!locked && <Button onClick={() => { if (window.confirm('Submit the bundle? Marks are locked afterwards.')) run.mutate(() => resultsApi.submitBundle(bundle.bundle_id), { onSuccess: () => toast.success('Bundle submitted'), onError: fail }); }}>Submit bundle</Button>}
      </div>
      <SimpleTable
        head={['Dummy no.', ...questions.map((q) => `Q${q.q} /${q.max}`), 'Total', '', '']}
        rows={(scripts.data?.data ?? []).map((s: Any) => [
          <span key="d" className="font-mono">{s.dummy_number}</span>,
          ...questions.map((q) => (
            <Input key={q.q} type="number" className="h-8 w-16" disabled={s.is_locked || locked} defaultValue={s.question_wise?.[q.q] ?? ''} max={q.max} onChange={(e) => setQw({ ...qw, [s.id]: { ...(qw[s.id] ?? {}), [q.q]: e.target.value } })} />
          )),
          questions.length ? (
            Object.values(qw[s.id] ?? {}).reduce((a, v) => a + (Number(v) || 0), 0) || s.marks || '—'
          ) : (
            <Input key="t" type="number" className="h-8 w-20" disabled={s.is_locked || locked} defaultValue={s.marks ?? ''} onChange={(e) => setTot({ ...tot, [s.id]: e.target.value })} />
          ),
          s.scan_available ? <Button key="sc" size="sm" variant="ghost" onClick={() => resultsApi.scan(s.id).then((r: Any) => window.open(r.data.url, '_blank', 'noopener')).catch(fail)}>Scan</Button> : '',
          <Button key="sv" size="sm" disabled={s.is_locked || locked} onClick={() => save(s)}>Save</Button>,
        ])}
      />
    </CardContent></Card>
  );
}

// ---- /student/results ------------------------------------------------------------------------------------------------------
function ResultsView({ data }: { data: Any }) {
  if (!data) return null;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3 text-sm">
        <Badge variant="outline">CGPA {data.cgpa ?? '—'}</Badge>
        <Badge variant="outline">Credits {data.credits_earned ?? '—'}</Badge>
        {data.standing && data.standing !== 'good' && <Badge variant="destructive">Standing: {data.standing}</Badge>}
      </div>
      {data.terms.length > 1 && (
        <div className="flex h-24 items-end gap-2">
          {data.terms.map((t: Any) => <div key={t.term.id} title={`Term ${t.term.term_number}: ${t.term.sgpa}`} className="w-8 rounded-t bg-primary" style={{ height: `${(Number(t.term.sgpa ?? 0) / 10) * 100}%` }} />)}
        </div>
      )}
      {data.terms.length === 0 && <p className="text-sm text-muted-foreground">No published results yet.</p>}
      {data.terms.map((t: Any) => (
        <Card key={t.term.id}><CardContent className="space-y-2 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-medium">Term {t.term.term_number}{t.term.term_name ? ` · ${t.term.term_name}` : ''} — SGPA {t.term.sgpa ?? '—'} · CGPA {t.term.cgpa ?? '—'} · {t.term.result_class ?? (t.term.backlog_count ? `${t.term.backlog_count} backlog(s)` : '')}</p>
            {t.term.version > 1 && <Badge variant="secondary">Revised</Badge>}
            {t.term.grade_card_id && <Button size="sm" variant="outline" onClick={() => resultsApi.cardPdf(t.term.grade_card_id).then((b) => openBlob(b)).catch(fail)}><Download className="h-3 w-3" /> Grade card</Button>}
          </div>
          <SimpleTable
            head={['Course', 'Credits', 'CIA', 'ESE', 'Grade', 'GP', 'Status']}
            rows={t.courses.map((c: Any) => [
              `${c.course_code} ${c.course_title ?? ''}${c.revised ? ' (revised)' : ''}`,
              c.credits,
              c.cia_marks ?? '—',
              c.ese_marks ?? '—',
              <Badge key="g" variant={CHIP[c.letter_grade] ?? 'outline'}>{c.letter_grade ?? '—'}{Number(c.grace_marks) > 0 ? '*' : ''}</Badge>,
              c.grade_point ?? '—',
              c.result_status,
            ])}
          />
        </CardContent></Card>
      ))}
    </div>
  );
}

export function StudentResultsPage() {
  useTitle('Results');
  const q = useQ(['me'], () => resultsApi.myResults());
  return (
    <div className="space-y-4">
      <PageHeader title="Results" description="Published results — current versions; a revised badge marks re-published terms." />
      <ResultsView data={q.data?.data} />
    </div>
  );
}

export function ParentResultsPage() {
  const { studentId } = useParams();
  useTitle('Ward results');
  const q = useQ(['ward', studentId], () => resultsApi.wardResults(studentId!), !!studentId);
  return (
    <div className="space-y-4">
      <PageHeader title="Results" description="Published results of your ward." />
      <ResultsView data={q.data?.data} />
    </div>
  );
}

// ---- /faculty/offerings/:id/results ---------------------------------------------------------------------------------------
export function OfferingResultsPage() {
  const { id } = useParams();
  useTitle('Result sheet');
  const q = useQ(['offering', id], () => resultsApi.offeringResults(id!), !!id);
  return (
    <div className="space-y-4">
      <PageHeader title="Result sheet" description="Published results of your offering." />
      <SimpleTable head={['Reg. no', 'Name', 'CIA', 'ESE', 'Total', 'Grade', 'Status']} rows={(q.data?.data ?? []).map((r: Any) => [r.registration_number, r.student_name, r.cia_marks ?? '—', r.ese_marks ?? '—', r.total_marks ?? '—', r.letter_grade ?? '—', r.result_status])} />
    </div>
  );
}

// ---- /admin/results/tabulation · analysis · rank-lists -------------------------------------------------------------------
export function TabulationPage() {
  useTitle('Tabulation register');
  const [f, setF] = useState({ batch_id: '', term_id: '' });
  const p = { batch_id: f.batch_id, term_id: f.term_id || undefined };
  const q = useQ(['tabulation', f], () => resultsApi.tabulation(p), !!f.batch_id);
  const rows = q.data?.data ?? [];
  const codes = Array.from(new Set(rows.flatMap((r: Any) => Object.keys(r.courses)))).sort() as string[];
  return (
    <div className="space-y-4">
      <PageHeader title="Tabulation register" description="Batch × term grade register of published results." />
      <div className="flex flex-wrap gap-2">
        <Input className="w-72" placeholder="Batch id" value={f.batch_id} onChange={(e) => setF({ ...f, batch_id: e.target.value })} />
        <Input className="w-72" placeholder="Term id (optional)" value={f.term_id} onChange={(e) => setF({ ...f, term_id: e.target.value })} />
        <Button variant="outline" disabled={!f.batch_id} onClick={() => resultsApi.tabulationXlsx(p).then((b) => openBlob(b, 'tabulation.xlsx')).catch(fail)}><Download className="h-4 w-4" /> XLSX</Button>
      </div>
      <SimpleTable head={['Reg. no', 'Name', ...codes, 'SGPA', 'CGPA', 'Credits', 'Backlogs', 'Class']} rows={rows.map((r: Any) => [r.registration_number, r.student_name, ...codes.map((c) => r.courses[c] ?? ''), r.sgpa ?? '—', r.cgpa ?? '—', r.credits_earned ?? '—', r.backlogs, r.result_class ?? '—'])} />
    </div>
  );
}

export function ResultAnalysisPage() {
  useTitle('Result analysis');
  const [f, setF] = useState({ session_id: '', batch_id: '' });
  const q = useQ(['analysis', f], () => resultsApi.analysis({ session_id: f.session_id || undefined, batch_id: f.batch_id || undefined }), !!(f.session_id || f.batch_id));
  const d = q.data?.data;
  const maxCount = Math.max(1, ...Object.values((d?.grade_distribution ?? {}) as Record<string, number>));
  return (
    <div className="space-y-4">
      <PageHeader title="Result analysis" description="Pass % by course, grade distribution and toppers." />
      <div className="flex flex-wrap gap-2">
        <Input className="w-72" placeholder="Exam session id" value={f.session_id} onChange={(e) => setF({ ...f, session_id: e.target.value })} />
        <Input className="w-72" placeholder="Batch id" value={f.batch_id} onChange={(e) => setF({ ...f, batch_id: e.target.value })} />
      </div>
      {d && (
        <>
          <p className="text-sm">{d.students} students · overall pass {d.pass_pct ?? '—'}%</p>
          <div className="flex h-32 items-end gap-2">
            {Object.entries(d.grade_distribution as Record<string, number>).map(([g, n]) => (
              <div key={g} className="flex flex-col items-center text-xs"><div className="w-8 rounded-t bg-primary" style={{ height: `${(n / maxCount) * 100}px` }} />{g} ({n})</div>
            ))}
          </div>
          <SimpleTable head={['Course', 'Appeared', 'Passed', 'Pass %']} rows={d.pass_pct_by_course.map((c: Any) => [c.course, c.appeared, c.passed, c.pass_pct])} />
          <SimpleTable head={['Rank', 'Reg. no', 'Name', 'SGPA', 'CGPA']} rows={d.toppers.map((t: Any) => [t.rank, t.registration_number, t.name, t.sgpa ?? '—', t.cgpa ?? '—'])} />
        </>
      )}
    </div>
  );
}

export function RankListPage() {
  useTitle('Rank lists');
  const [f, setF] = useState({ batch_id: '', term_id: '' });
  const q = useQ(['ranks', f], () => resultsApi.rankList({ batch_id: f.batch_id, term_id: f.term_id || undefined }), !!f.batch_id);
  return (
    <div className="space-y-4">
      <PageHeader title="Rank lists" description="Ranks by CGPA (or SGPA for a term) among students without backlogs." />
      <div className="flex flex-wrap gap-2">
        <Input className="w-72" placeholder="Batch id" value={f.batch_id} onChange={(e) => setF({ ...f, batch_id: e.target.value })} />
        <Input className="w-72" placeholder="Term id (optional)" value={f.term_id} onChange={(e) => setF({ ...f, term_id: e.target.value })} />
      </div>
      <SimpleTable head={['Rank', 'Reg. no', 'Name', 'SGPA', 'CGPA']} rows={(q.data?.data ?? []).map((t: Any) => [t.rank, t.registration_number, t.name, t.sgpa ?? '—', t.cgpa ?? '—'])} />
    </div>
  );
}

// ---- /admin/results/legacy-import ----------------------------------------------------------------------------------------
export function LegacyImportPage() {
  useTitle('Legacy result import');
  const [f, setF] = useState<{ batch_id: string; term_number: number; file: File | null }>({ batch_id: '', term_number: 1, file: null });
  const [imp, setImp] = useState<Any | null>(null);
  const run = useRun();
  const act = (a: 'validate' | 'apply' | 'rollback') => run.mutate(() => resultsApi.legacyAction(imp.id, a).then((r: Any) => setImp(r.data)), { onSuccess: () => toast.success(a), onError: fail });
  const rep = imp?.validation_report;
  return (
    <div className="space-y-4">
      <PageHeader title="Legacy result import" description="Upload → validate → apply (published as legacy rows) → roll back if nothing newer references them." />
      <div className="flex flex-wrap items-center gap-2">
        <Input className="w-72" placeholder="Batch id" value={f.batch_id} onChange={(e) => setF({ ...f, batch_id: e.target.value })} />
        <Input type="number" className="w-24" value={f.term_number} onChange={(e) => setF({ ...f, term_number: Number(e.target.value) || 1 })} />
        <input type="file" accept=".xlsx,.csv" onChange={(e) => setF({ ...f, file: e.target.files?.[0] ?? null })} />
        <Button disabled={!f.batch_id || !f.file} onClick={() => run.mutate(() => resultsApi.legacyUpload(f.batch_id, f.term_number, f.file!).then((r: Any) => setImp(r.data)), { onSuccess: () => toast.success('Uploaded'), onError: fail })}>Upload</Button>
      </div>
      <p className="text-xs text-muted-foreground">Columns: reg_no, course_code, course_title, credits, cia, ese, total, grade, gp, attempt.</p>
      {imp && (
        <Card><CardContent className="space-y-2 p-4 text-sm">
          <p>Status <StatusBadge status={imp.status} /></p>
          <div className="flex gap-2">
            {['uploaded', 'validated'].includes(imp.status) && <Button size="sm" variant="outline" onClick={() => act('validate')}>Validate</Button>}
            {imp.status === 'validated' && <Button size="sm" onClick={() => act('apply')}>Apply</Button>}
            {imp.status === 'applied' && <Button size="sm" variant="destructive" onClick={() => act('rollback')}>Roll back</Button>}
          </div>
          {rep && (
            <>
              <p>{rep.valid}/{rep.rows} rows valid · {rep.students} students · new legacy courses: {rep.courses_to_create.join(', ') || '—'}</p>
              <SimpleTable head={['Row', 'Field', 'Value', 'Error']} rows={rep.errors.map((e: Any) => [e.row, e.field, e.value ?? '', e.error])} />
            </>
          )}
        </CardContent></Card>
      )}
    </div>
  );
}

// ---- /results/lookup (public) -----------------------------------------------------------------------------------------------
export function PublicResultLookupPage() {
  useTitle('Result lookup');
  const [f, setF] = useState({ reg_no: '', dob: '', institution: new URLSearchParams(window.location.search).get('institution') ?? '' });
  const [res, setRes] = useState<Any | null>(null);
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-lg"><CardContent className="space-y-3 pt-6">
        <h1 className="text-lg font-semibold">Result lookup</h1>
        <Input placeholder="Registration number" value={f.reg_no} onChange={(e) => setF({ ...f, reg_no: e.target.value })} />
        <Input type="date" value={f.dob} onChange={(e) => setF({ ...f, dob: e.target.value })} />
        {!new URLSearchParams(window.location.search).get('institution') && <Input placeholder="Institution code" value={f.institution} onChange={(e) => setF({ ...f, institution: e.target.value })} />}
        <Button disabled={!f.reg_no || !f.dob} onClick={() => resultsApi.lookup(f).then((r: Any) => setRes(r.data)).catch((e) => { setRes(null); fail(e); })}>Show result</Button>
        {res && (
          <div className="space-y-1 text-sm">
            <p className="font-medium">{res.name} · {res.registration_number}</p>
            {res.terms.map((t: Any) => <p key={t.term_number}>Term {t.term_number}: SGPA {t.sgpa ?? '—'} · CGPA {t.cgpa ?? '—'} · {t.result}</p>)}
          </div>
        )}
      </CardContent></Card>
    </div>
  );
}
