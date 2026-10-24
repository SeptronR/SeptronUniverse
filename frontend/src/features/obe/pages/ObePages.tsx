import { useEffect, useState, type ReactNode } from 'react';
import { useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { SimpleTable } from '@/features/hr/components/shared';
import { obeApi } from '../api';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));
const useQ = <T,>(key: unknown[], fn: () => Promise<T>, enabled = true) => useQuery({ queryKey: ['obe', ...key], queryFn: fn, enabled, retry: false });
function useRun() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: () => qc.invalidateQueries({ queryKey: ['obe'] }) });
}
const lv = (v: number | null | undefined) => (v === null || v === undefined ? '—' : Number(v).toFixed(2));

/** Gap chip: green when met (gap ≤ 0), amber within 0.5, red beyond. */
function GapChip({ gap }: { gap: number | null | undefined }) {
  if (gap === null || gap === undefined) return <span className="text-muted-foreground">—</span>;
  const v = gap <= 0 ? 'success' : gap <= 0.5 ? 'warning' : 'destructive';
  return <Badge variant={v}>{gap <= 0 ? 'met' : `−${gap.toFixed(2)}`}</Badge>;
}

/** Level heatmap cell colour (0–3). */
function Heat({ v }: { v: number | null | undefined }) {
  if (v === null || v === undefined) return <td className="border px-2 py-1 text-center text-muted-foreground">—</td>;
  const tone = v >= 2.5 ? 'bg-emerald-500/30' : v >= 2 ? 'bg-emerald-500/15' : v >= 1 ? 'bg-amber-500/20' : 'bg-red-500/20';
  return <td className={`border px-2 py-1 text-center tabular-nums ${tone}`}>{Number(v).toFixed(2)}</td>;
}

function Heatmap({ data }: { data: Any }) {
  if (!data?.rows?.length) return <p className="text-sm text-muted-foreground">No computed values yet.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="text-xs">
        <thead><tr><th className="px-2 py-1" />{data.columns.map((c: string) => <th key={c} className="px-2 py-1 font-medium">{c}</th>)}</tr></thead>
        <tbody>{data.rows.map((r: string, i: number) => <tr key={r}><th className="px-2 py-1 text-left font-medium">{r}</th>{data.cells[i].map((v: number | null, j: number) => <Heat key={j} v={v} />)}</tr>)}</tbody>
      </table>
    </div>
  );
}

/** Programme + batch pickers (Phase 05 lookups). */
function ProgramBatchPicker({ value, onChange, batchRequired = true }: { value: { program_id: string; batch_id: string }; onChange: (v: { program_id: string; batch_id: string }) => void; batchRequired?: boolean }) {
  const programs = useQ(['programs'], () => obeApi.programs());
  const batches = useQ(['batches', value.program_id], () => obeApi.batches(value.program_id), !!value.program_id);
  const list = (r: Any) => (Array.isArray(r?.data) ? r.data : r?.data?.items ?? []);
  return (
    <div className="flex flex-wrap gap-2">
      <select className="h-9 rounded-md border bg-background px-2 text-sm" value={value.program_id} onChange={(e) => onChange({ program_id: e.target.value, batch_id: '' })}>
        <option value="">Programme…</option>
        {list(programs.data).map((p: Any) => <option key={p.id} value={p.id}>{p.code} — {p.name}</option>)}
      </select>
      {batchRequired && (
        <select className="h-9 rounded-md border bg-background px-2 text-sm" value={value.batch_id} onChange={(e) => onChange({ ...value, batch_id: e.target.value })} disabled={!value.program_id}>
          <option value="">Batch…</option>
          {list(batches.data).map((b: Any) => <option key={b.id} value={b.id}>{b.code ?? b.admission_year}</option>)}
        </select>
      )}
    </div>
  );
}

function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <Card><CardContent className="space-y-3 p-4">
      <div className="flex items-center justify-between"><h2 className="text-sm font-semibold">{title}</h2>{action}</div>
      {children}
    </CardContent></Card>
  );
}

// ---- /admin/obe/config ------------------------------------------------------------------------------------------------------
export function ObeConfigPage() {
  useTitle('Attainment config');
  const [sel, setSel] = useState({ program_id: '', batch_id: '' });
  const eff = useQ(['effective', sel.program_id], () => obeApi.effective(sel.program_id), !!sel.program_id);
  const [f, setF] = useState<Any | null>(null);
  const run = useRun();
  useEffect(() => { if (eff.data?.data) setF({ ...eff.data.data }); }, [eff.data]);
  const save = () => run.mutate(() => obeApi.saveConfig({
    scope_type: 'program', scope_id: sel.program_id,
    target_student_pct: Number(f.target_student_pct), target_marks_pct: Number(f.target_marks_pct),
    levels: f.levels.map((l: Any) => ({ level: Number(l.level), min_pct: Number(l.min_pct) })),
    direct_weight: Number(f.direct_weight), indirect_weight: Number(f.indirect_weight),
    cia_weight_in_direct: Number(f.cia_weight_in_direct), ese_weight_in_direct: Number(f.ese_weight_in_direct),
    co_target_level: Number(f.co_target_level), po_target_level: Number(f.po_target_level),
    ese_apportion_strategy: f.ese_apportion_strategy, credit_weighted_po: !!f.credit_weighted_po,
  }), { onSuccess: () => toast.success('Config saved'), onError: fail });
  const num = (k: string, label: string) => (
    <label className="space-y-1 text-xs"><span className="text-muted-foreground">{label}</span>
      <Input type="number" value={f?.[k] ?? ''} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></label>
  );
  const warn = f && (Number(f.direct_weight) + Number(f.indirect_weight) !== 100 || Number(f.cia_weight_in_direct) + Number(f.ese_weight_in_direct) !== 100);
  return (
    <div className="space-y-4">
      <PageHeader title="Attainment configuration" description="Effective config per programme: programme → regulation → platform defaults. Every run stores a snapshot." />
      <ProgramBatchPicker value={sel} onChange={setSel} batchRequired={false} />
      {f && (
        <>
          <p className="text-xs"><Badge variant="info">source: {f.source}</Badge></p>
          <Section title="Targets & weights">
            <div className="grid gap-3 sm:grid-cols-4">
              {num('target_student_pct', 'Students above target (%)')}
              {num('target_marks_pct', 'Target marks (% of CO max)')}
              {num('co_target_level', 'CO target level')}
              {num('po_target_level', 'PO target level')}
              {num('direct_weight', 'Direct weight')}
              {num('indirect_weight', 'Indirect weight')}
              {num('cia_weight_in_direct', 'CIA weight in direct')}
              {num('ese_weight_in_direct', 'ESE weight in direct')}
            </div>
            {warn && <p className="text-xs text-status-rejected">Direct + indirect and CIA + ESE must each add up to 100.</p>}
          </Section>
          <Section title="Level bands (% of students above target)">
            <div className="flex flex-wrap gap-3">
              {f.levels.map((l: Any, i: number) => (
                <label key={i} className="space-y-1 text-xs"><span className="text-muted-foreground">Level {l.level} from</span>
                  <Input type="number" className="w-24" value={l.min_pct} onChange={(e) => setF({ ...f, levels: f.levels.map((x: Any, j: number) => (j === i ? { ...x, min_pct: e.target.value } : x)) })} /></label>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <label>ESE apportion{' '}
                <select className="h-8 rounded-md border bg-background px-2" value={f.ese_apportion_strategy} onChange={(e) => setF({ ...f, ese_apportion_strategy: e.target.value })}>
                  <option value="question_wise">question-wise valuations</option><option value="qp_pattern">QP pattern CO weights</option><option value="uniform">uniform</option>
                </select></label>
              <label className="flex items-center gap-1"><input type="checkbox" checked={!!f.credit_weighted_po} onChange={(e) => setF({ ...f, credit_weighted_po: e.target.checked })} /> credit-weighted PO</label>
            </div>
          </Section>
          <Button disabled={run.isPending} onClick={save}>Save programme config</Button>
          <Section title="History">
            <SimpleTable head={['When', 'Action', 'Changes']} rows={(f.history ?? []).map((h: Any) => [new Date(h.at).toLocaleString(), h.action, <code key="c" className="text-[10px]">{JSON.stringify(h.new).slice(0, 160)}</code>])} empty="No edits yet." />
          </Section>
        </>
      )}
    </div>
  );
}

// ---- /faculty/offerings/:id/attainment ----------------------------------------------------------------------------------------
export function OfferingAttainmentPage() {
  const { id = '' } = useParams();
  useTitle('CO attainment');
  const q = useQ(['co', id], () => obeApi.co(id));
  const heat = useQ(['co-heat', id], () => obeApi.coHeatmap(id));
  const runs = useQ(['co-runs', id], () => obeApi.coRuns(id));
  const [showStudents, setShowStudents] = useState(false);
  const students = useQ(['co-students', id], () => obeApi.coStudents(id), showStudents);
  const [drawer, setDrawer] = useState<Any | null>(null);
  const run = useRun();
  const d = q.data?.data;
  const pre = d?.prerequisites;
  const tick = (ok: boolean | undefined, label: string) => <span className={ok ? 'text-status-approved' : 'text-status-pending'}>{ok ? '✓' : '•'} {label}</span>;
  return (
    <div className="space-y-4">
      <PageHeader title={`CO attainment${d ? ` — ${d.offering.course_code} ${d.offering.section_code ?? ''}` : ''}`} description="CIA question-wise + ESE (question-wise / apportioned) → direct; course-exit survey → indirect; final vs target." />
      {pre && (
        <Section title="Prerequisites" action={<Button size="sm" disabled={run.isPending} onClick={() => run.mutate(() => obeApi.coCompute(id, { include_indirect: true }), { onSuccess: (r: Any) => toast.success(r?.data?.warnings?.length ? `Queued — ${r.data.warnings.join(', ')}` : 'Queued'), onError: fail })}>Compute</Button>}>
          <div className="flex flex-wrap gap-4 text-sm">
            {tick(pre.cia_locked, `CIA locked${pre.cia_pending?.length ? ` (pending: ${pre.cia_pending.join(', ')})` : ''}`)}
            {tick(!pre.has_ese || pre.results_published, pre.has_ese ? 'Results published' : 'No ESE paper')}
            {tick(pre.survey_present, 'Course-exit survey')}
          </div>
          {d?.run && <p className="text-xs text-muted-foreground">Last run {new Date(d.run.run_at).toLocaleString()} · <StatusBadge status={d.run.status} /> {d.run.warnings?.map((w: string) => <Badge key={w} variant="warning" className="ml-1">{w}</Badge>)}</p>}
        </Section>
      )}
      <Section title="Course outcomes">
        <SimpleTable
          head={['CO', 'Assessed', 'Above target', 'CIA', 'ESE', 'Direct', 'Indirect', 'Final', 'Target', 'Gap', '']}
          rows={(d?.cos ?? []).map((c: Any) => [
            <span key="co" title={c.statement}>{c.co}</span>, c.students_assessed, c.students_above_target,
            lv(c.cia_level), lv(c.ese_level), lv(c.direct_level), lv(c.indirect_level), <b key="f">{lv(c.final_level)}</b>, lv(c.target), <GapChip key="g" gap={c.gap} />,
            <Button key="b" size="sm" variant="ghost" onClick={() => setDrawer(c)}>Breakdown</Button>,
          ])}
          empty="No computed run yet — check the prerequisites and compute."
        />
      </Section>
      <Section title="Heatmap — CO × assessment level"><Heatmap data={heat.data?.data} /></Section>
      <Section title="Student CO achievement" action={<Button size="sm" variant="outline" onClick={() => setShowStudents(!showStudents)}>{showStudents ? 'Hide' : 'Show'}</Button>}>
        {showStudents && (
          <SimpleTable
            head={['Reg. no', 'Name', ...((d?.cos ?? []).map((c: Any) => c.co))]}
            rows={(students.data?.data ?? []).map((s: Any) => [s.registration_number, s.student_name, ...s.cos.map((c: Any, i: number) => <span key={i} className={c.above_target ? 'text-status-approved' : 'text-status-rejected'}>{c.marks_pct ?? '—'}</span>)])}
          />
        )}
      </Section>
      <Section title="Run history">
        <SimpleTable head={['When', 'Status', 'Warnings']} rows={(runs.data?.data ?? []).map((r: Any) => [new Date(r.run_at).toLocaleString(), <StatusBadge key="s" status={r.status} />, (r.warnings ?? []).join(', ') || '—'])} />
      </Section>
      <Modal open={!!drawer} onOpenChange={(o) => !o && setDrawer(null)} title={`${drawer?.co ?? ''} breakdown`} size="lg">
        <SimpleTable head={['Assessment', 'Kind', 'Source', 'CO max', 'Assessed', 'Above', '%', 'Level']} rows={(drawer?.breakdown ?? []).map((p: Any) => [p.assessment, p.kind, p.source, p.co_max, p.students_assessed, p.students_above_target, p.pct, p.level])} />
      </Modal>
    </div>
  );
}

// ---- /admin/obe/program-attainment ------------------------------------------------------------------------------------------
export function ProgramAttainmentPage() {
  useTitle('Programme attainment');
  const [sel, setSel] = useState({ program_id: '', batch_id: '' });
  const ready = !!sel.program_id && !!sel.batch_id;
  const dash = useQ(['dash', sel], () => obeApi.dashboard(sel.program_id, sel.batch_id), ready);
  const po = useQ(['po', sel], () => obeApi.po(sel.program_id, sel.batch_id), ready);
  const [newAction, setNewAction] = useState<Any | null>(null);
  const run = useRun();
  const d = dash.data?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Programme attainment" description="PO / PSO attainment per batch: course contributions from CO runs and the CO-PO matrix, plus exit / alumni / employer surveys." />
      <div className="flex flex-wrap items-center gap-2">
        <ProgramBatchPicker value={sel} onChange={setSel} />
        <Button size="sm" disabled={!ready || run.isPending} onClick={() => run.mutate(() => obeApi.poCompute(sel.program_id, sel.batch_id, { include_indirect: true }), { onSuccess: () => toast.success('PO run queued'), onError: fail })}>Compute</Button>
      </div>
      {d && (
        <>
          <div className="flex flex-wrap gap-2 text-sm">
            <Badge variant={(d.coverage_pct ?? 0) >= 60 ? 'success' : 'warning'}>coverage {d.coverage_pct ?? 0}%</Badge>
            {d.run?.warnings?.map((w: string) => <Badge key={w} variant="warning">{w}</Badge>)}
            {Object.entries(d.cqi ?? {}).map(([k, v]) => <Badge key={k} variant="outline">CQI {k}: {String(v)}</Badge>)}
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Section title="PO / PSO radar">
              <div className="h-72"><ResponsiveContainer><RadarChart data={d.radar}><PolarGrid /><PolarAngleAxis dataKey="outcome" /><PolarRadiusAxis domain={[0, 3]} /><Radar dataKey="final" name="Final" stroke="#4f46e5" fill="#4f46e5" fillOpacity={0.35} /><Radar dataKey="target" name="Target" stroke="#f59e0b" fill="none" /><Legend /></RadarChart></ResponsiveContainer></div>
            </Section>
            <Section title="Direct vs indirect">
              <div className="h-72"><ResponsiveContainer><BarChart data={d.direct_vs_indirect}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="outcome" /><YAxis domain={[0, 3]} /><Tooltip /><Legend /><Bar dataKey="direct" fill="#4f46e5" /><Bar dataKey="indirect" fill="#10b981" /></BarChart></ResponsiveContainer></div>
            </Section>
          </div>
          <Section title="Course × PO contribution"><Heatmap data={d.heatmap} /></Section>
          <Section title="Outcomes">
            <SimpleTable head={['Outcome', 'Direct', 'Indirect', 'Final', 'Target', 'Gap', 'Courses']} rows={(po.data?.data?.outcomes ?? []).map((o: Any) => [<span key="o" title={o.statement}>{o.outcome}</span>, lv(o.direct), lv(o.indirect), <b key="f">{lv(o.final)}</b>, lv(o.target), <GapChip key="g" gap={o.gap} />, o.contributing_courses])} />
            {(po.data?.data?.peos ?? []).length > 0 && <p className="text-xs text-muted-foreground">PEO (derived): {po.data?.data?.peos.map((p: Any) => `${p.outcome} ${lv(p.level)}`).join(' · ')}</p>}
          </Section>
          <Section title="Gap list">
            <SimpleTable head={['Scope', 'Outcome', 'Final', 'Target', 'Gap', 'Suggested action', 'Open', '']} rows={d.gaps.map((g: Any, i: number) => [g.label, g.outcome, lv(g.final), lv(g.target), <GapChip key="g" gap={g.gap} />, <span key="s" className="text-xs">{g.suggested_action}</span>, g.open_actions, <Button key={i} size="sm" variant="outline" onClick={() => setNewAction({ scope_type: g.scope, scope_id: g.scope_id, outcome_id: g.outcome_id, gap: g.gap, action_text: g.suggested_action, due_on: '' })}>Create CQI action</Button>])} empty="No gaps — every outcome meets its target." />
          </Section>
        </>
      )}
      <CqiCreateModal value={newAction} onClose={() => setNewAction(null)} />
    </div>
  );
}

function CqiCreateModal({ value, onClose }: { value: Any | null; onClose: () => void }) {
  const [f, setF] = useState<Any | null>(value);
  const run = useRun();
  useEffect(() => setF(value), [value]);
  return (
    <Modal open={!!value} onOpenChange={(o) => !o && onClose()} title="New CQI action"
      footer={<Button disabled={!f?.action_text || run.isPending} onClick={() => run.mutate(() => obeApi.cqiCreate({ ...f, due_on: f.due_on || undefined, owner_staff_id: f.owner_staff_id || undefined, gap: f.gap ?? undefined, outcome_id: f.outcome_id ?? undefined }), { onSuccess: () => { toast.success('Action created'); onClose(); }, onError: fail })}>Create</Button>}>
      {f && (
        <div className="space-y-2 text-sm">
          <textarea className="min-h-24 w-full rounded-md border bg-background p-2" value={f.action_text} onChange={(e) => setF({ ...f, action_text: e.target.value })} />
          <Input placeholder="Owner staff id" value={f.owner_staff_id ?? ''} onChange={(e) => setF({ ...f, owner_staff_id: e.target.value })} />
          <Input type="date" value={f.due_on ?? ''} onChange={(e) => setF({ ...f, due_on: e.target.value })} />
        </div>
      )}
    </Modal>
  );
}

// ---- /admin/obe/trend --------------------------------------------------------------------------------------------------------
export function AttainmentTrendPage() {
  useTitle('Attainment trend');
  const [sel, setSel] = useState({ program_id: '', batch_id: '' });
  const q = useQ(['trend', sel.program_id], () => obeApi.poTrend(sel.program_id), !!sel.program_id);
  const t = q.data?.data;
  const data = (t?.batches ?? []).map((b: Any) => ({ batch: b.batch.code ?? b.batch.admission_year, ...b.outcomes }));
  const palette = ['#4f46e5', '#10b981', '#f59e0b', '#ef4444', '#0ea5e9', '#8b5cf6', '#14b8a6', '#f97316', '#84cc16', '#ec4899', '#64748b', '#a855f7', '#22c55e', '#eab308'];
  return (
    <div className="space-y-4">
      <PageHeader title="Attainment trend" description="Final PO / PSO levels of each batch's latest run." />
      <ProgramBatchPicker value={sel} onChange={setSel} batchRequired={false} />
      {t && (
        <Section title="Batches">
          <div className="h-80"><ResponsiveContainer><LineChart data={data}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="batch" /><YAxis domain={[0, 3]} /><Tooltip /><Legend />{t.outcomes.map((o: string, i: number) => <Line key={o} dataKey={o} stroke={palette[i % palette.length]} dot />)}</LineChart></ResponsiveContainer></div>
        </Section>
      )}
    </div>
  );
}

// ---- /admin/obe/cqi ------------------------------------------------------------------------------------------------------------
const COLUMNS = ['planned', 'in_progress', 'done', 'verified'] as const;
export function CqiBoardPage() {
  useTitle('CQI actions');
  const [mine, setMine] = useState(false);
  const q = useQ(['cqi', mine], () => obeApi.cqi({ mine }));
  const [evidence, setEvidence] = useState<Any | null>(null);
  const run = useRun();
  const move = (a: Any, status: string, extra: Any = {}) => run.mutate(() => obeApi.cqiStatus(a.id, { status, ...extra }), { onSuccess: () => toast.success(`Moved to ${status}`), onError: fail });
  const verify = (a: Any, approve: boolean) => run.mutate(() => obeApi.cqiVerify(a.id, { approve }), { onSuccess: () => toast.success(approve ? 'Verified' : 'Returned'), onError: fail });
  const rows: Any[] = q.data?.data ?? [];
  return (
    <div className="space-y-4">
      <PageHeader title="CQI actions" description="Continuous quality improvement register — owners move their actions; the HOD / OBE coordinator verifies with evidence." />
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> Only my actions</label>
      <div className="grid gap-3 md:grid-cols-4">
        {COLUMNS.map((col) => (
          <div key={col} className="space-y-2 rounded-lg border bg-muted/30 p-2">
            <p className="text-xs font-semibold uppercase text-muted-foreground">{col.replace('_', ' ')} · {rows.filter((r) => r.status === col).length}</p>
            {rows.filter((r) => r.status === col).map((a) => (
              <Card key={a.id}><CardContent className="space-y-1 p-3 text-xs">
                <p className="font-medium">{a.scope_label ?? a.scope_type}{a.outcome ? ` · ${a.outcome}` : ''}</p>
                <p>{a.action_text}</p>
                <p className="text-muted-foreground">{a.owner_name ?? 'unassigned'} · due {a.due_on ?? '—'} {a.overdue && <Badge variant="destructive">overdue</Badge>}</p>
                {a.gap !== null && <p>Gap {lv(a.gap)}{a.gap_after !== null && a.gap_after !== undefined ? ` → ${lv(a.gap_after)}` : ''}</p>}
                {a.evidence_url && <p className="truncate">Evidence: {a.evidence_url}</p>}
                <div className="flex flex-wrap gap-1 pt-1">
                  {a.status === 'planned' && <Button size="sm" variant="outline" onClick={() => move(a, 'in_progress')}>Start</Button>}
                  {(a.status === 'planned' || a.status === 'in_progress') && <Button size="sm" variant="outline" onClick={() => setEvidence(a)}>Done…</Button>}
                  {a.status === 'done' && <><Button size="sm" onClick={() => verify(a, true)}>Verify</Button><Button size="sm" variant="ghost" onClick={() => verify(a, false)}>Return</Button></>}
                </div>
              </CardContent></Card>
            ))}
          </div>
        ))}
      </div>
      <EvidenceModal action={evidence} onClose={() => setEvidence(null)} onSubmit={(url) => { move(evidence, 'done', { evidence_url: url }); setEvidence(null); }} />
    </div>
  );
}

function EvidenceModal({ action, onClose, onSubmit }: { action: Any | null; onClose: () => void; onSubmit: (url: string) => void }) {
  const [url, setUrl] = useState('');
  return (
    <Modal open={!!action} onOpenChange={(o) => !o && onClose()} title="Mark done — evidence" footer={<Button disabled={!url} onClick={() => onSubmit(url)}>Mark done</Button>}>
      <p className="mb-2 text-xs text-muted-foreground">Upload the evidence through Files and paste its link / key here.</p>
      <Input placeholder="Evidence URL or file key" value={url} onChange={(e) => setUrl(e.target.value)} />
    </Modal>
  );
}

// ---- /admin/obe/exports ---------------------------------------------------------------------------------------------------------
export function NbaExportPage() {
  useTitle('NBA SAR export');
  const [sel, setSel] = useState({ program_id: '', batch_id: '' });
  const [format, setFormat] = useState<'xlsx' | 'docx'>('xlsx');
  const [jobs, setJobs] = useState<string[]>([]);
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="NBA SAR export" description="Criterion 3 tables: 3.1 CO statements & CO-PO matrix, 3.2 CO attainment, 3.3 PO / PSO attainment, CQI actions." />
      <div className="flex flex-wrap items-center gap-2">
        <ProgramBatchPicker value={sel} onChange={setSel} />
        <select className="h-9 rounded-md border bg-background px-2 text-sm" value={format} onChange={(e) => setFormat(e.target.value as 'xlsx' | 'docx')}><option value="xlsx">XLSX</option><option value="docx">DOCX</option></select>
        <Button disabled={!sel.program_id || !sel.batch_id || run.isPending} onClick={() => run.mutate(() => obeApi.nbaExport({ ...sel, format }).then((r: Any) => setJobs((j) => [r.data.job_id, ...j])), { onSuccess: () => toast.success('Export queued'), onError: fail })}>Generate</Button>
      </div>
      <Section title="Exports">{jobs.length ? jobs.map((j) => <ExportRow key={j} jobId={j} />) : <p className="text-sm text-muted-foreground">Generated exports appear here.</p>}</Section>
    </div>
  );
}

function ExportRow({ jobId }: { jobId: string }) {
  const q = useQuery({ queryKey: ['obe', 'export', jobId], queryFn: () => obeApi.exportJob(jobId), refetchInterval: (s) => (['succeeded', 'failed', 'completed'].includes((s.state.data as Any)?.data?.status) ? false : 2000) });
  const j = (q.data as Any)?.data;
  return (
    <div className="flex items-center justify-between border-b py-2 text-sm">
      <span className="font-mono text-xs">{jobId.slice(0, 8)}</span>
      <StatusBadge status={j?.status} />
      {j?.file_url ? <a className="text-primary underline" href={j.file_url} target="_blank" rel="noreferrer">Download</a> : <span className="text-muted-foreground">{j?.progress ?? 0}%</span>}
    </div>
  );
}

// ---- /student/courses/:offeringId/outcomes ---------------------------------------------------------------------------------------
export function StudentOutcomesPage() {
  const { offeringId = '' } = useParams();
  useTitle('Course outcomes');
  const q = useQ(['me', offeringId], () => obeApi.me(offeringId));
  const d = q.data?.data;
  return (
    <div className="space-y-4">
      <PageHeader title={`Course outcomes${d ? ` — ${d.offering.course_code}` : ''}`} description="Your achievement of each course outcome (CIA + end-semester questions mapped to the outcome)." />
      {q.isError && <p className="text-sm text-muted-foreground">{getApiError(q.error)}</p>}
      {d && <SimpleTable head={['CO', 'Statement', 'Your marks %', '']} rows={d.cos.map((c: Any) => [c.co, <span key="s" className="text-xs">{c.statement}</span>, c.marks_pct ?? '—', c.above_target === null ? '—' : <Badge key="b" variant={c.above_target ? 'success' : 'warning'}>{c.above_target ? 'achieved' : 'below target'}</Badge>])} />}
    </div>
  );
}
