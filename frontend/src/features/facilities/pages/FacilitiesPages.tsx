import { useEffect, useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { toast } from '@/components/ui/Toaster';
import { SimpleTable } from '@/features/hr/components/shared';
import { facApi as fa } from '../api';

// Phase 25 web screens (Prompts/25 §25.9). Visibility, conflicts, SLA and confidentiality live in the API.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));
const useQ = <T,>(key: unknown[], fn: () => Promise<T>) => useQuery({ queryKey: ['fac', ...key], queryFn: fn, retry: false });
function useRun() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: () => qc.invalidateQueries({ queryKey: ['fac'] }) });
}
const list = (r: Any) => (Array.isArray(r?.data) ? r.data : r?.data?.items ?? []);
const when = (s?: string | null) => (s ? new Date(s).toLocaleString() : '—');
const day = (s?: string | null) => (s ? new Date(s).toLocaleDateString() : '—');
const rupees = (p?: number | null) => `₹${((p ?? 0) / 100).toLocaleString()}`;
const sel = 'h-9 rounded-md border bg-background px-2 text-sm';

function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <Card><CardContent className="space-y-3 p-4"><div className="flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">{title}</h2>{action}</div>{children}</CardContent></Card>;
}
function Stat({ label, value }: { label: string; value: ReactNode }) {
  return <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{label}</p><p className="text-xl font-semibold">{value}</p></CardContent></Card>;
}

// ---- calendar ------------------------------------------------------------------------------------------------------------
export function CalendarPage() {
  useTitle('Calendar');
  const [scope, setScope] = useState('mine');
  const q = useQ(['cal', scope], () => fa.calendar({ scope }));
  const run = useRun();
  const [feed, setFeed] = useState<Any>(null);
  const [form, setForm] = useState({ title: '', starts_at: '', event_type: 'general' });
  const items = q.data?.data?.items ?? [];
  return (
    <div className="space-y-4">
      <PageHeader title="Calendar" description="Academic calendar merged from terms, holidays, exams, registration windows, events and bookings." actions={<div className="flex gap-2"><select className={sel} value={scope} onChange={(e) => setScope(e.target.value)}>{['mine', 'college', 'institution'].map((s) => <option key={s}>{s}</option>)}</select><Button variant="outline" onClick={() => run.mutate(() => fa.feedToken(), { onSuccess: (r: Any) => setFeed(r?.data), onError: fail })}>Subscribe (iCal)</Button></div>} />
      {feed && <Card><CardContent className="p-4 text-sm">Add to Google / Outlook: <code className="break-all">{feed.webcal_url}</code></CardContent></Card>}
      <Section title={`${items.length} entries`}>
        <SimpleTable head={['Date', 'Title', 'Type', 'Source', 'Location']} rows={items.map((i: Any) => [i.all_day ? day(i.starts_at) : when(i.starts_at), i.title, i.event_type, i.source_type, i.location ?? '—'])} />
      </Section>
      <Section title="Add an entry (calendar managers)">
        <div className="flex flex-wrap gap-2">
          <Input placeholder="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          <Input type="datetime-local" value={form.starts_at} onChange={(e) => setForm({ ...form, starts_at: e.target.value })} />
          <select className={sel} value={form.event_type} onChange={(e) => setForm({ ...form, event_type: e.target.value })}>{['general', 'academic', 'exam', 'holiday', 'registration', 'deadline', 'meeting'].map((t) => <option key={t}>{t}</option>)}</select>
          <Button onClick={() => run.mutate(() => fa.saveEntry({ ...form, starts_at: new Date(form.starts_at).toISOString() }), { onSuccess: () => toast.success('Saved'), onError: fail })}>Add</Button>
        </div>
      </Section>
    </div>
  );
}

// ---- events -------------------------------------------------------------------------------------------------------------
const EVENT_ACTIONS: Record<string, string[]> = { proposed: ['submit', 'approve', 'reject', 'cancel'], approved: ['schedule', 'cancel'], scheduled: ['complete', 'cancel'] };
export function EventsPage() {
  useTitle('Events');
  const [status, setStatus] = useState('');
  const q = useQ(['events', status], () => fa.events({ status: status || undefined }));
  const run = useRun();
  const [form, setForm] = useState<Any>({ event_type: 'seminar', title: '', from_on: '', to_on: '', budget_paise: 0, registration: { open: true, fee_paise: 0 } });
  const [regs, setRegs] = useState<{ id: string; rows: Any[] } | null>(null);
  return (
    <div className="space-y-4">
      <PageHeader title="Events" description="Proposal → approval → budget → venue → registrations → attendance → certificates → report." actions={<select className={sel} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All statuses</option>{['proposed', 'approved', 'scheduled', 'completed', 'cancelled'].map((s) => <option key={s}>{s}</option>)}</select>} />
      <Section title="Propose an event">
        <div className="grid gap-2 md:grid-cols-6">
          <select className={sel} value={form.event_type} onChange={(e) => setForm({ ...form, event_type: e.target.value })}>{['conference', 'seminar', 'workshop', 'fdp', 'guest_lecture', 'cultural', 'sports', 'outreach', 'exhibition', 'alumni', 'other'].map((t) => <option key={t}>{t}</option>)}</select>
          <Input className="md:col-span-2" placeholder="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          <Input type="date" value={form.from_on} onChange={(e) => setForm({ ...form, from_on: e.target.value, to_on: form.to_on || e.target.value })} />
          <Input type="date" value={form.to_on} onChange={(e) => setForm({ ...form, to_on: e.target.value })} />
          <Input type="number" placeholder="Budget ₹" onChange={(e) => setForm({ ...form, budget_paise: Math.round(Number(e.target.value) * 100) })} />
        </div>
        <Button onClick={() => run.mutate(() => fa.createEvent(form), { onSuccess: () => toast.success('Proposed'), onError: fail })}>Save proposal</Button>
      </Section>
      <Section title="Events">
        <SimpleTable head={['Title', 'Type', 'Dates', 'Venue', 'Status', 'Registered', '']} rows={list(q.data).map((e: Any) => [e.title, e.event_type, `${e.from_on} → ${e.to_on}`, e.venue_label ?? '—', <StatusBadge key="s" status={e.status} />, `${e.counts?.registered ?? 0} / attended ${e.counts?.attended ?? 0}`,
          <div key="a" className="flex flex-wrap gap-1">
            {(EVENT_ACTIONS[e.status] ?? []).map((a) => <Button key={a} size="sm" variant="outline" onClick={() => run.mutate(() => fa.eventAction(e.id, a), { onError: fail })}>{a}</Button>)}
            {e.registration?.open && !e.my_registration && ['approved', 'scheduled'].includes(e.status) && <Button size="sm" onClick={() => run.mutate(() => fa.register(e.id), { onSuccess: () => toast.success('Registered'), onError: fail })}>Register</Button>}
            {e.is_organiser && <Button size="sm" variant="outline" onClick={() => fa.registrations(e.id).then((r: Any) => setRegs({ id: e.id, rows: list(r) })).catch(fail)}>Registrations</Button>}
            {e.is_organiser && ['scheduled', 'completed'].includes(e.status) && <Button size="sm" variant="outline" onClick={() => run.mutate(() => fa.certificates(e.id), { onSuccess: () => toast.success('Certificates queued'), onError: fail })}>Certificates</Button>}
          </div>])} />
      </Section>
      {regs && <Section title="Registrations" action={<Button size="sm" variant="outline" onClick={() => setRegs(null)}>Close</Button>}>
        <SimpleTable head={['Name', 'Type', 'Fee', 'Waitlisted', 'Attended', '']} rows={regs.rows.map((r: Any) => [r.name ?? '—', r.person_type, r.fee_status ?? '—', r.waitlisted ? 'yes' : 'no', r.attended ? 'yes' : 'no', !r.attended && <Button key="m" size="sm" variant="outline" onClick={() => run.mutate(() => fa.attendance(regs.id, { registration_ids: [r.id] }), { onSuccess: () => toast.success('Marked'), onError: fail })}>Mark present</Button>])} />
      </Section>}
    </div>
  );
}

// ---- bookings -----------------------------------------------------------------------------------------------------------
export function BookingsPage() {
  useTitle('Room & equipment bookings');
  const q = useQ(['bookings'], () => fa.bookings());
  const eq = useQ(['equipment'], () => fa.equipment().catch(() => ({ data: [] }) as Any));
  const run = useRun();
  const [win, setWin] = useState({ from: '', to: '', purpose: '' });
  const [avail, setAvail] = useState<Any[]>([]);
  const iso = (v: string) => (v ? new Date(v).toISOString() : '');
  return (
    <div className="space-y-4">
      <PageHeader title="Bookings" description="Conflicts are checked against the published timetable, extra classes, exam seating and approved bookings." />
      <Section title="Find a free room">
        <div className="flex flex-wrap gap-2"><Input type="datetime-local" value={win.from} onChange={(e) => setWin({ ...win, from: e.target.value })} /><Input type="datetime-local" value={win.to} onChange={(e) => setWin({ ...win, to: e.target.value })} /><Input placeholder="Purpose" value={win.purpose} onChange={(e) => setWin({ ...win, purpose: e.target.value })} />
          <Button variant="outline" onClick={() => fa.availability({ from_at: iso(win.from), to_at: iso(win.to) }).then((r: Any) => setAvail(r?.data?.rooms ?? [])).catch(fail)}>Check</Button></div>
        <SimpleTable head={['Room', 'Capacity', 'Available', 'Conflicts', '']} rows={avail.map((r: Any) => [`${r.room_code} · ${r.room_name}`, r.capacity, r.available ? 'yes' : 'no', r.conflicts.map((c: Any) => c.title).join(', ') || '—', r.available && <Button key="b" size="sm" onClick={() => run.mutate(() => fa.book({ room_id: r.room_id, from_at: iso(win.from), to_at: iso(win.to), purpose: win.purpose || 'Meeting' }), { onSuccess: () => toast.success('Requested'), onError: fail })}>Book</Button>])} />
      </Section>
      <Section title="Room bookings">
        <SimpleTable head={['Room', 'From', 'To', 'Purpose', 'By', 'Status', '']} rows={list(q.data).map((b: Any) => [b.room_code, when(b.from_at), when(b.to_at), b.purpose, b.requester_name ?? '—', <StatusBadge key="s" status={b.status} />,
          <div key="a" className="flex gap-1">{b.status === 'requested' && <><Button size="sm" variant="outline" onClick={() => run.mutate(() => fa.decide(b.id, 'approve'), { onError: fail })}>Approve</Button><Button size="sm" variant="outline" onClick={() => run.mutate(() => fa.decide(b.id, 'reject'), { onError: fail })}>Reject</Button></>}{['requested', 'approved'].includes(b.status) && <Button size="sm" variant="outline" onClick={() => run.mutate(() => fa.cancelBooking(b.id), { onError: fail })}>Cancel</Button>}</div>])} />
      </Section>
      <Section title="Equipment bookings">
        <SimpleTable head={['Asset', 'From', 'To', 'Status', '']} rows={list(eq.data).map((b: Any) => [`${b.asset_tag} · ${b.asset_name}`, when(b.from_at), when(b.to_at), <StatusBadge key="s" status={b.overdue ? 'overdue' : b.status} />,
          <div key="a" className="flex gap-1">{b.status === 'requested' && <Button size="sm" variant="outline" onClick={() => run.mutate(() => fa.eqAct(b.id, 'decide', { action: 'approve' }), { onError: fail })}>Approve</Button>}{b.status === 'approved' && <Button size="sm" variant="outline" onClick={() => run.mutate(() => fa.eqAct(b.id, 'handover', { condition: 'good' }), { onError: fail })}>Hand over</Button>}{b.status === 'handed_over' && <Button size="sm" variant="outline" onClick={() => run.mutate(() => fa.eqAct(b.id, 'return', { condition: 'good' }), { onError: fail })}>Return</Button>}</div>])} />
      </Section>
    </div>
  );
}

// ---- service desk -------------------------------------------------------------------------------------------------------
const COLUMNS = ['open', 'assigned', 'in_progress', 'reopened', 'resolved'];
export function ServiceDeskPage() {
  useTitle('Service desk');
  const q = useQ(['tickets'], () => fa.tickets());
  const d = useQ(['desk-dash'], () => fa.dashboard());
  const run = useRun();
  const [form, setForm] = useState({ category: 'it', description: '', priority: 'normal' });
  const rows = list(q.data);
  const dash = d.data?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Service desk" description="Maintenance and IT tickets with SLA timers, assignment, vendors / AMC and ratings." />
      {dash && <div className="grid gap-3 md:grid-cols-5"><Stat label="Open" value={dash.open} /><Stat label="SLA breached" value={dash.breached} /><Stat label="Due in 24 h" value={dash.due_24h} /><Stat label="MTTR (h)" value={dash.mttr_hours ?? '—'} /><Stat label="CSAT" value={dash.csat ?? '—'} /></div>}
      <Section title="Raise a ticket">
        <div className="flex flex-wrap gap-2"><select className={sel} value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>{['electrical', 'plumbing', 'it', 'network', 'furniture', 'cleaning', 'civil', 'security', 'asset', 'other'].map((c) => <option key={c}>{c}</option>)}</select>
          <select className={sel} value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>{['low', 'normal', 'high', 'urgent'].map((c) => <option key={c}>{c}</option>)}</select>
          <Input className="flex-1" placeholder="Describe the problem" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          <Button onClick={() => run.mutate(() => fa.raise(form), { onSuccess: () => toast.success('Ticket raised'), onError: fail })}>Raise</Button></div>
      </Section>
      <div className="grid gap-3 lg:grid-cols-5">
        {COLUMNS.map((col) => (
          <Card key={col}><CardContent className="space-y-2 p-3"><h3 className="text-sm font-semibold capitalize">{col.replace('_', ' ')}</h3>
            {rows.filter((r: Any) => r.status === col).slice(0, 40).map((r: Any) => (
              <div key={r.id} className={`rounded border p-2 text-xs ${r.sla_breached ? 'border-red-400' : ''}`}>
                <p className="font-medium">{r.ticket_number} · {r.category}</p><p className="line-clamp-2 text-muted-foreground">{r.description}</p><p>SLA {when(r.sla_due_at)}{r.sla_breached ? ' · breached' : ''}</p>
                <div className="mt-1 flex flex-wrap gap-1">
                  {['open', 'assigned', 'reopened'].includes(col) && <Button size="sm" variant="outline" onClick={() => run.mutate(() => fa.ticketAct(r.id, 'update', { status: 'in_progress' }), { onError: fail })}>Start</Button>}
                  {col !== 'resolved' && <Button size="sm" variant="outline" onClick={() => run.mutate(() => fa.ticketAct(r.id, 'resolve', { resolution: 'Resolved' }), { onError: fail })}>Resolve</Button>}
                  {col === 'resolved' && r.is_mine && <Button size="sm" variant="outline" onClick={() => run.mutate(() => fa.ticketAct(r.id, 'rate', { rating: 5 }), { onError: fail })}>Rate 5 & close</Button>}
                </div>
              </div>
            ))}
          </CardContent></Card>
        ))}
      </div>
    </div>
  );
}

// ---- security ------------------------------------------------------------------------------------------------------------
export function SecurityPage() {
  useTitle('Visitors & emergency');
  const v = useQ(['visitors'], () => fa.visitors().catch(() => ({ data: [] }) as Any));
  const a = useQ(['alerts'], () => fa.alerts().catch(() => ({ data: [] }) as Any));
  const run = useRun();
  const [code, setCode] = useState('');
  const [vis, setVis] = useState({ name: '', phone: '', purpose: '' });
  return (
    <div className="space-y-4">
      <PageHeader title="Security" description="Visitor passes, gate scans and the live SOS board." />
      <Section title="Live alerts">
        <SimpleTable head={['Raised', 'Type', 'By', 'Where', 'Status', '']} rows={list(a.data).map((x: Any) => [when(x.created_at), `${x.drill ? '[DRILL] ' : ''}${x.alert_type}`, x.raised_by_name ?? '—', x.map_url ? <a key="m" className="underline" href={x.map_url} target="_blank" rel="noreferrer">map</a> : x.location?.text ?? '—', <StatusBadge key="s" status={x.status} />,
          <div key="b" className="flex gap-1">{x.status === 'raised' && <Button size="sm" onClick={() => run.mutate(() => fa.alertAct(x.id, 'acknowledge'), { onError: fail })}>Acknowledge</Button>}{x.status !== 'resolved' && <><Button size="sm" variant="outline" onClick={() => run.mutate(() => fa.alertAct(x.id, 'resolve', { notes: 'Resolved' }), { onError: fail })}>Resolve</Button><Button size="sm" variant="outline" onClick={() => run.mutate(() => fa.alertAct(x.id, 'false-alarm'), { onError: fail })}>False alarm</Button></>}</div>])} />
      </Section>
      <Section title="Gate desk">
        <div className="flex flex-wrap gap-2"><Input placeholder="Pass code / QR" value={code} onChange={(e) => setCode(e.target.value)} /><Button onClick={() => run.mutate(() => fa.scan({ pass_code: code, direction: 'in' }), { onSuccess: () => toast.success('Checked in'), onError: fail })}>In</Button><Button variant="outline" onClick={() => run.mutate(() => fa.scan({ pass_code: code, direction: 'out' }), { onSuccess: () => toast.success('Checked out'), onError: fail })}>Out</Button></div>
        <div className="flex flex-wrap gap-2"><Input placeholder="Visitor name" value={vis.name} onChange={(e) => setVis({ ...vis, name: e.target.value })} /><Input placeholder="Phone" value={vis.phone} onChange={(e) => setVis({ ...vis, phone: e.target.value })} /><Input placeholder="Purpose" value={vis.purpose} onChange={(e) => setVis({ ...vis, purpose: e.target.value })} /><Button variant="outline" onClick={() => run.mutate(() => fa.issuePass({ visitor: { name: vis.name, phone: vis.phone }, purpose: vis.purpose }), { onSuccess: (r: Any) => toast.success(`Pass ${r?.data?.pass_code}`), onError: fail })}>Issue pass</Button></div>
        <SimpleTable head={['Code', 'Visitor', 'Host', 'Valid to', 'Status']} rows={list(v.data).slice(0, 100).map((p: Any) => [p.pass_code, p.visitor?.name, p.host_name ?? '—', when(p.valid_to), <StatusBadge key="s" status={p.status} />])} />
      </Section>
    </div>
  );
}

// ---- wellness --------------------------------------------------------------------------------------------------------------
export function WellnessPage() {
  useTitle('Wellness');
  const visits = useQ(['myvisits'], () => fa.myVisits().catch(() => ({ data: [] }) as Any));
  const slots = useQ(['slots'], () => fa.slots().catch(() => ({ data: [] }) as Any));
  const mine = useQ(['appts'], () => fa.myAppointments().catch(() => ({ data: [] }) as Any));
  const stats = useQ(['hstats'], () => fa.healthStats().catch(() => ({ data: null }) as Any));
  const run = useRun();
  const s = stats.data?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Wellness" description="Your health centre visits and counselling appointments are confidential." />
      {s && <div className="grid gap-3 md:grid-cols-4"><Stat label="Visits" value={s.visits} /><Stat label="Referrals" value={s.referrals} /><Stat label="Certificates" value={s.certificates} /><Stat label="Insured" value={s.insured} /></div>}
      <Section title="My health visits"><SimpleTable head={['Date', 'Complaint', 'Diagnosis', 'Referred']} rows={list(visits.data).map((x: Any) => [day(x.visited_at), x.complaint ?? '—', x.diagnosis ?? '—', x.referred_to ?? '—'])} /></Section>
      <Section title="My counselling appointments"><SimpleTable head={['When', 'Counsellor', 'Status']} rows={list(mine.data).map((x: Any) => [when(x.slot_at), x.counsellor_name, <StatusBadge key="s" status={x.status} />])} /></Section>
      <Section title="Book counselling"><SimpleTable head={['When', 'Counsellor', 'Minutes', '']} rows={list(slots.data).slice(0, 30).map((x: Any) => [when(x.slot_at), x.counsellor_name, x.duration_minutes, <Button key="b" size="sm" onClick={() => run.mutate(() => fa.bookSlot(x.id), { onSuccess: () => toast.success('Booked'), onError: fail })}>Book</Button>])} /></Section>
    </div>
  );
}

// ---- sports ---------------------------------------------------------------------------------------------------------------
export function SportsPage() {
  useTitle('Sports');
  const t = useQ(['teams'], () => fa.teams());
  const e = useQ(['sevents'], () => fa.sportsEvents());
  const p = useQ(['participation'], () => fa.participation());
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Sports" description="Teams, events and participation; verified participation becomes a student achievement." />
      <Section title="Teams"><SimpleTable head={['Team', 'Sport', 'Level', 'Coach', 'Members']} rows={list(t.data).map((x: Any) => [x.name ?? '—', x.sport, x.level, x.coach_name ?? '—', (x.members ?? []).length])} /></Section>
      <Section title="Events"><SimpleTable head={['Title', 'Level', 'From', 'Venue', 'Participants']} rows={list(e.data).map((x: Any) => [x.title, x.level, x.from_on, x.venue ?? '—', x.participants])} /></Section>
      <Section title="Participation"><SimpleTable head={['Student', 'Event', 'Result', 'Position', '']} rows={list(p.data).map((x: Any) => [x.student_name ?? '—', x.event_title, x.result ?? '—', x.position ?? '—', x.verified_by ? 'verified' : <Button key="v" size="sm" variant="outline" onClick={() => run.mutate(() => fa.verify(x.id), { onError: fail })}>Verify</Button>])} /></Section>
    </div>
  );
}

// ---- wallet / canteen POS ----------------------------------------------------------------------------------------------
export function WalletPage() {
  useTitle('Wallet');
  const w = useQ(['wallet'], () => fa.wallet().catch(() => ({ data: null }) as Any));
  const run = useRun();
  const [amt, setAmt] = useState('500');
  const [pos, setPos] = useState({ qr: '', amount: '' });
  const data = w.data?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Canteen & wallet" description="Prepaid wallet: top up online, pay at the canteen by QR." />
      {data && <Section title={`Balance ${rupees(data.balance_paise)}`} action={<code className="text-xs">{data.pay_qr}</code>}>
        <div className="flex gap-2"><Input type="number" value={amt} onChange={(e) => setAmt(e.target.value)} /><Button onClick={() => run.mutate(() => fa.topup(Math.round(Number(amt) * 100)), { onSuccess: () => toast.success('Topped up'), onError: fail })}>Top up</Button></div>
        <SimpleTable head={['When', 'Type', 'Amount', 'Merchant']} rows={(data.recent ?? []).map((t: Any) => [when(t.created_at), t.txn_type, rupees(t.amount_paise), t.merchant ?? '—'])} />
      </Section>}
      <Section title="Canteen POS (vendors / estate office)">
        <div className="flex flex-wrap gap-2"><Input placeholder="Wallet QR (W:…)" value={pos.qr} onChange={(e) => setPos({ ...pos, qr: e.target.value })} /><Input type="number" placeholder="₹" value={pos.amount} onChange={(e) => setPos({ ...pos, amount: e.target.value })} /><Button onClick={() => run.mutate(() => fa.debit({ qr: pos.qr, amount_paise: Math.round(Number(pos.amount) * 100) }), { onSuccess: (r: Any) => toast.success(`Paid · balance ${rupees(r?.data?.balance_after_paise)}`), onError: fail })}>Charge</Button></div>
      </Section>
    </div>
  );
}
