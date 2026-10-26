import { useEffect, useState, type ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { ScopeTabs } from '@/components/shared/ScopeTabs';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { toast } from '@/components/ui/Toaster';
import { SimpleTable } from '@/features/hr/components/shared';
import { iqacApi as ia } from '../api';

// Phase 32 web screens (Prompts/32 §32.9). Visibility (department / college / all), override verification and
// locking, response ownership and the review workflow are enforced by the API; these screens only present them.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));
const useQ = <T,>(key: unknown[], fn: () => Promise<T>, enabled = true) => useQuery({ queryKey: ['iqac', ...key], queryFn: fn, retry: false, enabled });
function useRun() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: () => qc.invalidateQueries({ queryKey: ['iqac'] }) });
}
const list = (r: Any) => (Array.isArray(r?.data) ? r.data : r?.data?.items ?? []);
const day = (s?: string | null) => (s ? new Date(s).toLocaleDateString() : '—');
const num = (v: Any) => (v === null || v === undefined ? '—' : Number(v).toLocaleString('en-IN', { maximumFractionDigits: 2 }));
const sel = 'h-9 rounded-md border bg-background px-2 text-sm';
const area = 'min-h-[160px] w-full rounded-md border bg-background p-2 text-sm';
const currentAY = () => {
  const d = new Date();
  const y = d.getMonth() >= 5 ? d.getFullYear() : d.getFullYear() - 1;
  return `${y}-${String(y + 1).slice(-2)}`;
};
const FRAMEWORKS = ['NAAC_2024', 'NBA_UG_ENGG', 'NIRF', 'AISHE', 'AICTE_APPROVAL', 'UGC_12B'];
const SUB_TYPES = ['aqar', 'nirf_data', 'aishe', 'aicte_approval', 'ugc_annual', 'nsp_return'];
const AUDIT_TYPES = ['academic', 'administrative', 'green', 'energy', 'gender', 'financial_statutory', 'ag'];
const EXPORTS = ['naac_ssr', 'naac_aqar', 'nba_sar', 'nirf_dcf', 'aishe_dcf', 'aicte', 'ugc_annual', 'docx', 'pdf', 'xlsx'];

function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <Card><CardContent className="space-y-3 p-4"><div className="flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">{title}</h2>{action}</div>{children}</CardContent></Card>;
}
function Stat({ label, value }: { label: string; value: ReactNode }) {
  return <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{label}</p><p className="text-xl font-semibold">{value ?? '—'}</p></CardContent></Card>;
}
function Meter({ pct }: { pct: number }) {
  return <div className="h-2 w-full rounded bg-muted"><div className="h-2 rounded bg-primary" style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} /></div>;
}
function SourceBadge({ source, verified }: { source: string; verified?: boolean }) {
  const tone: Record<string, string> = { auto: 'bg-muted', manual: 'bg-sky-100 text-sky-800', override: 'bg-amber-100 text-amber-800' };
  return <span className="flex gap-1"><span className={`rounded px-1.5 py-0.5 text-xs ${tone[source] ?? tone.auto}`}>{source}</span>{verified && <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-xs text-emerald-800">verified</span>}</span>;
}
function Spark({ values }: { values: (number | null)[] }) {
  const v = values.map((x) => Number(x ?? 0));
  const max = Math.max(1, ...v);
  return <div className="flex h-10 items-end gap-1">{v.map((x, i) => <div key={i} className="w-4 rounded-t bg-primary/70" style={{ height: `${Math.max(4, (100 * x) / max)}%` }} title={String(values[i] ?? '—')} />)}</div>;
}

// ---- dashboard ------------------------------------------------------------------------------------------------------------
export function IqacDashboardPage() {
  useTitle('IQAC dashboard');
  const [period, setPeriod] = useState(currentAY());
  const res = useQ(['dashboard', period], () => ia.dashboard(period));
  const d: Any = (res.data as Any)?.data;
  const sim = d?.score_simulation ?? {};
  return (
    <div className="space-y-4">
      <PageHeader title="IQAC dashboard" description="Cycle progress, verified metrics, evidence coverage, submissions due, audits, consistency alerts and the NAAC score simulation." actions={<Input className="w-28" value={period} onChange={(e) => setPeriod(e.target.value)} />} />
      {res.isError && <p className="text-sm text-destructive">{getApiError(res.error)}</p>}
      <div className="grid gap-3 md:grid-cols-6">
        <Stat label="Metrics" value={d?.metrics_total} />
        <Stat label="Verified %" value={d ? `${d.metrics_verified_pct}%` : undefined} />
        <Stat label="Overrides pending" value={d?.overrides_pending} />
        <Stat label="Audits open" value={d?.audits_open} />
        <Stat label="Consistency alerts" value={d?.consistency_alerts} />
        <Stat label="NAAC estimate" value={sim.grade_estimate ? `${sim.grade_estimate} (${sim.cgpa_estimate})` : undefined} />
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Section title="Cycles">
          {(d?.cycles ?? []).map((c: Any) => <div key={c.id} className="space-y-1"><div className="flex justify-between text-sm"><Link className="text-primary underline" to={`/iqac/cycles/${c.id}`}>{c.name}</Link><span>{c.completion_pct}% · <StatusBadge status={c.status} /></span></div><Meter pct={c.completion_pct} /></div>)}
          {!(d?.cycles ?? []).length && <p className="text-sm text-muted-foreground">No cycles.</p>}
        </Section>
        <Section title="Criteria heat map (simulated score / max)">
          <div className="grid grid-cols-7 gap-1">{Object.entries(sim.by_criterion ?? {}).map(([k, v]: Any) => { const pct = v.max ? (100 * v.earned) / v.max : 0; return <div key={k} className="rounded p-2 text-center text-xs" style={{ background: `hsl(${Math.round(pct * 1.2)}, 70%, 85%)` }}><div className="font-semibold">C{k}</div><div>{Math.round(pct)}%</div></div>; })}</div>
        </Section>
        <Section title="Top improvement gaps">
          <SimpleTable head={['Metric', 'Title', 'Max', 'Earned', 'Gap']} rows={(d?.top_gaps ?? []).map((g: Any) => [g.code, g.title, g.max_score, g.earned, g.gap])} />
        </Section>
        <Section title="Submissions due / evidence coverage">
          <SimpleTable head={['Type', 'Period', 'Status']} rows={(d?.submissions_due ?? []).map((s: Any) => [s.type, s.period, <StatusBadge key="s" status={s.status} />])} />
          <div className="flex flex-wrap gap-2 text-xs">{Object.entries(d?.evidence_counts ?? {}).map(([k, v]: Any) => <span key={k} className="rounded bg-muted px-2 py-1">Criterion {k}: {v}</span>)}</div>
        </Section>
      </div>
    </div>
  );
}

// ---- frameworks -------------------------------------------------------------------------------------------------------------
function Tree({ nodes, depth = 0 }: { nodes: Any[]; depth?: number }) {
  return <ul className={depth ? 'ml-4 border-l pl-3' : ''}>{nodes.map((n) => <li key={n.code} className="py-0.5 text-sm"><span className="font-medium">{n.code}</span> {n.title} {n.max_score != null && <span className="text-xs text-muted-foreground">({n.max_score})</span>} {n.metric_key && <span className="rounded bg-muted px-1 text-xs">{n.metric_key}</span>} {n.custom && <span className="text-xs text-amber-700">custom</span>}{n.children?.length > 0 && <Tree nodes={n.children} depth={depth + 1} />}</li>)}</ul>;
}

export function IqacFrameworksPage() {
  useTitle('Frameworks');
  const fws = useQ(['frameworks'], () => ia.frameworks());
  const [code, setCode] = useState('NAAC_2024');
  const tree = useQ(['framework', code], () => ia.framework(code));
  return (
    <div className="space-y-4">
      <PageHeader title="Frameworks" description="NAAC 2024, NBA GAPC v4, NIRF, AISHE, AICTE and UGC criteria trees with metric links (activation follows the feature flags)." />
      <div className="flex flex-wrap gap-2">{list(fws.data).map((f: Any) => <Button key={f.code} size="sm" variant={f.code === code ? 'default' : 'outline'} disabled={!f.active} onClick={() => setCode(f.code)}>{f.code} ({f.criteria_count}){!f.active && ' · off'}</Button>)}</div>
      <Section title={(tree.data as Any)?.data?.name ?? code}>{tree.isError ? <p className="text-sm text-destructive">{getApiError(tree.error)}</p> : <Tree nodes={(tree.data as Any)?.data?.criteria ?? []} />}</Section>
    </div>
  );
}

// ---- metrics ----------------------------------------------------------------------------------------------------------------
export function IqacMetricsPage({ hod = false }: { hod?: boolean }) {
  useTitle(hod ? 'Department quality' : 'Metrics');
  const [f, setF] = useState<Any>({ period: currentAY(), framework: hod ? '' : 'NAAC_2024', source: '' });
  const [scope, setScope] = useState<string | undefined>(hod ? 'department' : undefined);
  const res = useQ(['values', f, scope], () => ia.values({ period: f.period || undefined, framework: f.framework || undefined, source: f.source || undefined, scope, per_page: 500 }));
  const [open, setOpen] = useState<Any>(null);
  const run = useRun();
  const compute = () => run.mutate(() => ia.compute({ period_label: f.period, framework_code: f.framework || undefined }), { onSuccess: () => toast.success('Compute queued — values refresh when the job finishes'), onError: fail });
  return (
    <div className="space-y-4">
      <PageHeader title={hod ? 'Department quality metrics' : 'Metrics'} description="Value / numerator / denominator per period with source badges (auto / manual / override) and verification; drill down to source rows." actions={<ScopeTabs visibility={(res.data as Any)?.meta?.visibility} value={scope} onChange={setScope} />} />
      <div className="flex flex-wrap gap-2">
        <Input className="w-28" value={f.period} onChange={(e) => setF({ ...f, period: e.target.value })} />
        <select className={sel} value={f.framework} onChange={(e) => setF({ ...f, framework: e.target.value })}><option value="">All frameworks</option>{FRAMEWORKS.map((x) => <option key={x}>{x}</option>)}</select>
        <select className={sel} value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })}><option value="">Any source</option><option>auto</option><option>manual</option><option>override</option></select>
        {!hod && <Button size="sm" onClick={compute}>Compute</Button>}
      </div>
      {res.isError && <p className="text-sm text-destructive">{getApiError(res.error)}</p>}
      <SimpleTable head={['Metric', 'Period', 'Value', 'Numerator', 'Denominator', 'Source', '']} rows={list(res.data).map((m: Any) => [<span key="k" title={m.key}>{m.name ?? m.key}</span>, m.period, num(m.value), num(m.numerator), num(m.denominator), <span key="s" className="flex flex-wrap gap-1"><SourceBadge source={m.source} verified={m.verified} />{m.pending_override && <span className="rounded bg-amber-50 px-1 text-xs text-amber-700">pending override</span>}</span>, <Button key="d" size="sm" variant="outline" onClick={() => setOpen(m)}>Open</Button>])} />
      {open && <MetricDrawer m={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function MetricDrawer({ m, onClose }: { m: Any; onClose: () => void }) {
  const p = { period: m.period, college_id: m.college_id ?? undefined, program_id: m.program_id ?? undefined };
  const dd = useQ(['drill', m.key, p], () => ia.drilldown(m.key, p));
  const tr = useQ(['trend', m.key], () => ia.trend(m.key));
  const [ov, setOv] = useState<Any>({ value: '', reason: '' });
  const run = useRun();
  const rows: Any[] = (dd.data as Any)?.data?.rows ?? [];
  const cols = rows.length ? Object.keys(rows[0]).filter((c) => c !== 'id' && c !== 'link').slice(0, 7) : [];
  const body = { period_label: m.period, college_id: m.college_id ?? undefined, program_id: m.program_id ?? undefined };
  return (
    <Section title={`${m.name ?? m.key} · ${m.period}`} action={<Button size="sm" variant="outline" onClick={onClose}>Close</Button>}>
      <div className="grid gap-3 md:grid-cols-3">
        <Stat label="Value" value={num(m.value)} />
        <Stat label="Recomputed for your view" value={num((dd.data as Any)?.data?.value)} />
        <div><p className="text-xs text-muted-foreground">Trend</p><Spark values={(tr.data as Any)?.data?.values ?? []} /><p className="text-xs">{((tr.data as Any)?.data?.periods ?? []).join(' · ')}</p></div>
      </div>
      {m.stale_auto && <p className="text-xs text-muted-foreground">Auto value kept for peer teams: {m.stale_auto.value} (computed {day(m.stale_auto.computed_at)})</p>}
      {m.override_reason && <p className="text-xs">Override reason: {m.override_reason}</p>}
      <div className="flex flex-wrap gap-2">
        <Input className="w-32" placeholder="Override value" value={ov.value} onChange={(e) => setOv({ ...ov, value: e.target.value })} />
        <Input className="w-80" placeholder="Reason (mandatory)" value={ov.reason} onChange={(e) => setOv({ ...ov, reason: e.target.value })} />
        <Button size="sm" disabled={!ov.value || ov.reason.length < 5} onClick={() => run.mutate(() => ia.override(m.key, { ...body, value: ov.value, reason: ov.reason }), { onSuccess: () => toast.success('Override proposed'), onError: fail })}>Propose override</Button>
        <Button size="sm" variant="outline" onClick={() => run.mutate(() => ia.verify(m.key, { ...body, action: 'verify' }), { onSuccess: () => toast.success('Verified (locked)'), onError: fail })}>Verify</Button>
        {m.pending_override && <Button size="sm" variant="outline" onClick={() => run.mutate(() => ia.verify(m.key, { ...body, action: 'reject' }), { onError: fail })}>Reject proposal</Button>}
        {m.verified && <Button size="sm" variant="outline" onClick={() => run.mutate(() => ia.verify(m.key, { ...body, action: 'unverify' }), { onError: fail })}>Unverify</Button>}
        <Button size="sm" variant="outline" onClick={() => run.mutate(() => ia.drilldownExport(m.key, p), { onSuccess: () => toast.success('Export queued (xlsx)'), onError: fail })}>Export rows</Button>
      </div>
      {dd.isError ? <p className="text-sm text-destructive">{getApiError(dd.error)}</p> : <SimpleTable head={cols} rows={rows.slice(0, 100).map((r) => cols.map((c) => String(r[c] ?? '—')))} empty="No source rows (event-fed or manual metric)." />}
    </Section>
  );
}

// ---- evidence ---------------------------------------------------------------------------------------------------------------
export function IqacEvidencePage() {
  useTitle('Evidence');
  const [f, setF] = useState<Any>({ criterion: '', period: '', q: '' });
  const [scope, setScope] = useState<string | undefined>();
  const res = useQ(['evidence', f, scope], () => ia.evidence({ criterion: f.criterion || undefined, period: f.period || undefined, q: f.q || undefined, scope, per_page: 100 }));
  const sug = useQ(['suggestions'], () => ia.suggestions());
  const [n, setN] = useState<Any>({ criterion_code: '', period_label: currentAY(), title: '', doc_type: 'report', file_url: '' });
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Evidence repository" description="Documents tagged to criteria / metrics / periods, verification, auto-suggestions from modules and evidence packs." actions={<ScopeTabs visibility={(res.data as Any)?.meta?.visibility} value={scope} onChange={setScope} />} />
      <Section title="Upload / tag">
        <div className="flex flex-wrap gap-2">
          <Input className="w-24" placeholder="Criterion" value={n.criterion_code} onChange={(e) => setN({ ...n, criterion_code: e.target.value })} />
          <Input className="w-24" value={n.period_label} onChange={(e) => setN({ ...n, period_label: e.target.value })} />
          <Input className="w-64" placeholder="Title" value={n.title} onChange={(e) => setN({ ...n, title: e.target.value })} />
          <select className={sel} value={n.doc_type} onChange={(e) => setN({ ...n, doc_type: e.target.value })}>{['policy', 'minutes', 'certificate', 'report', 'photo', 'mou'].map((x) => <option key={x}>{x}</option>)}</select>
          <Input className="w-72" placeholder="File URL (uploaded file)" value={n.file_url} onChange={(e) => setN({ ...n, file_url: e.target.value })} />
          <Button size="sm" disabled={!n.title || !n.file_url} onClick={() => run.mutate(() => ia.createEvidence({ ...n, criterion_code: n.criterion_code || undefined }), { onSuccess: () => toast.success('Evidence uploaded'), onError: fail })}>Upload</Button>
          <Button size="sm" variant="outline" disabled={!f.criterion} onClick={() => run.mutate(() => ia.pack(f.criterion, f.period || undefined), { onSuccess: () => toast.success('Evidence pack queued'), onError: fail })}>Build pack for {f.criterion || '…'}</Button>
        </div>
      </Section>
      <Section title={`Suggestions inbox (${list(sug.data).length})`}>
        <SimpleTable head={['Module', 'Title', 'Criterion', '']} rows={list(sug.data).map((s: Any) => [s.module, s.title, s.criterion_code ?? '—', <span key="a" className="flex gap-1"><Button size="sm" onClick={() => run.mutate(() => ia.acceptSuggestion(s.id), { onError: fail })}>Accept</Button><Button size="sm" variant="outline" onClick={() => run.mutate(() => ia.dismissSuggestion(s.id), { onError: fail })}>Dismiss</Button></span>])} />
      </Section>
      <Section title={`Documents (${(res.data as Any)?.meta?.pagination?.total ?? list(res.data).length})`}>
        <div className="flex flex-wrap gap-2">
          <Input className="w-28" placeholder="Criterion" value={f.criterion} onChange={(e) => setF({ ...f, criterion: e.target.value })} />
          <Input className="w-28" placeholder="Period" value={f.period} onChange={(e) => setF({ ...f, period: e.target.value })} />
          <Input className="w-64" placeholder="Search title" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} />
        </div>
        <SimpleTable head={['Criterion', 'Title', 'Type', 'Period', 'Uploaded by', 'Status', '']} rows={list(res.data).map((e: Any) => [e.criterion_code ?? '—', <a key="t" className="text-primary underline" href={e.file_url} target="_blank" rel="noreferrer">{e.title}</a>, e.doc_type, e.period_label, e.uploaded_by_name ?? '—', e.verified ? 'verified' : 'unverified', !e.verified ? <Button key="v" size="sm" variant="outline" onClick={() => run.mutate(() => ia.verifyEvidence(e.id), { onError: fail })}>Verify</Button> : null])} />
      </Section>
    </div>
  );
}

// ---- cycles -----------------------------------------------------------------------------------------------------------------
export function IqacCyclesPage() {
  useTitle('Accreditation cycles');
  const res = useQ(['cycles'], () => ia.cycles());
  const [n, setN] = useState<Any>({ framework_code: 'NAAC_2024', name: '', period_from: '', period_to: '', submission_due_on: '', program_id: '' });
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Accreditation cycles" description="NAAC SSR / AQAR and NBA SAR (per programme) cycles: planning → data collection → drafting → internal review → submitted → peer visit → result." />
      <Section title="New cycle">
        <div className="flex flex-wrap gap-2">
          <select className={sel} value={n.framework_code} onChange={(e) => setN({ ...n, framework_code: e.target.value })}>{FRAMEWORKS.map((x) => <option key={x}>{x}</option>)}</select>
          <Input className="w-64" placeholder="Name" value={n.name} onChange={(e) => setN({ ...n, name: e.target.value })} />
          <Input type="date" className="w-40" value={n.period_from} onChange={(e) => setN({ ...n, period_from: e.target.value })} />
          <Input type="date" className="w-40" value={n.period_to} onChange={(e) => setN({ ...n, period_to: e.target.value })} />
          <Input type="date" className="w-40" value={n.submission_due_on} onChange={(e) => setN({ ...n, submission_due_on: e.target.value })} />
          {n.framework_code === 'NBA_UG_ENGG' && <Input className="w-72" placeholder="Programme id" value={n.program_id} onChange={(e) => setN({ ...n, program_id: e.target.value })} />}
          <Button size="sm" disabled={n.name.length < 3} onClick={() => run.mutate(() => ia.createCycle({ ...n, period_from: n.period_from || undefined, period_to: n.period_to || undefined, submission_due_on: n.submission_due_on || undefined, program_id: n.program_id || undefined }), { onSuccess: () => toast.success('Cycle created'), onError: fail })}>Create</Button>
        </div>
      </Section>
      <SimpleTable head={['Cycle', 'Framework', 'Period', 'Due', 'Status', 'Completion']} rows={list(res.data).map((c: Any) => [<Link key="n" className="text-primary underline" to={`/iqac/cycles/${c.id}`}>{c.name}</Link>, c.framework_code, `${day(c.period_from)} – ${day(c.period_to)}`, day(c.submission_due_on), <StatusBadge key="s" status={c.status} />, <div key="m" className="w-32"><Meter pct={c.completion_pct} /><span className="text-xs">{c.completion_pct}%</span></div>])} />
    </div>
  );
}

const NEXT: Record<string, string> = { planning: 'data_collection', data_collection: 'drafting', drafting: 'internal_review', internal_review: 'submitted', submitted: 'peer_visit', peer_visit: 'result' };

export function IqacCyclePage() {
  const { id = '' } = useParams();
  const c = useQ(['cycle', id], () => ia.cycle(id));
  const crits = useQ(['criteria', id], () => ia.criteria(id));
  const exps = useQ(['exports', id], () => ia.exports(id));
  const cy: Any = (c.data as Any)?.data;
  useTitle(cy?.name ?? 'Cycle');
  const [code, setCode] = useState<string | null>(null);
  const [assign, setAssign] = useState<Any>({ codes: '', owner_staff_id: '', due_on: '' });
  const [fmt, setFmt] = useState('naac_ssr');
  const [result, setResult] = useState<Any>({ score: '', grade: '' });
  const run = useRun();
  if (!cy) return <p className="p-4 text-sm text-muted-foreground">{c.isError ? getApiError(c.error) : 'Loading…'}</p>;
  const next = NEXT[cy.status];
  return (
    <div className="space-y-4">
      <PageHeader title={cy.name} description={`${cy.framework_code} · ${day(cy.period_from)} – ${day(cy.period_to)} · due ${day(cy.submission_due_on)}`} actions={<StatusBadge status={cy.status} />} />
      <div className="grid gap-3 md:grid-cols-4">
        <Stat label="Completion" value={`${cy.completion_pct}%`} />
        <Stat label="Criteria" value={cy.criteria_progress?.total} />
        <Stat label="Approved / final" value={(cy.criteria_progress?.approved ?? 0) + (cy.criteria_progress?.final ?? 0)} />
        <Stat label="Score / grade" value={cy.grade ? `${cy.score ?? ''} ${cy.grade}` : '—'} />
      </div>
      <Section title="Workflow">
        <div className="flex flex-wrap gap-2">
          {next === 'result' && <><Input className="w-24" placeholder="Score" value={result.score} onChange={(e) => setResult({ ...result, score: e.target.value })} /><Input className="w-20" placeholder="Grade" value={result.grade} onChange={(e) => setResult({ ...result, grade: e.target.value })} /></>}
          {next && <Button size="sm" onClick={() => run.mutate(() => ia.cycleStatus(id, { status: next, score: result.score || undefined, grade: result.grade || undefined }), { onError: fail })}>Move to {next.replace('_', ' ')}</Button>}
          <Input className="w-40" placeholder="Criteria (2.3.1, 2.4.2)" value={assign.codes} onChange={(e) => setAssign({ ...assign, codes: e.target.value })} />
          <Input className="w-72" placeholder="Owner staff id" value={assign.owner_staff_id} onChange={(e) => setAssign({ ...assign, owner_staff_id: e.target.value })} />
          <Input type="date" className="w-40" value={assign.due_on} onChange={(e) => setAssign({ ...assign, due_on: e.target.value })} />
          <Button size="sm" variant="outline" disabled={!assign.codes || !assign.owner_staff_id} onClick={() => run.mutate(() => ia.assign(id, { criterion_codes: assign.codes.split(',').map((x: string) => x.trim()).filter(Boolean), owner_staff_id: assign.owner_staff_id, due_on: assign.due_on || undefined }), { onSuccess: () => toast.success('Assigned'), onError: fail })}>Assign</Button>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select className={sel} value={fmt} onChange={(e) => setFmt(e.target.value)}>{EXPORTS.map((x) => <option key={x}>{x}</option>)}</select>
          <Button size="sm" variant="outline" onClick={() => run.mutate(() => ia.exportCycle(id, { format: fmt }), { onSuccess: () => toast.success('Export queued'), onError: fail })}>Export</Button>
          {list(exps.data).slice(0, 5).map((x: Any) => <a key={x.id} className="text-xs text-primary underline" href={x.file_url ?? '#'} target="_blank" rel="noreferrer">{x.format} · {day(x.created_at)}</a>)}
        </div>
      </Section>
      <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <Section title="Criteria">
          <div className="max-h-[560px] space-y-1 overflow-y-auto">{list(crits.data).map((r: Any) => <button key={r.code} className={`flex w-full items-center justify-between rounded px-2 py-1 text-left text-sm hover:bg-muted ${code === r.code ? 'bg-muted' : ''}`} onClick={() => setCode(r.code)}><span><b>{r.code}</b> {r.title}</span><StatusBadge status={r.status} /></button>)}</div>
        </Section>
        {code ? <ResponseEditor cycleId={id} code={code} /> : <Section title="Response"><p className="text-sm text-muted-foreground">Pick a criterion.</p></Section>}
      </div>
    </div>
  );
}

function ResponseEditor({ cycleId, code }: { cycleId: string; code: string }) {
  const res = useQ(['criterion', cycleId, code], () => ia.criterion(cycleId, code));
  const vers = useQ(['versions', cycleId, code], () => ia.versions(cycleId, code));
  const r: Any = (res.data as Any)?.data;
  const [text, setText] = useState('');
  const [ev, setEv] = useState('');
  const [remarks, setRemarks] = useState('');
  useEffect(() => { setText(r?.narrative ?? ''); setEv((r?.evidence_ids ?? []).join(', ')); }, [r?.id, r?.narrative, r?.evidence_ids]);
  const run = useRun();
  if (!r) return <Section title={code}><p className="text-sm text-muted-foreground">{res.isError ? getApiError(res.error) : 'Loading…'}</p></Section>;
  const words = text.replace(/<[^>]+>/g, ' ').split(/\s+/).filter(Boolean).length;
  return (
    <Section title={`${r.code} ${r.title}`} action={<StatusBadge status={r.status} />}>
      <p className="text-xs text-muted-foreground">Owner {r.owner_name ?? '—'} · due {day(r.due_on)} · {r.metric_type} · max {r.max_score ?? '—'}</p>
      {(r.metric_values ?? []).length > 0 && <SimpleTable head={['Metric', 'Period', 'Value', 'Numerator', 'Denominator', 'Source']} rows={r.metric_values.map((m: Any) => [m.name ?? m.key, m.period, num(m.value), num(m.numerator), num(m.denominator), <SourceBadge key="s" source={m.source} verified={m.verified} />])} />}
      <textarea className={area} value={text} onChange={(e) => setText(e.target.value)} placeholder="Narrative (rich text / HTML allowed)" />
      <p className={`text-xs ${r.word_limit && words > r.word_limit ? 'text-destructive' : 'text-muted-foreground'}`}>{words} words{r.word_limit ? ` / ${r.word_limit}` : ''}</p>
      <Input placeholder="Evidence ids (comma separated)" value={ev} onChange={(e) => setEv(e.target.value)} />
      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={() => run.mutate(() => ia.saveCriterion(cycleId, code, { narrative: text, evidence_ids: ev.split(',').map((x) => x.trim()).filter(Boolean) }), { onSuccess: () => toast.success('Saved (new version)'), onError: fail })}>Save</Button>
        <Button size="sm" variant="outline" onClick={() => run.mutate(() => ia.submit(cycleId, code), { onSuccess: () => toast.success('Submitted for review'), onError: fail })}>Submit for review</Button>
        <Input className="w-56" placeholder="Review remarks" value={remarks} onChange={(e) => setRemarks(e.target.value)} />
        <Button size="sm" variant="outline" onClick={() => run.mutate(() => ia.review(cycleId, code, { action: 'approve', remarks: remarks || undefined }), { onError: fail })}>Approve step</Button>
        <Button size="sm" variant="outline" onClick={() => run.mutate(() => ia.review(cycleId, code, { action: 'reject', remarks: remarks || undefined }), { onError: fail })}>Return</Button>
      </div>
      {(r.review_trail ?? []).length > 0 && <ul className="text-xs text-muted-foreground">{r.review_trail.map((t: Any, i: number) => <li key={i}>{day(t.at)} · {t.action}{t.remarks ? ` — ${t.remarks}` : ''}</li>)}</ul>}
      <details className="text-xs"><summary>Versions ({list(vers.data).length})</summary><ul>{list(vers.data).map((v: Any) => <li key={v.version}>v{v.version} · {day(v.at)} · {v.status} · {v.word_count} words</li>)}</ul></details>
    </Section>
  );
}

// ---- submissions ------------------------------------------------------------------------------------------------------------
export function IqacSubmissionsPage() {
  useTitle('Compliance submissions');
  const res = useQ(['submissions'], () => ia.submissions());
  const [n, setN] = useState<Any>({ submission_type: 'aishe', period_label: currentAY() });
  const [open, setOpen] = useState<string | null>(null);
  const diff = useQ(['diff', open], () => ia.diff(open as string), !!open);
  const [ack, setAck] = useState<Any>({ submitted_on: new Date().toISOString().slice(0, 10), ack_ref: '' });
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Compliance submissions" description="AQAR, NIRF, AISHE, AICTE EoA, UGC annual and NSP returns: generate from metrics → review the diff → mark submitted (payload immutable; corrections are new rows)." />
      <Section title="New submission">
        <div className="flex flex-wrap gap-2">
          <select className={sel} value={n.submission_type} onChange={(e) => setN({ ...n, submission_type: e.target.value })}>{SUB_TYPES.map((x) => <option key={x}>{x}</option>)}</select>
          <Input className="w-28" value={n.period_label} onChange={(e) => setN({ ...n, period_label: e.target.value })} />
          <Button size="sm" onClick={() => run.mutate(() => ia.createSubmission(n), { onSuccess: () => toast.success('Created'), onError: fail })}>Create</Button>
        </div>
      </Section>
      <SimpleTable head={['Type', 'Period', 'Status', 'Submitted', 'Ack', '']} rows={list(res.data).map((s: Any) => [s.submission_type, s.period_label, <StatusBadge key="s" status={s.status} />, day(s.submitted_on), s.ack_ref ?? '—', <span key="a" className="flex gap-1">{['draft', 'generated'].includes(s.status) && <Button size="sm" variant="outline" onClick={() => run.mutate(() => ia.generate(s.id), { onSuccess: () => toast.success('Payload generated'), onError: fail })}>Generate</Button>}<Button size="sm" variant="outline" onClick={() => setOpen(s.id)}>Diff</Button>{s.status === 'generated' && <Button size="sm" onClick={() => run.mutate(() => ia.markSubmitted(s.id, { ...ack, ack_ref: ack.ack_ref || undefined }), { onError: fail })}>Mark submitted</Button>}</span>])} />
      <div className="flex gap-2"><Input type="date" className="w-40" value={ack.submitted_on} onChange={(e) => setAck({ ...ack, submitted_on: e.target.value })} /><Input className="w-56" placeholder="Ack ref" value={ack.ack_ref} onChange={(e) => setAck({ ...ack, ack_ref: e.target.value })} /></div>
      {open && <Section title={`Diff vs ${(diff.data as Any)?.data?.vs_period ?? 'previous period'}`} action={<Button size="sm" variant="outline" onClick={() => setOpen(null)}>Close</Button>}><SimpleTable head={['Metric', 'Previous', 'Current', 'Δ']} rows={((diff.data as Any)?.data?.rows ?? []).map((r: Any) => [r.metric, r.previous ?? '—', r.current ?? '—', r.delta ?? '—'])} /></Section>}
    </div>
  );
}

// ---- audits -----------------------------------------------------------------------------------------------------------------
export function IqacAuditsPage({ hod = false }: { hod?: boolean }) {
  useTitle('Audit registers');
  const res = useQ(['audits'], () => ia.audits());
  const dash = useQ(['auditdash'], () => ia.auditDashboard());
  const [n, setN] = useState<Any>({ audit_type: 'green', period_label: currentAY(), auditor: '', finding: '' });
  const run = useRun();
  const d: Any = (dash.data as Any)?.data;
  const findings = list(res.data).flatMap((a: Any) => (a.findings ?? []).map((f: Any) => ({ ...f, audit: a })));
  const col = (st: string) => findings.filter((f: Any) => f.status === st);
  return (
    <div className="space-y-4">
      <PageHeader title={hod ? 'Audit findings owned' : 'Audit registers'} description="Academic & administrative, green / energy, gender, financial statutory and AG audits with findings, owners and due dates." />
      <div className="grid gap-3 md:grid-cols-4"><Stat label="Registers" value={d?.registers} /><Stat label="Findings open" value={d?.findings_open} /><Stat label="Overdue" value={d?.findings_overdue} /><Stat label="Closed" value={d?.findings_closed} /></div>
      {!hod && <Section title="New register">
        <div className="flex flex-wrap gap-2">
          <select className={sel} value={n.audit_type} onChange={(e) => setN({ ...n, audit_type: e.target.value })}>{AUDIT_TYPES.map((x) => <option key={x}>{x}</option>)}</select>
          <Input className="w-28" value={n.period_label} onChange={(e) => setN({ ...n, period_label: e.target.value })} />
          <Input className="w-56" placeholder="Auditor" value={n.auditor} onChange={(e) => setN({ ...n, auditor: e.target.value })} />
          <Input className="w-72" placeholder="First finding (optional)" value={n.finding} onChange={(e) => setN({ ...n, finding: e.target.value })} />
          <Button size="sm" onClick={() => run.mutate(() => ia.createAudit({ audit_type: n.audit_type, period_label: n.period_label, auditor: n.auditor || undefined, findings: n.finding ? [{ text: n.finding }] : [] }), { onSuccess: () => toast.success('Register created'), onError: fail })}>Create</Button>
        </div>
      </Section>}
      <div className="grid gap-3 md:grid-cols-3">
        {(['open', 'in_progress', 'closed'] as const).map((st) => <Section key={st} title={`${st.replace('_', ' ')} (${col(st).length})`}>
          {col(st).map((f: Any) => <div key={`${f.audit.id}-${f.no}`} className="space-y-1 rounded border p-2 text-sm"><p className="text-xs text-muted-foreground">{f.audit.audit_type} · {f.audit.period_label} · #{f.no} · due {day(f.due_on)}</p><p>{f.text}</p>
            <div className="flex gap-1">{st !== 'in_progress' && st !== 'closed' && <Button size="sm" variant="outline" onClick={() => run.mutate(() => ia.updateFinding(f.audit.id, f.no, { status: 'in_progress' }), { onError: fail })}>Start</Button>}{st !== 'closed' && <Button size="sm" variant="outline" onClick={() => run.mutate(() => ia.updateFinding(f.audit.id, f.no, { status: 'closed', action_taken: 'Action taken and filed' }), { onError: fail })}>Close</Button>}</div></div>)}
        </Section>)}
      </div>
    </div>
  );
}

// ---- consistency / disclosures ------------------------------------------------------------------------------------------------
export function IqacConsistencyPage() {
  useTitle('Consistency checks');
  const [period, setPeriod] = useState(currentAY());
  const res = useQ(['consistency', period], () => ia.consistency(period));
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Consistency checks" description="The same student counted once across NAAC / NIRF / AISHE; faculty vs HR; placed ≤ eligible; PhD awards; expenditure vs statements; programme approvals." actions={<span className="flex gap-2"><Input className="w-28" value={period} onChange={(e) => setPeriod(e.target.value)} /><Button size="sm" onClick={() => run.mutate(() => ia.runConsistency(period), { onError: fail })}>Run</Button></span>} />
      <SimpleTable head={['Check', 'Status', 'Details', 'Fix']} rows={((res.data as Any)?.data?.checks ?? []).map((c: Any) => [c.name, <StatusBadge key="s" status={c.status} />, <code key="d" className="text-xs">{JSON.stringify(c.details)}</code>, c.fix_link ? <Link key="f" className="text-primary underline" to={c.fix_link}>Fix</Link> : '—'])} />
    </div>
  );
}

export function IqacDisclosuresPage() {
  useTitle('Mandatory disclosures');
  const res = useQ(['disclosures'], () => ia.disclosures());
  const run = useRun();
  const d: Any = (res.data as Any)?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Mandatory disclosures" description={`Website feed (aggregates only, no PII) · refreshed ${day(d?.refreshed_at)} · period ${d?.period_label ?? '—'}`} actions={<Button size="sm" onClick={() => run.mutate(() => ia.refreshDisclosures(), { onSuccess: () => toast.success('Refreshed'), onError: fail })}>Refresh</Button>} />
      <SimpleTable head={['Item', 'Value', 'Period', 'Evidence']} rows={(d?.items ?? []).map((i: Any) => [i.title, i.value != null ? `${num(i.value)}${i.unit === 'pct' ? ' %' : ''}` : '—', i.period_label ?? '—', i.evidence_url ? <a key="e" className="text-primary underline" href={i.evidence_url} target="_blank" rel="noreferrer">link</a> : '—'])} />
    </div>
  );
}

// ---- department / faculty views ---------------------------------------------------------------------------------------------
export function HodQualityPage() {
  useTitle('Department quality');
  const cycles = useQ(['cycles'], () => ia.cycles());
  return (
    <div className="space-y-4">
      <IqacMetricsPage hod />
      <Section title="Assigned criterion responses">
        <SimpleTable head={['Cycle', 'Framework', 'Status', 'Completion']} rows={list(cycles.data).map((c: Any) => [<Link key="n" className="text-primary underline" to={`/iqac/cycles/${c.id}`}>{c.name}</Link>, c.framework_code, <StatusBadge key="s" status={c.status} />, `${c.completion_pct}%`])} />
      </Section>
      <IqacAuditsPage hod />
    </div>
  );
}

export function FacultyAccreditationPage() {
  useTitle('My accreditation tasks');
  const cycles = useQ(['cycles'], () => ia.cycles());
  const ev = useQ(['evidence', 'own'], () => ia.evidence({ scope: 'own', per_page: 50 }));
  return (
    <div className="space-y-4">
      <PageHeader title="Accreditation tasks" description="Criterion responses assigned to you and the evidence you uploaded." />
      <Section title="Cycles with my responses">
        <SimpleTable head={['Cycle', 'Framework', 'Status']} rows={list(cycles.data).map((c: Any) => [<Link key="n" className="text-primary underline" to={`/iqac/cycles/${c.id}`}>{c.name}</Link>, c.framework_code, <StatusBadge key="s" status={c.status} />])} />
      </Section>
      <Section title="My evidence">
        <SimpleTable head={['Criterion', 'Title', 'Period', 'Verified']} rows={list(ev.data).map((e: Any) => [e.criterion_code ?? '—', e.title, e.period_label ?? '—', e.verified ? 'yes' : 'no'])} />
      </Section>
    </div>
  );
}
