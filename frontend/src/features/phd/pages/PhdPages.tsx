import { useEffect, useState, type ReactNode } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
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
import { phdApi as pa } from '../api';

// Phase 31 web screens (Prompts/31 §31.9). Ownership (self / guide / DC / unit / all), load limits, sealed panels and
// workflows are enforced by the API; these screens only present them.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));
const useQ = <T,>(key: unknown[], fn: () => Promise<T>, enabled = true) => useQuery({ queryKey: ['phd', ...key], queryFn: fn, retry: false, enabled });
function useRun() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: () => qc.invalidateQueries({ queryKey: ['phd'] }) });
}
const list = (r: Any) => (Array.isArray(r?.data) ? r.data : r?.data?.items ?? []);
const day = (s?: string | null) => (s ? new Date(s).toLocaleDateString() : '—');
const inr = (p?: number | null) => `₹${((p ?? 0) / 100).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
const sel = 'h-9 rounded-md border bg-background px-2 text-sm';
const area = 'min-h-[80px] w-full rounded-md border bg-background p-2 text-sm';
const STATUSES = ['admitted', 'coursework', 'registered', 'synopsis_submitted', 'thesis_submitted', 'under_evaluation', 'viva_scheduled', 'awarded', 'discontinued'];
const thisMonth = () => new Date().toISOString().slice(0, 8) + '01';

function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <Card><CardContent className="space-y-3 p-4"><div className="flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">{title}</h2>{action}</div>{children}</CardContent></Card>;
}
function Stat({ label, value }: { label: string; value: ReactNode }) {
  return <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{label}</p><p className="text-xl font-semibold">{value ?? '—'}</p></CardContent></Card>;
}
function Meter({ pct }: { pct: number }) {
  return <div className="h-2 w-full rounded bg-muted"><div className={`h-2 rounded ${pct > 90 ? 'bg-destructive' : 'bg-primary'}`} style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} /></div>;
}
function Bars({ data }: { data?: Record<string, number> }) {
  const rows = Object.entries(data ?? {});
  const max = Math.max(1, ...rows.map((r) => r[1]));
  return <div className="space-y-1">{rows.map(([k, v]) => <div key={k} className="flex items-center gap-2 text-sm"><span className="w-40 truncate text-muted-foreground">{k}</span><div className="h-3 rounded bg-primary/70" style={{ width: `${Math.max(2, (100 * v) / max)}%` }} /><span>{v}</span></div>)}</div>;
}
function Chips({ chips }: { chips?: Any[] }) {
  const tone: Record<string, string> = { ok: 'bg-emerald-100 text-emerald-800', warn: 'bg-amber-100 text-amber-800', danger: 'bg-red-100 text-red-800', info: 'bg-muted' };
  return <span className="flex flex-wrap gap-1">{(chips ?? []).map((c: Any, i: number) => <span key={i} className={`rounded px-1.5 py-0.5 text-xs ${tone[c.tone] ?? tone.info}`}>{c.label}</span>)}</span>;
}

// ---- scholars ---------------------------------------------------------------------------------------------------------------
export function PhdScholarsPage({ portal = false }: { portal?: boolean }) {
  useTitle(portal ? 'My scholars' : 'PhD scholars');
  const [f, setF] = useState<Any>({ status: '', q: '' });
  const [scope, setScope] = useState<string | undefined>(portal ? 'own' : undefined);
  const res = useQ(['scholars', f, scope], () => pa.scholars({ status: f.status || undefined, q: f.q || undefined, scope, per_page: 200 }));
  const rows = list(res.data);
  const base = portal ? '/faculty/scholars' : '/admin/phd/scholars';
  return (
    <div className="space-y-4">
      <PageHeader title={portal ? 'My research scholars' : 'Research scholars'} description="Guide / co-guide / DC ownership, department and all views; duration chips against the maximum duration." actions={<ScopeTabs visibility={(res.data as Any)?.meta?.visibility} value={scope} onChange={setScope} />} />
      {!portal && <CreateScholar />}
      <Section title={`Scholars (${(res.data as Any)?.meta?.pagination?.total ?? rows.length})`}>
        <div className="flex flex-wrap gap-2">
          <select className={sel} value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="">All statuses</option>{STATUSES.map((s) => <option key={s}>{s}</option>)}</select>
          <Input className="w-64" placeholder="Name, reg. no. or area" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} />
        </div>
        <SimpleTable head={['Scholar', 'Reg. no.', 'Guide', 'Mode', 'Fellowship', 'Status', 'Duration']} rows={rows.map((s: Any) => [<Link key="n" className="text-primary underline" to={`${base}/${s.id}`}>{s.name}</Link>, s.registration_number, s.guide_name, s.mode, s.fellowship_type, <StatusBadge key="s" status={s.status} />, <Chips key="c" chips={s.chips} />])} />
      </Section>
    </div>
  );
}

function CreateScholar() {
  const [f, setF] = useState<Any>({ enrollment_id: '', guide_staff_id: '', mode: 'full_time', fellowship_type: 'none', research_area: '' });
  const run = useRun();
  const save = () => run.mutate(() => pa.createScholar({ ...f, research_area: f.research_area || undefined }), { onSuccess: () => toast.success('Scholar created (registration letter issued)'), onError: fail });
  return (
    <Section title="New scholar (load check → 409 GUIDE_LOAD_EXCEEDED)">
      <div className="flex flex-wrap gap-2">
        <Input className="w-72" placeholder="PhD enrolment id" value={f.enrollment_id} onChange={(e) => setF({ ...f, enrollment_id: e.target.value })} />
        <Input className="w-72" placeholder="Guide staff id" value={f.guide_staff_id} onChange={(e) => setF({ ...f, guide_staff_id: e.target.value })} />
        <select className={sel} value={f.mode} onChange={(e) => setF({ ...f, mode: e.target.value })}><option>full_time</option><option>part_time</option></select>
        <select className={sel} value={f.fellowship_type} onChange={(e) => setF({ ...f, fellowship_type: e.target.value })}>{['none', 'jrf', 'srf', 'institution', 'project'].map((x) => <option key={x}>{x}</option>)}</select>
        <Input className="w-72" placeholder="Research area" value={f.research_area} onChange={(e) => setF({ ...f, research_area: e.target.value })} />
        <Button size="sm" disabled={!f.enrollment_id || !f.guide_staff_id} onClick={save}>Create</Button>
      </div>
    </Section>
  );
}

const TABS = ['overview', 'coursework', 'dc', 'progress', 'fellowship', 'requests', 'thesis', 'examiners', 'viva', 'award'] as const;

export function PhdScholarPage() {
  const { id = '' } = useParams();
  const res = useQ(['scholar', id], () => pa.scholar(id));
  const s: Any = (res.data as Any)?.data;
  const [tab, setTab] = useState<(typeof TABS)[number]>('overview');
  useTitle(s?.name ?? 'Scholar');
  if (!s) return <p className="p-4 text-sm text-muted-foreground">{res.isError ? getApiError(res.error) : 'Loading…'}</p>;
  return (
    <div className="space-y-4">
      <PageHeader title={s.name ?? 'Scholar'} description={`${s.registration_number ?? ''} · ${s.research_area ?? ''} · guide ${s.guide_name ?? '—'}`} actions={<Chips chips={s.chips} />} />
      <div className="flex flex-wrap gap-1">{TABS.map((t) => <Button key={t} size="sm" variant={t === tab ? 'default' : 'outline'} onClick={() => setTab(t)}>{t}</Button>)}</div>
      {tab === 'overview' && <Overview s={s} />}
      {tab === 'coursework' && <CourseworkTab id={id} />}
      {tab === 'dc' && <DcTab id={id} />}
      {tab === 'progress' && <ProgressTab id={id} />}
      {tab === 'fellowship' && <FellowshipTab id={id} />}
      {tab === 'requests' && <RequestsTab id={id} />}
      {tab === 'thesis' && <ThesisTab id={id} />}
      {tab === 'examiners' && <ExaminersTab thesisId={s.thesis?.id} />}
      {tab === 'viva' && <VivaTab thesisId={s.thesis?.id} />}
      {tab === 'award' && <AwardTab thesisId={s.thesis?.id} />}
    </div>
  );
}

function Overview({ s }: { s: Any }) {
  const run = useRun();
  const [reason, setReason] = useState('voluntary');
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Section title="Record">
        <SimpleTable head={['Field', 'Value']} rows={[['Status', <StatusBadge key="s" status={s.status} />], ['Mode', s.mode], ['Fellowship', s.fellowship_type], ['Registration', day(s.registration_date)], ['Max duration', day(s.max_duration_end)], ['Coursework', s.coursework_status], ['Co-guide', s.co_guide_name ?? s.external_co_guide?.name ?? '—'], ['Relation', (s.relation ?? []).join(', ')]]} />
        <div className="flex gap-2">
          <select className={sel} value={reason} onChange={(e) => setReason(e.target.value)}>{['voluntary', 'unsatisfactory_progress', 'max_duration_exceeded', 'other'].map((x) => <option key={x}>{x}</option>)}</select>
          <Button size="sm" variant="outline" onClick={() => window.confirm('Discontinue this scholar?') && run.mutate(() => pa.discontinue(s.id, { reason }), { onSuccess: () => toast.success('Discontinued'), onError: fail })}>Discontinue</Button>
        </div>
      </Section>
      <Section title="Timeline"><SimpleTable head={['When', 'Action', 'Detail']} rows={(s.timeline ?? []).slice().reverse().map((t: Any) => [day(t.at), t.action, JSON.stringify(t.detail)])} /></Section>
      <Section title="Publications (Phase 30 — tagged to the scholar)"><SimpleTable head={['Title', 'Venue', 'Year', 'Verified']} rows={(s.publications ?? []).map((p: Any) => [p.title, p.venue, p.year, p.is_verified ? 'yes' : 'no'])} /></Section>
      <Section title="Ethics approval">{s.ethics_approval ? <p className="text-sm">{s.ethics_approval.project_title} · {s.ethics_approval.decision ?? 'under review'} · {s.ethics_approval.approval_no ?? ''}</p> : <p className="text-sm text-muted-foreground">None linked</p>}</Section>
    </div>
  );
}

function CourseworkTab({ id }: { id: string }) {
  const res = useQ(['cw', id], () => pa.coursework(id));
  const c: Any = (res.data as Any)?.data;
  const [ids, setIds] = useState('');
  const run = useRun();
  if (!c) return null;
  return (
    <Section title={`Coursework · ${c.status}`}>
      <p className="text-sm">{c.credits_earned} / {c.credits_required} credits · methodology {c.methodology_done ? 'done' : 'pending'} · deadline {day(c.deadline)}</p>
      <SimpleTable head={['Code', 'Title', 'Credits', 'Methodology', 'Result']} rows={(c.courses ?? []).map((x: Any) => [x.code, x.title, x.credits, x.is_methodology ? 'yes' : '', x.result ?? '—'])} />
      <div className="flex flex-wrap gap-2">
        <Input className="w-[32rem]" placeholder="Course ids (comma separated; research methodology mandatory)" value={ids} onChange={(e) => setIds(e.target.value)} />
        <Button size="sm" onClick={() => run.mutate(() => pa.planCoursework(id, { course_ids: ids.split(',').map((x) => x.trim()).filter(Boolean) }), { onSuccess: () => toast.success('Planned'), onError: fail })}>Plan</Button>
        <Button size="sm" variant="outline" onClick={() => run.mutate(() => pa.completeCoursework(id), { onSuccess: () => toast.success('Registered'), onError: fail })}>Complete → registered</Button>
        <Button size="sm" variant="outline" onClick={() => { const r = window.prompt('Exemption reason (M.Phil / prior coursework)'); if (r) run.mutate(() => pa.exemption(id, { reason: r }), { onSuccess: () => toast.success('Exemption requested'), onError: fail }); }}>Request exemption</Button>
      </div>
    </Section>
  );
}

function DcTab({ id }: { id: string }) {
  const dc = useQ(['dc', id], () => pa.dc(id));
  const mt = useQ(['meetings', id], () => pa.meetings(id));
  const run = useRun();
  const [members, setMembers] = useState('');
  const [ext, setExt] = useState('');
  const [m, setM] = useState<Any>({ meeting_no: 1, held_on: new Date().toISOString().slice(0, 10), agenda: '' });
  const [minutes, setMinutes] = useState<Record<string, string>>({});
  const d: Any = (dc.data as Any)?.data;
  const body = () => ({
    members: [
      ...members.split(',').map((x) => x.trim()).filter(Boolean).map((sid) => ({ staff_id: sid, role: 'member' })),
      ...(ext ? [{ external: { name: ext }, role: 'external' }] : []),
    ],
  });
  return (
    <div className="space-y-4">
      <Section title="Doctoral committee">
        {d ? <SimpleTable head={['Member', 'Role']} rows={d.members.map((x: Any) => [x.name ?? x.staff_id, x.role])} /> : <p className="text-sm text-muted-foreground">Not constituted</p>}
        <div className="flex flex-wrap gap-2">
          <Input className="w-96" placeholder="Internal member staff ids (comma separated)" value={members} onChange={(e) => setMembers(e.target.value)} />
          <Input className="w-64" placeholder="External member name" value={ext} onChange={(e) => setExt(e.target.value)} />
          <Button size="sm" onClick={() => run.mutate(() => (d ? pa.reconstitute(id, body()) : pa.constitute(id, body())), { onSuccess: () => toast.success('Saved'), onError: fail })}>{d ? 'Reconstitute' : 'Constitute'}</Button>
        </div>
      </Section>
      <Section title="Meetings">
        <div className="flex flex-wrap gap-2">
          <Input className="w-20" type="number" value={m.meeting_no} onChange={(e) => setM({ ...m, meeting_no: Number(e.target.value) })} />
          <Input className="w-40" type="date" value={m.held_on} onChange={(e) => setM({ ...m, held_on: e.target.value })} />
          <Input className="w-96" placeholder="Agenda" value={m.agenda} onChange={(e) => setM({ ...m, agenda: e.target.value })} />
          <Button size="sm" onClick={() => run.mutate(() => pa.schedule(id, { ...m, agenda: m.agenda || undefined }), { onSuccess: () => toast.success('Scheduled'), onError: fail })}>Schedule</Button>
        </div>
        <SimpleTable head={['No.', 'Held on', 'Status', 'Recommendations', 'Minutes', '']} rows={list(mt.data).map((x: Any) => [x.meeting_no, day(x.held_on), <StatusBadge key="s" status={x.status} />, (x.recommendations ?? []).map((r: Any) => r.text).join('; '), x.status === 'scheduled' ? <Input key="mi" className="w-64" value={minutes[x.id] ?? ''} onChange={(e) => setMinutes({ ...minutes, [x.id]: e.target.value })} /> : (x.minutes ?? '').slice(0, 80), x.status === 'scheduled' ? <Button key="b" size="sm" onClick={() => run.mutate(() => pa.minutes(x.id, { minutes: minutes[x.id] || 'Minutes recorded', recommendations: [] }), { onError: fail })}>Record</Button> : x.status === 'held' ? <Button key="a" size="sm" onClick={() => run.mutate(() => pa.approveMeeting(x.id), { onError: fail })}>Approve</Button> : null])} />
      </Section>
    </div>
  );
}

function ProgressTab({ id, portal = false }: { id: string; portal?: boolean }) {
  const rep = useQ(['reports', id], () => pa.reports(id));
  const per = useQ(['periods', id], () => pa.periods(id));
  const run = useRun();
  const [f, setF] = useState<Any>({ period_label: '', report_url: '', summary: '' });
  return (
    <div className="space-y-4">
      <Section title="Periods"><SimpleTable head={['Period', 'Due', 'Status']} rows={list(per.data).map((p: Any) => [p.period_label, day(p.due_on), <StatusBadge key="s" status={p.status} />])} /></Section>
      {portal && (
        <Section title="Submit a report">
          <div className="flex flex-wrap gap-2">
            <Input className="w-28" placeholder="2026-H1" value={f.period_label} onChange={(e) => setF({ ...f, period_label: e.target.value })} />
            <Input className="w-80" placeholder="Report file URL" value={f.report_url} onChange={(e) => setF({ ...f, report_url: e.target.value })} />
          </div>
          <textarea className={area} placeholder="Summary" value={f.summary} onChange={(e) => setF({ ...f, summary: e.target.value })} />
          <Button size="sm" onClick={() => run.mutate(() => pa.submitReport(id, f), { onSuccess: () => toast.success('Submitted'), onError: fail })}>Submit</Button>
        </Section>
      )}
      <Section title="Reports">
        <SimpleTable head={['Period', 'Status', 'Guide remarks', 'DC rating', '']} rows={list(rep.data).map((r: Any) => [r.period_label, <StatusBadge key="s" status={r.status} />, r.guide_remarks ?? '—', r.dc_rating ?? '—', portal ? null : r.status === 'submitted' ? <Button key="g" size="sm" onClick={() => { const t = window.prompt('Guide remarks'); if (t) run.mutate(() => pa.guideReview(r.id, { remarks: t }), { onError: fail }); }}>Review</Button> : r.status === 'guide_reviewed' ? <span key="d" className="flex gap-1"><Button size="sm" onClick={() => run.mutate(() => pa.dcReview(r.id, { rating: 'satisfactory' }), { onError: fail })}>Satisfactory</Button><Button size="sm" variant="outline" onClick={() => run.mutate(() => pa.dcReview(r.id, { rating: 'unsatisfactory' }), { onError: fail })}>Unsatisfactory</Button></span> : null])} />
      </Section>
    </div>
  );
}

function FellowshipTab({ id }: { id: string }) {
  const res = useQ(['fellowships', id], () => pa.fellowships(id));
  const st = useQ(['statement', id], () => pa.statement(id));
  const run = useRun();
  const [f, setF] = useState<Any>({ fellowship_type: 'jrf', from_on: new Date().toISOString().slice(0, 10), hra_applicable: true, funding_source: 'UGC' });
  return (
    <div className="space-y-4">
      <Section title="Fellowships">
        <SimpleTable head={['Type', 'Monthly', 'HRA', 'From', 'To', 'Contingency (used)', 'Source', 'Status']} rows={list(res.data).map((x: Any) => [x.fellowship_type, inr(x.monthly_paise), inr(x.hra_paise), day(x.from_on), day(x.to_on), `${inr(x.contingency_paise)} (${inr(x.contingency_used_paise)})`, x.funding_source, <StatusBadge key="s" status={x.status} />])} />
        <div className="flex flex-wrap gap-2">
          <select className={sel} value={f.fellowship_type} onChange={(e) => setF({ ...f, fellowship_type: e.target.value })}>{['jrf', 'srf', 'institution', 'project'].map((x) => <option key={x}>{x}</option>)}</select>
          <Input className="w-40" type="date" value={f.from_on} onChange={(e) => setF({ ...f, from_on: e.target.value })} />
          <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={f.hra_applicable} onChange={(e) => setF({ ...f, hra_applicable: e.target.checked })} />HRA</label>
          <Input className="w-40" placeholder="Funding source" value={f.funding_source} onChange={(e) => setF({ ...f, funding_source: e.target.value })} />
          <Button size="sm" onClick={() => run.mutate(() => pa.createFellowship(id, f), { onSuccess: () => toast.success('Created'), onError: fail })}>Create</Button>
        </div>
      </Section>
      <Section title="Agency statement"><SimpleTable head={['Month', 'Kind', 'Amount', 'Status']} rows={list(st.data).map((d: Any) => [d.month, d.kind, inr(d.amount_paise), d.status])} /></Section>
    </div>
  );
}

const REQ_TYPES = ['extension', 'change_of_guide', 'mode_change', 'leave', 'coursework_exemption'];

function RequestsTab({ id, portal = false }: { id: string; portal?: boolean }) {
  const res = useQ(['requests', id], () => pa.scholarRequests(id));
  const run = useRun();
  const [f, setF] = useState<Any>({ request_type: 'extension', months: 6, new_guide_staff_id: '', new_mode: 'part_time', leave_type: 'medical', from_on: '', to_on: '', reason: '' });
  const raise = () => {
    const d: Any = { reason: f.reason };
    if (f.request_type === 'extension') d.months = Number(f.months);
    if (f.request_type === 'change_of_guide') d.new_guide_staff_id = f.new_guide_staff_id;
    if (f.request_type === 'mode_change') d.new_mode = f.new_mode;
    if (f.request_type === 'leave') Object.assign(d, { leave_type: f.leave_type, from_on: f.from_on, to_on: f.to_on });
    run.mutate(() => pa.raise(id, { request_type: f.request_type, details: d }), { onSuccess: () => toast.success('Requested'), onError: fail });
  };
  return (
    <div className="space-y-4">
      <Section title="Raise a request (phd.request: guide → research cell → dean)">
        <div className="flex flex-wrap gap-2">
          <select className={sel} value={f.request_type} onChange={(e) => setF({ ...f, request_type: e.target.value })}>{REQ_TYPES.map((x) => <option key={x}>{x}</option>)}</select>
          {f.request_type === 'extension' && <Input className="w-24" type="number" value={f.months} onChange={(e) => setF({ ...f, months: e.target.value })} />}
          {f.request_type === 'change_of_guide' && <Input className="w-72" placeholder="New guide staff id" value={f.new_guide_staff_id} onChange={(e) => setF({ ...f, new_guide_staff_id: e.target.value })} />}
          {f.request_type === 'mode_change' && <select className={sel} value={f.new_mode} onChange={(e) => setF({ ...f, new_mode: e.target.value })}><option>part_time</option><option>full_time</option></select>}
          {f.request_type === 'leave' && <><select className={sel} value={f.leave_type} onChange={(e) => setF({ ...f, leave_type: e.target.value })}>{['maternity', 'medical', 'other'].map((x) => <option key={x}>{x}</option>)}</select><Input className="w-40" type="date" value={f.from_on} onChange={(e) => setF({ ...f, from_on: e.target.value })} /><Input className="w-40" type="date" value={f.to_on} onChange={(e) => setF({ ...f, to_on: e.target.value })} /></>}
          <Input className="w-80" placeholder="Reason" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} />
          <Button size="sm" disabled={f.reason.length < 3} onClick={raise}>Raise</Button>
        </div>
      </Section>
      <RequestTable rows={list(res.data)} portal={portal} />
    </div>
  );
}

function RequestTable({ rows, portal = false }: { rows: Any[]; portal?: boolean }) {
  const run = useRun();
  return (
    <Section title="Requests">
      <SimpleTable head={['Scholar', 'Type', 'Details', 'Status', 'Workflow', 'Implications', '']} rows={rows.map((r: Any) => [r.scholar_name, r.request_type, JSON.stringify(r.details).slice(0, 80), <StatusBadge key="s" status={r.status} />, r.workflow_status ? `${r.workflow_status} · step ${r.current_step ?? '—'}` : '—', (r.implications ?? []).join('; '), portal ? null : <span key="a" className="flex gap-1">{r.request_type === 'change_of_guide' && !r.details?.noc && <Button size="sm" variant="outline" onClick={() => run.mutate(() => pa.noc(r.id, { granted: true }), { onError: fail })}>NOC</Button>}{r.request_type === 'cancellation_review' && ['requested', 'in_review'].includes(r.status) ? <><Button size="sm" variant="outline" onClick={() => run.mutate(() => pa.cancellationDecision(r.id, { decision: 'warning' }), { onError: fail })}>Warning</Button><Button size="sm" onClick={() => window.confirm('Discontinue the scholar?') && run.mutate(() => pa.cancellationDecision(r.id, { decision: 'discontinue' }), { onError: fail })}>Discontinue</Button></> : ['requested', 'in_review'].includes(r.status) && <><Button size="sm" onClick={() => run.mutate(() => pa.decide(r.id, { approve: true }), { onError: fail })}>Approve</Button><Button size="sm" variant="outline" onClick={() => run.mutate(() => pa.decide(r.id, { approve: false }), { onError: fail })}>Reject</Button></>}</span>])} />
    </Section>
  );
}

function ThesisTab({ id, portal = false }: { id: string; portal?: boolean }) {
  const res = useQ(['theses', id], () => pa.theses(id));
  const run = useRun();
  const [f, setF] = useState<Any>({ stage: 'synopsis', title: '', file_url: '', ai_declaration: false, ai_generated_pct: '' });
  const submit = () => run.mutate(() => pa.submitThesis(id, { ...f, ai_generated_pct: f.ai_generated_pct === '' ? undefined : Number(f.ai_generated_pct) }), { onSuccess: () => toast.success('Submitted — the similarity check follows'), onError: fail });
  return (
    <div className="space-y-4">
      {portal && (
        <Section title="Submit (AI-content declaration mandatory)">
          <div className="flex flex-wrap gap-2">
            <select className={sel} value={f.stage} onChange={(e) => setF({ ...f, stage: e.target.value })}>{['pre_synopsis', 'synopsis', 'thesis', 'revised_thesis'].map((x) => <option key={x}>{x}</option>)}</select>
            <Input className="w-96" placeholder="Title" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
            <Input className="w-80" placeholder="File URL" value={f.file_url} onChange={(e) => setF({ ...f, file_url: e.target.value })} />
            <Input className="w-28" placeholder="AI-generated %" value={f.ai_generated_pct} onChange={(e) => setF({ ...f, ai_generated_pct: e.target.value })} />
            <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={f.ai_declaration} onChange={(e) => setF({ ...f, ai_declaration: e.target.checked })} />I declare the AI-generated content</label>
            <Button size="sm" disabled={f.title.length < 3 || !f.file_url} onClick={submit}>Submit</Button>
          </div>
        </Section>
      )}
      <Section title="Submissions">
        <SimpleTable head={['Stage', 'Title', 'Submitted', 'Similarity', 'AI %', 'Status', 'Flags', '']} rows={list(res.data).map((t: Any) => [t.stage, t.title, day(t.submitted_at), t.similarity_pct != null ? `${t.similarity_pct} % / ${t.similarity_limit_pct} %` : '—', t.ai_generated_pct ?? '—', <StatusBadge key="s" status={t.status} />, (t.flags ?? []).join(', '), <span key="a" className="flex gap-1">{t.certificate_document_id && <a className="text-primary underline" href={pa.certificateUrl(t.id)} target="_blank" rel="noreferrer">Certificate</a>}{!portal && t.status === 'submitted' && <Button size="sm" variant="outline" onClick={() => run.mutate(() => pa.check(t.id), { onError: fail })}>Check</Button>}{!portal && t.status === 'plagiarism_checked' && <Button size="sm" onClick={() => run.mutate(() => pa.dcApproval(t.id), { onSuccess: () => toast.success('DC approval started'), onError: fail })}>DC approval</Button>}</span>])} />
      </Section>
    </div>
  );
}

function ExaminersTab({ thesisId }: { thesisId?: string }) {
  const res = useQ(['panel', thesisId], () => pa.panel(thesisId as string), !!thesisId);
  const rec = useQ(['recs', thesisId], () => pa.recommendations(thesisId as string), !!thesisId);
  const run = useRun();
  const [rows, setRows] = useState<Any[]>([{ name: '', affiliation: '', email: '', state: '', country: 'India', is_external: true, coi_declaration: true }]);
  if (!thesisId) return <p className="text-sm text-muted-foreground">No thesis yet</p>;
  const r: Any = (rec.data as Any)?.data;
  return (
    <div className="space-y-4">
      <Section title={`Panel (sealed for the scholar) · ${r?.consolidated ?? '—'} (${r?.received ?? 0}/${r?.total ?? 0})`}>
        <SimpleTable head={['Examiner', 'Affiliation', 'State / country', 'Status', 'Due', 'Recommendation', '']} rows={list(res.data).map((x: Any) => [x.hidden ? 'hidden' : x.name, x.affiliation, `${x.state ?? ''} ${x.country ?? ''}`, <StatusBadge key="s" status={x.status} />, day(x.due_on), x.recommendation ?? '—', <span key="a" className="flex gap-1">{x.status === 'approved' && <Button size="sm" onClick={() => run.mutate(() => pa.invite(x.id), { onError: fail })}>Invite</Button>}{x.status === 'accepted' && <Button size="sm" variant="outline" onClick={() => run.mutate(() => pa.dispatch(x.id), { onError: fail })}>Dispatch</Button>}{x.status === 'report_received' && !x.remuneration_paise && <Button size="sm" variant="outline" onClick={() => run.mutate(() => pa.remuneration(x.id, { amount_paise: 500000 }), { onError: fail })}>Remuneration</Button>}</span>])} />
      </Section>
      <Section title="Propose a panel (≥ 2 external, ≥ 1 outside the state / country, no co-authors)">
        {rows.map((e, i) => (
          <div key={i} className="flex flex-wrap gap-2">
            {(['name', 'affiliation', 'email', 'state', 'country'] as const).map((k) => <Input key={k} className="w-44" placeholder={k} value={e[k]} onChange={(ev) => setRows(rows.map((x, j) => (j === i ? { ...x, [k]: ev.target.value } : x)))} />)}
          </div>
        ))}
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => setRows([...rows, { name: '', affiliation: '', email: '', state: '', country: 'India', is_external: true, coi_declaration: true }])}>Add examiner</Button>
          <Button size="sm" onClick={() => run.mutate(() => pa.propose(thesisId, { examiners: rows.map((e) => ({ ...e, state: e.state || undefined })) }), { onSuccess: () => toast.success('Proposed — phd.examiner_panel started'), onError: fail })}>Propose</Button>
        </div>
      </Section>
    </div>
  );
}

function VivaTab({ thesisId }: { thesisId?: string }) {
  const res = useQ(['viva', thesisId], () => pa.viva(thesisId as string), !!thesisId);
  const run = useRun();
  const [f, setF] = useState<Any>({ scheduled_at: '', venue_or_link: '', examiner: '' });
  if (!thesisId) return <p className="text-sm text-muted-foreground">No thesis yet</p>;
  const v: Any = (res.data as Any)?.data;
  return (
    <Section title="Viva-voce (open defence)">
      {v ? <SimpleTable head={['When', 'Venue', 'Panel', 'Result']} rows={[[day(v.scheduled_at), v.venue_or_link, (v.panel ?? []).map((p: Any) => `${p.name} (${p.role})`).join(', '), v.result ?? '—']]} /> : <p className="text-sm text-muted-foreground">Not scheduled</p>}
      <div className="flex flex-wrap gap-2">
        <Input className="w-56" type="datetime-local" value={f.scheduled_at} onChange={(e) => setF({ ...f, scheduled_at: e.target.value })} />
        <Input className="w-64" placeholder="Venue / link" value={f.venue_or_link} onChange={(e) => setF({ ...f, venue_or_link: e.target.value })} />
        <Input className="w-56" placeholder="External examiner name" value={f.examiner} onChange={(e) => setF({ ...f, examiner: e.target.value })} />
        <Button size="sm" onClick={() => run.mutate(() => pa.scheduleViva(thesisId, { scheduled_at: new Date(f.scheduled_at).toISOString(), venue_or_link: f.venue_or_link, panel: [{ name: 'Guide', role: 'guide' }, { name: f.examiner, role: 'external_examiner' }] }), { onSuccess: () => toast.success('Scheduled'), onError: fail })}>Schedule</Button>
        {v && !v.result && ['recommended', 're_viva', 'not_recommended'].map((r) => <Button key={r} size="sm" variant="outline" onClick={() => run.mutate(() => pa.vivaResult(v.id, { result: r, report_url: 'mock://viva-report.pdf', held_at: new Date().toISOString() }), { onError: fail })}>{r}</Button>)}
      </div>
    </Section>
  );
}

function AwardTab({ thesisId }: { thesisId?: string }) {
  const res = useQ(['award', thesisId], () => pa.award(thesisId as string), !!thesisId);
  const etd = useQ(['etd', thesisId], () => pa.etd(thesisId as string), !!thesisId);
  const run = useRun();
  const [on, setOn] = useState(new Date().toISOString().slice(0, 10));
  const [resolution, setResolution] = useState('');
  if (!thesisId) return <p className="text-sm text-muted-foreground">No thesis yet</p>;
  const a: Any = (res.data as Any)?.data;
  return (
    <div className="space-y-4">
      <Section title={`Award · ${a?.status ?? '—'}`}>
        <p className="text-sm">Date of award {day(a?.date_of_award)} · Phase 18 award {a?.degree_awarded_id ?? '—'} · ETD due {day(a?.etd_due_on)}</p>
        <div className="flex flex-wrap gap-2">
          <Input className="w-40" type="date" value={on} onChange={(e) => setOn(e.target.value)} />
          <Input className="w-72" placeholder="Academic council resolution id (when governance.minutes)" value={resolution} onChange={(e) => setResolution(e.target.value)} />
          <Button size="sm" onClick={() => run.mutate(() => pa.requestAward(thesisId, { date_of_award: on, resolution_id: resolution || undefined }), { onSuccess: () => toast.success('phd.award started'), onError: fail })}>Request award</Button>
        </div>
      </Section>
      <Section title="ETD (Shodhganga / institutional)">
        <SimpleTable head={['Repository', 'Status', 'Handle', 'Embargo', '']} rows={list(etd.data).map((u: Any) => [u.repository, <StatusBadge key="s" status={u.status} />, u.handle ?? '—', u.embargo?.status ?? '—', u.status === 'failed' ? <Button key="r" size="sm" onClick={() => run.mutate(() => pa.retryEtd(u.id), { onError: fail })}>Retry</Button> : null])} />
        <Button size="sm" onClick={() => run.mutate(() => pa.upload(thesisId), { onSuccess: () => toast.success('Uploaded'), onError: fail })}>Upload</Button>
      </Section>
    </div>
  );
}

// ---- research cell desks ------------------------------------------------------------------------------------------------------
export function PhdGuidesPage() {
  useTitle('Guide load');
  const res = useQ(['load'], () => pa.guideLoad());
  return (
    <div className="space-y-4">
      <PageHeader title="Guide load" description="Current scholars against the cadre limit (faculty_profiles.max_scholars overrides phd.rules)." />
      <Section title="Guides"><SimpleTable head={['Guide', 'Cadre', 'Current / max', 'Load', 'Available']} rows={list(res.data).map((g: Any) => [g.name, g.cadre, `${g.current} / ${g.max}`, <Meter key="m" pct={(100 * g.current) / Math.max(1, g.max)} />, g.available])} /></Section>
    </div>
  );
}

export function PhdFellowshipsPage() {
  useTitle('Fellowships');
  const [month, setMonth] = useState(thisMonth());
  const [status, setStatus] = useState('');
  const [picked, setPicked] = useState<string[]>([]);
  const res = useQ(['disb', month, status], () => pa.disbursements({ month, status: status || undefined }));
  const run = useRun();
  const rows = list(res.data);
  return (
    <div className="space-y-4">
      <PageHeader title="Fellowships" description="Monthly run → approval → payment batch (payout / payroll); holds release as arrears on the next run." />
      <Section title="Monthly run" action={<Button size="sm" onClick={() => run.mutate(() => pa.run(month), { onSuccess: (r: Any) => toast.success(`${r.data.created} pending · ${r.data.held} held`), onError: fail })}>Run {month.slice(0, 7)}</Button>}>
        <div className="flex flex-wrap gap-2">
          <Input className="w-40" type="date" value={month} onChange={(e) => setMonth(e.target.value)} />
          <select className={sel} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All</option>{['pending', 'approved', 'paid', 'held'].map((x) => <option key={x}>{x}</option>)}</select>
          <Button size="sm" variant="outline" disabled={!picked.length} onClick={() => { const ref = window.prompt('Payment batch reference'); if (ref) run.mutate(() => pa.pay({ disbursement_ids: picked, reference: ref }), { onSuccess: () => { toast.success('Payment requested'); setPicked([]); }, onError: fail }); }}>Pay ({picked.length})</Button>
        </div>
        <SimpleTable head={['', 'Scholar', 'Type', 'Month', 'Kind', 'Amount', 'Status', 'Hold reason', '']} rows={rows.map((d: Any) => [<input key="c" type="checkbox" checked={picked.includes(d.id)} onChange={() => setPicked((p) => (p.includes(d.id) ? p.filter((x) => x !== d.id) : [...p, d.id]))} />, d.scholar_name, d.fellowship_type, d.month, d.kind, inr(d.amount_paise), <StatusBadge key="s" status={d.status} />, d.hold_reason ?? '', <span key="a" className="flex gap-1">{d.status === 'pending' && <Button size="sm" onClick={() => run.mutate(() => pa.approve(d.id), { onError: fail })}>Approve</Button>}{['pending', 'approved'].includes(d.status) && <Button size="sm" variant="outline" onClick={() => { const r = window.prompt('Hold reason'); if (r) run.mutate(() => pa.hold(d.id, r), { onError: fail }); }}>Hold</Button>}{d.status === 'held' && <Button size="sm" variant="outline" onClick={() => run.mutate(() => pa.release(d.id), { onError: fail })}>Release</Button>}</span>])} />
      </Section>
    </div>
  );
}

export function PhdRequestsPage() {
  useTitle('Scholar requests');
  const [type, setType] = useState('');
  const res = useQ(['req', type], () => pa.requests({ type: type || undefined }));
  return (
    <div className="space-y-4">
      <PageHeader title="Scholar requests" description="Extensions, guide changes (old guide NOC), mode changes, leave, exemptions and cancellation reviews." actions={<select className={sel} value={type} onChange={(e) => setType(e.target.value)}><option value="">All types</option>{[...REQ_TYPES, 'cancellation_review'].map((x) => <option key={x}>{x}</option>)}</select>} />
      <RequestTable rows={list(res.data)} />
    </div>
  );
}

export function PhdThesisQueuePage() {
  useTitle('Thesis queue');
  const [status, setStatus] = useState('submitted');
  const res = useQ(['tq', status], () => pa.thesisQueue({ status: status || undefined }));
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Plagiarism & DC approvals" description="Similarity ≤ phd.rules.similarity_max_pct passes; DC approval runs phd.thesis_dc_approval." actions={<select className={sel} value={status} onChange={(e) => setStatus(e.target.value)}>{['submitted', 'plagiarism_checked', 'dc_approved', 'rejected', ''].map((x) => <option key={x} value={x}>{x || 'all'}</option>)}</select>} />
      <Section title="Submissions"><SimpleTable head={['Stage', 'Title', 'Submitted', 'Similarity', 'Status', 'Flags', '']} rows={list(res.data).map((t: Any) => [t.stage, t.title, day(t.submitted_at), t.similarity_pct ?? '—', <StatusBadge key="s" status={t.status} />, (t.flags ?? []).join(', '), t.status === 'submitted' ? <Button key="c" size="sm" onClick={() => run.mutate(() => pa.check(t.id), { onError: fail })}>Check</Button> : t.status === 'plagiarism_checked' ? <Button key="d" size="sm" onClick={() => run.mutate(() => pa.dcApproval(t.id), { onError: fail })}>DC approval</Button> : null])} /></Section>
    </div>
  );
}

export function PhdExaminersPage() {
  useTitle('Examiners');
  const res = useQ(['tracker'], () => pa.tracker());
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Examiner tracker" description="Invitations, acceptances, reports, replacements and remuneration." />
      <Section title="Examiners"><SimpleTable head={['Examiner', 'Affiliation', 'Status', 'Invited', 'Due', 'Report', 'Recommendation', '']} rows={list(res.data).map((x: Any) => [x.name, x.affiliation, <StatusBadge key="s" status={x.status} />, day(x.invited_at), day(x.due_on), day(x.report_received_at), x.recommendation ?? '—', <span key="a" className="flex gap-1">{x.status === 'approved' && <Button size="sm" onClick={() => run.mutate(() => pa.invite(x.id), { onError: fail })}>Invite</Button>}{x.status === 'accepted' && <Button size="sm" variant="outline" onClick={() => { const rec = window.prompt('Recommendation (accept / minor / major / reject)'); if (rec) run.mutate(() => pa.report(x.id, { report_url: 'mock://report.pdf', recommendation: rec }), { onError: fail }); }}>Record report</Button>}{['declined', 'invited'].includes(x.status) && <Button size="sm" variant="outline" onClick={() => { const name = window.prompt('Replacement examiner name'); const email = name && window.prompt('Email'); if (name && email) run.mutate(() => pa.replace(x.id, { replacement: { name, affiliation: 'TBD', email, country: 'India', state: 'Other' } }), { onError: fail }); }}>Replace</Button>}</span>])} /></Section>
    </div>
  );
}

export function PhdVivaPage() {
  useTitle('Viva-voce');
  const res = useQ(['upcoming'], () => pa.upcoming());
  return (
    <div className="space-y-4">
      <PageHeader title="Viva-voce" description="Upcoming open defences (notices are published to the calendar)." />
      <Section title="Upcoming"><SimpleTable head={['Scholar', 'Thesis', 'When', 'Venue / link']} rows={list(res.data).map((v: Any) => [v.scholar_name, v.title, day(v.scheduled_at), v.venue_or_link])} /></Section>
    </div>
  );
}

export function PhdAwardsPage() {
  useTitle('Awards & ETD');
  const [year, setYear] = useState('');
  const res = useQ(['awards', year], () => pa.awards({ year: year || undefined }));
  const etd = useQ(['etdboard'], () => pa.etdStatus());
  return (
    <div className="space-y-4">
      <PageHeader title="Awards & ETD" description="Phase 18 PhD awards, provisional certificates and Shodhganga deposits (30-day deadline)." actions={<Input className="w-24" placeholder="Year" value={year} onChange={(e) => setYear(e.target.value)} />} />
      <Section title="Awards"><SimpleTable head={['Scholar', 'Degree', 'Specialisation', 'Date of award', 'Status', 'ETD due']} rows={list(res.data).map((a: Any) => [a.name, a.degree_name, a.specialization, day(a.date_of_award), a.status, day(a.etd_due_on)])} /></Section>
      <Section title="ETD status"><SimpleTable head={['Scholar', 'Date of award', 'Deposits']} rows={list(etd.data).map((a: Any) => [a.name, day(a.date_of_award), (a.etd ?? []).map((u: Any) => `${u.repository}: ${u.status}${u.handle ? ` (${u.handle})` : ''}`).join(', ') || 'none'])} /></Section>
    </div>
  );
}

export function PhdStatsPage() {
  useTitle('PhD stats');
  const res = useQ(['stats'], () => pa.stats());
  const s: Any = (res.data as Any)?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="PhD stats" description="NIRF GPHD, time to award, guide utilisation, fellowship spend, plagiarism and examiner turnaround." actions={<span className="flex gap-2">{['scholars', 'fellowships', 'awards', 'ugc_return', 'examiners'].map((k) => <a key={k} className="text-sm text-primary underline" href={pa.reportUrl(k)}>{k}.xlsx</a>)}</span>} />
      <div className="grid gap-4 md:grid-cols-4">
        <Stat label="GPHD (this year)" value={s?.gphd} />
        <Stat label="Avg. months to award" value={s?.avg_duration_months} />
        <Stat label="Guide utilisation %" value={s?.guide_utilisation_pct} />
        <Stat label="Fellowship spend" value={inr(s?.fellowship_spend_paise)} />
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Section title="By status"><Bars data={s?.by_status} /></Section>
        <Section title="By department"><Bars data={s?.by_department} /></Section>
        <Section title="Awarded per year"><Bars data={s?.awarded_by_year} /></Section>
        <Section title="Plagiarism"><p className="text-sm">{s?.plagiarism?.checked ?? 0} checked · avg {s?.plagiarism?.avg_pct ?? '—'} % · {s?.plagiarism?.above_limit ?? 0} above the limit · examiner turnaround {s?.examiner_turnaround_days ?? '—'} days</p></Section>
      </div>
    </div>
  );
}

// ---- scholar portal ------------------------------------------------------------------------------------------------------------
function useMe() {
  const res = useQ(['me'], () => pa.me());
  return (res.data as Any)?.data as Any;
}

export function ScholarHomePage() {
  useTitle('My PhD');
  const res = useQ(['dash'], () => pa.dashboard());
  const d: Any = (res.data as Any)?.data;
  if (!d) return <p className="p-4 text-sm text-muted-foreground">{res.isError ? getApiError(res.error) : 'Loading…'}</p>;
  return (
    <div className="space-y-4">
      <PageHeader title="My PhD" description={`${d.scholar.research_area ?? ''} · guide ${d.scholar.guide_name ?? '—'}`} actions={<StatusBadge status={d.scholar.status} />} />
      <div className="grid gap-4 md:grid-cols-4">
        <Stat label="Duration used" value={d.duration_pct != null ? `${d.duration_pct} %` : '—'} />
        <Stat label="Coursework" value={d.coursework ? `${d.coursework.credits_earned}/${d.coursework.credits_required}` : '—'} />
        <Stat label="Open requests" value={d.open_requests} />
        <Stat label="Thesis" value={d.thesis ? `${d.thesis.stage} · ${d.thesis.status}` : '—'} />
      </div>
      {d.duration_pct != null && <Meter pct={d.duration_pct} />}
      <Section title="Deadlines"><SimpleTable head={['What', 'Due', 'Kind']} rows={(d.deadlines ?? []).map((x: Any) => [x.label, day(x.due_on), x.kind])} /></Section>
      <Section title="DC recommendations"><SimpleTable head={['Meeting', 'Recommendation', 'Due']} rows={(d.open_recommendations ?? []).map((r: Any) => [r.meeting_no, r.text, day(r.due_on)])} /></Section>
      {d.viva && <Section title="Viva-voce"><p className="text-sm">{day(d.viva.scheduled_at)} · {d.viva.venue_or_link} · {d.viva.result ?? 'scheduled'}</p></Section>}
    </div>
  );
}

export function ScholarProgressPage() {
  useTitle('Progress reports');
  const me = useMe();
  return me ? <div className="space-y-4"><PageHeader title="Progress reports" description="Half-yearly reports → guide review → DC rating." /><ProgressTab id={me.id} portal /><DcTab id={me.id} /></div> : null;
}

export function ScholarThesisPage() {
  useTitle('Thesis');
  const me = useMe();
  return me ? <div className="space-y-4"><PageHeader title="Thesis" description="Submissions, similarity results and certificates; examiner identities stay sealed until the viva." /><ThesisTab id={me.id} portal />{me.thesis?.id && <VivaTab thesisId={me.thesis.id} />}</div> : null;
}

export function ScholarFellowshipPage() {
  useTitle('Fellowship');
  const res = useQ(['mydisb'], () => pa.myDisbursements());
  const run = useRun();
  const rows = list(res.data);
  return (
    <div className="space-y-4">
      <PageHeader title="Fellowship" description="Monthly disbursements, holds and contingency claims." />
      <Section title="Disbursements" action={rows[0] && <Button size="sm" variant="outline" onClick={() => { const amt = Number(window.prompt('Contingency claim amount (₹)')); const desc = amt && window.prompt('Description'); if (amt && desc) run.mutate(() => pa.contingency(rows[0].id, { amount_paise: Math.round(amt * 100), description: desc, bills: [] }), { onSuccess: () => toast.success('Claimed'), onError: fail }); }}>Contingency claim</Button>}>
        <SimpleTable head={['Month', 'Kind', 'Amount', 'Status', 'Hold reason']} rows={rows.map((d: Any) => [d.month, d.kind, inr(d.amount_paise), <StatusBadge key="s" status={d.status} />, d.hold_reason ?? ''])} />
      </Section>
    </div>
  );
}

export function ScholarRequestsPage() {
  useTitle('Requests');
  const me = useMe();
  return me ? <div className="space-y-4"><PageHeader title="Requests" description="Extension, change of guide, mode change, leave and coursework exemption." /><RequestsTab id={me.id} portal /></div> : null;
}

export function ScholarCourseworkPage() {
  useTitle('Coursework');
  const me = useMe();
  return me ? <div className="space-y-4"><PageHeader title="Coursework" description="Credits earned from published results; research methodology is mandatory." /><CourseworkTab id={me.id} /></div> : null;
}

// ---- external examiner token page (no sign-in) ---------------------------------------------------------------------------------
export function ExaminerTokenPage() {
  useTitle('Thesis evaluation');
  const { token = '' } = useParams();
  const [sp] = useSearchParams();
  const institution = sp.get('institution') ?? '';
  const res = useQ(['token', token], () => pa.tokenView(institution, token), !!institution);
  const run = useRun();
  const [rep, setRep] = useState<Any>({ report_url: '', recommendation: 'accept', remarks: '' });
  const v: Any = (res.data as Any)?.data;
  if (!institution) return <p className="p-6 text-sm">The link is missing its institution.</p>;
  if (!v) return <p className="p-6 text-sm text-muted-foreground">{res.isError ? getApiError(res.error) : 'Loading…'}</p>;
  return (
    <div className="mx-auto max-w-2xl space-y-4 p-6">
      <PageHeader title="PhD thesis evaluation" description={`${v.institution ?? ''} · ${v.thesis_title ?? ''}`} />
      <Section title={`Dear ${v.name}`}>
        <p className="text-sm">Status: {v.status}{v.due_on ? ` · report due ${day(v.due_on)}` : ''}</p>
        {v.status === 'invited' && <div className="flex gap-2"><Button size="sm" onClick={() => run.mutate(() => pa.tokenRespond(institution, token, { accept: true }), { onError: fail })}>Accept</Button><Button size="sm" variant="outline" onClick={() => run.mutate(() => pa.tokenRespond(institution, token, { accept: false }), { onError: fail })}>Decline</Button></div>}
        {v.download_url && <a className="text-sm text-primary underline" href={v.download_url} target="_blank" rel="noreferrer">Download the thesis (watermarked)</a>}
        {v.status === 'accepted' && (
          <div className="space-y-2">
            <Input placeholder="Report file URL" value={rep.report_url} onChange={(e) => setRep({ ...rep, report_url: e.target.value })} />
            <select className={sel} value={rep.recommendation} onChange={(e) => setRep({ ...rep, recommendation: e.target.value })}>{['accept', 'minor', 'major', 'reject'].map((x) => <option key={x}>{x}</option>)}</select>
            <textarea className={area} placeholder="Remarks" value={rep.remarks} onChange={(e) => setRep({ ...rep, remarks: e.target.value })} />
            <Button size="sm" disabled={!rep.report_url} onClick={() => run.mutate(() => pa.tokenReport(institution, token, rep), { onSuccess: () => toast.success('Report received — thank you'), onError: fail })}>Submit report</Button>
          </div>
        )}
      </Section>
    </div>
  );
}
