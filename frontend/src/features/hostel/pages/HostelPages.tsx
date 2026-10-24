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
import { hostelApi } from '../api';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));
const useQ = <T,>(key: unknown[], fn: () => Promise<T>, enabled = true) => useQuery({ queryKey: ['hostel', ...key], queryFn: fn, enabled, retry: false });
function useRun() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: () => qc.invalidateQueries({ queryKey: ['hostel'] }) });
}
const rupees = (p: number | null | undefined) => `₹${((p ?? 0) / 100).toLocaleString('en-IN')}`;
const dt = (v?: string | null) => (v ? new Date(v).toLocaleString() : '—');
const list = (r: Any) => (Array.isArray(r?.data) ? r.data : r?.data?.items ?? []);
const openBlob = (b: Blob, name: string) => { const u = URL.createObjectURL(b); const a = document.createElement('a'); a.href = u; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(u), 30000); };

function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <Card><CardContent className="space-y-3 p-4"><div className="flex items-center justify-between"><h2 className="text-sm font-semibold">{title}</h2>{action}</div>{children}</CardContent></Card>;
}

function HostelPicker({ value, onChange, all = true }: { value: string; onChange: (v: string) => void; all?: boolean }) {
  const q = useQ(['hostels'], () => hostelApi.hostels());
  return (
    <select className="h-9 rounded-md border bg-background px-2 text-sm" value={value} onChange={(e) => onChange(e.target.value)}>
      {all && <option value="">All my hostels</option>}
      {!all && <option value="">Hostel…</option>}
      {list(q.data).map((h: Any) => <option key={h.id} value={h.id}>{h.name}</option>)}
    </select>
  );
}

// ---- /admin/hostel/hostels (+ occupancy map) -----------------------------------------------------------------------------------
export function HostelsPage() {
  useTitle('Hostels');
  const q = useQ(['hostels'], () => hostelApi.hostels());
  const colleges = useQ(['colleges'], () => hostelApi.colleges());
  const [sel, setSel] = useState<Any | null>(null);
  const occ = useQ(['occ', sel?.id], () => hostelApi.occupancy(sel.id), !!sel);
  const blocks = useQ(['blocks', sel?.id], () => hostelApi.blocks(sel.id), !!sel);
  const [form, setForm] = useState<Any | null>(null);
  const [bulk, setBulk] = useState<Any | null>(null);
  const run = useRun();
  const scopes: string[] = (q.data as Any)?.meta?.visibility?.scopes ?? [];
  return (
    <div className="space-y-4">
      <PageHeader title="Hostels" description={`Structure, occupancy and fee plans${scopes.length ? ` · scope: ${scopes.join(', ')}` : ''}.`} actions={<Button onClick={() => setForm({ college_id: '', name: '', hostel_type: 'boys' })}>New hostel</Button>} />
      <div className="grid gap-3 md:grid-cols-3">
        {list(q.data).map((h: Any) => (
          <Card key={h.id} className={sel?.id === h.id ? 'ring-2 ring-primary' : ''}><CardContent className="space-y-1 p-4 text-sm">
            <p className="font-medium">{h.name} <Badge variant="outline">{h.hostel_type}</Badge></p>
            <p>{h.occupied} checked in · {h.allotted} allotted · {h.vacant} vacant of {h.capacity}</p>
            <p className="text-xs text-muted-foreground">{h.blocks} blocks · warden {h.warden_name ?? '—'}</p>
            <div className="flex gap-1 pt-1"><Button size="sm" variant="outline" onClick={() => setSel(h)}>Occupancy</Button><Button size="sm" variant="ghost" onClick={() => hostelApi.rulesPdf(h.id).then((b) => openBlob(b, `${h.name}-rules.pdf`)).catch(fail)}>Rules PDF</Button></div>
          </CardContent></Card>
        ))}
      </div>
      {sel && occ.data && (
        <Section title={`${sel.name} — occupancy`} action={<Button size="sm" onClick={() => setBulk({ block_id: list(blocks.data)[0]?.id ?? '', floor_from: 1, floor_to: 4, rooms_per_floor: 10, room_type: 'double', number_pattern: '{floor}{seq:02}' })}>Add rooms</Button>}>
          <div className="flex flex-wrap gap-2 text-xs">{Object.entries((occ.data as Any).data.totals).map(([k, v]) => <Badge key={k} variant="outline">{k}: {String(v)}</Badge>)}</div>
          {(occ.data as Any).data.blocks.map((b: Any) => (
            <div key={b.id} className="space-y-1">
              <p className="text-xs font-semibold">Block {b.name}</p>
              <div className="flex flex-wrap gap-1">
                {b.rooms.map((r: Any) => (
                  <div key={r.id} className="rounded border p-1 text-[10px]" title={`${r.room_type}${r.status !== 'available' ? ` · ${r.status}` : ''}`}>
                    <p className="font-medium">{r.room_number}</p>
                    <div className="flex gap-0.5">{r.beds.map((bed: Any) => <span key={bed.id} title={bed.resident ? `${bed.resident} (${bed.registration_number})` : bed.status} className={`inline-block h-3 w-3 rounded-sm ${bed.status === 'blocked' ? 'bg-muted-foreground' : bed.allocation_id ? (bed.status === 'allocated' ? 'bg-emerald-500' : 'bg-amber-400') : 'bg-muted'}`} />)}</div>
                  </div>
                ))}
              </div>
            </div>
          ))}
          <p className="text-xs text-muted-foreground">Green = checked in · amber = allotted · grey = vacant · dark = blocked.</p>
        </Section>
      )}
      <Modal open={!!form} onOpenChange={(o) => !o && setForm(null)} title="New hostel" footer={<Button disabled={!form?.name || !form?.college_id} onClick={() => run.mutate(() => hostelApi.createHostel(form), { onSuccess: () => { toast.success('Created'); setForm(null); }, onError: fail })}>Create</Button>}>
        {form && <div className="space-y-2 text-sm">
          <select className="h-9 w-full rounded-md border bg-background px-2" value={form.college_id} onChange={(e) => setForm({ ...form, college_id: e.target.value })}><option value="">College…</option>{list(colleges.data).map((c: Any) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
          <Input placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <select className="h-9 w-full rounded-md border bg-background px-2" value={form.hostel_type} onChange={(e) => setForm({ ...form, hostel_type: e.target.value })}>{['boys', 'girls', 'coed', 'pg', 'international', 'staff'].map((t) => <option key={t}>{t}</option>)}</select>
        </div>}
      </Modal>
      <Modal open={!!bulk} onOpenChange={(o) => !o && setBulk(null)} title="Generate rooms" footer={<Button disabled={!bulk?.block_id} onClick={() => run.mutate(() => hostelApi.bulkRooms(sel.id, { ...bulk, floor_from: Number(bulk.floor_from), floor_to: Number(bulk.floor_to), rooms_per_floor: Number(bulk.rooms_per_floor) }), { onSuccess: (r: Any) => { toast.success(r?.message ?? 'Rooms created'); setBulk(null); }, onError: fail })}>Generate</Button>}>
        {bulk && <div className="grid grid-cols-2 gap-2 text-sm">
          <select className="col-span-2 h-9 rounded-md border bg-background px-2" value={bulk.block_id} onChange={(e) => setBulk({ ...bulk, block_id: e.target.value })}><option value="">Block…</option>{list(blocks.data).map((b: Any) => <option key={b.id} value={b.id}>{b.name}</option>)}</select>
          <label>Floor from <Input type="number" value={bulk.floor_from} onChange={(e) => setBulk({ ...bulk, floor_from: e.target.value })} /></label>
          <label>Floor to <Input type="number" value={bulk.floor_to} onChange={(e) => setBulk({ ...bulk, floor_to: e.target.value })} /></label>
          <label>Rooms per floor <Input type="number" value={bulk.rooms_per_floor} onChange={(e) => setBulk({ ...bulk, rooms_per_floor: e.target.value })} /></label>
          <label>Type <select className="h-9 w-full rounded-md border bg-background px-2" value={bulk.room_type} onChange={(e) => setBulk({ ...bulk, room_type: e.target.value })}>{['single', 'double', 'triple', 'dorm'].map((t) => <option key={t}>{t}</option>)}</select></label>
          <label className="col-span-2">Number pattern <Input value={bulk.number_pattern} onChange={(e) => setBulk({ ...bulk, number_pattern: e.target.value })} /></label>
        </div>}
      </Modal>
    </div>
  );
}

// ---- /admin/hostel/applications ------------------------------------------------------------------------------------------------
export function ApplicationsPage() {
  useTitle('Hostel applications');
  const [status, setStatus] = useState('');
  const q = useQ(['apps', status], () => hostelApi.applications({ status: status || undefined }));
  const [preview, setPreview] = useState<Any | null>(null);
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Applications & allotment" description="Priority-scored applications; allotment walks preferences in score order — the rest are wait-listed." />
      <div className="flex flex-wrap items-center gap-2">
        <select className="h-9 rounded-md border bg-background px-2 text-sm" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All</option>{['applied', 'waitlisted', 'allotted', 'declined', 'cancelled'].map((s) => <option key={s}>{s}</option>)}</select>
        <Button variant="outline" onClick={() => run.mutate(() => hostelApi.allot({ dry_run: true }).then((r: Any) => setPreview(r.data)), { onError: fail })}>Dry run</Button>
        <Button onClick={() => run.mutate(() => hostelApi.allot({ dry_run: false }), { onSuccess: () => toast.success('Allotment run queued'), onError: fail })}>Run allotment</Button>
        {preview && <span className="text-sm">Dry run: {preview.allotted} allotted · {preview.waitlisted} wait-listed {Object.entries(preview.by_hostel ?? {}).map(([k, v]) => `· ${k} ${String(v)}`).join(' ')}</span>}
      </div>
      <SimpleTable head={['Reg. no', 'Name', 'Score', 'Pref. type', 'Distance', 'Status', 'Position', '']} rows={list(q.data).map((a: Any) => [a.student.registration_number, a.student.name, a.priority_score ?? '—', a.room_type_pref ?? '—', a.distance_km ?? '—', <StatusBadge key="s" status={a.status} />, a.position ?? '—',
        ['applied', 'waitlisted'].includes(a.status) ? <Button key="d" size="sm" variant="ghost" onClick={() => run.mutate(() => hostelApi.decline(a.id), { onError: fail })}>Decline</Button> : null])} />
    </div>
  );
}

// ---- /admin/hostel/allocations -------------------------------------------------------------------------------------------------
export function AllocationsPage() {
  useTitle('Hostel allocations');
  const [tab, setTab] = useState('allotted');
  const [hostel, setHostel] = useState('');
  const q = useQ(['allocs', tab, hostel], () => hostelApi.allocations({ status: tab, hostel_id: hostel || undefined }));
  const [dialog, setDialog] = useState<{ kind: 'checkin' | 'transfer' | 'vacate' | 'evict'; a: Any } | null>(null);
  const [f, setF] = useState<Any>({});
  const run = useRun();
  const act = () => {
    const a = dialog!.a;
    const call = dialog!.kind === 'checkin' ? hostelApi.checkIn(a.id, { room_condition: { notes: f.notes ?? 'ok' }, inventory: (f.inventory ?? 'bed,table,chair').split(',').map((s: string) => s.trim()) })
      : dialog!.kind === 'transfer' ? hostelApi.transfer(a.id, { new_bed_id: f.bed_id, reason: f.reason ?? 'transfer' })
        : dialog!.kind === 'vacate' ? hostelApi.vacate(a.id, { room_condition: { notes: f.notes ?? '' }, damages: f.damage ? [{ item: f.damage_item || 'Damages', amount_paise: Math.round(Number(f.damage) * 100) }] : [] })
          : hostelApi.evict(a.id, { reason: f.reason ?? '' });
    run.mutate(() => call, { onSuccess: () => { toast.success('Done'); setDialog(null); setF({}); }, onError: fail });
  };
  return (
    <div className="space-y-4">
      <PageHeader title="Allocations" description="Check-in with room condition, transfer, vacate (damages → no-dues → deposit refund), eviction (warden → registrar)." />
      <div className="flex flex-wrap gap-2">{['allotted', 'checked_in', 'vacated', 'transferred', 'evicted'].map((t) => <Button key={t} size="sm" variant={tab === t ? 'default' : 'outline'} onClick={() => setTab(t)}>{t.replace('_', ' ')}</Button>)}<HostelPicker value={hostel} onChange={setHostel} /></div>
      <SimpleTable head={['Reg. no', 'Name', 'Hostel', 'Room / bed', 'Fee', 'Deposit', 'Status', '']} rows={list(q.data).map((a: Any) => [a.student.registration_number, a.student.name, a.hostel, `${a.room_number ?? ''} ${a.bed_label ?? ''}`, <StatusBadge key="f" status={a.fee_status ?? '—'} />, <StatusBadge key="d" status={a.deposit_status ?? '—'} />, <StatusBadge key="s" status={a.status} />,
        <div key="b" className="flex flex-wrap gap-1">
          {a.status === 'allotted' && <Button size="sm" onClick={() => setDialog({ kind: 'checkin', a })}>Check in</Button>}
          {['allotted', 'checked_in'].includes(a.status) && <><Button size="sm" variant="outline" onClick={() => setDialog({ kind: 'transfer', a })}>Transfer</Button><Button size="sm" variant="outline" onClick={() => setDialog({ kind: 'vacate', a })}>Vacate</Button><Button size="sm" variant="destructive" onClick={() => setDialog({ kind: 'evict', a })}>Evict</Button></>}
        </div>])} />
      <Modal open={!!dialog} onOpenChange={(o) => !o && setDialog(null)} title={dialog ? `${dialog.kind} — ${dialog.a.student.name}` : ''} footer={<Button onClick={act}>Confirm</Button>}>
        <div className="space-y-2 text-sm">
          {dialog?.kind === 'checkin' && <><Input placeholder="Room condition notes" value={f.notes ?? ''} onChange={(e) => setF({ ...f, notes: e.target.value })} /><Input placeholder="Inventory (comma separated)" value={f.inventory ?? 'bed,table,chair,cupboard'} onChange={(e) => setF({ ...f, inventory: e.target.value })} /></>}
          {dialog?.kind === 'transfer' && <><Input placeholder="New bed id (from the occupancy map)" value={f.bed_id ?? ''} onChange={(e) => setF({ ...f, bed_id: e.target.value })} /><Input placeholder="Reason" value={f.reason ?? ''} onChange={(e) => setF({ ...f, reason: e.target.value })} /></>}
          {dialog?.kind === 'vacate' && <><Input placeholder="Condition notes" value={f.notes ?? ''} onChange={(e) => setF({ ...f, notes: e.target.value })} /><Input placeholder="Damage item" value={f.damage_item ?? ''} onChange={(e) => setF({ ...f, damage_item: e.target.value })} /><Input type="number" placeholder="Damage charge (₹)" value={f.damage ?? ''} onChange={(e) => setF({ ...f, damage: e.target.value })} /></>}
          {dialog?.kind === 'evict' && <textarea className="min-h-20 w-full rounded-md border bg-background p-2" placeholder="Reason" value={f.reason ?? ''} onChange={(e) => setF({ ...f, reason: e.target.value })} />}
        </div>
      </Modal>
    </div>
  );
}

// ---- /admin/hostel/room-changes --------------------------------------------------------------------------------------------------
export function RoomChangesPage() {
  useTitle('Room changes');
  const q = useQ(['rc'], () => hostelApi.roomChanges({ status: 'requested' }));
  const [bed, setBed] = useState<Record<string, string>>({});
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Room change requests" description="Approve with a target bed — the transfer runs at once." />
      <SimpleTable head={['Student', 'Reason', 'Requested bed', 'Target bed', '']} rows={list(q.data).map((r: Any) => [r.student?.name, r.reason, r.requested_bed_id ?? '—', <Input key="b" className="w-72" placeholder="Bed id" value={bed[r.id] ?? r.requested_bed_id ?? ''} onChange={(e) => setBed({ ...bed, [r.id]: e.target.value })} />,
        <div key="a" className="flex gap-1"><Button size="sm" onClick={() => run.mutate(() => hostelApi.decideRoomChange(r.id, { approve: true, bed_id: bed[r.id] || r.requested_bed_id }), { onSuccess: () => toast.success('Applied'), onError: fail })}>Approve</Button><Button size="sm" variant="ghost" onClick={() => run.mutate(() => hostelApi.decideRoomChange(r.id, { approve: false }), { onError: fail })}>Reject</Button></div>])} empty="No open requests." />
    </div>
  );
}

// ---- /admin/hostel/roll-call ---------------------------------------------------------------------------------------------------
export function RollCallPage() {
  useTitle('Night roll-call');
  const [hostel, setHostel] = useState('');
  const today = new Date().toISOString().slice(0, 10);
  const q = useQ(['rc-today', hostel], () => hostelApi.rollCalls({ hostel_id: hostel, on_date: today }), !!hostel);
  const history = useQ(['rc-hist', hostel], () => hostelApi.rollCalls({ hostel_id: hostel }), !!hostel);
  const [marks, setMarks] = useState<Record<string, string>>({});
  const run = useRun();
  const rc = list(q.data)[0];
  return (
    <div className="space-y-4">
      <PageHeader title="Night roll-call" description="Residents on approved leave are pre-filled; unmarked residents become absent after the cut-off." />
      <div className="flex gap-2"><HostelPicker value={hostel} onChange={setHostel} all={false} />{hostel && !rc && <Button onClick={() => run.mutate(() => hostelApi.startRollCall({ hostel_id: hostel }), { onError: fail })}>Start tonight's roll-call</Button>}</div>
      {rc && (
        <Section title={`Tonight · ${Object.entries(rc.counts).map(([k, v]) => `${k} ${String(v)}`).join(' · ')}`} action={<Button size="sm" onClick={() => run.mutate(() => hostelApi.markRollCall(rc.id, Object.entries(marks).map(([allocation_id, status]) => ({ allocation_id, status }))), { onSuccess: () => { toast.success('Saved'); setMarks({}); }, onError: fail })}>Save {Object.keys(marks).length || ''}</Button>}>
          <SimpleTable head={['Room', 'Student', 'Status']} rows={rc.entries.map((e: Any) => [e.room_number, e.student.name, (
            <div key="s" className="flex gap-1">{['present', 'absent', 'on_leave'].map((s) => <Button key={s} size="sm" variant={(marks[e.allocation_id] ?? e.status) === s ? 'default' : 'outline'} onClick={() => setMarks({ ...marks, [e.allocation_id]: s })}>{s.replace('_', ' ')}</Button>)}</div>
          )])} empty="Entries appear for residents on leave; mark the rest from the residents list." />
        </Section>
      )}
      {hostel && <Section title="History"><SimpleTable head={['Date', 'Counts']} rows={list(history.data).map((r: Any) => [r.on_date, Object.entries(r.counts).map(([k, v]) => `${k} ${String(v)}`).join(' · ')])} /></Section>}
    </div>
  );
}

// ---- /admin/hostel/mess ---------------------------------------------------------------------------------------------------------
export function MessPage() {
  useTitle('Mess');
  const plans = useQ(['mess-plans'], () => hostelApi.messPlans());
  const rebates = useQ(['rebates'], () => hostelApi.rebates({ status: 'requested' }));
  const [month, setMonth] = useState(new Date(new Date().getFullYear(), new Date().getMonth() - 1, 1).toISOString().slice(0, 10));
  const bills = useQ(['bills', month], () => hostelApi.bills({ month }));
  const [qr, setQr] = useState('');
  const [meal, setMeal] = useState('lunch');
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Mess" description="Plans and menus, meal attendance (mess-card QR), rebates and monthly bills." />
      <Section title="Plans"><SimpleTable head={['Plan', 'Diet', 'Monthly fee', 'Subscribers']} rows={list(plans.data).map((p: Any) => [p.name, p.diet, rupees(p.monthly_fee_paise), p.subscribers])} /></Section>
      <Section title="Meal attendance (scan / paste mess-card QR)">
        <div className="flex gap-2"><select className="h-9 rounded-md border bg-background px-2 text-sm" value={meal} onChange={(e) => setMeal(e.target.value)}>{['breakfast', 'lunch', 'snacks', 'dinner'].map((m) => <option key={m}>{m}</option>)}</select>
          <Input className="w-96" placeholder="ms.…" value={qr} onChange={(e) => setQr(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && qr && run.mutate(() => hostelApi.markMeal({ qr: qr.trim(), meal, source: 'qr' }).then((r: Any) => { toast.success(r.data.recorded ? 'Recorded' : 'Already recorded'); setQr(''); }), { onError: fail })} /></div>
      </Section>
      <Section title="Rebate requests"><SimpleTable head={['Student', 'From', 'To', 'Days', 'Reason', '']} rows={list(rebates.data).map((r: Any) => [r.student?.name, r.from_on, r.to_on, r.days, r.reason, <div key="a" className="flex gap-1"><Button size="sm" onClick={() => run.mutate(() => hostelApi.decideRebate(r.id, true), { onError: fail })}>Approve</Button><Button size="sm" variant="ghost" onClick={() => run.mutate(() => hostelApi.decideRebate(r.id, false), { onError: fail })}>Reject</Button></div>])} empty="No pending rebates." /></Section>
      <Section title="Bills" action={<div className="flex gap-2"><Input type="date" value={month} onChange={(e) => setMonth(e.target.value)} /><Button size="sm" onClick={() => run.mutate(() => hostelApi.billRun({ month }), { onSuccess: () => toast.success('Bill run queued'), onError: fail })}>Run bills</Button></div>}>
        <SimpleTable head={['Student', 'Plan', 'Days', 'Rebate', 'Amount', 'Invoice', '']} rows={list(bills.data).map((b: Any) => [b.student?.name, b.plan, b.days_billed, b.rebate_days, rupees(b.amount_paise), <StatusBadge key="s" status={b.invoice_status ?? '—'} />, <Button key="p" size="sm" variant="ghost" onClick={() => hostelApi.billPdf(b.id).then((x) => openBlob(x, `mess-bill-${b.month}.pdf`)).catch(fail)}>PDF</Button>])} />
      </Section>
    </div>
  );
}

// ---- /admin/hostel/visitors -----------------------------------------------------------------------------------------------------
export function VisitorsPage() {
  useTitle('Visitors');
  const q = useQ(['visitors'], () => hostelApi.visitors());
  const [f, setF] = useState<Any | null>(null);
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Visitors register" description="ID proof numbers are masked in lists." actions={<Button onClick={() => setF({ enrollment_id: '', visitor_name: '', relation: '', phone: '', id_proof_type: 'Aadhaar', id_proof_no: '' })}>Log visitor</Button>} />
      <SimpleTable head={['Visitor', 'Relation', 'Student', 'ID', 'In', 'Out', '']} rows={list(q.data).map((v: Any) => [v.visitor_name, v.relation, v.student?.name, `${v.id_proof_type ?? ''} ${v.id_proof_no ?? ''}`, dt(v.in_at), dt(v.out_at), !v.out_at ? <Button key="o" size="sm" variant="outline" onClick={() => run.mutate(() => hostelApi.visitorOut(v.id), { onError: fail })}>Out</Button> : null])} />
      <Modal open={!!f} onOpenChange={(o) => !o && setF(null)} title="Log visitor" footer={<Button disabled={!f?.enrollment_id || !f?.visitor_name} onClick={() => run.mutate(() => hostelApi.logVisitor(f), { onSuccess: () => { toast.success('Logged'); setF(null); }, onError: fail })}>Log in</Button>}>
        {f && <div className="space-y-2 text-sm">{(['enrollment_id', 'visitor_name', 'relation', 'phone', 'id_proof_type', 'id_proof_no'] as const).map((k) => <Input key={k} placeholder={k.replace(/_/g, ' ')} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} />)}</div>}
      </Modal>
    </div>
  );
}

// ---- /admin/hostel/leaves (+ gate fallback) ---------------------------------------------------------------------------------------
export function LeavesPage() {
  useTitle('Leaves & out-pass');
  const [status, setStatus] = useState('requested');
  const q = useQ(['leaves', status], () => hostelApi.leaves({ status: status || undefined }));
  const late = useQ(['late'], () => hostelApi.lateList());
  const [scan, setScan] = useState('');
  const run = useRun();
  const consent: Record<string, 'warning' | 'success' | 'outline'> = { pending: 'warning', otp_verified: 'success', not_required: 'outline' };
  return (
    <div className="space-y-4">
      <PageHeader title="Leaves & out-pass" description="Guardian consent gate, warden approval, gate QR mark-out / return, late and absconding board." />
      <Section title="Gate (web scanner fallback)"><div className="flex gap-2"><Input className="w-96" placeholder="Pass QR (hl…)" value={scan} onChange={(e) => setScan(e.target.value)} />
        <Button size="sm" disabled={!scan} onClick={() => run.mutate(() => hostelApi.gateScan(scan.trim(), 'out').then((r: Any) => { toast.success(`${r.data.student?.name ?? ''} marked out`); setScan(''); }), { onError: fail })}>Mark out</Button>
        <Button size="sm" variant="outline" disabled={!scan} onClick={() => run.mutate(() => hostelApi.gateScan(scan.trim(), 'in').then((r: Any) => { toast.success(`${r.data.student?.name ?? ''} ${r.data.result}${r.data.late_minutes ? ` (${r.data.late_minutes} min late)` : ''}`); setScan(''); }), { onError: fail })}>Mark in</Button></div></Section>
      <div className="flex gap-1">{['requested', 'approved', 'out', 'late_return', 'absconding', 'returned', 'rejected', ''].map((s) => <Button key={s || 'all'} size="sm" variant={status === s ? 'default' : 'outline'} onClick={() => setStatus(s)}>{s ? s.replace('_', ' ') : 'all'}</Button>)}</div>
      <SimpleTable head={['Student', 'Type', 'From', 'To', 'Consent', 'Status', '']} rows={list(q.data).map((l: Any) => [l.student.name, l.leave_type.replace('_', ' '), dt(l.from_at), dt(l.to_at), <Badge key="c" variant={consent[l.guardian_consent] ?? 'outline'}>{l.guardian_consent.replace('_', ' ')}</Badge>, <span key="s"><StatusBadge status={l.status} />{l.late_minutes ? ` ${l.late_minutes}m` : ''}</span>,
        <div key="a" className="flex gap-1">
          {l.status === 'requested' && <><Button size="sm" disabled={l.guardian_consent === 'pending'} onClick={() => run.mutate(() => hostelApi.decideLeave(l.id, 'approve'), { onError: fail })}>Approve</Button><Button size="sm" variant="ghost" onClick={() => run.mutate(() => hostelApi.decideLeave(l.id, 'reject'), { onError: fail })}>Reject</Button></>}
          {['out', 'absconding'].includes(l.status) && <Button size="sm" variant="outline" onClick={() => { const r = window.prompt('Remarks'); if (r) run.mutate(() => hostelApi.markReturned(l.id, r), { onError: fail }); }}>Mark returned</Button>}
        </div>])} />
      <Section title="Late / absconding"><SimpleTable head={['Student', 'Due', 'Status']} rows={list(late.data).map((l: Any) => [l.student.name, dt(l.to_at), <StatusBadge key="s" status={l.status} />])} empty="Nobody overdue." /></Section>
    </div>
  );
}

// ---- /admin/hostel/complaints, discipline, quarters, reports -------------------------------------------------------------------
export function ComplaintsPage() {
  useTitle('Hostel complaints');
  const q = useQ(['complaints'], () => hostelApi.complaints());
  const run = useRun();
  const cols = ['open', 'assigned', 'in_progress', 'resolved', 'closed'];
  const next: Record<string, string> = { open: 'assigned', assigned: 'in_progress', in_progress: 'resolved', resolved: 'closed' };
  const rows: Any[] = list(q.data);
  return (
    <div className="space-y-4">
      <PageHeader title="Complaints" description="Triage by the warden; residents rate the resolution." />
      <div className="grid gap-3 md:grid-cols-5">{cols.map((c) => (
        <div key={c} className="space-y-2 rounded-lg border bg-muted/30 p-2"><p className="text-xs font-semibold uppercase text-muted-foreground">{c.replace('_', ' ')} · {rows.filter((r) => r.status === c).length}</p>
          {rows.filter((r) => r.status === c).map((r) => <Card key={r.id}><CardContent className="space-y-1 p-2 text-xs"><p className="font-medium">{r.category} · {r.room_number ?? ''}</p><p>{r.description}</p><p className="text-muted-foreground">{r.student?.name}</p>{next[c] && <Button size="sm" variant="outline" onClick={() => run.mutate(() => hostelApi.updateComplaint(r.id, next[c]), { onError: fail })}>→ {next[c].replace('_', ' ')}</Button>}</CardContent></Card>)}
        </div>
      ))}</div>
    </div>
  );
}

export function DisciplinePage() {
  useTitle('Hostel discipline');
  const q = useQ(['discipline'], () => hostelApi.discipline());
  const [f, setF] = useState<Any | null>(null);
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Hostel discipline" description="Warnings, fines (invoiced), suspensions and evictions; guardians are notified." actions={<Button onClick={() => setF({ enrollment_id: '', incident_on: new Date().toISOString().slice(0, 10), description: '', action: 'warning', fine: '' })}>Record</Button>} />
      <SimpleTable head={['Date', 'Student', 'Action', 'Fine', 'Description']} rows={list(q.data).map((d: Any) => [d.incident_on, d.student.name, <Badge key="a" variant={d.action === 'warning' ? 'warning' : 'destructive'}>{d.action}</Badge>, d.fine_paise ? rupees(d.fine_paise) : '—', d.description])} />
      <Modal open={!!f} onOpenChange={(o) => !o && setF(null)} title="Record an incident" footer={<Button disabled={!f?.enrollment_id || (f?.description ?? '').length < 5} onClick={() => run.mutate(() => hostelApi.recordDiscipline({ enrollment_id: f.enrollment_id, incident_on: f.incident_on, description: f.description, action: f.action, fine_paise: f.fine ? Math.round(Number(f.fine) * 100) : undefined }), { onSuccess: () => { toast.success('Recorded'); setF(null); }, onError: fail })}>Save</Button>}>
        {f && <div className="space-y-2 text-sm">
          <Input placeholder="Enrolment id" value={f.enrollment_id} onChange={(e) => setF({ ...f, enrollment_id: e.target.value })} />
          <Input type="date" value={f.incident_on} onChange={(e) => setF({ ...f, incident_on: e.target.value })} />
          <select className="h-9 w-full rounded-md border bg-background px-2" value={f.action} onChange={(e) => setF({ ...f, action: e.target.value })}>{['warning', 'fine', 'suspension', 'eviction'].map((a) => <option key={a}>{a}</option>)}</select>
          {f.action === 'fine' && <Input type="number" placeholder="Fine (₹)" value={f.fine} onChange={(e) => setF({ ...f, fine: e.target.value })} />}
          <textarea className="min-h-20 w-full rounded-md border bg-background p-2" placeholder="Description" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />
        </div>}
      </Modal>
    </div>
  );
}

export function QuartersPage() {
  useTitle('Staff quarters');
  const q = useQ(['quarters'], () => hostelApi.quarters());
  const [alloc, setAlloc] = useState<Any | null>(null);
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Staff quarters" description="Allocations with monthly rent deduction through payroll." />
      <SimpleTable head={['Unit', 'Type', 'Rent', 'Occupant', 'Since', 'Status', '']} rows={list(q.data).map((x: Any) => [x.unit_code, x.quarter_type ?? '—', rupees(x.rent_paise), x.occupant ?? '—', x.from_on ?? '—', <StatusBadge key="s" status={x.status} />,
        x.allocation_id ? <Button key="v" size="sm" variant="outline" onClick={() => run.mutate(() => hostelApi.vacateQuarter(x.allocation_id), { onError: fail })}>Vacate</Button> : x.status === 'vacant' ? <Button key="a" size="sm" onClick={() => setAlloc({ id: x.id, staff_id: '', rent_deduction: true })}>Allocate</Button> : null])} />
      <Modal open={!!alloc} onOpenChange={(o) => !o && setAlloc(null)} title="Allocate quarter" footer={<Button disabled={!alloc?.staff_id} onClick={() => run.mutate(() => hostelApi.allocateQuarter(alloc.id, { staff_id: alloc.staff_id, rent_deduction: alloc.rent_deduction }), { onSuccess: () => { toast.success('Allocated'); setAlloc(null); }, onError: fail })}>Allocate</Button>}>
        {alloc && <div className="space-y-2 text-sm"><Input placeholder="Staff id" value={alloc.staff_id} onChange={(e) => setAlloc({ ...alloc, staff_id: e.target.value })} /><label className="flex items-center gap-1"><input type="checkbox" checked={alloc.rent_deduction} onChange={(e) => setAlloc({ ...alloc, rent_deduction: e.target.checked })} /> deduct rent from salary</label></div>}
      </Modal>
    </div>
  );
}

export function HostelReportsPage() {
  useTitle('Hostel reports');
  const [hostel, setHostel] = useState('');
  return (
    <div className="space-y-4">
      <PageHeader title="Hostel registers" description="Exports run as background jobs (download from Background jobs)." />
      <HostelPicker value={hostel} onChange={setHostel} />
      <div className="flex flex-wrap gap-2">{['occupancy', 'fees', 'roll_call', 'leaves', 'mess', 'visitors', 'discipline'].map((k) => <Button key={k} variant="outline" onClick={() => hostelApi.report(k, hostel || undefined).then(() => toast.success('Queued')).catch(fail)}>{k.replace('_', ' ')}</Button>)}</div>
    </div>
  );
}

// ---- /student/hostel ---------------------------------------------------------------------------------------------------------
export function StudentHostelPage() {
  useTitle('My hostel');
  const allocs = useQ(['me-alloc'], () => hostelApi.myAllocations());
  const apps = useQ(['me-apps'], () => hostelApi.myApplications());
  const leaves = useQ(['me-leaves'], () => hostelApi.myLeaves().catch(() => ({ data: [] }) as Any));
  const subs = useQ(['me-subs'], () => hostelApi.subscriptions({ mine: true }).catch(() => ({ data: [] }) as Any));
  const bills = useQ(['me-bills'], () => hostelApi.myBills().catch(() => ({ data: [] }) as Any));
  const hostels = useQ(['hostels-all'], () => hostelApi.hostels().catch(() => ({ data: [] }) as Any));
  const [apply, setApply] = useState<Any | null>(null);
  const [leave, setLeave] = useState<Any | null>(null);
  const [otp, setOtp] = useState<Record<string, string>>({});
  const run = useRun();
  const active = list(allocs.data).find((a: Any) => ['allotted', 'checked_in'].includes(a.status));
  return (
    <div className="space-y-4">
      <PageHeader title="My hostel" description="Room, leaves & out-pass with QR, mess and bills." />
      <Section title="Room" action={!active ? <Button size="sm" onClick={() => setApply({ hostel_preference: [], room_type_pref: 'double', distance_km: '' })}>Apply</Button> : <Button size="sm" variant="outline" onClick={() => run.mutate(() => hostelApi.vacateRequest(), { onSuccess: () => toast.success('Warden notified'), onError: fail })}>Request vacate</Button>}>
        {active ? <p className="text-sm">{active.hostel} · room {active.room_number} bed {active.bed_label} · <StatusBadge status={active.status} /> · fee <StatusBadge status={active.fee_status ?? '—'} /></p> : <p className="text-sm text-muted-foreground">No allocation.</p>}
        <SimpleTable head={['Applied', 'Score', 'Status', 'Position']} rows={list(apps.data).map((a: Any) => [new Date(a.created_at).toLocaleDateString(), a.priority_score ?? '—', <StatusBadge key="s" status={a.status} />, a.position ?? '—'])} empty="No applications." />
      </Section>
      <Section title="Leaves & out-pass" action={active?.status === 'checked_in' ? <Button size="sm" onClick={() => setLeave({ leave_type: 'out_pass', from_at: '', to_at: '', destination: '', reason: '' })}>New request</Button> : null}>
        <SimpleTable head={['Type', 'From', 'To', 'Consent', 'Status', 'Pass', '']} rows={list(leaves.data).map((l: Any) => [l.leave_type.replace('_', ' '), dt(l.from_at), dt(l.to_at), l.guardian_consent.replace('_', ' '), <StatusBadge key="s" status={l.status} />, l.qr_token ? <code key="q" className="text-[10px]">{l.qr_token.slice(0, 18)}…</code> : '—',
          l.guardian_consent === 'pending' ? <div key="o" className="flex gap-1"><Button size="sm" variant="outline" onClick={() => run.mutate(() => hostelApi.sendOtp(l.id), { onSuccess: () => toast.success('OTP sent to your guardian'), onError: fail })}>Send OTP</Button><Input className="w-24" placeholder="OTP" value={otp[l.id] ?? ''} onChange={(e) => setOtp({ ...otp, [l.id]: e.target.value })} /><Button size="sm" onClick={() => run.mutate(() => hostelApi.verifyOtp(l.id, otp[l.id] ?? ''), { onError: fail })}>Verify</Button></div>
            : ['requested', 'approved'].includes(l.status) ? <Button key="c" size="sm" variant="ghost" onClick={() => run.mutate(() => hostelApi.cancelLeave(l.id), { onError: fail })}>Cancel</Button> : null])} empty="No leaves." />
      </Section>
      <Section title="Mess">
        <SimpleTable head={['Plan', 'From', 'Status', 'Mess card']} rows={list(subs.data).map((s: Any) => [s.plan, s.from_on, <StatusBadge key="s" status={s.status} />, s.qr_token ? <code key="q" className="text-[10px]">{s.qr_token}</code> : '—'])} empty="Not subscribed." />
        <SimpleTable head={['Month', 'Days', 'Rebate', 'Amount', 'Invoice']} rows={list(bills.data).map((b: Any) => [b.month, b.days_billed, b.rebate_days, rupees(b.amount_paise), <StatusBadge key="s" status={b.invoice_status ?? '—'} />])} empty="No bills." />
      </Section>
      <Modal open={!!apply} onOpenChange={(o) => !o && setApply(null)} title="Hostel application" footer={<Button disabled={!apply?.hostel_preference?.length} onClick={() => run.mutate(() => hostelApi.apply({ hostel_preference: apply.hostel_preference, room_type_pref: apply.room_type_pref, distance_km: apply.distance_km ? Number(apply.distance_km) : undefined }), { onSuccess: () => { toast.success('Applied'); setApply(null); }, onError: fail })}>Apply</Button>}>
        {apply && <div className="space-y-2 text-sm">
          <p className="text-xs text-muted-foreground">Pick hostels in order of preference.</p>
          {list(hostels.data).map((h: Any) => <label key={h.id} className="flex items-center gap-2"><input type="checkbox" checked={apply.hostel_preference.includes(h.id)} onChange={(e) => setApply({ ...apply, hostel_preference: e.target.checked ? [...apply.hostel_preference, h.id] : apply.hostel_preference.filter((x: string) => x !== h.id) })} />{h.name} ({h.hostel_type})</label>)}
          <select className="h-9 w-full rounded-md border bg-background px-2" value={apply.room_type_pref} onChange={(e) => setApply({ ...apply, room_type_pref: e.target.value })}>{['single', 'double', 'triple', 'dorm'].map((t) => <option key={t}>{t}</option>)}</select>
          <Input type="number" placeholder="Distance from home (km)" value={apply.distance_km} onChange={(e) => setApply({ ...apply, distance_km: e.target.value })} />
        </div>}
      </Modal>
      <Modal open={!!leave} onOpenChange={(o) => !o && setLeave(null)} title="Leave / out-pass" footer={<Button disabled={!leave?.from_at || !leave?.to_at} onClick={() => run.mutate(() => hostelApi.requestLeave({ ...leave, from_at: new Date(leave.from_at).toISOString(), to_at: new Date(leave.to_at).toISOString() }), { onSuccess: () => { toast.success('Requested'); setLeave(null); }, onError: fail })}>Request</Button>}>
        {leave && <div className="space-y-2 text-sm">
          <select className="h-9 w-full rounded-md border bg-background px-2" value={leave.leave_type} onChange={(e) => setLeave({ ...leave, leave_type: e.target.value })}>{['out_pass', 'day_leave', 'home_leave', 'medical'].map((t) => <option key={t} value={t}>{t.replace('_', ' ')}</option>)}</select>
          <label className="block">From <Input type="datetime-local" value={leave.from_at} onChange={(e) => setLeave({ ...leave, from_at: e.target.value })} /></label>
          <label className="block">To <Input type="datetime-local" value={leave.to_at} onChange={(e) => setLeave({ ...leave, to_at: e.target.value })} /></label>
          <Input placeholder="Destination" value={leave.destination} onChange={(e) => setLeave({ ...leave, destination: e.target.value })} />
          <Input placeholder="Reason" value={leave.reason} onChange={(e) => setLeave({ ...leave, reason: e.target.value })} />
        </div>}
      </Modal>
    </div>
  );
}

// ---- /parent/hostel ----------------------------------------------------------------------------------------------------------
export function ParentHostelPage() {
  useTitle("Ward's hostel");
  const allocs = useQ(['ward-alloc'], () => hostelApi.wardAllocations());
  const leaves = useQ(['ward-leaves'], () => hostelApi.wardLeaves().catch(() => ({ data: [] }) as Any));
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Ward's hostel" description="Room, leave consent, out / return timeline and late alerts." />
      <SimpleTable head={['Student', 'Hostel', 'Room', 'Status']} rows={list(allocs.data).map((a: Any) => [a.student.name, a.hostel, `${a.room_number ?? ''} ${a.bed_label ?? ''}`, <StatusBadge key="s" status={a.status} />])} empty="No allocation." />
      <Section title="Leaves">
        <SimpleTable head={['Student', 'Type', 'From', 'To', 'Out', 'Back', 'Status', '']} rows={list(leaves.data).map((l: Any) => [l.student.name, l.leave_type.replace('_', ' '), dt(l.from_at), dt(l.to_at), dt(l.actual_out_at), dt(l.actual_return_at), <span key="s"><StatusBadge status={l.status} />{l.late_minutes ? ` ${l.late_minutes}m late` : ''}</span>,
          l.guardian_consent === 'pending' ? <Button key="a" size="sm" onClick={() => run.mutate(() => hostelApi.parentApprove(l.id), { onSuccess: () => toast.success('Consent given'), onError: fail })}>Approve</Button> : null])} empty="No leaves." />
      </Section>
    </div>
  );
}
