import { useEffect, useMemo, useState, type ReactNode } from 'react';
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
import { transportApi } from '../api';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));
const useQ = <T,>(key: unknown[], fn: () => Promise<T>, enabled = true, refetchInterval?: number) =>
  useQuery({ queryKey: ['transport', ...key], queryFn: fn, enabled, retry: false, refetchInterval });
function useRun() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: () => qc.invalidateQueries({ queryKey: ['transport'] }) });
}
const rupees = (p: number | null | undefined) => `₹${((p ?? 0) / 100).toLocaleString('en-IN')}`;
const dt = (v?: string | null) => (v ? new Date(v).toLocaleString() : '—');
const hm = (v?: string | null) => (v ? v.slice(0, 5) : '—');
const list = (r: Any) => (Array.isArray(r?.data) ? r.data : r?.data?.items ?? []);
const today = () => new Date().toISOString().slice(0, 10);
const openBlob = (b: Blob, name: string) => { const u = URL.createObjectURL(b); const a = document.createElement('a'); a.href = u; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(u), 30000); };
const sel = 'h-9 rounded-md border bg-background px-2 text-sm';

function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <Card><CardContent className="space-y-3 p-4"><div className="flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">{title}</h2>{action}</div>{children}</CardContent></Card>;
}

function Chips({ chips }: { chips: string[] }) {
  if (!chips?.length) return <Badge variant="outline">compliant</Badge>;
  return <div className="flex flex-wrap gap-1">{chips.map((c) => <Badge key={c} variant={c.endsWith('expired') ? 'destructive' : 'warning'}>{c.replace('_', ' ')}</Badge>)}</div>;
}

function RoutePicker({ value, onChange, label = 'All routes' }: { value: string; onChange: (v: string) => void; label?: string }) {
  const q = useQ(['routes'], () => transportApi.routes());
  return <select className={sel} value={value} onChange={(e) => onChange(e.target.value)}><option value="">{label}</option>{list(q.data).map((r: Any) => <option key={r.id} value={r.id}>{r.code} — {r.name}</option>)}</select>;
}

/** Lightweight SVG map: stops (dots joined in order) and vehicles (labelled markers) on an equirectangular projection. */
function MiniMap({ stops = [], vehicles = [], trace = [], height = 320 }: { stops?: Any[]; vehicles?: Any[]; trace?: Any[]; height?: number }) {
  const pts = [...stops, ...vehicles, ...trace].filter((p: Any) => p.lat != null && p.lng != null);
  if (!pts.length) return <p className="text-sm text-muted-foreground">No coordinates to plot.</p>;
  const lats = pts.map((p: Any) => Number(p.lat)), lngs = pts.map((p: Any) => Number(p.lng));
  const [minLa, maxLa, minLn, maxLn] = [Math.min(...lats), Math.max(...lats), Math.min(...lngs), Math.max(...lngs)];
  const w = 600, pad = 20;
  const x = (lng: number) => pad + ((lng - minLn) / (maxLn - minLn || 1)) * (w - 2 * pad);
  const y = (lat: number) => pad + ((maxLa - lat) / (maxLa - minLa || 1)) * (height - 2 * pad);
  const line = (arr: Any[]) => arr.map((p: Any) => `${x(Number(p.lng))},${y(Number(p.lat))}`).join(' ');
  return (
    <svg viewBox={`0 0 ${w} ${height}`} className="w-full rounded-md border bg-muted/30" role="img" aria-label="Route map">
      {stops.length > 1 && <polyline points={line(stops)} fill="none" stroke="currentColor" strokeOpacity={0.35} strokeWidth={2} />}
      {trace.length > 1 && <polyline points={line(trace)} fill="none" stroke="#2563eb" strokeWidth={2} />}
      {stops.map((s: Any) => <g key={s.id ?? `${s.lat}${s.lng}`}><circle cx={x(Number(s.lng))} cy={y(Number(s.lat))} r={4} fill="#64748b" /><text x={x(Number(s.lng)) + 6} y={y(Number(s.lat)) + 3} fontSize={9}>{s.sequence ? `${s.sequence}. ` : ''}{s.name}</text></g>)}
      {vehicles.map((v: Any) => <g key={v.vehicle_id}><circle cx={x(Number(v.lng))} cy={y(Number(v.lat))} r={7} fill={v.deviation ? '#dc2626' : '#16a34a'} /><text x={x(Number(v.lng)) + 9} y={y(Number(v.lat)) - 6} fontSize={10} fontWeight={600}>{v.registration_no ?? 'bus'}{v.eta_min != null ? ` · ${v.next_stop} in ${v.eta_min}′` : ''}</text></g>)}
    </svg>
  );
}

// ---- /admin/transport/fleet ------------------------------------------------------------------------------------------------
export function FleetPage() {
  useTitle('Fleet');
  const q = useQ(['vehicles'], () => transportApi.vehicles());
  const [form, setForm] = useState<Any | null>(null);
  const [open, setOpen] = useState<Any | null>(null);
  const run = useRun();
  const scopes: string[] = (q.data as Any)?.meta?.visibility?.scopes ?? [];
  return (
    <div className="space-y-4">
      <PageHeader title="Fleet" description={`Vehicles, statutory documents and costs${scopes.length ? ` · scope: ${scopes.join(', ')}` : ''}.`} actions={<Button onClick={() => setForm({ registration_no: '', vehicle_type: 'bus', capacity: 50 })}>Add vehicle</Button>} />
      <SimpleTable
        head={['Registration', 'Type', 'Capacity', 'Driver', 'Status', 'Compliance', '']}
        rows={list(q.data).map((v: Any) => [
          <button key="r" className="font-medium underline-offset-2 hover:underline" onClick={() => setOpen(v)}>{v.registration_no}</button>,
          v.vehicle_type, v.capacity ?? '—', v.driver_name ?? '—', <StatusBadge key="s" status={v.status} />, <Chips key="c" chips={v.chips} />,
          <div key="a" className="flex gap-1"><Button size="sm" variant="outline" onClick={() => setForm({ ...v })}>Edit</Button>{v.status !== 'retired' && <Button size="sm" variant="ghost" onClick={() => run.mutate(() => transportApi.retireVehicle(v.id), { onSuccess: () => toast.success('Retired'), onError: fail })}>Retire</Button>}</div>,
        ])}
      />
      <Modal open={!!form} onOpenChange={(o) => !o && setForm(null)} title={form?.id ? `Edit ${form.registration_no}` : 'Add vehicle'} footer={<Button onClick={() => {
        const keys = ['vehicle_type', 'capacity', 'make_model', 'year', 'insurance_expiry', 'fitness_expiry', 'permit_expiry', 'puc_expiry'];
        const body: Any = Object.fromEntries(keys.filter((k) => form[k] !== undefined && form[k] !== '').map((k) => [k, ['capacity', 'year'].includes(k) ? Number(form[k]) : form[k]]));
        if (!form.id) body.registration_no = form.registration_no;
        else body.version = form.version;
        run.mutate(() => transportApi.saveVehicle(body, form.id), { onSuccess: () => { toast.success('Saved'); setForm(null); }, onError: fail });
      }}>Save</Button>}>
        {form && <div className="grid grid-cols-2 gap-2 text-sm">
          {!form.id && <label className="col-span-2">Registration <Input value={form.registration_no} onChange={(e) => setForm({ ...form, registration_no: e.target.value })} /></label>}
          <label>Type <select className={`${sel} w-full`} value={form.vehicle_type} onChange={(e) => setForm({ ...form, vehicle_type: e.target.value })}>{['bus', 'minibus', 'van', 'car'].map((t) => <option key={t}>{t}</option>)}</select></label>
          <label>Capacity <Input type="number" value={form.capacity ?? ''} onChange={(e) => setForm({ ...form, capacity: e.target.value })} /></label>
          <label>Make / model <Input value={form.make_model ?? ''} onChange={(e) => setForm({ ...form, make_model: e.target.value })} /></label>
          <label>Year <Input type="number" value={form.year ?? ''} onChange={(e) => setForm({ ...form, year: e.target.value })} /></label>
          {['insurance', 'fitness', 'permit', 'puc'].map((d) => <label key={d}>{d} expiry <Input type="date" value={form[`${d}_expiry`] ?? ''} onChange={(e) => setForm({ ...form, [`${d}_expiry`]: e.target.value })} /></label>)}
        </div>}
      </Modal>
      {open && <VehicleDrawer vehicle={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function VehicleDrawer({ vehicle, onClose }: { vehicle: Any; onClose: () => void }) {
  const [tab, setTab] = useState<'documents' | 'maintenance' | 'fuel'>('documents');
  const m = useQ(['mnt', vehicle.id], () => transportApi.maintenance(vehicle.id), tab === 'maintenance');
  const f = useQ(['fuel', vehicle.id], () => transportApi.fuel(vehicle.id), tab === 'fuel');
  const c = useQ(['cost', vehicle.id], () => transportApi.costs(vehicle.id));
  const [entry, setEntry] = useState<Any>({ date: today(), litres: '', cost: '', odometer: '', type: 'service', vendor: '' });
  const run = useRun();
  const cost = (c.data as Any)?.data ?? {};
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`${vehicle.registration_no} — ${vehicle.make_model ?? vehicle.vehicle_type}`}>
      <div className="space-y-3 text-sm">
        <div className="flex flex-wrap gap-2"><Badge variant="outline">{cost.km ?? 0} km logged</Badge><Badge variant="outline">cost/km {cost.cost_per_km != null ? `₹${cost.cost_per_km}` : '—'}</Badge><Badge variant="outline">km/l {cost.km_per_litre ?? '—'}</Badge></div>
        <div className="flex gap-1">{(['documents', 'maintenance', 'fuel'] as const).map((t) => <Button key={t} size="sm" variant={tab === t ? 'default' : 'outline'} onClick={() => setTab(t)}>{t}</Button>)}</div>
        {tab === 'documents' && <SimpleTable head={['Document', 'Expiry', 'Days left', 'State']} rows={(vehicle.compliance ?? []).map((d: Any) => [d.document, d.expiry ?? '—', d.days_left ?? '—', <StatusBadge key="s" status={d.state} />])} />}
        {tab === 'maintenance' && <>
          <SimpleTable head={['Date', 'Type', 'Odometer', 'Cost', 'Vendor', 'Next due']} rows={list(m.data).map((r: Any) => [r.service_date, r.maintenance_type ?? '—', r.odometer ?? '—', rupees(r.cost_paise), r.vendor ?? '—', r.next_due_date ?? '—'])} />
          <div className="grid grid-cols-3 gap-2">
            <Input type="date" value={entry.date} onChange={(e) => setEntry({ ...entry, date: e.target.value })} />
            <Input placeholder="Type" value={entry.type} onChange={(e) => setEntry({ ...entry, type: e.target.value })} />
            <Input placeholder="Cost ₹" type="number" value={entry.cost} onChange={(e) => setEntry({ ...entry, cost: e.target.value })} />
            <Input placeholder="Odometer" type="number" value={entry.odometer} onChange={(e) => setEntry({ ...entry, odometer: e.target.value })} />
            <Input placeholder="Vendor" value={entry.vendor} onChange={(e) => setEntry({ ...entry, vendor: e.target.value })} />
            <Button onClick={() => run.mutate(() => transportApi.addMaintenance(vehicle.id, { service_date: entry.date, maintenance_type: entry.type, cost_paise: Math.round(Number(entry.cost) * 100), odometer: entry.odometer ? Number(entry.odometer) : null, vendor: entry.vendor || null }), { onSuccess: () => toast.success('Logged'), onError: fail })}>Add</Button>
          </div>
        </>}
        {tab === 'fuel' && <>
          <SimpleTable head={['Date', 'Litres', 'Cost', 'Odometer']} rows={list(f.data).map((r: Any) => [r.filled_on, r.litres, rupees(r.cost_paise), r.odometer ?? '—'])} />
          <div className="grid grid-cols-4 gap-2">
            <Input type="date" value={entry.date} onChange={(e) => setEntry({ ...entry, date: e.target.value })} />
            <Input placeholder="Litres" type="number" value={entry.litres} onChange={(e) => setEntry({ ...entry, litres: e.target.value })} />
            <Input placeholder="Cost ₹" type="number" value={entry.cost} onChange={(e) => setEntry({ ...entry, cost: e.target.value })} />
            <Input placeholder="Odometer" type="number" value={entry.odometer} onChange={(e) => setEntry({ ...entry, odometer: e.target.value })} />
          </div>
          <Button disabled={!entry.litres} onClick={() => run.mutate(() => transportApi.addFuel(vehicle.id, { filled_on: entry.date, litres: Number(entry.litres), cost_paise: Math.round(Number(entry.cost) * 100), odometer: entry.odometer ? Number(entry.odometer) : null }), { onSuccess: () => toast.success('Logged'), onError: fail })}>Add fuel</Button>
        </>}
      </div>
    </Modal>
  );
}

// ---- /admin/transport/routes -----------------------------------------------------------------------------------------------
export function RoutesPage() {
  useTitle('Routes');
  const q = useQ(['routes'], () => transportApi.routes());
  const vehicles = useQ(['vehicles'], () => transportApi.vehicles());
  const [cur, setCur] = useState<Any | null>(null);
  const [form, setForm] = useState<Any | null>(null);
  const [stop, setStop] = useState<Any | null>(null);
  const run = useRun();
  const route = useMemo(() => list(q.data).find((r: Any) => r.id === cur), [q.data, cur]);
  const move = (i: number, d: number) => {
    const ids = route.stops.map((s: Any) => s.id);
    const j = i + d;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    run.mutate(() => transportApi.reorder(route.id, ids), { onError: fail });
  };
  return (
    <div className="space-y-4">
      <PageHeader title="Routes & stops" description="Ordered stops with per-stop fees, times and coordinates; capacity comes from the route vehicle." actions={<Button onClick={() => setForm({ code: '', name: '', fee_paise: '' })}>New route</Button>} />
      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        <div className="space-y-2">
          {list(q.data).map((r: Any) => (
            <Card key={r.id} className={cur === r.id ? 'ring-2 ring-primary' : ''}><CardContent className="cursor-pointer space-y-1 p-3 text-sm" onClick={() => setCur(r.id)}>
              <p className="font-medium">{r.code} — {r.name} {!r.is_active && <Badge variant="outline">inactive</Badge>}</p>
              <p className="text-xs text-muted-foreground">{r.vehicle_registration ?? 'no vehicle'} · {r.capacity_used}/{r.capacity ?? '—'} seats · {r.stops.length} stops</p>
            </CardContent></Card>
          ))}
        </div>
        {route ? (
          <Section title={`${route.code} — ${route.name}`} action={<div className="flex gap-1">
            <Button size="sm" variant="outline" onClick={() => setForm({ ...route })}>Edit</Button>
            <Button size="sm" variant="outline" onClick={() => setStop({ name: '', fee_paise: '', pickup_time: '', drop_time: '', lat: '', lng: '' })}>Add stop</Button>
            <Button size="sm" variant="ghost" onClick={() => transportApi.routeSheet(route.id).then((b) => openBlob(b, `route-${route.code}.pdf`)).catch(fail)}>Route sheet</Button>
          </div>}>
            <MiniMap stops={route.stops} />
            <SimpleTable head={['#', 'Stop', 'Pickup', 'Drop', 'Fee', 'Passengers', '']} rows={route.stops.map((s: Any, i: number) => [
              s.sequence, s.name, hm(s.pickup_time), hm(s.drop_time), rupees(s.effective_fee_paise), s.passengers,
              <div key="m" className="flex gap-1"><Button size="sm" variant="ghost" onClick={() => move(i, -1)}>↑</Button><Button size="sm" variant="ghost" onClick={() => move(i, 1)}>↓</Button><Button size="sm" variant="ghost" onClick={() => setStop({ ...s, fee_paise: s.fee_paise ?? '' })}>Edit</Button></div>,
            ])} />
          </Section>
        ) : <p className="text-sm text-muted-foreground">Pick a route.</p>}
      </div>
      <Modal open={!!form} onOpenChange={(o) => !o && setForm(null)} title={form?.id ? 'Edit route' : 'New route'} footer={<Button onClick={() => {
        const body: Any = { name: form.name, vehicle_id: form.vehicle_id || null, fee_paise: form.fee_paise === '' ? null : Number(form.fee_paise) };
        if (!form.id) body.code = form.code;
        run.mutate(() => transportApi.saveRoute(body, form.id), { onSuccess: () => { toast.success('Saved'); setForm(null); }, onError: fail });
      }}>Save</Button>}>
        {form && <div className="space-y-2 text-sm">
          {!form.id && <Input placeholder="Code (R11)" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} />}
          <Input placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <select className={`${sel} w-full`} value={form.vehicle_id ?? ''} onChange={(e) => setForm({ ...form, vehicle_id: e.target.value })}><option value="">No vehicle</option>{list(vehicles.data).filter((v: Any) => v.status !== 'retired').map((v: Any) => <option key={v.id} value={v.id}>{v.registration_no} ({v.capacity})</option>)}</select>
          <label>Route fee (paise) <Input type="number" value={form.fee_paise ?? ''} onChange={(e) => setForm({ ...form, fee_paise: e.target.value })} /></label>
        </div>}
      </Modal>
      <Modal open={!!stop} onOpenChange={(o) => !o && setStop(null)} title={stop?.id ? 'Edit stop' : 'Add stop'} footer={<Button disabled={!stop?.name} onClick={() => {
        const body: Any = { name: stop.name, pickup_time: stop.pickup_time || null, drop_time: stop.drop_time || null, fee_paise: stop.fee_paise === '' ? null : Number(stop.fee_paise), lat: stop.lat === '' ? null : Number(stop.lat), lng: stop.lng === '' ? null : Number(stop.lng) };
        run.mutate(() => (stop.id ? transportApi.updateStop(stop.id, body) : transportApi.addStop(route.id, body)), { onSuccess: () => { toast.success('Saved'); setStop(null); }, onError: fail });
      }}>Save</Button>}>
        {stop && <div className="grid grid-cols-2 gap-2 text-sm">
          <label className="col-span-2">Name <Input value={stop.name} onChange={(e) => setStop({ ...stop, name: e.target.value })} /></label>
          <label>Pickup <Input type="time" value={hm(stop.pickup_time) === '—' ? '' : hm(stop.pickup_time)} onChange={(e) => setStop({ ...stop, pickup_time: e.target.value })} /></label>
          <label>Drop <Input type="time" value={hm(stop.drop_time) === '—' ? '' : hm(stop.drop_time)} onChange={(e) => setStop({ ...stop, drop_time: e.target.value })} /></label>
          <label>Lat <Input value={stop.lat ?? ''} onChange={(e) => setStop({ ...stop, lat: e.target.value })} /></label>
          <label>Lng <Input value={stop.lng ?? ''} onChange={(e) => setStop({ ...stop, lng: e.target.value })} /></label>
          <label className="col-span-2">Fee (paise; blank = route fee) <Input type="number" value={stop.fee_paise} onChange={(e) => setStop({ ...stop, fee_paise: e.target.value })} /></label>
        </div>}
      </Modal>
    </div>
  );
}

// ---- /admin/transport/allocations -------------------------------------------------------------------------------------------
export function AllocationsPage() {
  useTitle('Transport allocations');
  const [f, setF] = useState<Any>({ route_id: '', status: '', person_type: '', scope: '' });
  const q = useQ(['allocs', f], () => transportApi.allocations({ route_id: f.route_id || undefined, status: f.status || undefined, person_type: f.person_type || undefined, scope: f.scope || undefined }));
  const routes = useQ(['routes'], () => transportApi.routes());
  const reqs = useQ(['requests'], () => transportApi.requests(), true);
  const [alloc, setAlloc] = useState<Any | null>(null);
  const [bulk, setBulk] = useState<Any | null>(null);
  const [change, setChange] = useState<Any | null>(null);
  const run = useRun();
  const scopes: string[] = (q.data as Any)?.meta?.visibility?.scopes ?? [];
  const rmap = Object.fromEntries(list(routes.data).map((r: Any) => [r.id, r]));
  const chosen = alloc ? rmap[alloc.route_id] : null;
  return (
    <div className="space-y-4">
      <PageHeader title="Allocations" description="Students and staff on routes — capacity, fee status, changes and suspensions." actions={<div className="flex gap-1"><Button onClick={() => setAlloc({ person_type: 'student', person_id: '', route_id: '', stop_id: '', payroll_deduction: false })}>Allocate</Button><Button variant="outline" onClick={() => setBulk({ person_type: 'student', route_id: '', stop_id: '', ids: '' })}>Bulk (CSV ids)</Button></div>} />
      <div className="flex flex-wrap items-center gap-2">
        {scopes.length > 1 && <div className="flex gap-1">{scopes.map((s) => <Button key={s} size="sm" variant={f.scope === s ? 'default' : 'outline'} onClick={() => setF({ ...f, scope: s })}>{s}</Button>)}</div>}
        <RoutePicker value={f.route_id} onChange={(v) => setF({ ...f, route_id: v })} />
        <select className={sel} value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="">Any status</option>{['active', 'suspended', 'pending', 'closed', 'rejected'].map((s) => <option key={s}>{s}</option>)}</select>
        <select className={sel} value={f.person_type} onChange={(e) => setF({ ...f, person_type: e.target.value })}><option value="">Students & staff</option><option value="student">Students</option><option value="staff">Staff</option></select>
      </div>
      <SimpleTable
        head={['Person', 'Dept', 'Route', 'Stop', 'Fee', 'Fee status', 'Status', '']}
        rows={list(q.data).map((a: Any) => [
          <span key="p">{a.person_name ?? a.person_id} <span className="text-xs text-muted-foreground">{a.person_code} · {a.person_type}</span></span>,
          a.department_code ?? '—', a.route_code, a.stop_name ?? '—', rupees(a.fee_paise), a.fee_status ?? '—', <StatusBadge key="s" status={a.status} />,
          <div key="x" className="flex gap-1">
            {['active', 'suspended'].includes(a.status) && <Button size="sm" variant="outline" onClick={() => setChange({ id: a.id, new_route_id: a.route_id, new_stop_id: '', effective_on: today() })}>Change</Button>}
            {a.status === 'active' && <Button size="sm" variant="ghost" onClick={() => run.mutate(() => transportApi.setStatus(a.id, 'suspend', 'manual'), { onError: fail })}>Suspend</Button>}
            {a.status === 'suspended' && <Button size="sm" variant="ghost" onClick={() => run.mutate(() => transportApi.setStatus(a.id, 'reactivate'), { onError: fail })}>Reactivate</Button>}
            {['active', 'suspended'].includes(a.status) && <Button size="sm" variant="ghost" onClick={() => run.mutate(() => transportApi.setStatus(a.id, 'close'), { onError: fail })}>Close</Button>}
          </div>,
        ])}
      />
      {list(reqs.data).length > 0 && (
        <Section title={`Requests queue (${list(reqs.data).length})`}>
          <SimpleTable head={['Person', 'Route', 'Stop', '']} rows={list(reqs.data).map((r: Any) => [r.person_name, r.route_code, r.stop_name, <div key="d" className="flex gap-1"><Button size="sm" onClick={() => run.mutate(() => transportApi.decide(r.id, { decision: 'approve' }), { onSuccess: (x: Any) => toast.success(x?.data?.warning ?? 'Approved'), onError: fail })}>Approve</Button><Button size="sm" variant="ghost" onClick={() => run.mutate(() => transportApi.decide(r.id, { decision: 'reject' }), { onError: fail })}>Reject</Button></div>])} />
        </Section>
      )}
      <Modal open={!!alloc} onOpenChange={(o) => !o && setAlloc(null)} title="Allocate" footer={<Button disabled={!alloc?.person_id || !alloc?.stop_id} onClick={() => run.mutate(() => transportApi.allocate(alloc), { onSuccess: (r: Any) => { toast.success(r?.data?.warning ? `Allocated (${r.data.warning})` : 'Allocated'); setAlloc(null); }, onError: fail })}>Allocate</Button>}>
        {alloc && <div className="space-y-2 text-sm">
          <select className={`${sel} w-full`} value={alloc.person_type} onChange={(e) => setAlloc({ ...alloc, person_type: e.target.value })}><option value="student">Student</option><option value="staff">Staff</option></select>
          <Input placeholder={alloc.person_type === 'student' ? 'Student id' : 'Staff id'} value={alloc.person_id} onChange={(e) => setAlloc({ ...alloc, person_id: e.target.value.trim() })} />
          <RoutePicker value={alloc.route_id} onChange={(v) => setAlloc({ ...alloc, route_id: v, stop_id: '' })} label="Route…" />
          {chosen && <>
            <div className="h-2 w-full overflow-hidden rounded bg-muted"><div className={`h-2 ${chosen.capacity_used >= (chosen.capacity ?? Infinity) ? 'bg-destructive' : 'bg-primary'}`} style={{ width: `${Math.min(100, (100 * chosen.capacity_used) / (chosen.capacity || 1))}%` }} /></div>
            <p className="text-xs text-muted-foreground">{chosen.capacity_used} of {chosen.capacity ?? '—'} seats taken</p>
            <select className={`${sel} w-full`} value={alloc.stop_id} onChange={(e) => setAlloc({ ...alloc, stop_id: e.target.value })}><option value="">Stop…</option>{chosen.stops.map((s: Any) => <option key={s.id} value={s.id}>{s.sequence}. {s.name} — {rupees(s.effective_fee_paise)}</option>)}</select>
          </>}
          {alloc.person_type === 'staff' && <label className="flex items-center gap-2"><input type="checkbox" checked={alloc.payroll_deduction} onChange={(e) => setAlloc({ ...alloc, payroll_deduction: e.target.checked })} /> Deduct from payroll</label>}
        </div>}
      </Modal>
      <Modal open={!!bulk} onOpenChange={(o) => !o && setBulk(null)} title="Bulk allocation" footer={<Button disabled={!bulk?.stop_id || !bulk?.ids} onClick={() => run.mutate(() => transportApi.bulk({ person_type: bulk.person_type, route_id: bulk.route_id, stop_id: bulk.stop_id, person_ids: bulk.ids.split(/[\s,;]+/).filter(Boolean) }), { onSuccess: () => { toast.success('Queued — the job report lists failures'); setBulk(null); }, onError: fail })}>Queue</Button>}>
        {bulk && <div className="space-y-2 text-sm">
          <select className={`${sel} w-full`} value={bulk.person_type} onChange={(e) => setBulk({ ...bulk, person_type: e.target.value })}><option value="student">Students</option><option value="staff">Staff</option></select>
          <RoutePicker value={bulk.route_id} onChange={(v) => setBulk({ ...bulk, route_id: v, stop_id: '' })} label="Route…" />
          {rmap[bulk.route_id] && <select className={`${sel} w-full`} value={bulk.stop_id} onChange={(e) => setBulk({ ...bulk, stop_id: e.target.value })}><option value="">Stop…</option>{rmap[bulk.route_id].stops.map((s: Any) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>}
          <textarea className="h-32 w-full rounded-md border bg-background p-2 font-mono text-xs" placeholder="One id per line (or comma separated)" value={bulk.ids} onChange={(e) => setBulk({ ...bulk, ids: e.target.value })} />
        </div>}
      </Modal>
      <Modal open={!!change} onOpenChange={(o) => !o && setChange(null)} title="Change route / stop" footer={<Button disabled={!change?.new_stop_id} onClick={() => run.mutate(() => transportApi.change(change.id, change), { onSuccess: () => { toast.success('Changed'); setChange(null); }, onError: fail })}>Change</Button>}>
        {change && <div className="space-y-2 text-sm">
          <RoutePicker value={change.new_route_id} onChange={(v) => setChange({ ...change, new_route_id: v, new_stop_id: '' })} label="Route…" />
          {rmap[change.new_route_id] && <select className={`${sel} w-full`} value={change.new_stop_id} onChange={(e) => setChange({ ...change, new_stop_id: e.target.value })}><option value="">Stop…</option>{rmap[change.new_route_id].stops.map((s: Any) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>}
          <label>Effective from <Input type="date" value={change.effective_on} onChange={(e) => setChange({ ...change, effective_on: e.target.value })} /></label>
        </div>}
      </Modal>
    </div>
  );
}

// ---- /admin/transport/trips ----------------------------------------------------------------------------------------------------
export function TripsPage() {
  useTitle('Trips');
  const [day, setDay] = useState(today());
  const [route, setRoute] = useState('');
  const q = useQ(['trips', day, route], () => transportApi.trips({ date: day, route_id: route || undefined }), true, 30000);
  const [sched, setSched] = useState<Any | null>(null);
  const [adhoc, setAdhoc] = useState<Any | null>(null);
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Trips" description="Pickup and drop trips per working day; drivers start / end them from the driver app." actions={<div className="flex gap-1"><Button onClick={() => setSched({ date_from: today(), date_to: today() })}>Schedule</Button><Button variant="outline" onClick={() => setAdhoc({ route_id: '', trip_date: today(), direction: 'pickup' })}>Ad-hoc trip</Button></div>} />
      <div className="flex gap-2"><Input type="date" className="w-44" value={day} onChange={(e) => setDay(e.target.value)} /><RoutePicker value={route} onChange={setRoute} /></div>
      <SimpleTable
        head={['Route', 'Direction', 'Vehicle', 'Driver', 'Status', 'Progress', 'Next stop', 'Delay', 'Boarded', '']}
        rows={list(q.data).map((t: Any) => [
          t.route_code, t.direction, t.vehicle_registration, t.driver_name ?? '—', <StatusBadge key="s" status={t.status} />,
          `${t.stops_done}/${t.stops_total}`, t.next_stop ?? '—', t.delay_minutes != null ? <Badge key="d" variant={t.delay_minutes > 15 ? 'destructive' : 'outline'}>{t.delay_minutes} min</Badge> : '—', `${t.boarded}/${t.manifest}`,
          ['scheduled', 'in_progress'].includes(t.status) ? <Button key="c" size="sm" variant="ghost" onClick={() => { const reason = window.prompt('Reason for cancelling'); if (reason) run.mutate(() => transportApi.cancel(t.id, reason), { onSuccess: () => toast.success('Cancelled; passengers notified'), onError: fail }); }}>Cancel</Button> : null,
        ])}
      />
      <Modal open={!!sched} onOpenChange={(o) => !o && setSched(null)} title="Schedule trips" footer={<Button onClick={() => run.mutate(() => transportApi.schedule(sched), { onSuccess: () => { toast.success('Queued'); setSched(null); }, onError: fail })}>Queue</Button>}>
        {sched && <div className="grid grid-cols-2 gap-2 text-sm"><label>From <Input type="date" value={sched.date_from} onChange={(e) => setSched({ ...sched, date_from: e.target.value })} /></label><label>To <Input type="date" value={sched.date_to} onChange={(e) => setSched({ ...sched, date_to: e.target.value })} /></label><p className="col-span-2 text-xs text-muted-foreground">Weekends per the working-day setting, holidays and days outside a term are skipped.</p></div>}
      </Modal>
      <Modal open={!!adhoc} onOpenChange={(o) => !o && setAdhoc(null)} title="Ad-hoc trip" footer={<Button disabled={!adhoc?.route_id} onClick={() => run.mutate(() => transportApi.adhoc(adhoc), { onSuccess: () => { toast.success('Created'); setAdhoc(null); }, onError: fail })}>Create</Button>}>
        {adhoc && <div className="space-y-2 text-sm"><RoutePicker value={adhoc.route_id} onChange={(v) => setAdhoc({ ...adhoc, route_id: v })} label="Route…" /><Input type="date" value={adhoc.trip_date} onChange={(e) => setAdhoc({ ...adhoc, trip_date: e.target.value })} /><select className={`${sel} w-full`} value={adhoc.direction} onChange={(e) => setAdhoc({ ...adhoc, direction: e.target.value })}><option value="pickup">pickup</option><option value="drop">drop</option></select></div>}
      </Modal>
    </div>
  );
}

// ---- /admin/transport/live ------------------------------------------------------------------------------------------------------
export function LiveMapPage() {
  useTitle('Live fleet');
  const [route, setRoute] = useState('');
  const live = useQ(['live', route], () => transportApi.live({ route_id: route || undefined }), true, 10000);
  const routes = useQ(['routes'], () => transportApi.routes());
  const [replayDay, setReplayDay] = useState(today());
  const trips = useQ(['trips', replayDay, route], () => transportApi.trips({ date: replayDay, route_id: route || undefined }));
  const [trip, setTrip] = useState('');
  const trace = useQ(['trace', trip], () => transportApi.trace(trip), !!trip);
  const [pos, setPos] = useState(100);
  const pts: Any[] = (trace.data as Any)?.data?.points ?? [];
  const shown = pts.slice(0, Math.max(1, Math.round((pts.length * pos) / 100)));
  const stops = route ? list(routes.data).find((r: Any) => r.id === route)?.stops ?? [] : [];
  return (
    <div className="space-y-4">
      <PageHeader title="Live fleet" description="Vehicle positions refresh every 10 s (WebSocket fleet channel when connected); red markers are off-route." />
      <div className="flex gap-2"><RoutePicker value={route} onChange={setRoute} /></div>
      <Section title={`${list(live.data).length} vehicle(s) reporting`}>
        <MiniMap stops={stops} vehicles={list(live.data)} />
        <SimpleTable head={['Vehicle', 'Route', 'Speed', 'Next stop', 'ETA', 'Last fix', 'Alert']} rows={list(live.data).map((v: Any) => [v.registration_no, v.route ?? '—', v.speed != null ? `${v.speed} km/h` : '—', v.next_stop ?? '—', v.eta_min != null ? `${v.eta_min} min` : '—', dt(v.at), v.deviation ? <Badge key="d" variant="destructive">off route</Badge> : ''])} />
      </Section>
      <Section title="Trip replay" action={<div className="flex gap-1">{trip && <Button size="sm" variant="outline" onClick={() => transportApi.gpx(trip).then((b) => openBlob(b, `trip-${trip}.gpx`)).catch(fail)}>GPX</Button>}</div>}>
        <div className="flex flex-wrap gap-2"><Input type="date" className="w-44" value={replayDay} onChange={(e) => setReplayDay(e.target.value)} /><select className={sel} value={trip} onChange={(e) => setTrip(e.target.value)}><option value="">Trip…</option>{list(trips.data).map((t: Any) => <option key={t.id} value={t.id}>{t.route_code} {t.direction} ({t.status})</option>)}</select></div>
        {trip && <>
          <MiniMap trace={shown} stops={list(routes.data).find((r: Any) => r.id === list(trips.data).find((t: Any) => t.id === trip)?.route_id)?.stops ?? []} />
          <input type="range" min={1} max={100} value={pos} onChange={(e) => setPos(Number(e.target.value))} className="w-full" aria-label="Replay position" />
          <p className="text-xs text-muted-foreground">{shown.length} of {pts.length} points ({(trace.data as Any)?.data?.total_points ?? 0} raw, {(trace.data as Any)?.data?.km ?? 0} km){shown.length ? ` · ${dt(shown[shown.length - 1].at)}` : ''}</p>
        </>}
      </Section>
    </div>
  );
}

// ---- /admin/transport/devices ----------------------------------------------------------------------------------------------------
export function DevicesPage() {
  useTitle('GPS devices');
  const q = useQ(['devices'], () => transportApi.devices());
  const vehicles = useQ(['vehicles'], () => transportApi.vehicles());
  const [form, setForm] = useState<Any | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const run = useRun();
  const showToken = (r: Any) => setToken(r?.data?.token ?? null);
  return (
    <div className="space-y-4">
      <PageHeader title="GPS devices" description="Fitted trackers post to /transport/gps/device-ingest with their token (shown once)." actions={<Button onClick={() => setForm({ device_id: '', vehicle_id: '' })}>Register device</Button>} />
      <SimpleTable head={['Device', 'Vehicle', 'Active', 'Last seen', '']} rows={list(q.data).map((d: Any) => [d.device_id, d.vehicle_registration ?? '—', d.is_active ? 'yes' : 'no', dt(d.last_seen_at), <div key="a" className="flex gap-1"><Button size="sm" variant="outline" onClick={() => run.mutate(() => transportApi.rotate(d.id).then(showToken), { onError: fail })}>Rotate token</Button>{d.is_active && <Button size="sm" variant="ghost" onClick={() => run.mutate(() => transportApi.removeDevice(d.id), { onError: fail })}>Deactivate</Button>}</div>])} />
      <Modal open={!!form} onOpenChange={(o) => !o && setForm(null)} title="Register device" footer={<Button disabled={!form?.device_id} onClick={() => run.mutate(() => transportApi.addDevice({ device_id: form.device_id, vehicle_id: form.vehicle_id || null }).then(showToken), { onSuccess: () => setForm(null), onError: fail })}>Register</Button>}>
        {form && <div className="space-y-2 text-sm"><Input placeholder="Device id / IMEI" value={form.device_id} onChange={(e) => setForm({ ...form, device_id: e.target.value })} /><select className={`${sel} w-full`} value={form.vehicle_id} onChange={(e) => setForm({ ...form, vehicle_id: e.target.value })}><option value="">Vehicle…</option>{list(vehicles.data).map((v: Any) => <option key={v.id} value={v.id}>{v.registration_no}</option>)}</select></div>}
      </Modal>
      <Modal open={!!token} onOpenChange={(o) => !o && setToken(null)} title="Device token">
        <p className="text-sm">Copy it into the device now — it is not shown again.</p>
        <code className="block break-all rounded bg-muted p-2 text-xs">{token}</code>
      </Modal>
    </div>
  );
}

// ---- /admin/transport/reports -----------------------------------------------------------------------------------------------------
const KINDS = ['occupancy', 'fees', 'on_time', 'cost_per_km', 'compliance', 'fuel', 'driver_trips'];
export function TransportReportsPage() {
  useTitle('Transport reports');
  const [kind, setKind] = useState('occupancy');
  const stats = useQ(['stats'], () => transportApi.stats());
  const q = useQ(['report', kind], () => transportApi.report(kind));
  const s = (stats.data as Any)?.data ?? {};
  const rep = (q.data as Any)?.data ?? { columns: [], rows: [] };
  return (
    <div className="space-y-4">
      <PageHeader title="Transport reports" description="Occupancy, fee collection, punctuality, costs and compliance." actions={<Button variant="outline" onClick={() => transportApi.exportReport(kind).then(() => toast.success('Export queued — see Jobs')).catch(fail)}>Export XLSX</Button>} />
      <div className="grid gap-3 md:grid-cols-4">
        {[['Vehicles', `${s.vehicles_active ?? 0}/${s.vehicles ?? 0} active`], ['Passengers', `${s.students ?? 0} students · ${s.staff ?? 0} staff`], ['Occupancy', `${s.occupancy_pct ?? 0}%`], ['On time', s.on_time_pct != null ? `${s.on_time_pct}%` : '—'], ['Trips today', `${s.trips_today ?? 0} (${s.in_progress ?? 0} running)`], ['Delayed', s.delayed ?? 0], ['Cost / km', s.cost_per_km != null ? `₹${s.cost_per_km}` : '—'], ['Compliance alerts', s.compliance_alerts ?? 0]].map(([k, v]) => (
          <Card key={String(k)}><CardContent className="p-3"><p className="text-xs text-muted-foreground">{k}</p><p className="text-lg font-semibold">{String(v)}</p></CardContent></Card>
        ))}
      </div>
      <div className="flex flex-wrap gap-1">{KINDS.map((k) => <Button key={k} size="sm" variant={kind === k ? 'default' : 'outline'} onClick={() => setKind(k)}>{k.replace('_', ' ')}</Button>)}</div>
      <SimpleTable head={rep.columns} rows={rep.rows.map((r: Any) => rep.columns.map((c: string) => (c.endsWith('_paise') ? rupees(r[c]) : String(r[c] ?? '—'))))} />
    </div>
  );
}

// ---- /admin/transport/settings ----------------------------------------------------------------------------------------------------
export function TransportSettingsPage() {
  useTitle('Transport settings');
  return (
    <div className="space-y-4">
      <PageHeader title="Transport settings" description="Trip times, GPS interval, alerts, capacity and fee rules live under Settings › transport." />
      <Card><CardContent className="space-y-2 p-4 text-sm">
        <p>Keys: <code>transport.trip_schedule</code>, <code>gps_ping_interval_s</code>, <code>eta_notify_minutes</code>, <code>expiry_alert_days</code>, <code>capacity_hard_limit</code>, <code>block_expired_vehicles</code>, <code>self_service_requests</code>, <code>prorata_change</code>, <code>fee_grace_days</code>, <code>notify_boarding</code>, <code>working_days</code>.</p>
        <Button variant="outline" onClick={() => (window.location.href = '/admin/settings?category=transport')}>Open settings</Button>
      </CardContent></Card>
    </div>
  );
}

// ---- portals ---------------------------------------------------------------------------------------------------------------------
function PassengerCard({ v, title }: { v: Any; title?: string }) {
  const live = useQ(['live-me', v.route?.id], () => transportApi.live({ route_id: v.route?.id }), !!v.live_available, 10000);
  if (!v.allocation) return <p className="text-sm text-muted-foreground">No transport allocation.</p>;
  return (
    <Section title={title ?? `${v.route.code} — ${v.route.name}`} action={<StatusBadge status={v.allocation.status} />}>
      <div className="grid gap-2 text-sm md:grid-cols-2">
        <p>Stop: <b>{v.stop?.name ?? '—'}</b></p><p>Pickup {hm(v.pickup_time)} · Drop {hm(v.drop_time)}</p>
        <p>Vehicle: {v.vehicle ?? '—'} · Driver: {v.driver_name ?? '—'}</p>
        <p>Fee {rupees(v.allocation.fee_paise)} · {v.allocation.fee_status ?? 'no invoice'}{v.allocation.invoice_id && v.allocation.fee_status !== 'paid' ? <a className="ml-2 text-primary underline" href="/student/fees">Pay</a> : null}</p>
      </div>
      <div className="flex flex-wrap gap-1">{(v.today_trips ?? []).map((t: Any) => <Badge key={t.id} variant="outline">{t.direction}: {t.status}</Badge>)}</div>
      {v.live_available ? <MiniMap stops={v.route.stops} vehicles={list(live.data)} height={240} /> : <p className="text-xs text-muted-foreground">Live tracking appears while your bus is on a trip.</p>}
    </Section>
  );
}

export function MyTransportPage() {
  useTitle('My transport');
  const q = useQ(['me'], () => transportApi.me());
  const reqs = useQ(['myreq'], () => transportApi.myRequests());
  const pub = useQ(['public'], () => transportApi.publicRoutes());
  const [req, setReq] = useState<Any>({ route: '', stop_id: '' });
  const run = useRun();
  const routes = list(pub.data);
  const r = routes.find((x: Any) => x.code === req.route);
  return (
    <div className="space-y-4">
      <PageHeader title="My transport" description="Your route, stop, times, fee and the live bus during trips." />
      {q.data && <PassengerCard v={(q.data as Any).data} />}
      <Section title="Request a route / change">
        <div className="flex flex-wrap gap-2">
          <select className={sel} value={req.route} onChange={(e) => setReq({ route: e.target.value, stop_id: '' })}><option value="">Route…</option>{routes.map((x: Any) => <option key={x.code} value={x.code}>{x.code} — {x.name}</option>)}</select>
          {r && <select className={sel} value={req.stop_id} onChange={(e) => setReq({ ...req, stop_id: e.target.value })}><option value="">Stop…</option>{r.stops.map((s: Any) => <option key={s.id} value={s.id}>{s.name} ({hm(s.pickup_time)}) — {rupees(s.fee_paise)}</option>)}</select>}
          <Button disabled={!req.stop_id} onClick={() => run.mutate(() => transportApi.request({ route_id: r.id, stop_id: req.stop_id }), { onSuccess: () => toast.success('Requested'), onError: fail })}>Request</Button>
        </div>
        <SimpleTable head={['Route', 'Stop', 'Status']} rows={list(reqs.data).map((x: Any) => [x.route_code, x.stop_name, <StatusBadge key="s" status={x.status} />])} />
      </Section>
    </div>
  );
}

export function ParentTransportPage() {
  useTitle('Ward transport');
  const q = useQ(['wards'], () => transportApi.wards());
  return (
    <div className="space-y-4">
      <PageHeader title="Transport" description="Your ward's bus live during trips; boarding and alighting alerts arrive as notifications." />
      {list(q.data).length === 0 && <p className="text-sm text-muted-foreground">No ward uses college transport.</p>}
      {list(q.data).map((v: Any) => <PassengerCard key={v.allocation.id} v={v} title={`${v.allocation.person_name} — ${v.route.code}`} />)}
    </div>
  );
}

export function StaffTransportPage() {
  useTitle('My transport');
  return <MyTransportPage />;
}

// ---- /driver (web fallback of the driver app) ----------------------------------------------------------------------------------------
export function DriverPage() {
  useTitle('Driver');
  const q = useQ(['driver', today()], () => transportApi.driverTrips(), true, 20000);
  const [cur, setCur] = useState<string>('');
  const man = useQ(['manifest', cur], () => transportApi.manifest(cur), !!cur, 15000);
  const [odo, setOdo] = useState('');
  const [qr, setQr] = useState('');
  const [watch, setWatch] = useState<number | null>(null);
  const run = useRun();
  const trip = list(q.data).find((t: Any) => t.id === cur);
  const startGps = () => {
    if (!navigator.geolocation) return toast.error('No GPS on this device');
    const id = navigator.geolocation.watchPosition((p) => {
      transportApi.ping({ trip_id: cur, pings: [{ lat: p.coords.latitude, lng: p.coords.longitude, speed_kmh: p.coords.speed != null ? p.coords.speed * 3.6 : null, recorded_at: new Date(p.timestamp).toISOString() }] }).catch(() => undefined);
    }, () => undefined, { enableHighAccuracy: true, maximumAge: 10000 });
    setWatch(id);
  };
  const stopGps = () => { if (watch != null) navigator.geolocation.clearWatch(watch); setWatch(null); };
  useEffect(() => () => { if (watch != null) navigator.geolocation.clearWatch(watch); }, [watch]);
  return (
    <div className="space-y-4">
      <PageHeader title="Today's trips" description="Start the trip, share GPS, mark stops and scan ID cards; end it with the odometer." />
      <div className="grid gap-2 md:grid-cols-2">
        {list(q.data).map((t: Any) => (
          <Card key={t.id} className={cur === t.id ? 'ring-2 ring-primary' : ''}><CardContent className="cursor-pointer space-y-1 p-3 text-sm" onClick={() => setCur(t.id)}>
            <p className="font-medium">{t.route_code} · {t.direction} <StatusBadge status={t.status} /></p>
            <p className="text-xs text-muted-foreground">{t.vehicle_registration} · {t.stops_done}/{t.stops_total} stops · boarded {t.boarded}/{t.manifest}</p>
          </CardContent></Card>
        ))}
        {list(q.data).length === 0 && <p className="text-sm text-muted-foreground">No trips today.</p>}
      </div>
      {trip && <Section title={`${trip.route_code} ${trip.direction}`} action={<div className="flex items-center gap-1">
        <Input className="w-28" placeholder="Odometer" type="number" value={odo} onChange={(e) => setOdo(e.target.value)} />
        {trip.status === 'scheduled' && <Button size="sm" onClick={() => run.mutate(() => transportApi.start(trip.id, { odometer: odo ? Number(odo) : null }), { onSuccess: () => { toast.success('Started'); startGps(); }, onError: fail })}>Start</Button>}
        {trip.status === 'in_progress' && <>{watch == null ? <Button size="sm" variant="outline" onClick={startGps}>Share GPS</Button> : <Badge variant="outline">GPS on</Badge>}<Button size="sm" variant="destructive" onClick={() => run.mutate(() => transportApi.end(trip.id, { odometer: odo ? Number(odo) : null }), { onSuccess: (r: Any) => { toast.success(`Ended${r?.data?.km != null ? ` · ${r.data.km} km` : ''}`); stopGps(); }, onError: fail })}>End</Button></>}
      </div>}>
        {trip.status === 'in_progress' && <div className="flex gap-2"><Input placeholder="Scan / type ID-card QR or register no." value={qr} onChange={(e) => setQr(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && qr) run.mutate(() => transportApi.scan(trip.id, { qr, event: trip.direction === 'pickup' ? 'board' : 'alight' }), { onSuccess: (r: Any) => { toast.success(`${r?.data?.person_name ?? 'Passenger'} ${r?.data?.event}${r?.data?.warning ? ` — ${r.data.warning}` : ''}`); setQr(''); }, onError: fail }); }} /></div>}
        {((man.data as Any)?.data?.stops ?? []).map((s: Any) => (
          <div key={s.stop_id} className="rounded border p-2 text-sm">
            <div className="flex items-center justify-between"><p className="font-medium">{s.sequence}. {s.stop} {s.arrived_at && <Badge variant="outline">arrived {new Date(s.arrived_at).toLocaleTimeString()}</Badge>}</p>
              {trip.status === 'in_progress' && <div className="flex gap-1">{!s.arrived_at && <Button size="sm" variant="outline" onClick={() => run.mutate(() => transportApi.stopEvent(trip.id, { stop_id: s.stop_id, event: 'arrived' }), { onError: fail })}>Arrived</Button>}{s.arrived_at && !s.departed_at && <Button size="sm" variant="outline" onClick={() => run.mutate(() => transportApi.stopEvent(trip.id, { stop_id: s.stop_id, event: 'departed' }), { onError: fail })}>Departed</Button>}</div>}
            </div>
            <div className="mt-1 flex flex-wrap gap-1">{s.passengers.map((p: Any) => <Badge key={p.person_id} variant={p.boarded ? 'default' : p.suspended ? 'destructive' : 'outline'} title={p.phone ?? ''}>{p.name}</Badge>)}</div>
          </div>
        ))}
      </Section>}
    </div>
  );
}
