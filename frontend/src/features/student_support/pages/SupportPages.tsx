import { useEffect, useState, type ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Lock } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { ScopeTabs } from '@/components/shared/ScopeTabs';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { toast } from '@/components/ui/Toaster';
import { SimpleTable } from '@/features/hr/components/shared';
import { ssApi as sa } from '../api';

// Phase 27 web screens (Prompts/27 §27.9). Ownership, confidentiality, thresholds and scopes live in the API.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));
const useQ = <T,>(key: unknown[], fn: () => Promise<T>, enabled = true) => useQuery({ queryKey: ['support', ...key], queryFn: fn, retry: false, enabled });
function useRun() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: () => qc.invalidateQueries({ queryKey: ['support'] }) });
}
const list = (r: Any) => (Array.isArray(r?.data) ? r.data : r?.data?.items ?? []);
const when = (s?: string | null) => (s ? new Date(s).toLocaleString() : '—');
const day = (s?: string | null) => (s ? new Date(s).toLocaleDateString() : '—');
const today = () => new Date().toISOString().slice(0, 10);
const sel = 'h-9 rounded-md border bg-background px-2 text-sm';
const area = 'min-h-[80px] w-full rounded-md border bg-background p-2 text-sm';
const GRV_CATS = ['academic', 'exam', 'fee', 'hostel', 'harassment', 'ragging', 'discrimination', 'infrastructure', 'other'];
const GRV_COLUMNS = ['open', 'acknowledged', 'under_review', 'escalated', 'reopened', 'resolved', 'closed'];
const SANCTIONS = ['warning', 'fine', 'suspension', 'expulsion', 'community_service', 'hostel_eviction', 'debar_placement'];
const SURVEY_TYPES = ['course', 'faculty', 'institution', 'course_exit', 'program_exit', 'alumni', 'employer', 'hostel', 'parent', 'sss'];
const ACTIVITY = ['nss', 'ncc', 'community_service', 'club', 'sports'];

function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <Card><CardContent className="space-y-3 p-4"><div className="flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">{title}</h2>{action}</div>{children}</CardContent></Card>;
}
function Stat({ label, value }: { label: string; value: ReactNode }) {
  return <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{label}</p><p className="text-xl font-semibold">{value ?? '—'}</p></CardContent></Card>;
}
function RiskChip({ level }: { level?: string | null }) {
  if (!level) return <span className="text-muted-foreground">—</span>;
  const cls = level === 'high' ? 'bg-red-100 text-red-800' : level === 'medium' ? 'bg-amber-100 text-amber-800' : 'bg-emerald-100 text-emerald-800';
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ${cls}`}>{level}</span>;
}
function slaLeft(due?: string | null) {
  if (!due) return '—';
  const h = Math.round((new Date(due).getTime() - Date.now()) / 36e5);
  return h >= 0 ? `${h} h left` : <span className="text-red-600">{-h} h overdue</span>;
}

// ---- mentoring admin ------------------------------------------------------------------------------------------------------
export function MentoringAdminPage() {
  useTitle('Mentoring');
  const [scope, setScope] = useState<string>();
  const [wizard, setWizard] = useState<Any>({ rule: 'round_robin', ratio: 20 });
  const [preview, setPreview] = useState<Any>(null);
  const q = useQ(['assign', scope], () => sa.assignments({ scope }));
  const load = useQ(['load'], () => sa.load());
  const stats = useQ(['stats'], () => sa.stats());
  const run = useRun();
  const rows = list(q.data);
  const s: Any = stats.data?.data ?? {};
  const l: Any = load.data?.data ?? {};
  return (
    <div className="space-y-4">
      <PageHeader title="Mentoring" description="Assignments per term, bulk allocation, load and session compliance." actions={<ScopeTabs visibility={(q.data as Any)?.meta?.visibility} value={scope} onChange={setScope} />} />
      <div className="grid gap-3 md:grid-cols-4">
        <Stat label="Coverage" value={`${s.mentoring?.coverage_pct ?? 0}%`} />
        <Stat label="Mentor : mentee" value={s.mentoring?.mentor_mentee_ratio} />
        <Stat label="Session compliance" value={`${l.compliance_pct ?? 0}%`} />
        <Stat label="Mentors over ratio" value={(l.rows ?? []).filter((r: Any) => r.over_ratio).length} />
      </div>
      <Section title="Bulk assign">
        <div className="flex flex-wrap items-end gap-2">
          <select className={sel} value={wizard.rule} onChange={(e) => setWizard({ ...wizard, rule: e.target.value })}>
            <option value="round_robin">Round robin (department)</option><option value="section_advisor">Class advisor per section</option><option value="department">Department list</option>
          </select>
          <Input className="w-24" type="number" value={wizard.ratio} onChange={(e) => setWizard({ ...wizard, ratio: Number(e.target.value) })} />
          <Input className="w-80" placeholder="Department id (optional)" value={wizard.department_id ?? ''} onChange={(e) => setWizard({ ...wizard, department_id: e.target.value || undefined })} />
          <Button size="sm" variant="outline" onClick={() => run.mutate(() => sa.bulkAssign({ term_id: l.term_id, rule: wizard.rule, ratio: wizard.ratio, scope: { department_id: wizard.department_id }, preview: true }), { onSuccess: (r: Any) => setPreview(r.data), onError: fail })}>Preview</Button>
          <Button size="sm" disabled={!preview} onClick={() => run.mutate(() => sa.bulkAssign({ term_id: l.term_id, rule: wizard.rule, ratio: wizard.ratio, scope: { department_id: wizard.department_id } }), { onSuccess: () => toast.success('Bulk assignment queued'), onError: fail })}>Assign</Button>
        </div>
        {preview && <p className="text-sm text-muted-foreground">{preview.students} students · {preview.assigned} to assign · {preview.skipped_existing} already assigned · {preview.unassigned} without a mentor · {preview.mentors} mentors</p>}
      </Section>
      <Section title={`Assignments (${rows.length})`}>
        <SimpleTable head={['Student', 'Reg. no', 'Mentor', 'Risk', 'Sessions', 'Since']} rows={rows.map((a: Any) => [a.student_name, a.registration_number, a.mentor_name, <RiskChip key="r" level={a.risk_level} />, a.sessions, day(a.from_on)])} />
      </Section>
      <Section title="Mentor load">
        <SimpleTable head={['Mentor', 'Mentees', 'Sessions', 'Compliant mentees', '']} rows={(l.rows ?? []).map((r: Any) => [r.mentor_name, r.mentees, r.sessions, r.compliant_mentees, r.over_ratio ? <StatusBadge key="o" status="over_ratio" /> : null])} />
      </Section>
    </div>
  );
}

// ---- faculty mentees + 360 -------------------------------------------------------------------------------------------------
export function MenteesPage() {
  useTitle('My mentees');
  const q = useQ(['mentees'], () => sa.mentees());
  const slots = useQ(['slots'], () => sa.mySlots());
  const [slot, setSlot] = useState<Any>({ starts_at: '', minutes: 30, repeat_weeks: 0, location: '' });
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="My mentees" description="Mentee cards with risk chips; open a card for the 360° view, sessions and referrals." />
      <div className="grid gap-3 md:grid-cols-3">
        {list(q.data).map((m: Any) => (
          <Link key={m.id} to={`/faculty/mentees/${m.student_program_enrollment_id}`}>
            <Card><CardContent className="space-y-1 p-4"><div className="flex items-center justify-between"><p className="font-medium">{m.student_name}</p><RiskChip level={m.risk_level} /></div><p className="text-xs text-muted-foreground">{m.registration_number} · {m.sessions} session(s)</p></CardContent></Card>
          </Link>
        ))}
      </div>
      <Section title="My slots">
        <div className="flex flex-wrap items-end gap-2">
          <Input type="datetime-local" value={slot.starts_at} onChange={(e) => setSlot({ ...slot, starts_at: e.target.value })} />
          <Input className="w-24" type="number" value={slot.minutes} onChange={(e) => setSlot({ ...slot, minutes: Number(e.target.value) })} />
          <Input className="w-24" type="number" placeholder="weeks" value={slot.repeat_weeks} onChange={(e) => setSlot({ ...slot, repeat_weeks: Number(e.target.value) })} />
          <Input className="w-48" placeholder="Location" value={slot.location} onChange={(e) => setSlot({ ...slot, location: e.target.value })} />
          <Button size="sm" disabled={!slot.starts_at} onClick={() => {
            const start = new Date(slot.starts_at);
            run.mutate(() => sa.publishSlots({ starts_at: start.toISOString(), ends_at: new Date(start.getTime() + slot.minutes * 60000).toISOString(), repeat_weeks: slot.repeat_weeks, location: slot.location || undefined }), { onSuccess: () => toast.success('Published'), onError: fail });
          }}>Publish</Button>
        </div>
        <SimpleTable head={['When', 'Booked', 'Bookings', '']} rows={list(slots.data).map((s: Any) => [when(s.starts_at), `${s.booked}/${s.capacity}`,
          (s.bookings ?? []).map((b: Any) => <div key={b.id} className="flex items-center gap-2">{b.student_name ?? b.guardian_name} <StatusBadge status={b.status} />{b.status === 'booked' && <><Button size="sm" variant="outline" onClick={() => run.mutate(() => sa.bookingAction(b.id, 'attended'))}>Attended</Button><Button size="sm" variant="outline" onClick={() => run.mutate(() => sa.bookingAction(b.id, 'no-show'))}>No-show</Button></>}</div>),
          s.booked === 0 ? <Button key="d" size="sm" variant="outline" onClick={() => run.mutate(() => sa.deleteSlot(s.id), { onError: fail })}>Delete</Button> : null])} />
      </Section>
    </div>
  );
}

export function Mentee360Page() {
  const { enrollmentId = '' } = useParams();
  const q = useQ(['360', enrollmentId], () => sa.mentee360(enrollmentId));
  const run = useRun();
  const p: Any = q.data?.data ?? {};
  useTitle(p.student?.name ? `${p.student.name} · 360°` : 'Mentee');
  const [f, setF] = useState<Any>({ held_on: today(), mode: 'in_person', notes: '', concerns: [], items: '', confidential: false, share: false, summary: '', follow_up_on: '' });
  const [refer, setRefer] = useState('');
  const assignment = (p.sessions ?? [])[0]?.assignment_id;
  const [assignmentId, setAssignmentId] = useState<string>();
  const aId = assignmentId ?? assignment;
  return (
    <div className="space-y-4">
      <PageHeader title={p.student?.name ?? 'Mentee'} description={`${p.student?.registration_number ?? ''} · access: ${p.access ?? '—'} · standing: ${p.standing ?? '—'}`} />
      <div className="grid gap-3 md:grid-cols-5">
        <Stat label="Attendance" value={p.attendance_pct != null ? `${p.attendance_pct}%` : '—'} />
        <Stat label="CIA avg (scaled)" value={p.cia_summary?.avg_scaled} />
        <Stat label="Overdue dues" value={`₹${((p.dues?.overdue_paise ?? 0) / 100).toLocaleString()}`} />
        <Stat label="Open holds" value={(p.holds ?? []).length} />
        <Stat label="Risk" value={<RiskChip level={p.risk?.level} />} />
      </div>
      {p.risk && <Section title="Risk factors"><SimpleTable head={['Factor', 'Value', 'Weight', 'Points']} rows={Object.entries(p.risk.factors ?? {}).map(([k, v]: Any) => [k, v.value, v.weight, v.points])} /></Section>}
      <Section title="Log a session">
        {!assignment && <Input placeholder="Assignment id" value={assignmentId ?? ''} onChange={(e) => setAssignmentId(e.target.value)} />}
        <div className="flex flex-wrap gap-2">
          <Input type="date" value={f.held_on} onChange={(e) => setF({ ...f, held_on: e.target.value })} />
          <select className={sel} value={f.mode} onChange={(e) => setF({ ...f, mode: e.target.value })}>{['in_person', 'online', 'phone', 'group'].map((m) => <option key={m}>{m}</option>)}</select>
          {['academic', 'personal', 'financial', 'health', 'career'].map((c) => <label key={c} className="flex items-center gap-1 text-sm"><input type="checkbox" checked={f.concerns.includes(c)} onChange={(e) => setF({ ...f, concerns: e.target.checked ? [...f.concerns, c] : f.concerns.filter((x: string) => x !== c) })} />{c}</label>)}
        </div>
        <textarea className={area} placeholder="Notes (voice-to-text on mobile)" value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} />
        <textarea className={area} placeholder="Action items — one per line" value={f.items} onChange={(e) => setF({ ...f, items: e.target.value })} />
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <label className="flex items-center gap-1"><input type="checkbox" checked={f.confidential} onChange={(e) => setF({ ...f, confidential: e.target.checked })} /><Lock className="h-3 w-3" /> Confidential</label>
          <label className="flex items-center gap-1"><input type="checkbox" checked={f.share} onChange={(e) => setF({ ...f, share: e.target.checked })} /> Share summary with guardian</label>
          <Input type="date" value={f.follow_up_on} onChange={(e) => setF({ ...f, follow_up_on: e.target.value })} />
        </div>
        {f.share && <Input placeholder="Guardian summary" value={f.summary} onChange={(e) => setF({ ...f, summary: e.target.value })} />}
        <Button size="sm" disabled={!aId} onClick={() => run.mutate(() => sa.logSession({
          assignment_id: aId, held_on: f.held_on, mode: f.mode, notes: f.notes || undefined, concerns: f.concerns,
          action_items: f.items.split('\n').filter(Boolean).map((t: string) => ({ text: t, owner: 'student' })),
          follow_up_on: f.follow_up_on || undefined, is_confidential: f.confidential, share_with_guardian: f.share, guardian_summary: f.summary || undefined,
        }), { onSuccess: () => toast.success('Session logged'), onError: fail })}>Save session</Button>
      </Section>
      <Section title="Sessions">
        <SimpleTable head={['Date', 'Mode', 'Notes', 'Action items']} rows={(p.sessions ?? []).map((s: Any) => [day(s.held_on), s.mode, s.redacted ? <span key="r" className="flex items-center gap-1 text-muted-foreground"><Lock className="h-3 w-3" /> confidential</span> : s.notes, (s.action_items ?? []).map((a: Any, i: number) => <label key={i} className="flex items-center gap-1 text-xs"><input type="checkbox" checked={!!a.done} onChange={(e) => run.mutate(() => sa.tickAction(s.id, i, e.target.checked))} />{a.text}</label>)])} />
      </Section>
      <Section title="Refer to counselling">
        <div className="flex gap-2"><Input placeholder="Reason" value={refer} onChange={(e) => setRefer(e.target.value)} /><Button size="sm" disabled={refer.length < 3} onClick={() => run.mutate(() => sa.refer({ enrollment_id: enrollmentId, reason: refer }), { onSuccess: () => { setRefer(''); toast.success('Referred'); }, onError: fail })}>Refer</Button></div>
        <SimpleTable head={['Status', 'Since']} rows={(p.referrals ?? []).map((r: Any) => [<StatusBadge key="s" status={r.status} />, day(r.created_at)])} />
      </Section>
      <Section title="Achievements"><SimpleTable head={['Title', 'Category', 'Verified']} rows={(p.achievements ?? []).map((a: Any) => [a.title, a.category, a.verified ? 'yes' : 'no'])} /></Section>
    </div>
  );
}

// ---- risk -------------------------------------------------------------------------------------------------------------------
export function RiskPage() {
  useTitle('Early warning');
  const [scope, setScope] = useState<string>();
  const [level, setLevel] = useState('high');
  const [open, setOpen] = useState<Any>(null);
  const q = useQ(['risk', scope, level], () => sa.riskFlags({ scope, level: level || undefined }));
  const heat = useQ(['heat'], () => sa.riskHeatmap());
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Early warning" description="Risk score per student per term — attendance, CIA, dues, standing, hostel, engagement." actions={<div className="flex gap-2"><ScopeTabs visibility={(q.data as Any)?.meta?.visibility} value={scope} onChange={setScope} /><Button size="sm" onClick={() => run.mutate(() => sa.riskCompute({}), { onSuccess: () => toast.success('Risk computation queued'), onError: fail })}>Recompute</Button></div>} />
      <Section title="By department"><SimpleTable head={['Department', 'Low', 'Medium', 'High']} rows={list(heat.data).map((c: Any) => [c.department_code ?? '—', c.low, c.medium, <span key="h" className="font-semibold text-red-700">{c.high}</span>])} /></Section>
      <Section title="Students" action={<select className={sel} value={level} onChange={(e) => setLevel(e.target.value)}><option value="">All levels</option><option>high</option><option>medium</option><option>low</option></select>}>
        <SimpleTable head={['Student', 'Score', 'Level', 'Attendance', 'Acknowledged', '']} rows={list(q.data).map((f: Any) => [f.student_name, f.score, <RiskChip key="l" level={f.level} />, f.factors?.attendance?.avg_pct ?? '—', f.acknowledged ? f.action ?? 'yes' : 'no',
          <div key="a" className="flex gap-1"><Button size="sm" variant="outline" onClick={() => setOpen(f)}>Factors</Button>{!f.acknowledged && <Button size="sm" onClick={() => { const action = window.prompt('Action taken'); if (action) run.mutate(() => sa.riskAck(f.id, action), { onError: fail }); }}>Acknowledge</Button>}</div>])} />
      </Section>
      {open && <Section title={`Factors — ${open.student_name}`} action={<Button size="sm" variant="outline" onClick={() => setOpen(null)}>Close</Button>}><SimpleTable head={['Factor', 'Normalised', 'Weight', 'Points']} rows={Object.entries(open.factors ?? {}).map(([k, v]: Any) => [k, v.value, v.weight, v.points])} /></Section>}
    </div>
  );
}

// ---- grievances -------------------------------------------------------------------------------------------------------------
export function GrievancesAdminPage() {
  useTitle('Grievances');
  const [scope, setScope] = useState<string>();
  const [cat, setCat] = useState('');
  const q = useQ(['grv', scope, cat], () => sa.grievances({ scope, category: cat || undefined }));
  const rows = list(q.data);
  const exportReg = async (kind: string) => {
    try {
      const r: Any = await sa.grievanceRegister(kind);
      toast.success(`${kind.toUpperCase()} register: ${r.data.rows.length} rows (received ${r.data.totals.received}, resolved ${r.data.totals.resolved})`);
    } catch (e) { fail(e); }
  };
  return (
    <div className="space-y-4">
      <PageHeader title="Grievances" description="Kanban by status with SLA timers; confidential tickets only for the routed committee." actions={<div className="flex gap-2"><ScopeTabs visibility={(q.data as Any)?.meta?.visibility} value={scope} onChange={setScope} /><select className={sel} value={cat} onChange={(e) => setCat(e.target.value)}><option value="">All categories</option>{GRV_CATS.map((c) => <option key={c}>{c}</option>)}</select></div>} />
      <div className="flex gap-2">{['ugc', 'icc', 'anti_ragging'].map((k) => <Button key={k} size="sm" variant="outline" onClick={() => exportReg(k)}>{k.toUpperCase()} register</Button>)}</div>
      <div className="grid gap-3 overflow-x-auto md:grid-cols-7">
        {GRV_COLUMNS.map((col) => (
          <div key={col} className="space-y-2">
            <p className="text-xs font-semibold uppercase text-muted-foreground">{col.replace('_', ' ')} ({rows.filter((g: Any) => g.status === col).length})</p>
            {rows.filter((g: Any) => g.status === col).map((g: Any) => (
              <Link key={g.id} to={`/admin/grievances/${g.id}`}>
                <Card><CardContent className="space-y-1 p-3 text-xs"><div className="flex items-center justify-between font-medium">{g.ticket_number}{g.confidential && <Lock className="h-3 w-3" />}</div><p>{g.category} · {g.committee ?? '—'}</p><p>{slaLeft(g.sla_due_at)}</p></CardContent></Card>
              </Link>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

export function GrievanceTicketPage() {
  const { id = '' } = useParams();
  const q = useQ(['grv', id], () => sa.grievance(id));
  const run = useRun();
  const g: Any = q.data?.data ?? {};
  useTitle(g.ticket_number ?? 'Grievance');
  const [note, setNote] = useState('');
  const [internal, setInternal] = useState(true);
  const [resolution, setResolution] = useState('');
  return (
    <div className="space-y-4">
      <PageHeader title={`${g.ticket_number ?? ''} · ${g.category ?? ''}`} description={`${g.is_anonymous ? 'Anonymous' : g.raised_by_name ?? ''} · committee ${g.committee ?? '—'} · SLA ${g.sla_due_at ? when(g.sla_due_at) : '—'}`} actions={<StatusBadge status={g.status} />} />
      <Section title="Description">{g.confidential && <p className="flex items-center gap-1 text-xs text-amber-700"><Lock className="h-3 w-3" /> Confidential category — every read is audited</p>}<p className="whitespace-pre-wrap text-sm">{g.description}</p></Section>
      <Section title="Triage">
        <div className="flex flex-wrap gap-2">
          <select className={sel} defaultValue="" onChange={(e) => e.target.value && run.mutate(() => sa.grievanceTriage(id, { committee: e.target.value }), { onError: fail })}><option value="">Route to…</option>{['grievance_cell', 'icc', 'anti_ragging', 'sc_st_cell', 'obc_cell'].map((c) => <option key={c}>{c}</option>)}</select>
          <select className={sel} defaultValue="" onChange={(e) => e.target.value && run.mutate(() => sa.grievanceTriage(id, { priority: e.target.value }), { onError: fail })}><option value="">Priority…</option>{['low', 'normal', 'high', 'urgent'].map((c) => <option key={c}>{c}</option>)}</select>
          <Button size="sm" variant="outline" onClick={() => run.mutate(() => sa.grievanceTriage(id, { status: 'under_review' }), { onError: fail })}>Under review</Button>
          <Button size="sm" variant="outline" onClick={() => { const r = window.prompt('Escalation reason'); if (r) run.mutate(() => sa.grievanceEscalate(id, r), { onError: fail }); }}>Escalate</Button>
          <Button size="sm" variant="outline" onClick={() => run.mutate(() => sa.grievanceClose(id), { onError: fail })}>Close</Button>
        </div>
        <div className="flex gap-2"><Input placeholder="Resolution" value={resolution} onChange={(e) => setResolution(e.target.value)} /><Button size="sm" disabled={resolution.length < 3} onClick={() => run.mutate(() => sa.grievanceResolve(id, resolution), { onError: fail })}>Resolve</Button></div>
      </Section>
      <Section title="Timeline">
        <ul className="space-y-1 text-sm">{(g.timeline ?? []).map((t: Any, i: number) => <li key={i} className={t.is_internal ? 'text-amber-800' : ''}>{when(t.at)} · {t.by ?? ''} {t.is_internal && '(internal)'} — {t.note}</li>)}</ul>
        <textarea className={area} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Update" />
        <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={internal} onChange={(e) => setInternal(e.target.checked)} /> Internal note (hidden from the complainant)</label>
        <Button size="sm" disabled={!note} onClick={() => run.mutate(() => sa.grievanceUpdate(id, { note, is_internal: internal }), { onSuccess: () => setNote(''), onError: fail })}>Post</Button>
      </Section>
      {g.satisfaction_rating && <Section title="Rating"><p className="text-sm">{g.satisfaction_rating}/5</p></Section>}
    </div>
  );
}

function RaiseGrievance({ onDone, wards }: { onDone?: () => void; wards?: Any[] }) {
  const run = useRun();
  const [f, setF] = useState<Any>({ category: 'academic', description: '', is_anonymous: false });
  const [secret, setSecret] = useState<Any>(null);
  return (
    <Section title="Raise a grievance">
      <div className="flex flex-wrap gap-2">
        <select className={sel} value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>{GRV_CATS.map((c) => <option key={c}>{c}</option>)}</select>
        {wards && wards.length > 0 && <select className={sel} value={f.on_behalf_enrollment_id ?? ''} onChange={(e) => setF({ ...f, on_behalf_enrollment_id: e.target.value || undefined })}><option value="">For…</option>{wards.map((w: Any) => <option key={w.id} value={w.id}>{w.name}</option>)}</select>}
        <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={f.is_anonymous} onChange={(e) => setF({ ...f, is_anonymous: e.target.checked })} /> Anonymous</label>
      </div>
      <textarea className={area} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} placeholder="Describe the issue (at least 10 characters)" />
      <Button size="sm" disabled={f.description.length < 10} onClick={() => run.mutate(() => sa.raiseGrievance(f), { onSuccess: (r: Any) => { setSecret(r.data); setF({ ...f, description: '' }); onDone?.(); }, onError: fail })}>Submit</Button>
      {secret && <p className="text-sm">Ticket <b>{secret.ticket_number}</b> · {secret.committee ?? ''}{secret.tracking_secret && <> · tracking secret (shown once): <code>{secret.tracking_secret}</code></>}</p>}
    </Section>
  );
}

function GrievanceList({ rows }: { rows: Any[] }) {
  const run = useRun();
  return (
    <SimpleTable head={['Ticket', 'Category', 'Status', 'SLA', '']} rows={rows.map((g: Any) => [g.ticket_number, g.category, <StatusBadge key="s" status={g.status} />, slaLeft(g.sla_due_at),
      <div key="a" className="flex gap-1">
        {['resolved', 'closed'].includes(g.status) && !g.satisfaction_rating && [5, 4, 3, 2, 1].map((n) => <Button key={n} size="sm" variant="outline" onClick={() => run.mutate(() => sa.grievanceRate(g.id, n), { onError: fail })}>{n}★</Button>)}
        {['resolved', 'closed'].includes(g.status) && <Button size="sm" variant="outline" onClick={() => { const r = window.prompt('Why reopen?'); if (r) run.mutate(() => sa.grievanceReopen(g.id, r), { onError: fail }); }}>Reopen</Button>}
      </div>])} />
  );
}

export function StudentGrievancesPage() {
  useTitle('My grievances');
  const q = useQ(['grv-me'], () => sa.myGrievances());
  return <div className="space-y-4"><PageHeader title="Grievances" description="Raise (optionally anonymous), track and rate." /><RaiseGrievance /><Section title="My grievances"><GrievanceList rows={list(q.data)} /></Section></div>;
}

export function PublicGrievancePage() {
  useTitle('Anonymous grievance');
  const [f, setF] = useState<Any>({ institution: new URLSearchParams(window.location.search).get('institution') ?? '', category: 'ragging', description: '' });
  const [out, setOut] = useState<Any>(null);
  return (
    <div className="mx-auto max-w-xl space-y-4 p-6">
      <PageHeader title="Report anonymously" description="No login needed. Keep the ticket number and secret to track your report." />
      <Input placeholder="Institution code" value={f.institution} onChange={(e) => setF({ ...f, institution: e.target.value })} />
      <select className={sel} value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>{GRV_CATS.map((c) => <option key={c}>{c}</option>)}</select>
      <textarea className={area} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} placeholder="What happened?" />
      <Button disabled={f.description.length < 10 || !f.institution} onClick={async () => { try { const r: Any = await sa.anonymousGrievance(f.institution, { category: f.category, description: f.description }); setOut(r.data); } catch (e) { fail(e); } }}>Submit</Button>
      {out && <Card><CardContent className="p-4 text-sm">Ticket <b>{out.ticket_number}</b> · secret <code>{out.tracking_secret}</code> — shown once. <Link className="underline" to={`/grievance/track?institution=${f.institution}`}>Track</Link></CardContent></Card>}
    </div>
  );
}

export function GrievanceTrackPage() {
  useTitle('Track grievance');
  const [f, setF] = useState<Any>({ institution: new URLSearchParams(window.location.search).get('institution') ?? '', ticket_number: '', secret: '' });
  const [out, setOut] = useState<Any>(null);
  return (
    <div className="mx-auto max-w-xl space-y-4 p-6">
      <PageHeader title="Track a grievance" description="Ticket number + the secret shown when you submitted." />
      {(['institution', 'ticket_number', 'secret'] as const).map((k) => <Input key={k} placeholder={k.replace('_', ' ')} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} />)}
      <Button onClick={async () => { try { const r: Any = await sa.trackGrievance(f); setOut(r.data); } catch (e) { setOut(null); fail(e); } }}>Track</Button>
      {out && <Section title={`${out.ticket_number} · ${out.status}`}><ul className="space-y-1 text-sm">{(out.timeline ?? []).map((t: Any, i: number) => <li key={i}>{when(t.at)} — {t.note}</li>)}</ul></Section>}
    </div>
  );
}

// ---- discipline -------------------------------------------------------------------------------------------------------------
export function DisciplinePage() {
  useTitle('Discipline');
  const [scope, setScope] = useState<string>();
  const q = useQ(['cases', scope], () => sa.cases({ scope }));
  const run = useRun();
  const [f, setF] = useState<Any>({ subject_type: 'student', subject_id: '', category: 'misconduct', description: '' });
  return (
    <div className="space-y-4">
      <PageHeader title="Discipline" description="Cases for students and staff: inquiry → hearing → decision → appeal." actions={<div className="flex gap-2"><ScopeTabs visibility={(q.data as Any)?.meta?.visibility} value={scope} onChange={setScope} /><Button size="sm" variant="outline" onClick={async () => { try { const r: Any = await sa.disciplineRegister(); toast.success(`${r.data.length} rows in the register`); } catch (e) { fail(e); } }}>Register</Button></div>} />
      <Section title="Report a case">
        <div className="flex flex-wrap gap-2">
          <select className={sel} value={f.subject_type} onChange={(e) => setF({ ...f, subject_type: e.target.value })}><option>student</option><option>staff</option></select>
          <Input className="w-80" placeholder={f.subject_type === 'student' ? 'Enrolment id' : 'Staff id'} value={f.subject_id} onChange={(e) => setF({ ...f, subject_id: e.target.value })} />
          <Input className="w-48" placeholder="Category" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} />
        </div>
        <textarea className={area} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} placeholder="What was reported" />
        <Button size="sm" disabled={!f.subject_id || f.description.length < 5} onClick={() => run.mutate(() => sa.reportCase(f), { onSuccess: () => toast.success('Reported'), onError: fail })}>Report</Button>
      </Section>
      <Section title="Cases"><SimpleTable head={['Case', 'Subject', 'Category', 'Status', 'Sanctions', 'Appeal']} rows={list(q.data).map((c: Any) => [<Link key="l" className="underline" to={`/admin/discipline/${c.id}`}>{c.case_number}</Link>, `${c.subject_name ?? ''} (${c.subject_type})`, c.category, <StatusBadge key="s" status={c.status} />, (c.sanctions ?? []).map((s: Any) => s.type).join(', ') || '—', c.appeal_status ?? '—'])} /></Section>
    </div>
  );
}

export function DisciplineCasePage() {
  const { id = '' } = useParams();
  const q = useQ(['case', id], () => sa.caseFile(id));
  const coms = useQ(['coms', 'discipline'], () => sa.committees({ committee_type: 'discipline' }));
  const run = useRun();
  const c: Any = q.data?.data ?? {};
  useTitle(c.case_number ?? 'Case');
  const [notice, setNotice] = useState('');
  const [hearingAt, setHearingAt] = useState('');
  const [sanctions, setSanctions] = useState<Any[]>([{ type: 'warning' }]);
  const [decision, setDecision] = useState('');
  const severe = sanctions.some((s) => ['suspension', 'expulsion'].includes(s.type));
  return (
    <div className="space-y-4">
      <PageHeader title={`${c.case_number ?? ''} · ${c.subject_name ?? ''}`} description={`${c.subject_type ?? ''} · ${c.category ?? ''} · committee ${c.committee_name ?? '—'}`} actions={<StatusBadge status={c.status} />} />
      <Section title="Case">{<p className="whitespace-pre-wrap text-sm">{c.description}</p>}<SimpleTable head={['Evidence', 'Note']} rows={(c.evidence ?? []).map((e: Any) => [e.name, e.note ?? ''])} /></Section>
      <Section title="Inquiry & notice">
        <div className="flex flex-wrap gap-2">
          <select className={sel} defaultValue="" onChange={(e) => e.target.value && run.mutate(() => sa.inquiry(id, { committee_id: e.target.value }), { onError: fail })}><option value="">Assign committee…</option>{list(coms.data).map((m: Any) => <option key={m.id} value={m.id}>{m.name}</option>)}</select>
          <Input className="w-96" placeholder="Notice text" value={notice} onChange={(e) => setNotice(e.target.value)} />
          <Button size="sm" disabled={notice.length < 5} onClick={() => run.mutate(() => sa.notice(id, { notice_text: notice }), { onSuccess: () => setNotice(''), onError: fail })}>Send notice</Button>
          <Input type="datetime-local" value={hearingAt} onChange={(e) => setHearingAt(e.target.value)} />
          <Button size="sm" disabled={!hearingAt} onClick={() => run.mutate(() => sa.hearing(id, { hearing_at: new Date(hearingAt).toISOString() }), { onError: fail })}>Schedule hearing</Button>
        </div>
        <SimpleTable head={['Notice', 'Sent']} rows={(c.notices ?? []).map((n: Any) => [n.text, when(n.at)])} />
        <SimpleTable head={['Statement', 'Submitted']} rows={(c.statements ?? []).map((s: Any) => [s.text, when(s.at)])} />
      </Section>
      <Section title="Decision (sanction builder)">
        {sanctions.map((s, i) => (
          <div key={i} className="flex flex-wrap gap-2">
            <select className={sel} value={s.type} onChange={(e) => setSanctions(sanctions.map((x, j) => (j === i ? { ...x, type: e.target.value } : x)))}>{SANCTIONS.map((t) => <option key={t}>{t}</option>)}</select>
            {s.type === 'fine' && <Input className="w-40" type="number" placeholder="Amount ₹" onChange={(e) => setSanctions(sanctions.map((x, j) => (j === i ? { ...x, amount_paise: Math.round(Number(e.target.value) * 100) } : x)))} />}
            {s.type === 'suspension' && <><Input type="date" onChange={(e) => setSanctions(sanctions.map((x, j) => (j === i ? { ...x, from_on: e.target.value } : x)))} /><Input type="date" onChange={(e) => setSanctions(sanctions.map((x, j) => (j === i ? { ...x, to_on: e.target.value } : x)))} /></>}
            {s.type === 'community_service' && <Input className="w-32" type="number" placeholder="Hours" onChange={(e) => setSanctions(sanctions.map((x, j) => (j === i ? { ...x, hours: Number(e.target.value) } : x)))} />}
            <Button size="sm" variant="outline" onClick={() => setSanctions(sanctions.filter((_, j) => j !== i))}>Remove</Button>
          </div>
        ))}
        <Button size="sm" variant="outline" onClick={() => setSanctions([...sanctions, { type: 'warning' }])}>Add sanction</Button>
        <p className="text-xs text-muted-foreground">Effects preview: {sanctions.map((s) => ({ fine: 'fee invoice (discipline_fine)', suspension: 'hold ALL for the period + attendance policy', expulsion: 'enrolment expelled + hold ALL', community_service: 'hours target on the activity ledger', hostel_eviction: 'hostel eviction event', debar_placement: 'placement blacklist event', warning: 'record only' } as Record<string, string>)[s.type]).join(' · ')}{severe && ' · needs principal approval'}</p>
        <textarea className={area} value={decision} onChange={(e) => setDecision(e.target.value)} placeholder="Decision text (goes into the decision letter)" />
        <Button size="sm" disabled={decision.length < 5 || !sanctions.length} onClick={() => run.mutate(() => sa.decide(id, { sanctions, decision_text: decision }), { onError: fail })}>Decide</Button>
        <SimpleTable head={['Effect', 'Status', 'Detail']} rows={(c.effects ?? []).map((e: Any) => [e.type, e.status, e.fee_invoice_id ?? e.hold_id ?? e.hours_target ?? ''])} />
      </Section>
      {c.appeal && <Section title="Appeal">
        <p className="text-sm">{c.appeal.grounds}</p>
        {c.status === 'appealed' && <div className="flex gap-2">{['uphold', 'modify', 'revoke'].map((o) => <Button key={o} size="sm" variant="outline" onClick={() => { const r = window.prompt('Remarks'); if (r) run.mutate(() => sa.appealDecide(id, { outcome: o, remarks: r, sanctions: o === 'modify' ? sanctions : undefined }), { onError: fail }); }}>{o}</Button>)}</div>}
        {c.appeal.outcome && <p className="text-sm">Outcome: {c.appeal.outcome} — {c.appeal.remarks}</p>}
      </Section>}
      <Section title="Timeline"><ul className="space-y-1 text-sm">{(c.timeline ?? []).map((t: Any, i: number) => <li key={i}>{when(t.at)} — {t.action}</li>)}</ul></Section>
      {c.status !== 'closed' && <Button size="sm" variant="outline" onClick={() => run.mutate(() => sa.closeCase(id), { onError: fail })}>Close case</Button>}
    </div>
  );
}

export function StudentDisciplinePage() {
  useTitle('Disciplinary notices');
  const q = useQ(['cases-me'], () => sa.myCases());
  const run = useRun();
  const [text, setText] = useState<Record<string, string>>({});
  return (
    <div className="space-y-4">
      <PageHeader title="Disciplinary notices" description="Notices, your statement and appeal." />
      {list(q.data).length === 0 && <p className="text-sm text-muted-foreground">No cases.</p>}
      {list(q.data).map((c: Any) => (
        <Section key={c.id} title={`${c.case_number} · ${c.category}`} action={<StatusBadge status={c.status} />}>
          <ul className="text-sm">{(c.notices ?? []).map((n: Any, i: number) => <li key={i}>{when(n.at)} — {n.text}</li>)}</ul>
          {c.hearing_at && <p className="text-sm">Hearing: {when(c.hearing_at)}</p>}
          {(c.sanctions ?? []).length > 0 && <p className="text-sm">Sanctions: {(c.sanctions ?? []).map((s: Any) => s.type).join(', ')}</p>}
          {c.is_subject && !['decided', 'closed', 'appealed'].includes(c.status) && <><textarea className={area} value={text[c.id] ?? ''} onChange={(e) => setText({ ...text, [c.id]: e.target.value })} placeholder="Your statement" /><Button size="sm" onClick={() => run.mutate(() => sa.statement(c.id, { text: text[c.id] }), { onError: fail })}>Submit statement</Button></>}
          {c.can_appeal && <Button size="sm" variant="outline" onClick={() => { const g = window.prompt('Grounds of appeal'); if (g) run.mutate(() => sa.appeal(c.id, { grounds: g }), { onError: fail }); }}>Appeal</Button>}
        </Section>
      ))}
    </div>
  );
}

// ---- surveys ----------------------------------------------------------------------------------------------------------------
export function SurveysAdminPage() {
  useTitle('Surveys');
  const q = useQ(['surveys'], () => sa.surveys());
  const sss = useQ(['sss'], () => sa.sssScore());
  const run = useRun();
  const [f, setF] = useState<Any>({ survey_type: 'course', title: '', reminder_days: '3,1', closes_at: '' });
  return (
    <div className="space-y-4">
      <PageHeader title="Surveys" description="Builder with templates and CO/PO tags, auto targets, windows, reminders; completion and analytics." />
      <div className="grid gap-3 md:grid-cols-3"><Stat label="SSS score (0–4)" value={sss.data?.data?.score} /><Stat label="SSS respondents" value={sss.data?.data?.respondents} /><Stat label="Surveys" value={list(q.data).length} /></div>
      <Section title="New survey">
        <div className="flex flex-wrap gap-2">
          <select className={sel} value={f.survey_type} onChange={(e) => setF({ ...f, survey_type: e.target.value })}>{SURVEY_TYPES.map((t) => <option key={t}>{t}</option>)}</select>
          <Input className="w-80" placeholder="Title" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
          <Input type="datetime-local" value={f.closes_at} onChange={(e) => setF({ ...f, closes_at: e.target.value })} />
          <Input className="w-32" placeholder="Reminder days" value={f.reminder_days} onChange={(e) => setF({ ...f, reminder_days: e.target.value })} />
          <Button size="sm" disabled={f.title.length < 3} onClick={() => run.mutate(() => sa.createSurvey({ survey_type: f.survey_type, title: f.title, closes_at: f.closes_at ? new Date(f.closes_at).toISOString() : undefined, reminder_days: String(f.reminder_days).split(',').map((x) => Number(x.trim())).filter((x) => !Number.isNaN(x)) }), { onSuccess: () => toast.success('Created from template'), onError: fail })}>Create</Button>
        </div>
      </Section>
      <Section title="Surveys"><SimpleTable head={['Title', 'Type', 'Status', 'Responses', 'Closes', '']} rows={list(q.data).map((s: Any) => [<Link key="l" className="underline" to={`/admin/surveys/${s.id}`}>{s.title}</Link>, s.survey_type, <StatusBadge key="s" status={s.status} />, s.responses, when(s.closes_at),
        <div key="a" className="flex gap-1">{s.status === 'draft' && <Button size="sm" variant="outline" onClick={() => run.mutate(() => sa.surveyAction(s.id, 'open'), { onError: fail })}>Open</Button>}{s.status === 'open' && <><Button size="sm" variant="outline" onClick={() => run.mutate(() => sa.surveyAction(s.id, 'remind'), { onError: fail })}>Remind</Button><Button size="sm" variant="outline" onClick={() => run.mutate(() => sa.surveyAction(s.id, 'close'), { onError: fail })}>Close</Button></>}{s.status === 'closed' && <Button size="sm" variant="outline" onClick={() => run.mutate(() => sa.surveyAction(s.id, 'analyse'), { onError: fail })}>Analyse</Button>}</div>])} /></Section>
    </div>
  );
}

export function SurveyDetailPage() {
  const { id = '' } = useParams();
  const s = useQ(['survey', id], () => sa.survey(id));
  const comp = useQ(['comp', id], () => sa.completion(id));
  const [target, setTarget] = useState('');
  const an = useQ(['an', id, target], () => sa.analytics(id, { target_id: target || undefined }));
  const cmp = useQ(['cmp', id], () => sa.compare(id));
  const sv: Any = s.data?.data ?? {};
  const a: Any = an.data?.data ?? {};
  useTitle(sv.title ?? 'Survey');
  return (
    <div className="space-y-4">
      <PageHeader title={sv.title ?? 'Survey'} description={`${sv.survey_type ?? ''} · ${sv.status ?? ''} · min responses ${sv.min_responses ?? 5}`} actions={<Button size="sm" variant="outline" onClick={async () => { try { await sa.exportSurvey(id); toast.success('Export queued'); } catch (e) { fail(e); } }}>Export</Button>} />
      <div className="grid gap-3 md:grid-cols-3"><Stat label="Responses" value={comp.data?.data?.responses} /><Stat label="Expected" value={comp.data?.data?.expected} /><Stat label="Completion" value={comp.data?.data?.completion_pct != null ? `${comp.data.data.completion_pct}%` : '—'} /></div>
      <Section title="Completion by target" action={<select className={sel} value={target} onChange={(e) => setTarget(e.target.value)}><option value="">All targets</option>{(comp.data?.data?.by_target ?? []).filter((t: Any) => t.target_id).map((t: Any) => <option key={t.target_id} value={t.target_id}>{t.label}</option>)}</select>}>
        <SimpleTable head={['Target', 'Expected', 'Responses']} rows={(comp.data?.data?.by_target ?? []).slice(0, 50).map((t: Any) => [t.label, t.expected, t.responses])} />
      </Section>
      <Section title={`Analytics · n=${a.n ?? 0} · overall ${a.overall ?? '—'}${a.previous_overall != null ? ` (prev ${a.previous_overall})` : ''}`}>
        {an.error ? <p className="text-sm text-muted-foreground">{getApiError(an.error)}</p> : <SimpleTable head={['Question', 'n', 'Mean', 'Distribution']} rows={(a.per_question ?? []).map((p: Any) => [p.text, p.n, p.mean ?? '—', Object.entries(p.distribution ?? {}).map(([k, v]) => `${k}:${v}`).join('  ')])} />}
        {a.co_scores && <p className="text-sm">CO: {Object.entries(a.co_scores).map(([k, v]) => `${k} ${v}`).join(' · ')}</p>}
        {a.po_scores && <p className="text-sm">PO: {Object.entries(a.po_scores).map(([k, v]) => `${k} ${v}`).join(' · ')}</p>}
        {(a.comments_masked ?? []).length > 0 && <ul className="list-disc pl-5 text-sm">{a.comments_masked.slice(0, 20).map((c: string, i: number) => <li key={i}>{c}</li>)}</ul>}
      </Section>
      <Section title="Comparison"><SimpleTable head={['Group', 'n', 'Overall']} rows={(cmp.data?.data?.rows ?? []).map((r: Any) => [r.label ?? r.key, r.n, r.overall ?? '—'])} /></Section>
    </div>
  );
}

function SurveyForm({ surveyId, target, onDone }: { surveyId: string; target?: Any; onDone: () => void }) {
  const q = useQ(['form', surveyId, target?.target_id], () => sa.surveyForm(surveyId, { target_id: target?.target_id }));
  const [ans, setAns] = useState<Record<string, Any>>({});
  const run = useRun();
  const form: Any = q.data?.data ?? {};
  return (
    <Section title={`${form.title ?? ''}${target?.label ? ` — ${target.label}` : ''}`}>
      {(form.questions ?? []).map((qq: Any) => (
        <div key={qq.id} className="space-y-1">
          <p className="text-sm">{qq.text}</p>
          {qq.type === 'text' ? <Input value={ans[qq.id] ?? ''} onChange={(e) => setAns({ ...ans, [qq.id]: e.target.value })} />
            : qq.type === 'yesno' ? <div className="flex gap-2">{['yes', 'no'].map((v) => <Button key={v} size="sm" variant={ans[qq.id] === v ? 'default' : 'outline'} onClick={() => setAns({ ...ans, [qq.id]: v })}>{v}</Button>)}</div>
              : <div className="flex gap-1">{Array.from({ length: (qq.scale ?? 5) + (qq.scale === 4 ? 1 : 0) }, (_, i) => (qq.scale === 4 ? i : i + 1)).map((v) => <Button key={v} size="sm" variant={ans[qq.id] === v ? 'default' : 'outline'} onClick={() => setAns({ ...ans, [qq.id]: v })}>{v}</Button>)}</div>}
        </div>
      ))}
      <Button size="sm" onClick={() => run.mutate(() => sa.respond(surveyId, { target_id: target?.target_id ?? undefined, answers: ans }), { onSuccess: () => { toast.success('Thank you'); onDone(); }, onError: fail })}>Submit</Button>
    </Section>
  );
}

export function MySurveysPage() {
  useTitle('My surveys');
  const q = useQ(['pending'], () => sa.pendingSurveys());
  const [open, setOpen] = useState<Any>(null);
  return (
    <div className="space-y-4">
      <PageHeader title="Surveys" description="Responses are anonymous — only a one-way hash is kept." />
      {list(q.data).length === 0 && <p className="text-sm text-muted-foreground">Nothing pending.</p>}
      {list(q.data).map((s: Any) => (
        <Section key={s.survey_id} title={s.title} action={<span className="text-xs text-muted-foreground">closes {when(s.closes_at)}</span>}>
          <div className="flex flex-wrap gap-2">{s.targets.map((t: Any) => <Button key={t.target_id ?? 'i'} size="sm" variant="outline" disabled={t.responded} onClick={() => setOpen({ id: s.survey_id, target: t })}>{t.label ?? 'Respond'}{t.responded ? ' ✓' : ''}</Button>)}</div>
        </Section>
      ))}
      {open && <SurveyForm surveyId={open.id} target={open.target} onDone={() => setOpen(null)} />}
    </div>
  );
}

export function FacultySurveysPage() {
  useTitle('My feedback results');
  const q = useQ(['surveys-f'], () => sa.surveys({ survey_type: 'course' }));
  const [sid, setSid] = useState('');
  const [target, setTarget] = useState('');
  const an = useQ(['an-f', sid, target], () => sa.analytics(sid, { target_id: target }), !!sid && !!target);
  const a: Any = an.data?.data ?? {};
  return (
    <div className="space-y-4">
      <PageHeader title="Feedback results" description="Your own offerings, shown once the minimum number of responses exists." />
      <div className="flex gap-2"><select className={sel} value={sid} onChange={(e) => setSid(e.target.value)}><option value="">Survey…</option>{list(q.data).map((s: Any) => <option key={s.id} value={s.id}>{s.title}</option>)}</select><Input className="w-96" placeholder="Offering id" value={target} onChange={(e) => setTarget(e.target.value)} /></div>
      {an.error && <p className="text-sm text-muted-foreground">{getApiError(an.error)}</p>}
      {an.data && <Section title={`n=${a.n} · overall ${a.overall ?? '—'}`}><SimpleTable head={['Question', 'Mean']} rows={(a.per_question ?? []).map((p: Any) => [p.text, p.mean ?? '—'])} /><ul className="list-disc pl-5 text-sm">{(a.comments_masked ?? []).map((c: string, i: number) => <li key={i}>{c}</li>)}</ul></Section>}
    </div>
  );
}

// ---- clubs ------------------------------------------------------------------------------------------------------------------
export function ClubsAdminPage() {
  useTitle('Clubs & activities');
  const q = useQ(['clubs'], () => sa.clubs());
  const hours = useQ(['hours', 'pending'], () => sa.hours({ status: 'pending' }));
  const ach = useQ(['ach', 'pending'], () => sa.achievements({ verified: false }));
  const credit = useQ(['credit'], () => sa.creditEligible());
  const run = useRun();
  const [club, setClub] = useState<Any>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [f, setF] = useState<Any>({ name: '', club_type: 'technical' });
  return (
    <div className="space-y-4">
      <PageHeader title="Clubs & activities" description="Clubs, office bearers, join approvals, events, hours verification, achievements." />
      <Section title="New club"><div className="flex gap-2"><Input placeholder="Name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /><select className={sel} value={f.club_type} onChange={(e) => setF({ ...f, club_type: e.target.value })}>{['technical', 'cultural', 'sports', 'social', 'professional_chapter', 'nss', 'ncc', 'extension'].map((t) => <option key={t}>{t}</option>)}</select><Button size="sm" disabled={f.name.length < 2} onClick={() => run.mutate(() => sa.createClub(f), { onSuccess: () => setF({ name: '', club_type: 'technical' }), onError: fail })}>Create</Button></div></Section>
      <Section title="Clubs"><SimpleTable head={['Club', 'Type', 'Advisor', 'Members', 'Pending', 'Events', '']} rows={list(q.data).map((c: Any) => [c.name, c.club_type, c.advisor_name, c.members, c.pending, c.events, <Button key="o" size="sm" variant="outline" onClick={() => setClub(c)}>Open</Button>])} /></Section>
      {club && <ClubPanel club={club} onClose={() => setClub(null)} />}
      <Section title="Hours verification queue" action={<div className="flex gap-1"><Button size="sm" disabled={!picked.length} onClick={() => run.mutate(() => sa.verifyHours({ ids: picked, approve: true }), { onSuccess: () => setPicked([]), onError: fail })}>Verify {picked.length}</Button><Button size="sm" variant="outline" disabled={!picked.length} onClick={() => run.mutate(() => sa.verifyHours({ ids: picked, approve: false, remarks: 'insufficient evidence' }), { onSuccess: () => setPicked([]), onError: fail })}>Reject</Button></div>}>
        <SimpleTable head={['', 'Student', 'Type', 'Hours', 'Date', 'Evidence']} rows={list(hours.data).slice(0, 200).map((h: Any) => [<input key="c" type="checkbox" checked={picked.includes(h.id)} onChange={(e) => setPicked(e.target.checked ? [...picked, h.id] : picked.filter((x) => x !== h.id))} />, h.student_name, h.activity_type, h.hours, day(h.on_date), h.evidence_url ? <a key="e" className="underline" href={h.evidence_url} target="_blank" rel="noreferrer">view</a> : '—'])} />
      </Section>
      <Section title="Credit-eligible">{credit.error ? <p className="text-sm text-muted-foreground">{getApiError(credit.error)}</p> : <SimpleTable head={['Student', 'Course', 'Verified hours', 'Min', 'Mapped']} rows={list(credit.data).map((r: Any) => [r.student_name, r.course_code, r.verified_hours, r.min_hours, r.mapped ? 'yes' : 'no'])} />}</Section>
      <Section title="Achievements to verify"><SimpleTable head={['Student', 'Title', 'Category', 'Level', '']} rows={list(ach.data).slice(0, 100).map((a: Any) => [a.student_name, a.title, a.category, a.level, <Button key="v" size="sm" variant="outline" onClick={() => run.mutate(() => sa.verifyAchievement(a.id), { onError: fail })}>Verify</Button>])} /></Section>
    </div>
  );
}

function ClubPanel({ club, onClose }: { club: Any; onClose: () => void }) {
  const m = useQ(['members', club.id], () => sa.members(club.id));
  const ev = useQ(['cevents', club.id], () => sa.clubEvents(club.id));
  const run = useRun();
  const [e, setE] = useState<Any>({ title: '', held_on: today(), event_id: '' });
  return (
    <Section title={club.name} action={<Button size="sm" variant="outline" onClick={onClose}>Close</Button>}>
      <SimpleTable head={['Student', 'Role', '']} rows={list(m.data).map((x: Any) => [x.student_name, <StatusBadge key="r" status={x.role} />,
        x.role === 'pending' ? <div key="d" className="flex gap-1"><Button size="sm" onClick={() => run.mutate(() => sa.decideMember(club.id, x.id, true), { onError: fail })}>Approve</Button><Button size="sm" variant="outline" onClick={() => run.mutate(() => sa.decideMember(club.id, x.id, false), { onError: fail })}>Decline</Button></div>
          : <select key="s" className={sel} value={x.role} onChange={(ev2) => run.mutate(() => sa.setRole(club.id, x.id, ev2.target.value), { onError: fail })}>{['member', 'president', 'vice_president', 'secretary', 'treasurer', 'coordinator'].map((r) => <option key={r}>{r}</option>)}</select>])} />
      <div className="flex flex-wrap gap-2"><Input placeholder="Event title" value={e.title} onChange={(x) => setE({ ...e, title: x.target.value })} /><Input type="date" value={e.held_on} onChange={(x) => setE({ ...e, held_on: x.target.value })} /><Input className="w-80" placeholder="Linked event id (Phase 25, optional)" value={e.event_id} onChange={(x) => setE({ ...e, event_id: x.target.value })} /><Button size="sm" disabled={e.title.length < 2} onClick={() => run.mutate(() => sa.addClubEvent(club.id, { title: e.title, held_on: e.held_on, event_id: e.event_id || undefined }), { onError: fail })}>Record event</Button></div>
      <SimpleTable head={['Event', 'Date', 'Participants', 'Linked']} rows={list(ev.data).map((x: Any) => [x.title, day(x.held_on), x.participants_count ?? '—', x.event_title ?? '—'])} />
    </Section>
  );
}

export function StudentClubsPage() {
  useTitle('Clubs & activities');
  const q = useQ(['clubs-all'], () => sa.clubs());
  const led = useQ(['ledger'], () => sa.ledger());
  const ach = useQ(['ach-me'], () => sa.myAchievements());
  const run = useRun();
  const [h, setH] = useState<Any>({ activity_type: 'nss', hours: 2, on_date: today(), description: '', evidence_url: '' });
  const [a, setA] = useState<Any>({ category: 'technical', title: '' });
  const l: Any = led.data?.data ?? {};
  return (
    <div className="space-y-4">
      <PageHeader title="Clubs & activities" description="Join clubs, log hours with evidence, track your ledger and achievements." />
      <Section title="Clubs"><SimpleTable head={['Club', 'Type', 'Members', 'My role', '']} rows={list(q.data).map((c: Any) => [c.name, c.club_type, c.members, c.my_role ?? '—', !c.my_role ? <Button key="j" size="sm" variant="outline" onClick={() => run.mutate(() => sa.join(c.id), { onSuccess: () => toast.success('Request sent'), onError: fail })}>Join</Button> : null])} /></Section>
      <Section title="Log hours">
        <div className="flex flex-wrap gap-2"><select className={sel} value={h.activity_type} onChange={(e) => setH({ ...h, activity_type: e.target.value })}>{ACTIVITY.map((t) => <option key={t}>{t}</option>)}</select><Input className="w-24" type="number" value={h.hours} onChange={(e) => setH({ ...h, hours: Number(e.target.value) })} /><Input type="date" value={h.on_date} onChange={(e) => setH({ ...h, on_date: e.target.value })} /><Input placeholder="Description" value={h.description} onChange={(e) => setH({ ...h, description: e.target.value })} /><Input placeholder="Evidence URL" value={h.evidence_url} onChange={(e) => setH({ ...h, evidence_url: e.target.value })} />
          <Button size="sm" onClick={() => run.mutate(() => sa.logHours({ ...h, evidence_url: h.evidence_url || undefined, description: h.description || undefined }), { onSuccess: () => toast.success('Logged — awaiting verification'), onError: fail })}>Log</Button></div>
      </Section>
      <div className="grid gap-3 md:grid-cols-3"><Stat label="Total hours" value={l.total} /><Stat label="Verified" value={l.verified} /><Stat label="Pending" value={l.pending} /></div>
      <Section title="Ledger"><SimpleTable head={['Date', 'Type', 'Hours', 'Status']} rows={(l.entries ?? []).map((x: Any) => [day(x.on_date), x.activity_type, x.hours, <StatusBadge key="s" status={x.status} />])} /></Section>
      <Section title="Achievements">
        <div className="flex gap-2"><select className={sel} value={a.category} onChange={(e) => setA({ ...a, category: e.target.value })}>{['sports', 'cultural', 'technical', 'research', 'hackathon', 'other'].map((t) => <option key={t}>{t}</option>)}</select><Input placeholder="Title" value={a.title} onChange={(e) => setA({ ...a, title: e.target.value })} /><Button size="sm" disabled={a.title.length < 2} onClick={() => run.mutate(() => sa.submitAchievement(a), { onSuccess: () => setA({ ...a, title: '' }), onError: fail })}>Submit</Button></div>
        <SimpleTable head={['Title', 'Category', 'Verified']} rows={list(ach.data).map((x: Any) => [x.title, x.category, x.verified ? 'yes' : 'pending'])} />
      </Section>
    </div>
  );
}

// ---- student mentor ---------------------------------------------------------------------------------------------------------
export function StudentMentorPage() {
  useTitle('My mentor');
  const q = useQ(['my-mentor'], () => sa.myMentor());
  const ses = useQ(['my-sessions'], () => sa.mySessions());
  const run = useRun();
  const m: Any = q.data?.data ?? {};
  return (
    <div className="space-y-4">
      <PageHeader title="My mentor" description={m.mentor_name ? `${m.mentor_name} · ${m.mentor_email ?? ''}` : 'No mentor assigned yet'} />
      <Section title="Book a slot"><div className="flex flex-wrap gap-2">{(m.next_slots ?? []).map((s: Any) => <Button key={s.id} size="sm" variant="outline" onClick={() => run.mutate(() => sa.bookSlot(s.id), { onSuccess: () => toast.success('Booked'), onError: fail })}>{when(s.starts_at)}</Button>)}{(m.next_slots ?? []).length === 0 && <p className="text-sm text-muted-foreground">No open slots.</p>}</div></Section>
      <Section title="Action items"><ul className="space-y-1 text-sm">{(m.open_action_items ?? []).map((a: Any, i: number) => <li key={i} className="flex items-center gap-2"><input type="checkbox" onChange={(e) => run.mutate(() => sa.tickAction(a.session_id, a.index, e.target.checked))} />{a.text}{a.due_on && ` (due ${day(a.due_on)})`}</li>)}</ul></Section>
      <Section title="Sessions"><SimpleTable head={['Date', 'Mode', 'Notes']} rows={list(ses.data).map((s: Any) => [day(s.held_on), s.mode, s.redacted ? <span key="r" className="flex items-center gap-1 text-muted-foreground"><Lock className="h-3 w-3" /> confidential</span> : s.notes ?? '—'])} /></Section>
    </div>
  );
}

// ---- parent -----------------------------------------------------------------------------------------------------------------
export function ParentSupportPage() {
  useTitle('Mentoring & support');
  const mentors = useQ(['ward-mentors'], () => sa.wardMentors());
  const notes = useQ(['ward-sessions'], () => sa.mySessions());
  const grv = useQ(['ward-grv'], () => sa.wardGrievances());
  const notices = useQ(['ward-cases'], () => sa.myCases());
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Mentoring & support" description="Book a mentor meeting, read shared notes, raise grievances, notices and the parent survey." />
      {list(mentors.data).map((m: Any, i: number) => (
        <Section key={i} title={m.mentor_name ? `Mentor: ${m.mentor_name}` : 'No mentor assigned'}>
          <div className="flex flex-wrap gap-2">{(m.next_slots ?? []).map((s: Any) => <Button key={s.id} size="sm" variant="outline" onClick={() => run.mutate(() => sa.bookSlot(s.id, {}), { onSuccess: () => toast.success('Meeting booked'), onError: fail })}>{when(s.starts_at)}</Button>)}</div>
        </Section>
      ))}
      <Section title="Shared meeting notes"><SimpleTable head={['Date', 'Summary']} rows={list(notes.data).filter((s: Any) => s.guardian_summary).map((s: Any) => [day(s.held_on), s.guardian_summary])} /></Section>
      <RaiseGrievance />
      <Section title="Ward grievances"><GrievanceList rows={list(grv.data)} /></Section>
      <Section title="Disciplinary notices"><SimpleTable head={['Case', 'Status', 'Notices']} rows={list(notices.data).map((c: Any) => [c.case_number, <StatusBadge key="s" status={c.status} />, (c.notices ?? []).map((n: Any) => n.text).join(' · ')])} /></Section>
      <MySurveysPage />
    </div>
  );
}
