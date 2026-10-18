import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download, Printer } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { ScopeTabs } from '@/components/shared/ScopeTabs';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input, Select } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs';
import { toast } from '@/components/ui/Toaster';
import { SimpleTable } from '@/features/hr/components/shared';
import { examsApi, openBlob } from '../api';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));
const useQ = <T,>(key: unknown[], fn: () => Promise<T>, enabled = true) => useQuery({ queryKey: ['exams', ...key], queryFn: fn, enabled, retry: false });
function useRun() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: () => qc.invalidateQueries({ queryKey: ['exams'] }) });
}
const FLOW = ['draft', 'registration_open', 'registration_closed', 'scheduled', 'in_progress', 'valuation', 'result_processing', 'results_published', 'closed'];
const inr = (p?: number | null) => `₹${((p ?? 0) / 100).toLocaleString('en-IN')}`;

// ---- /admin/exams/sessions -------------------------------------------------------------------------------------------
export function ExamSessionsPage() {
  useTitle('Exam sessions');
  const list = useQ(['sessions'], () => examsApi.sessions());
  const [form, setForm] = useState({ name: '', term_id: '', exam_kind: 'regular' });
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Exam sessions" description="Regular / supplementary / arrear / improvement sessions with fee rules, date-sheets and hall tickets." />
      <div className="flex flex-wrap gap-2">
        <Input className="w-64" placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <Input className="w-72" placeholder="Term id" value={form.term_id} onChange={(e) => setForm({ ...form, term_id: e.target.value })} />
        <Select className="w-40" value={form.exam_kind} options={['regular', 'supplementary', 'arrear', 'improvement', 'special', 'practical'].map((k) => ({ value: k, label: k }))} onChange={(e) => setForm({ ...form, exam_kind: e.target.value })} />
        <Button disabled={!form.name || !form.term_id} onClick={() => run.mutate(() => examsApi.createSession(form), { onSuccess: () => toast.success('Session created'), onError: fail })}>Create</Button>
      </div>
      <SimpleTable
        head={['Session', 'Kind', 'Status', 'Papers', 'Confirmed', 'Fee pending', '']}
        rows={(list.data?.data ?? []).map((s: Any) => [s.name, s.exam_kind, <StatusBadge key="s" status={s.status} />, s.counts?.papers ?? 0, s.counts?.confirmed ?? 0, s.counts?.fee_pending ?? 0, <Link key="o" className="text-primary underline" to={`/admin/exams/sessions/${s.id}`}>Open</Link>])}
      />
    </div>
  );
}

function PapersTab({ id }: { id: string }) {
  const papers = useQ(['papers', id], () => examsApi.papers(id));
  const [edits, setEdits] = useState<Record<string, Any>>({});
  const [clash, setClash] = useState<Any | null>(null);
  const run = useRun();
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" onClick={() => run.mutate(() => examsApi.papersBulk(id, true).then((r: Any) => toast.info(`Preview: ${r.data.theory} theory, ${r.data.practical} practical, ${r.data.project_viva} viva, ${r.data.arrear_only} arrear-only, ${r.data.existing} existing`)), { onError: fail })}>Bulk preview</Button>
        <Button onClick={() => run.mutate(() => examsApi.papersBulk(id, false), { onSuccess: () => toast.success('Bulk creation queued — see Jobs'), onError: fail })}>Bulk create</Button>
        <Button disabled={!Object.keys(edits).length} onClick={() => run.mutate(() => examsApi.dateSheet(id, Object.entries(edits).map(([paper_id, e]) => ({ paper_id, ...e }))), { onSuccess: () => { setEdits({}); toast.success('Date-sheet saved'); }, onError: fail })}>Save date-sheet</Button>
        <Button variant="outline" onClick={() => examsApi.clashes(id).then((r: Any) => setClash(r.data)).catch(fail)}>Check clashes</Button>
        <Button variant="outline" onClick={() => run.mutate(() => examsApi.publishDateSheet(id), { onSuccess: () => toast.success('Published'), onError: (e) => { fail(e); } })}>Publish</Button>
        <Button variant="ghost" onClick={() => run.mutate(() => examsApi.publishDateSheet(id, true), { onSuccess: () => toast.success('Force-published (exceptions recorded)'), onError: fail })}>Force publish (COE)</Button>
        <Button variant="ghost" onClick={() => examsApi.dateSheetPdf(id).then((b) => openBlob(b)).catch(fail)}><Download className="h-4 w-4" /> PDF</Button>
        <Button variant="ghost" onClick={() => examsApi.dateSheetIcs(id).then((b) => openBlob(b, 'date-sheet.ics')).catch(fail)}>ICS</Button>
      </div>
      {clash && (
        <Card><CardContent className="space-y-1 p-3 text-sm">
          <p className="font-medium">{clash.items.length} clash(es) · {clash.holidays.length} holiday conflict(s) · {clash.unscheduled.length} unscheduled</p>
          {clash.items.slice(0, 20).map((c: Any, i: number) => <p key={i}>{c.registration_number}: {c.papers.join(' + ')} on {c.exam_date} {c.session_slot}</p>)}
          {clash.holidays.map((h: Any, i: number) => <p key={`h${i}`} className="text-destructive">{h.paper} on {h.date} — {h.holiday}</p>)}
        </CardContent></Card>
      )}
      <SimpleTable
        head={['Paper', 'Course', 'Type', 'Date', 'Slot', 'Registered', 'Status']}
        rows={(papers.data?.data ?? []).map((p: Any) => [
          p.paper_code,
          `${p.course_code} ${p.course_title ?? ''}`,
          p.paper_type,
          <Input key="d" type="date" className="h-8 w-40" defaultValue={p.exam_date ?? ''} onChange={(e) => setEdits({ ...edits, [p.id]: { ...(edits[p.id] ?? { session_slot: p.session_slot ?? 'FN' }), exam_date: e.target.value } })} />,
          <Select key="s" className="h-8 w-20" defaultValue={p.session_slot ?? 'FN'} options={['FN', 'AN', 'EVE'].map((x) => ({ value: x, label: x }))} onChange={(e) => setEdits({ ...edits, [p.id]: { ...(edits[p.id] ?? { exam_date: p.exam_date }), session_slot: e.target.value } })} />,
          p.registered,
          <StatusBadge key="st" status={p.status} />,
        ])}
      />
    </div>
  );
}

function RegistrationsTab({ id }: { id: string }) {
  const [f, setF] = useState({ status: '', search: '', scope: undefined as string | undefined });
  const list = useQ(['regs', id, f], () => examsApi.registrations(id, { status: f.status || undefined, search: f.search || undefined, scope: f.scope, page_size: 100 }));
  const run = useRun();
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <ScopeTabs visibility={list.data?.meta.visibility} value={f.scope} onChange={(scope) => setF({ ...f, scope })} />
        <Select className="w-36" value={f.status} placeholder="Any status" options={['draft', 'fee_pending', 'confirmed', 'cancelled', 'debarred'].map((s) => ({ value: s, label: s }))} onChange={(e) => setF({ ...f, status: e.target.value })} />
        <Input className="w-56" placeholder="Reg. no. / name" value={f.search} onChange={(e) => setF({ ...f, search: e.target.value })} />
        <Button variant="outline" onClick={() => run.mutate(() => examsApi.bulkRegister(id), { onSuccess: () => toast.success('Bulk registration queued'), onError: fail })}>Bulk register</Button>
      </div>
      <SimpleTable
        head={['Student', 'Status', 'Fee', 'Items', 'Hall ticket', '']}
        rows={(list.data?.data ?? []).map((r: Any) => [
          `${r.student_name ?? ''} (${r.registration_number ?? ''})`,
          <StatusBadge key="s" status={r.status} />,
          `${inr(r.total_fee_paise)}${r.invoice_status ? ` · ${r.invoice_status}` : ''}`,
          r.items.map((i: Any) => <Badge key={i.id} variant={['detained', 'debarred'].includes(i.eligibility) ? 'destructive' : 'outline'} className="mr-1">{i.course_code}{i.attempt_type !== 'regular' ? ` (${i.attempt_type})` : ''}</Badge>),
          r.hall_ticket_number ?? '—',
          <div key="a" className="flex gap-1">
            {r.hall_ticket_number && <Button size="sm" variant="ghost" onClick={() => examsApi.hallTicket(r.id).then((b) => openBlob(b)).catch(fail)}><Printer className="h-3 w-3" /></Button>}
            {!['cancelled', 'debarred'].includes(r.status) && <Button size="sm" variant="outline" onClick={() => { const reason = window.prompt('Reason'); if (reason) run.mutate(() => examsApi.regAction(r.id, 'cancel', reason), { onError: fail }); }}>Cancel</Button>}
            {['cancelled', 'debarred'].includes(r.status) && <Button size="sm" variant="outline" onClick={() => run.mutate(() => examsApi.regAction(r.id, 'reinstate', 'reinstated'), { onError: fail })}>Reinstate</Button>}
          </div>,
        ])}
      />
    </div>
  );
}

function EligibilityHallTab({ id }: { id: string }) {
  const sum = useQ(['elig', id], () => examsApi.eligibilitySummary(id));
  const run = useRun();
  const d = sum.data?.data;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => run.mutate(() => examsApi.applyEligibility(id), { onSuccess: () => toast.success('Eligibility apply queued'), onError: fail })}>Apply latest eligibility</Button>
        <Button variant="outline" onClick={() => run.mutate(() => examsApi.applyEligibility(id, true), { onSuccess: () => toast.success('Recompute + apply queued'), onError: fail })}>Recompute & apply</Button>
        <Button onClick={() => run.mutate(() => examsApi.generateHallTickets(id), { onSuccess: () => toast.success('Hall tickets queued — skipped reasons in the job result'), onError: fail })}>Generate hall tickets</Button>
        <Button variant="outline" onClick={() => run.mutate(() => examsApi.generateHallTickets(id, false), { onSuccess: () => toast.success('Regeneration queued'), onError: fail })}>Regenerate all</Button>
      </div>
      <p className="text-sm">{d?.registrations ?? 0} registrations · {d?.items ?? 0} items</p>
      <SimpleTable head={['Eligibility', 'Items']} rows={Object.entries(d?.by_decision ?? {}).map(([k, v]) => [k, String(v)])} />
    </div>
  );
}

function SeatingTab({ id }: { id: string }) {
  const [form, setForm] = useState({ exam_date: '', session_slot: 'FN', rooms: '', strategy: 'mixed_course' });
  const rows = useQ(['seating', id, form.exam_date, form.session_slot], () => examsApi.seating(id, { date: form.exam_date || undefined, slot: form.session_slot }), !!form.exam_date);
  const run = useRun();
  const plans = Array.from(new Map((rows.data?.data ?? []).map((r: Any) => [r.seating_plan_id, r.room_code])).entries());
  const body = (dry: boolean) => ({ exam_date: form.exam_date, session_slot: form.session_slot, room_ids: form.rooms.split(',').map((x) => x.trim()).filter(Boolean), strategy: form.strategy, dry_run: dry });
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Input type="date" className="w-40" value={form.exam_date} onChange={(e) => setForm({ ...form, exam_date: e.target.value })} />
        <Select className="w-20" value={form.session_slot} options={['FN', 'AN', 'EVE'].map((x) => ({ value: x, label: x }))} onChange={(e) => setForm({ ...form, session_slot: e.target.value })} />
        <Input className="w-96" placeholder="Room ids (comma separated)" value={form.rooms} onChange={(e) => setForm({ ...form, rooms: e.target.value })} />
        <Select className="w-36" value={form.strategy} options={[{ value: 'mixed_course', label: 'Mixed course' }, { value: 'by_course', label: 'By course' }]} onChange={(e) => setForm({ ...form, strategy: e.target.value })} />
        <Button variant="outline" disabled={!form.exam_date || !form.rooms} onClick={() => run.mutate(() => examsApi.seatingGenerate(id, body(true)).then((r: Any) => toast.info(`${r.data.candidates} candidates / ${r.data.seats} seats`)), { onError: fail })}>Preview</Button>
        <Button disabled={!form.exam_date || !form.rooms} onClick={() => run.mutate(() => examsApi.seatingGenerate(id, body(false)), { onSuccess: () => toast.success('Seating generated'), onError: fail })}>Generate</Button>
        <Button variant="outline" disabled={!form.exam_date} onClick={() => run.mutate(() => examsApi.publishSeating(id, { date: form.exam_date, slot: form.session_slot }), { onSuccess: () => toast.success('Published — hall tickets regenerated'), onError: fail })}>Publish</Button>
      </div>
      <div className="flex gap-2">{plans.map(([pid, code]) => <span key={String(pid)} className="flex gap-1"><Button size="sm" variant="ghost" onClick={() => examsApi.chart(String(pid)).then((b) => openBlob(b)).catch(fail)}>{String(code)} chart</Button><Button size="sm" variant="ghost" onClick={() => examsApi.chart(String(pid), true).then((b) => openBlob(b)).catch(fail)}>door list</Button></span>)}</div>
      <SimpleTable head={['Room', 'Seat', 'Hall ticket', 'Reg. no.', 'Paper', 'Status']} rows={(rows.data?.data ?? []).map((r: Any) => [r.room_code, r.seat_number, r.hall_ticket_number, r.registration_number, r.paper_code, r.status])} empty="Pick a date / slot." />
    </div>
  );
}

function InvigilationTab({ id }: { id: string }) {
  const [range, setRange] = useState({ from: '', to: '' });
  const roster = useQ(['roster', id], () => examsApi.roster(id));
  const rem = useQ(['remuneration', id], () => examsApi.remuneration(id));
  const run = useRun();
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Input type="date" className="w-40" value={range.from} onChange={(e) => setRange({ ...range, from: e.target.value })} />
        <Input type="date" className="w-40" value={range.to} onChange={(e) => setRange({ ...range, to: e.target.value })} />
        <Button disabled={!range.from || !range.to} onClick={() => run.mutate(() => examsApi.autoAssign(id, { date_from: range.from, date_to: range.to, dry_run: false }), { onSuccess: () => toast.success('Auto-assignment queued'), onError: fail })}>Auto-assign</Button>
      </div>
      <SimpleTable
        head={['Date', 'Slot', 'Room', 'Staff', 'Role', 'Status', '']}
        rows={(roster.data?.data ?? []).map((d: Any) => [d.exam_date, d.session_slot, d.room_code ?? '—', d.staff_name, d.role, <StatusBadge key="s" status={d.status} />, d.status === 'swap_requested' && (
          <div key="b" className="flex gap-1">
            <Button size="sm" onClick={() => run.mutate(() => examsApi.swapDecide(d.id, 'approve'), { onSuccess: () => toast.success('Swapped'), onError: fail })}>Approve swap</Button>
            <Button size="sm" variant="outline" onClick={() => run.mutate(() => examsApi.swapDecide(d.id, 'reject'), { onError: fail })}>Reject</Button>
          </div>
        )])}
      />
      <p className="text-sm">Remuneration total {inr(rem.data?.data?.total_paise)} · {Object.entries(rem.data?.data?.by_role ?? {}).map(([k, v]) => `${k} ${inr(v as number)}`).join(' · ')}</p>
    </div>
  );
}

function QpTab({ id }: { id: string }) {
  const papers = useQ(['papers', id], () => examsApi.papers(id));
  const [paper, setPaper] = useState('');
  const sets = useQ(['qp', paper], () => examsApi.qp(paper), !!paper);
  const [form, setForm] = useState({ set_label: 'A', setter_staff_id: '', external: '' });
  const run = useRun();
  return (
    <div className="space-y-3">
      <Select className="w-80" value={paper} placeholder="Paper" options={(papers.data?.data ?? []).map((p: Any) => ({ value: p.id, label: `${p.paper_code} ${p.course_title ?? ''}` }))} onChange={(e) => setPaper(e.target.value)} />
      {paper && (
        <div className="flex flex-wrap gap-2">
          <Input className="w-16" value={form.set_label} onChange={(e) => setForm({ ...form, set_label: e.target.value })} />
          <Input className="w-72" placeholder="Internal setter staff id" value={form.setter_staff_id} onChange={(e) => setForm({ ...form, setter_staff_id: e.target.value })} />
          <Input className="w-56" placeholder="or external setter name" value={form.external} onChange={(e) => setForm({ ...form, external: e.target.value })} />
          <Button onClick={() => run.mutate(() => examsApi.qpCreate(paper, { set_label: form.set_label, setter_staff_id: form.setter_staff_id || null, external_setter: form.external ? { name: form.external } : null }), { onSuccess: () => toast.success('Setter invited'), onError: fail })}>Invite setter</Button>
        </div>
      )}
      <SimpleTable
        head={['Set', 'Setter', 'Status', 'File', '']}
        rows={(sets.data?.data ?? []).map((a: Any) => [a.set_label, a.setter_name, <StatusBadge key="s" status={a.status} />, a.has_file ? 'encrypted' : '—', (
          <div key="b" className="flex gap-1">
            {a.status === 'submitted' && <Button size="sm" onClick={() => run.mutate(() => examsApi.qpScrutinise(a.id, 'approve'), { onError: fail })}>Approve</Button>}
            {a.status === 'approved' && <Button size="sm" onClick={() => run.mutate(() => examsApi.qpSelect(a.id), { onSuccess: () => toast.success('Selected'), onError: fail })}>Select</Button>}
            {['selected', 'printed'].includes(a.status) && <Button size="sm" variant="outline" onClick={() => { const copies = Number(window.prompt('Copies', '60')); if (copies) examsApi.qpPrint(a.id, copies).then((r: Any) => examsApi.qpDownload(r.data.download_token)).then((b) => openBlob(b)).catch(fail); }}>Print</Button>}
          </div>
        )])}
      />
    </div>
  );
}

function ConductTab({ id }: { id: string }) {
  const papers = useQ(['papers', id], () => examsApi.papers(id));
  const [paper, setPaper] = useState('');
  const roster = useQ(['hall', paper], () => examsApi.hallRoster(paper), !!paper);
  const [rows, setRows] = useState<Record<string, Any>>({});
  const [mal, setMal] = useState<Any | null>(null);
  const [report, setReport] = useState('');
  const run = useRun();
  return (
    <div className="space-y-3">
      <Select className="w-80" value={paper} placeholder="Paper" options={(papers.data?.data ?? []).map((p: Any) => ({ value: p.id, label: `${p.paper_code} ${p.exam_date ?? ''} ${p.session_slot ?? ''}` }))} onChange={(e) => setPaper(e.target.value)} />
      {paper && <Button disabled={!Object.keys(rows).length} onClick={() => run.mutate(() => examsApi.markHall(paper, Object.entries(rows).map(([exam_registration_item_id, r]) => ({ exam_registration_item_id, ...r }))), { onSuccess: () => { setRows({}); toast.success('Saved'); }, onError: fail })}>Save attendance</Button>}
      <SimpleTable
        head={['Room / seat', 'Hall ticket', 'Student', 'Status', 'Booklet no.', '']}
        rows={(roster.data?.data ?? []).map((r: Any) => [
          `${r.room_code ?? '—'} ${r.seat_number ?? ''}`,
          r.hall_ticket_number,
          r.student_name,
          <Select key="s" className="h-8 w-28" value={rows[r.exam_registration_item_id]?.status ?? r.status ?? ''} placeholder="—" options={['present', 'absent', 'late'].map((x) => ({ value: x, label: x }))} onChange={(e) => setRows({ ...rows, [r.exam_registration_item_id]: { ...(rows[r.exam_registration_item_id] ?? { answer_booklet_number: r.answer_booklet_number }), status: e.target.value } })} />,
          <Input key="b" className="h-8 w-32" defaultValue={r.answer_booklet_number ?? ''} onChange={(e) => setRows({ ...rows, [r.exam_registration_item_id]: { ...(rows[r.exam_registration_item_id] ?? { status: r.status ?? 'present' }), answer_booklet_number: e.target.value || null } })} />,
          <Button key="m" size="sm" variant="ghost" onClick={() => setMal(r)}>Malpractice</Button>,
        ])}
      />
      <Modal open={!!mal} onOpenChange={(o) => !o && setMal(null)} title={`Malpractice — ${mal?.hall_ticket_number ?? ''}`}
        footer={<Button disabled={report.length < 3} onClick={() => run.mutate(() => examsApi.malpractice(paper, { exam_registration_item_id: mal.exam_registration_item_id, category: 'material', invigilator_report: report }), { onSuccess: () => { toast.success('Reported'); setMal(null); }, onError: fail })}>Report</Button>}>
        <Input placeholder="Invigilator report" value={report} onChange={(e) => setReport(e.target.value)} />
      </Modal>
    </div>
  );
}

export function ExamSessionWorkspacePage() {
  const { id } = useParams();
  const s = useQ(['session', id], () => examsApi.session(id!), !!id);
  const run = useRun();
  const d = s.data?.data;
  useTitle(d?.name ?? 'Exam session');
  if (!id) return null;
  const next = d ? FLOW[FLOW.indexOf(d.status) + 1] : undefined;
  return (
    <div className="space-y-4">
      <PageHeader title={d?.name ?? 'Exam session'} description={d ? `${d.exam_kind} · ${d.status}${d.is_locked ? ' · locked' : ''}` : ''} />
      {next && <Button variant="outline" onClick={() => run.mutate(() => examsApi.status(id, next), { onSuccess: () => toast.success(`→ ${next}`), onError: fail })}>Move to {next.replace(/_/g, ' ')}</Button>}
      <Tabs defaultValue="papers">
        <TabsList>
          <TabsTrigger value="papers">Papers & date-sheet</TabsTrigger>
          <TabsTrigger value="registrations">Registrations</TabsTrigger>
          <TabsTrigger value="eligibility">Eligibility & hall tickets</TabsTrigger>
          <TabsTrigger value="seating">Seating</TabsTrigger>
          <TabsTrigger value="invigilation">Invigilation</TabsTrigger>
          <TabsTrigger value="qp">Question papers</TabsTrigger>
          <TabsTrigger value="conduct">Conduct</TabsTrigger>
        </TabsList>
        <TabsContent value="papers"><PapersTab id={id} /></TabsContent>
        <TabsContent value="registrations"><RegistrationsTab id={id} /></TabsContent>
        <TabsContent value="eligibility"><EligibilityHallTab id={id} /></TabsContent>
        <TabsContent value="seating"><SeatingTab id={id} /></TabsContent>
        <TabsContent value="invigilation"><InvigilationTab id={id} /></TabsContent>
        <TabsContent value="qp"><QpTab id={id} /></TabsContent>
        <TabsContent value="conduct"><ConductTab id={id} /></TabsContent>
      </Tabs>
    </div>
  );
}

// ---- faculty -----------------------------------------------------------------------------------------------------------
export function MyDutiesPage() {
  useTitle('My exam duties');
  const duties = useQ(['my-duties'], () => examsApi.myDuties());
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="My exam duties" description="Invigilation duties, swap requests and duty letters." />
      <SimpleTable
        head={['Date', 'Slot', 'Room', 'Role', 'Status', '']}
        rows={(duties.data?.data ?? []).map((d: Any) => [d.exam_date, d.session_slot, d.room_code ?? '—', d.role, <StatusBadge key="s" status={d.status} />, (
          <div key="b" className="flex gap-1">
            <Button size="sm" variant="ghost" onClick={() => examsApi.dutyLetter(d.id).then((b) => openBlob(b)).catch(fail)}>Letter</Button>
            {['assigned', 'accepted'].includes(d.status) && <Button size="sm" variant="outline" onClick={() => { const reason = window.prompt('Reason for the swap'); if (reason) run.mutate(() => examsApi.swapRequest(d.id, reason), { onSuccess: () => toast.success('Swap requested'), onError: fail }); }}>Request swap</Button>}
          </div>
        )])}
        empty="No duties."
      />
    </div>
  );
}

export function MyQpPage() {
  useTitle('Question paper setting');
  const list = useQ(['my-qp'], () => examsApi.myQp());
  const [file, setFile] = useState<Record<string, File>>({});
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Question paper setting" description="Upload your set (stored encrypted) or generate it from the blueprint." />
      <SimpleTable
        head={['Paper', 'Set', 'Status', 'Due', '']}
        rows={(list.data?.data ?? []).map((a: Any) => [`${a.paper_code} ${a.course_code ?? ''}`, a.set_label, <StatusBadge key="s" status={a.status} />, a.due_at ?? '—', (
          <div key="b" className="flex flex-wrap gap-1">
            <input type="file" accept=".pdf,.docx" onChange={(e) => e.target.files?.[0] && setFile({ ...file, [a.id]: e.target.files[0] })} />
            <Button size="sm" disabled={!file[a.id]} onClick={() => run.mutate(() => examsApi.qpUpload(a.id, file[a.id]), { onSuccess: () => toast.success('Uploaded'), onError: fail })}>Upload</Button>
            {a.blueprint_id && <Button size="sm" variant="outline" onClick={() => run.mutate(() => examsApi.qpGenerate(a.id), { onSuccess: () => toast.success('Generated'), onError: fail })}>Generate</Button>}
          </div>
        )])}
        empty="No assignments."
      />
    </div>
  );
}

// ---- student / parent ----------------------------------------------------------------------------------------------------
export function StudentExamsPage({ wardId }: { wardId?: string }) {
  useTitle('Exams');
  const reg = useQ(['my-reg', wardId], () => examsApi.myRegistration({ student_id: wardId }));
  const seats = useQ(['my-seats'], () => examsApi.mySeats(), !wardId);
  const run = useRun();
  const r = reg.data?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Exams" description="Register and pay, download your hall ticket, see your seats." />
      {reg.error && <p className="text-sm text-muted-foreground">{getApiError(reg.error)}</p>}
      {r && (
        <Card><CardContent className="space-y-3 p-4">
          <p className="font-medium">{r.session_name} · <StatusBadge status={r.status} /> {r.hall_ticket_number && <Badge variant="info">HT {r.hall_ticket_number}</Badge>}</p>
          {r.holds.length > 0 && <p className="rounded bg-destructive/10 p-2 text-sm text-destructive">Holds: {r.holds.join('; ')}</p>}
          <SimpleTable head={['Course', 'Type', 'Attempt', 'Date', 'Eligibility', 'Fee', 'Seat']} rows={r.items.map((i: Any) => [`${i.course_code} ${i.course_title ?? ''}`, i.paper_type, `${i.attempt_type} #${i.attempt_number}`, `${i.exam_date ?? 'TBA'} ${i.session_slot ?? ''}`, i.eligibility, inr(i.fee_paise), i.seat ? `${i.seat.room} / ${i.seat.seat}` : '—'])} />
          <p className="text-sm">Total {inr(r.total_fee_paise)}{r.late_fee_paise ? ` (incl. late fee ${inr(r.late_fee_paise)})` : ''}{r.invoice_status ? ` · invoice ${r.invoice_status}` : ''}</p>
          <div className="flex gap-2">
            {!wardId && r.status === 'draft' && <Button onClick={() => run.mutate(() => examsApi.submit(), { onSuccess: () => toast.success('Submitted — pay from Fees'), onError: fail })}>Submit registration</Button>}
            {r.status === 'fee_pending' && <Link className="self-center text-sm text-primary underline" to={wardId ? '/parent/fees' : '/student/fees'}>Pay the exam fee</Link>}
            {!wardId && r.hall_ticket_available && <Button variant="outline" onClick={() => examsApi.myHallTicket().then((b) => openBlob(b, `hall-ticket-${r.hall_ticket_number}.pdf`)).catch(fail)}><Download className="h-4 w-4" /> Hall ticket</Button>}
          </div>
        </CardContent></Card>
      )}
      {!wardId && (seats.data?.data ?? []).length > 0 && <SimpleTable head={['Course', 'Date', 'Slot', 'Room', 'Seat']} rows={(seats.data?.data ?? []).map((s: Any) => [s.course, s.date, s.slot, `${s.room} ${s.room_name ?? ''}`, s.seat])} />}
    </div>
  );
}

export function ParentExamsPage() {
  const { studentId } = useParams();
  return <StudentExamsPage wardId={studentId} />;
}
