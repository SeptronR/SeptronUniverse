import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { DndContext, closestCenter, type DragEndEvent } from '@dnd-kit/core';
import { SortableContext, arrayMove, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { getApiError } from '@/api/axios';
import { ChartView, Heatmap, Sparkline, type ChartData } from '@/components/charts/ChartView';
import { PageHeader } from '@/components/shared/PageHeader';
import { ScopeTabs } from '@/components/shared/ScopeTabs';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { SimpleTable } from '@/features/hr/components/shared';
import type { VisibilityMeta } from '@/utils/types';
import { anApi } from '../api';
import { drillUrl } from '../components/drill';

// Phase 35 web screens (Prompts/35 §35.9). Visibility, permissions, feature gates and masking are enforced by the API.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));
const useQ = <T,>(key: unknown[], fn: () => Promise<T>, enabled = true) => useQuery({ queryKey: ['an', ...key], queryFn: fn, retry: false, enabled });
function useRun() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: () => qc.invalidateQueries({ queryKey: ['an'] }), onError: fail });
}
const list = (r: Any) => (Array.isArray(r?.data) ? r.data : []);
const sel = 'h-9 rounded-md border bg-background px-2 text-sm';
const ROLES = ['institution_admin', 'vice_chancellor', 'registrar', 'controller_of_examinations', 'college_admin', 'dean', 'hod', 'faculty', 'class_advisor', 'student', 'parent', 'accountant', 'hr_officer', 'admissions_officer', 'placement_officer', 'hostel_warden', 'librarian', 'transport_manager', 'estate_officer', 'iqac_coordinator', 'research_cell', 'alumni_coordinator', 'auditor'];
const INTERVENTIONS = ['mentor_meeting', 'guardian_call', 'counselling', 'fee_plan', 'remedial_class', 'hostel_warden', 'other'];

function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <Card><CardContent className="space-y-3 p-4"><div className="flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">{title}</h2>{action}</div>{children}</CardContent></Card>;
}
function Err({ q }: { q: Any }) {
  return q.isError ? <p className="text-sm text-destructive">{getApiError(q.error)}</p> : null;
}

// ---- /admin/analytics — catalogue explorer -------------------------------------------------------------------------------
export function CataloguePage() {
  useTitle('Analytics');
  const navigate = useNavigate();
  const cat = useQ(['catalogue'], () => anApi.catalogue());
  const [module, setModule] = useState('');
  const [key, setKey] = useState('');
  const [dims, setDims] = useState<Record<string, string>>({ period: '' });
  const [params, setParams] = useState<Record<string, string>>({});
  const [compare, setCompare] = useState('');
  const items: Any[] = list(cat.data);
  const modules = useMemo(() => Array.from(new Set(items.map((c) => c.module))).sort(), [items]);
  const spec = items.find((c) => c.key === key);
  const chart = useQ(['chart', key, dims, params, compare], () => anApi.chart(key, {}, dims, { ...params, ...(compare ? { compare } : {}) }), !!key);
  const run = useRun();
  const props = Object.entries((spec?.params_schema?.properties ?? {}) as Record<string, Any>);
  return (
    <div className="space-y-4">
      <PageHeader title="Analytics" description="Pick a chart, set dims / parameters, compare colleges or departments, export." />
      <Err q={cat} />
      <Section title="Chart">
        <div className="flex flex-wrap gap-2">
          <select aria-label="Module" className={sel} value={module} onChange={(e) => { setModule(e.target.value); setKey(''); }}>
            <option value="">All modules</option>
            {modules.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
          <select aria-label="Chart" className={`${sel} min-w-[18rem]`} value={key} onChange={(e) => { setKey(e.target.value); setParams({}); }}>
            <option value="">Choose a chart…</option>
            {items.filter((c) => !module || c.module === module).map((c) => <option key={c.key} value={c.key}>{c.title} ({c.key})</option>)}
          </select>
          {spec?.dims?.includes('period') && (
            <select aria-label="Period" className={sel} value={dims.period} onChange={(e) => setDims({ ...dims, period: e.target.value })}>
              {['', 'today', 'last_7d', 'last_30d', 'last_90d', 'this_month', 'this_year', 'fy', 'last_12m'].map((p) => <option key={p} value={p}>{p || 'default period'}</option>)}
            </select>
          )}
          {props.map(([name, s]) => (
            <Input key={name} aria-label={name} placeholder={`${name}${s.default ? ` (${s.default})` : ''}`} className="w-48" value={params[name] ?? ''} onChange={(e) => setParams({ ...params, [name]: e.target.value })} />
          ))}
          <select aria-label="Compare" className={sel} value={compare} onChange={(e) => setCompare(e.target.value)}>
            <option value="">No comparison</option>
            <option value="college">College vs college</option>
            <option value="department">Department vs department</option>
          </select>
          {key && (
            <>
              <Button variant="outline" onClick={() => anApi.chartCsv(key).then((b) => window.open(URL.createObjectURL(b), '_blank')).catch(fail)}>CSV</Button>
              <Button variant="outline" onClick={() => run.mutate(() => anApi.exportChart(key, { format: 'xlsx', dims, params }).then(() => toast.success('Export queued — see Jobs')))}>Export xlsx</Button>
            </>
          )}
        </div>
      </Section>
      <Err q={chart} />
      {chart.data?.data && (
        <ChartView
          data={chart.data.data as ChartData}
          height={340}
          onPoint={(p) => {
            const url = drillUrl(chart.data!.data as ChartData, p);
            if (url) navigate(url);
          }}
        />
      )}
    </div>
  );
}

// ---- /admin/analytics/targets ----------------------------------------------------------------------------------------------
export function TargetsPage() {
  useTitle('KPI targets');
  const q = useQ(['targets'], () => anApi.targets());
  const alerts = useQ(['alerts'], () => anApi.alerts());
  const run = useRun();
  const [edit, setEdit] = useState<Record<string, string>>({});
  const t = q.data?.data ?? {};
  const keys = Object.keys(t.history ?? t.targets ?? {});
  return (
    <div className="space-y-4">
      <PageHeader title="KPI targets" description="Targets per KPI with history; breaches notify the alert recipients once and send a recovery notice." actions={<Button variant="outline" onClick={() => run.mutate(() => anApi.evaluate().then(() => toast.success('Evaluation queued')))}>Evaluate now</Button>} />
      <Err q={q} />
      <Section title="Targets" action={<Button onClick={() => run.mutate(() => anApi.putTargets({ targets: Object.fromEntries(Object.entries(edit).filter(([, v]) => v !== '').map(([k, v]) => [k, Number(v)])) }).then(() => toast.success('Targets saved')))}>Save</Button>}>
        <SimpleTable
          head={['KPI', 'Target', 'Trend (60 days)', 'New target']}
          rows={keys.map((k) => [
            k.replace(/_/g, ' '),
            t.targets?.[k] ?? '—',
            <Sparkline key="s" points={t.history?.[k] ?? []} />,
            <Input key="i" className="w-28" aria-label={`target ${k}`} value={edit[k] ?? ''} onChange={(e) => setEdit({ ...edit, [k]: e.target.value })} />,
          ])}
        />
        <p className="text-xs text-muted-foreground">Alert recipients: {JSON.stringify(t.alert_recipients ?? {})}</p>
      </Section>
      <Section title="Alerts">
        <SimpleTable head={['KPI', 'Value', 'Target', 'Scope', 'Since', 'State']} rows={list(alerts.data).map((a: Any) => [a.key, a.value ?? '—', a.target, a.scope, a.since ? new Date(a.since).toLocaleString() : '—', a.open ? 'open' : `recovered ${a.recovered_at ? new Date(a.recovered_at).toLocaleDateString() : ''}`])} />
      </Section>
    </div>
  );
}

// ---- /admin/analytics/readmodels -------------------------------------------------------------------------------------------
export function ReadModelsPage() {
  useTitle('Read models');
  const q = useQuery({ queryKey: ['an', 'readmodels'], queryFn: () => anApi.readmodels(), refetchInterval: 15_000, retry: false });
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Read models" description="Materialized views behind the dashboards: refreshed by Beat when dirty, or now (job with progress in the Jobs tray)." actions={<Button onClick={() => run.mutate(() => anApi.refresh([]).then(() => toast.success('Refresh queued')))}>Refresh all</Button>} />
      <Err q={q} />
      <SimpleTable
        head={['View', 'Refreshed', 'Duration', 'Rows', 'Interval', 'Dirty', 'Status', '']}
        rows={list(q.data).map((v: Any) => [
          <span key="n" title={v.description}>{v.view}</span>,
          v.refreshed_at ? new Date(v.refreshed_at).toLocaleString() : 'never',
          v.duration_ms !== null && v.duration_ms !== undefined ? `${v.duration_ms} ms` : '—',
          v.rows ?? '—',
          `${v.interval_minutes} min`,
          v.dirty,
          v.stale ? <span key="s" className="text-amber-700">stale</span> : 'fresh',
          <Button key="b" size="sm" variant="outline" onClick={() => run.mutate(() => anApi.refresh([v.view]).then(() => toast.success(`${v.view} queued`)))}>Refresh</Button>,
        ])}
      />
    </div>
  );
}

// ---- /admin/analytics/digests -----------------------------------------------------------------------------------------------
export function DigestsPage() {
  useTitle('Dashboard digests');
  const q = useQ(['digests'], () => anApi.digests());
  const run = useRun();
  const [form, setForm] = useState({ cadence: 'weekly', roles: 'vice_chancellor,registrar', hour: '7', channels: 'in_app,email' });
  return (
    <div className="space-y-4">
      <PageHeader title="Dashboard digests" description="Each recipient gets their own dashboard (their own visibility) as a PDF link by in-app / email / WhatsApp." />
      <Err q={q} />
      <Section title="New schedule">
        <div className="flex flex-wrap gap-2">
          <select aria-label="Cadence" className={sel} value={form.cadence} onChange={(e) => setForm({ ...form, cadence: e.target.value })}><option value="daily">Daily</option><option value="weekly">Weekly (Monday)</option></select>
          <Input aria-label="Roles" className="w-72" value={form.roles} onChange={(e) => setForm({ ...form, roles: e.target.value })} placeholder="role slugs, comma separated" />
          <Input aria-label="Hour" className="w-20" value={form.hour} onChange={(e) => setForm({ ...form, hour: e.target.value })} />
          <Input aria-label="Channels" className="w-48" value={form.channels} onChange={(e) => setForm({ ...form, channels: e.target.value })} />
          <Button onClick={() => run.mutate(() => anApi.createDigest({ cadence: form.cadence, roles: form.roles.split(',').map((s) => s.trim()).filter(Boolean), hour: Number(form.hour), channels: form.channels.split(',').map((s) => s.trim()).filter(Boolean) }).then(() => toast.success('Schedule created')))}>Create</Button>
        </div>
      </Section>
      <SimpleTable
        head={['Cadence', 'Roles', 'Hour', 'Channels', 'Last sent', '']}
        rows={list(q.data).map((d: Any) => [
          d.cadence,
          (d.roles ?? []).join(', '),
          d.hour,
          (d.channels ?? []).join(', '),
          d.last_sent_at ? new Date(d.last_sent_at).toLocaleString() : '—',
          <span key="a" className="flex gap-1">
            <Button size="sm" variant="outline" onClick={() => run.mutate(() => anApi.sendDigest(d.id).then(() => toast.success('Sending — see Jobs')))}>Send now</Button>
            <Button size="sm" variant="ghost" onClick={() => run.mutate(() => anApi.deleteDigest(d.id))}>Delete</Button>
          </span>,
        ])}
      />
    </div>
  );
}

// ---- /admin/dashboard-layouts -------------------------------------------------------------------------------------------------
function SortableRow({ w, onSize, onHide }: { w: Any; onSize: (s: string) => void; onHide: () => void }) {
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id: w.key });
  const style = { transform: transform ? `translate3d(0, ${transform.y}px, 0)` : undefined, transition };
  return (
    <li ref={setNodeRef} style={style} className="flex items-center gap-2 rounded-md border bg-card px-3 py-2 text-sm">
      <button type="button" aria-label={`Drag ${w.key}`} className="cursor-grab text-muted-foreground" {...attributes} {...listeners}>⋮⋮</button>
      <span className="flex-1 truncate">{w.key}</span>
      <span className="text-xs text-muted-foreground">{w.kind}</span>
      <select aria-label="Size" className="h-8 rounded border bg-background px-1 text-xs" value={w.size ?? 'md'} onChange={(e) => onSize(e.target.value)}>
        {['sm', 'md', 'lg', 'xl'].map((s) => <option key={s} value={s}>{s}</option>)}
      </select>
      <Button size="sm" variant="ghost" onClick={onHide}>{w.hidden ? 'Show' : 'Hide'}</Button>
    </li>
  );
}

export function DashboardLayoutsPage() {
  useTitle('Dashboard layouts');
  const [role, setRole] = useState('hod');
  const q = useQ(['layout', role], () => anApi.layout(role));
  const preview = useQ(['preview', role], () => anApi.dashboard({ role }));
  const run = useRun();
  const [widgets, setWidgets] = useState<Any[]>([]);
  useEffect(() => setWidgets(q.data?.data?.widgets ?? []), [q.data]);
  const onDragEnd = (e: DragEndEvent) => {
    if (!e.over || e.active.id === e.over.id) return;
    const from = widgets.findIndex((w) => w.key === e.active.id);
    const to = widgets.findIndex((w) => w.key === e.over!.id);
    setWidgets(arrayMove(widgets, from, to));
  };
  const save = () => run.mutate(() => anApi.putLayout(role, { widgets: widgets.map((w, i) => ({ key: w.key, size: w.size, position: i, hidden: !!w.hidden })) }).then(() => toast.success('Layout saved')));
  return (
    <div className="space-y-4">
      <PageHeader title="Dashboard layouts" description="Reorder, resize or hide widgets per role for this institution; users can still pin / hide within it." actions={<div className="flex gap-2"><Button variant="outline" onClick={() => run.mutate(() => anApi.resetLayout(role).then(() => toast.success('Reset to defaults')))}>Reset</Button><Button onClick={save}>Save</Button></div>} />
      <select aria-label="Role" className={sel} value={role} onChange={(e) => setRole(e.target.value)}>
        {ROLES.map((r) => <option key={r} value={r}>{r.replace(/_/g, ' ')}</option>)}
      </select>
      <Err q={q} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Widgets (drag to reorder)">
          <DndContext collisionDetection={closestCenter} onDragEnd={onDragEnd}>
            <SortableContext items={widgets.map((w) => w.key)} strategy={verticalListSortingStrategy}>
              <ul className="space-y-1.5">
                {widgets.map((w, i) => (
                  <SortableRow key={w.key} w={w} onSize={(s) => setWidgets(widgets.map((x, j) => (j === i ? { ...x, size: s } : x)))} onHide={() => setWidgets(widgets.map((x, j) => (j === i ? { ...x, hidden: !x.hidden } : x)))} />
                ))}
              </ul>
            </SortableContext>
          </DndContext>
        </Section>
        <Section title="Live preview (as you, in this role when held)">
          <Err q={preview} />
          <ul className="space-y-1 text-sm">
            {(preview.data?.data?.widgets ?? []).map((w: Any) => <li key={w.key} className="flex justify-between"><span>{w.title ?? w.key}</span><span className="text-xs text-muted-foreground">{w.unavailable ? 'unavailable' : w.kind}</span></li>)}
          </ul>
        </Section>
      </div>
    </div>
  );
}

// ---- /admin/risk/analytics — early warning ----------------------------------------------------------------------------------
export function RiskAnalyticsPage() {
  useTitle('Early warning');
  const [groupBy, setGroupBy] = useState('department');
  const [scope, setScope] = useState<string | undefined>();
  const [level, setLevel] = useState('high');
  const [factor, setFactor] = useState('');
  const [unack, setUnack] = useState(false);
  const [noInt, setNoInt] = useState('');
  const [logFor, setLogFor] = useState<Any | null>(null);
  const cohort = useQ(['cohort', groupBy, scope], () => anApi.cohort({ group_by: groupBy, scope }));
  const students = useQ(['students', level, factor, unack, noInt, scope], () => anApi.riskStudents({ level: level || undefined, factor: factor || undefined, unacknowledged: unack || undefined, no_intervention_days: noInt ? Number(noInt) : undefined, scope }));
  const eff = useQ(['eff', scope], () => anApi.effectiveness({ scope }));
  const run = useRun();
  const c = cohort.data?.data ?? {};
  const visibility = cohort.data?.meta?.visibility as VisibilityMeta | undefined;
  const heatPoints = (c.cells ?? []).map((x: Any) => ({ label: x.group, low: x.low, medium: x.medium, high: x.high }));
  const trend: ChartData = {
    key: 'risk.trend',
    kind: 'line',
    title: 'Risk levels across terms',
    series: c.trend ?? [],
    dims: { series: ['low', 'medium', 'high'] },
    table: { columns: ['term', 'low', 'medium', 'high'], rows: (c.trend ?? []).map((p: Any) => [p.label, p.low ?? 0, p.medium ?? 0, p.high ?? 0]) },
    generated_at: new Date().toISOString(),
  };
  const factors: ChartData = {
    key: 'risk.factor_means',
    kind: 'bar',
    title: 'Factor means (0–1)',
    series: Object.entries(c.factor_means ?? {}).map(([label, value]) => ({ label, value })),
    dims: { series: ['value'] },
    table: { columns: ['factor', 'mean'], rows: Object.entries(c.factor_means ?? {}).map(([k, v]) => [k, v as number]) },
    generated_at: new Date().toISOString(),
  };
  const effRows = Object.entries((eff.data?.data?.by_type ?? {}) as Record<string, Any>);
  return (
    <div className="space-y-4">
      <PageHeader title="Early warning" description="Cohorts over the Phase 27 risk flags; interventions are logged as mentoring sessions so the mentor timeline stays single-sourced." actions={<Button variant="outline" onClick={() => run.mutate(() => anApi.exportCohort({ kind: 'cohort', scope }).then(() => toast.success('Export queued')))}>Export cohort</Button>} />
      {visibility && <ScopeTabs visibility={visibility} value={scope} onChange={setScope} />}
      <Err q={cohort} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Cohort heat map" action={<select aria-label="Group by" className={sel} value={groupBy} onChange={(e) => setGroupBy(e.target.value)}>{['department', 'program', 'batch', 'hostel', 'category'].map((g) => <option key={g} value={g}>{g}</option>)}</select>}>
          <div className="h-72"><Heatmap points={heatPoints} keys={['low', 'medium', 'high']} onPoint={(p) => setLevel(String(p.series ?? 'high'))} /></div>
        </Section>
        <ChartView data={factors} />
        <ChartView data={trend} />
        <Section title="Intervention effectiveness (this term)">
          <SimpleTable head={['Type', 'Improved', 'Same', 'Worse', 'Total']} rows={effRows.map(([t, s]) => [t.replace(/_/g, ' '), s.improved, s.same, s.worse, s.total])} />
        </Section>
      </div>
      <Section title="Students">
        <div className="flex flex-wrap gap-2">
          <select aria-label="Level" className={sel} value={level} onChange={(e) => setLevel(e.target.value)}><option value="">Any level</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select>
          <select aria-label="Factor" className={sel} value={factor} onChange={(e) => setFactor(e.target.value)}><option value="">Any factor</option>{['attendance', 'cia', 'dues', 'standing', 'hostel', 'engagement'].map((f) => <option key={f} value={f}>{f}</option>)}</select>
          <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={unack} onChange={(e) => setUnack(e.target.checked)} />Unacknowledged</label>
          <Input aria-label="No intervention in days" className="w-44" placeholder="no intervention in N days" value={noInt} onChange={(e) => setNoInt(e.target.value)} />
        </div>
        <Err q={students} />
        <SimpleTable
          head={['Student', 'Score', 'Level', 'Mentor', 'Last intervention', 'Ack', '']}
          rows={list(students.data).map((s: Any) => [
            s.enrollment_id ? <Link key="l" className="text-primary underline" to={`/faculty/mentees/${s.enrollment_id}`}>{s.student_name ?? s.registration_number}</Link> : '—',
            s.score,
            s.level,
            s.mentor ?? '—',
            s.last_intervention ? `${String(s.last_intervention.intervention_type ?? '').replace(/_/g, ' ')} · ${s.last_intervention.held_on}` : '—',
            s.acknowledged ? 'yes' : 'no',
            s.enrollment_id ? <Button key="b" size="sm" variant="outline" onClick={() => setLogFor(s)}>Log intervention</Button> : null,
          ])}
        />
      </Section>
      {logFor && <LogInterventionDialog student={logFor} onClose={() => setLogFor(null)} onSaved={() => { setLogFor(null); void students.refetch(); }} />}
    </div>
  );
}

function LogInterventionDialog({ student, onClose, onSaved }: { student: Any; onClose: () => void; onSaved: () => void }) {
  const [type, setType] = useState(INTERVENTIONS[0]);
  const [notes, setNotes] = useState('');
  const [follow, setFollow] = useState('');
  const save = async () => {
    try {
      await anApi.logIntervention(student.enrollment_id, { intervention_type: type, notes: notes || undefined, follow_up_on: follow || undefined });
      toast.success('Intervention logged');
      onSaved();
    } catch (e) {
      fail(e);
    }
  };
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`Log intervention — ${student.student_name ?? student.registration_number}`} footer={<Button onClick={() => void save()}>Save</Button>}>
      <div className="space-y-2">
        <select aria-label="Type" className={`${sel} w-full`} value={type} onChange={(e) => setType(e.target.value)}>{INTERVENTIONS.map((t) => <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>)}</select>
        <textarea aria-label="Notes" className="min-h-[90px] w-full rounded-md border bg-background p-2 text-sm" value={notes} onChange={(e) => setNotes(e.target.value)} />
        <Input aria-label="Follow up on" type="date" value={follow} onChange={(e) => setFollow(e.target.value)} />
      </div>
    </Modal>
  );
}
