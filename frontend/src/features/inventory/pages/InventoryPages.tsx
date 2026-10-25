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
import { inventoryApi as inv } from '../api';

// Phase 22 web screens (Prompts/22 §22.9). Rules and visibility live in the API.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));
const useQ = <T,>(key: unknown[], fn: () => Promise<T>, enabled = true) => useQuery({ queryKey: ['inventory', ...key], queryFn: fn, enabled, retry: false });
function useRun() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: () => qc.invalidateQueries({ queryKey: ['inventory'] }) });
}
const rupees = (p: number | null | undefined) => (p == null ? '—' : `₹${(p / 100).toLocaleString('en-IN')}`);
const dt = (v?: string | null) => (v ? new Date(v).toLocaleDateString() : '—');
const list = (r: Any) => (Array.isArray(r?.data) ? r.data : r?.data?.items ?? []);
const today = () => new Date().toISOString().slice(0, 10);
const openBlob = (b: Blob, name: string) => { const u = URL.createObjectURL(b); const a = document.createElement('a'); a.href = u; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(u), 30000); };
const sel = 'h-9 rounded-md border bg-background px-2 text-sm';
const currentFy = () => { const d = new Date(); const y = d.getMonth() >= 3 ? d.getFullYear() : d.getFullYear() - 1; return `${y}-${String(y + 1).slice(2)}`; };

function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <Card><CardContent className="space-y-3 p-4"><div className="flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">{title}</h2>{action}</div>{children}</CardContent></Card>;
}
function StorePicker({ value, onChange, label = 'Store…' }: { value: string; onChange: (v: string) => void; label?: string }) {
  const q = useQ(['stores'], () => inv.stores());
  return <select className={sel} value={value} onChange={(e) => onChange(e.target.value)}><option value="">{label}</option>{list(q.data).map((s: Any) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>;
}
function ItemPicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const q = useQ(['items-all'], () => inv.items());
  return <select className={`${sel} w-full`} value={value} onChange={(e) => onChange(e.target.value)}><option value="">Item…</option>{list(q.data).map((i: Any) => <option key={i.id} value={i.id}>{i.item_code} · {i.name}{i.is_hazardous ? ' ⚠' : ''}</option>)}</select>;
}
function ScopeTabs({ data, value, onChange }: { data: Any; value: string; onChange: (v: string) => void }) {
  const scopes: string[] = data?.meta?.visibility?.scopes ?? [];
  if (scopes.length < 2) return null;
  return <div className="flex gap-1">{['self', ...scopes.filter((s) => s !== 'self')].map((s) => <Button key={s} size="sm" variant={value === s ? 'default' : 'outline'} onClick={() => onChange(s)}>{s === 'self' ? 'Mine' : s}</Button>)}</div>;
}

// ---- /admin/inventory/items -----------------------------------------------------------------------------------------------
export function ItemsPage() {
  useTitle('Items');
  const [f, setF] = useState<Any>({ q: '', category_id: '' });
  const q = useQ(['items', f], () => inv.items({ q: f.q || undefined, category_id: f.category_id || undefined }));
  const cats = useQ(['cats'], () => inv.categories());
  const [form, setForm] = useState<Any | null>(null);
  const [safety, setSafety] = useState<Any | null>(null);
  const [csv, setCsv] = useState<string | null>(null);
  const [ledger, setLedger] = useState<Any | null>(null);
  const led = useQ(['ledger', ledger?.id], () => inv.ledger(ledger.id), !!ledger);
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Items" description="Catalogue with categories; hazardous items carry safety data." actions={<div className="flex gap-1"><Button onClick={() => setForm({ name: '', unit: 'nos', is_consumable: true, is_hazardous: false })}>New item</Button><Button variant="outline" onClick={() => setCsv('code,name,unit,category,consumable,min_stock,reorder_qty,unit_cost_paise,gst_rate\n')}>Import CSV</Button></div>} />
      <div className="flex flex-wrap gap-2">
        <Input className="w-64" placeholder="Search" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} />
        <select className={sel} value={f.category_id} onChange={(e) => setF({ ...f, category_id: e.target.value })}><option value="">All categories</option>{list(cats.data).map((c: Any) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
      </div>
      <SimpleTable head={['Code', 'Item', 'Category', 'Unit', 'On hand', 'Min', 'Cost', '']} rows={list(q.data).slice(0, 300).map((i: Any) => [
        i.item_code, <span key="n">{i.name} {i.is_hazardous && <Badge variant="destructive" className="cursor-pointer" onClick={() => setSafety(i)}>hazardous</Badge>}</span>, i.category ?? '—', i.unit, i.on_hand, i.min_stock_level ?? '—', rupees(i.unit_cost_paise),
        <div key="a" className="flex gap-1"><Button size="sm" variant="ghost" onClick={() => setLedger(i)}>Ledger</Button><Button size="sm" variant="outline" onClick={() => setForm({ ...i })}>Edit</Button></div>,
      ])} />
      <Modal open={!!form} onOpenChange={(o) => !o && setForm(null)} title={form?.id ? 'Edit item' : 'New item'} footer={<Button disabled={!form?.name} onClick={() => {
        const body: Any = { name: form.name, unit: form.unit, category_id: form.category_id || null, min_stock_level: form.min_stock_level === '' || form.min_stock_level == null ? null : Number(form.min_stock_level), reorder_qty: form.reorder_qty === '' || form.reorder_qty == null ? null : Number(form.reorder_qty), gst_rate: form.gst_rate == null || form.gst_rate === '' ? null : Number(form.gst_rate), is_hazardous: !!form.is_hazardous, safety_data: form.is_hazardous ? form.safety_data ?? null : null };
        if (!form.id) Object.assign(body, { item_code: form.item_code || null, is_consumable: !!form.is_consumable, unit_cost_paise: form.unit_cost_paise ? Number(form.unit_cost_paise) : null });
        else body.version = form.version;
        run.mutate(() => inv.saveItem(body, form.id), { onSuccess: () => { toast.success('Saved'); setForm(null); }, onError: fail });
      }}>Save</Button>}>
        {form && <div className="grid grid-cols-2 gap-2 text-sm">
          <label className="col-span-2">Name <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
          {!form.id && <label>Code (blank = auto) <Input value={form.item_code ?? ''} onChange={(e) => setForm({ ...form, item_code: e.target.value })} /></label>}
          <label>Unit <Input value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })} /></label>
          <label>Category <select className={`${sel} w-full`} value={form.category_id ?? ''} onChange={(e) => setForm({ ...form, category_id: e.target.value })}><option value="">—</option>{list(cats.data).map((c: Any) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
          <label>Min stock <Input type="number" value={form.min_stock_level ?? ''} onChange={(e) => setForm({ ...form, min_stock_level: e.target.value })} /></label>
          <label>Reorder qty <Input type="number" value={form.reorder_qty ?? ''} onChange={(e) => setForm({ ...form, reorder_qty: e.target.value })} /></label>
          <label>GST % <Input type="number" value={form.gst_rate ?? ''} onChange={(e) => setForm({ ...form, gst_rate: e.target.value })} /></label>
          {!form.id && <label>Unit cost (paise) <Input type="number" value={form.unit_cost_paise ?? ''} onChange={(e) => setForm({ ...form, unit_cost_paise: e.target.value })} /></label>}
          {!form.id && <label className="flex items-center gap-2"><input type="checkbox" checked={form.is_consumable} onChange={(e) => setForm({ ...form, is_consumable: e.target.checked })} /> Consumable</label>}
          <label className="flex items-center gap-2"><input type="checkbox" checked={form.is_hazardous} onChange={(e) => setForm({ ...form, is_hazardous: e.target.checked })} /> Hazardous</label>
          {form.is_hazardous && <>
            <label>Hazard class <Input value={form.safety_data?.hazard_class ?? ''} onChange={(e) => setForm({ ...form, safety_data: { ...(form.safety_data ?? {}), hazard_class: e.target.value } })} /></label>
            <label>Storage <Input value={form.safety_data?.storage ?? ''} onChange={(e) => setForm({ ...form, safety_data: { ...(form.safety_data ?? {}), storage: e.target.value } })} /></label>
            <label>MSDS URL <Input value={form.safety_data?.msds_url ?? ''} onChange={(e) => setForm({ ...form, safety_data: { ...(form.safety_data ?? {}), msds_url: e.target.value } })} /></label>
            <label>Expiry <Input type="date" value={form.safety_data?.expiry ?? ''} onChange={(e) => setForm({ ...form, safety_data: { ...(form.safety_data ?? {}), expiry: e.target.value } })} /></label>
          </>}
        </div>}
      </Modal>
      <Modal open={!!safety} onOpenChange={(o) => !o && setSafety(null)} title={`Safety data — ${safety?.name ?? ''}`}>
        {safety && <dl className="grid grid-cols-2 gap-1 text-sm">{Object.entries(safety.safety_data ?? {}).map(([k, v]) => <><dt key={`${k}t`} className="text-muted-foreground">{k}</dt><dd key={`${k}d`}>{String(v)}</dd></>)}</dl>}
      </Modal>
      <Modal open={csv != null} onOpenChange={(o) => !o && setCsv(null)} title="Import items" footer={<Button onClick={() => run.mutate(() => inv.importItems(csv ?? ''), { onSuccess: () => { toast.success('Import queued — the job report lists failed rows'); setCsv(null); }, onError: fail })}>Queue import</Button>}>
        <textarea className="h-48 w-full rounded-md border bg-background p-2 font-mono text-xs" value={csv ?? ''} onChange={(e) => setCsv(e.target.value)} />
      </Modal>
      <Modal open={!!ledger} onOpenChange={(o) => !o && setLedger(null)} title={`Ledger — ${ledger?.name ?? ''}`}>
        <SimpleTable head={['Date', 'Type', 'Qty', 'Balance', 'Ref']} rows={list(led.data).slice(0, 100).map((r: Any) => [dt(r.occurred_at), r.txn_type, r.quantity, r.balance, r.reference_type ?? '—'])} />
      </Modal>
    </div>
  );
}

// ---- /admin/inventory/stores --------------------------------------------------------------------------------------------------
export function StoresPage() {
  useTitle('Stores');
  const q = useQ(['stores'], () => inv.stores());
  const [cur, setCur] = useState('');
  const [below, setBelow] = useState(false);
  const stock = useQ(['stock', cur, below], () => inv.stock(cur, below || undefined), !!cur);
  const tx = useQ(['tx', cur], () => inv.transactions({ store_id: cur }), !!cur);
  const [dlg, setDlg] = useState<Any | null>(null);
  const run = useRun();
  const go = () => {
    const lines = [{ item_id: dlg.item_id, quantity: Number(dlg.quantity) }];
    const body: Any =
      dlg.kind === 'transfer' ? { from_store_id: cur, to_store_id: dlg.to_store_id, items: lines }
        : dlg.kind === 'adjust' ? { store_id: cur, item_id: dlg.item_id, quantity: Number(dlg.quantity), reason: dlg.reason }
          : dlg.kind === 'write-off' ? { store_id: cur, items: lines, reason: dlg.reason, approval_ref: dlg.approval_ref || null }
            : dlg.kind === 'return' ? { store_id: cur, items: lines }
              : { store_id: cur, items: lines, issued_to_type: dlg.issued_to_type, issued_to_id: dlg.issued_to_id || null, safety_ack: !!dlg.safety_ack };
    run.mutate(() => inv.move(dlg.kind, body), { onSuccess: () => { toast.success('Recorded'); setDlg(null); }, onError: fail });
  };
  return (
    <div className="space-y-4">
      <PageHeader title="Stores & stock" description="Every movement is a ledger transaction; stock never goes negative." />
      <div className="grid gap-3 md:grid-cols-3">{list(q.data).map((s: Any) => (
        <Card key={s.id} className={cur === s.id ? 'ring-2 ring-primary' : ''}><CardContent className="cursor-pointer space-y-1 p-3 text-sm" onClick={() => setCur(s.id)}>
          <p className="font-medium">{s.name} <Badge variant="outline">{s.store_type}</Badge></p>
          <p className="text-xs text-muted-foreground">{s.items} items · {s.below_min} below min · keeper {s.keeper_name ?? '—'}{s.value_paise ? ` · ${rupees(s.value_paise)}` : ''}</p>
        </CardContent></Card>
      ))}</div>
      {cur && <Section title="Stock" action={<div className="flex flex-wrap items-center gap-1">
        <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={below} onChange={(e) => setBelow(e.target.checked)} /> below min</label>
        {(['issue', 'return', 'transfer', 'adjust', 'write-off'] as const).map((k) => <Button key={k} size="sm" variant="outline" onClick={() => setDlg({ kind: k, item_id: '', quantity: 1, issued_to_type: 'department', reason: '' })}>{k}</Button>)}
      </div>}>
        <SimpleTable head={['Code', 'Item', 'Qty', 'Min', 'Reorder', '']} rows={list(stock.data).map((r: Any) => [r.item_code, <span key="n">{r.item_name} {r.is_hazardous && <Badge variant="destructive">hazardous</Badge>}</span>, `${r.quantity} ${r.unit}`, r.min_stock_level ?? '—', r.reorder_qty ?? '—', r.below_min ? <Badge key="b" variant="warning">below min</Badge> : null])} />
        <h3 className="pt-2 text-xs font-semibold uppercase text-muted-foreground">Transactions</h3>
        <SimpleTable head={['When', 'Item', 'Type', 'Qty', 'To / ref']} rows={list(tx.data).slice(0, 50).map((t: Any) => [dt(t.occurred_at), t.item_name, t.txn_type, t.quantity, t.issued_to_type ?? t.reference_type ?? '—'])} />
      </Section>}
      <Modal open={!!dlg} onOpenChange={(o) => !o && setDlg(null)} title={dlg ? `Stock ${dlg.kind}` : ''} footer={<Button disabled={!dlg?.item_id} onClick={go}>Record</Button>}>
        {dlg && <div className="space-y-2 text-sm">
          <ItemPicker value={dlg.item_id} onChange={(v) => setDlg({ ...dlg, item_id: v })} />
          <Input type="number" placeholder={dlg.kind === 'adjust' ? 'Signed change (e.g. -2)' : 'Quantity'} value={dlg.quantity} onChange={(e) => setDlg({ ...dlg, quantity: e.target.value })} />
          {dlg.kind === 'issue' && <><select className={`${sel} w-full`} value={dlg.issued_to_type} onChange={(e) => setDlg({ ...dlg, issued_to_type: e.target.value })}>{['department', 'lab', 'staff', 'student', 'event'].map((t) => <option key={t}>{t}</option>)}</select><Input placeholder="Recipient id (optional)" value={dlg.issued_to_id ?? ''} onChange={(e) => setDlg({ ...dlg, issued_to_id: e.target.value })} /><label className="flex items-center gap-2"><input type="checkbox" checked={!!dlg.safety_ack} onChange={(e) => setDlg({ ...dlg, safety_ack: e.target.checked })} /> Receiver acknowledged the safety data (hazardous items)</label></>}
          {dlg.kind === 'transfer' && <StorePicker value={dlg.to_store_id ?? ''} onChange={(v) => setDlg({ ...dlg, to_store_id: v })} label="To store…" />}
          {['adjust', 'write-off'].includes(dlg.kind) && <Input placeholder="Reason" value={dlg.reason} onChange={(e) => setDlg({ ...dlg, reason: e.target.value })} />}
          {dlg.kind === 'write-off' && <Input placeholder="Approval reference (above threshold)" value={dlg.approval_ref ?? ''} onChange={(e) => setDlg({ ...dlg, approval_ref: e.target.value })} />}
        </div>}
      </Modal>
    </div>
  );
}

// ---- /admin/inventory/suppliers --------------------------------------------------------------------------------------------------
export function SuppliersPage() {
  useTitle('Suppliers');
  const [status, setStatus] = useState('');
  const q = useQ(['suppliers', status], () => inv.suppliers({ status: status || undefined }));
  const [form, setForm] = useState<Any | null>(null);
  const [stmt, setStmt] = useState<Any | null>(null);
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Suppliers" description="Registered (portal) → verified → active; blacklisting blocks new POs." actions={<Button onClick={() => setForm({ name: '', gstin: '', pan: '', email: '', supplier_type: 'company' })}>Add supplier</Button>} />
      <select className={sel} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Any status</option>{['registered', 'active', 'blacklisted'].map((s) => <option key={s}>{s}</option>)}</select>
      <SimpleTable head={['Supplier', 'GSTIN', 'Categories', 'Rating', 'Bank', 'Status', '']} rows={list(q.data).map((s: Any) => [
        s.name, s.gstin ?? '—', (s.categories ?? []).join(', '), s.rating ?? '—', s.bank_details ? `${s.bank_details.bank ?? ''} ${s.bank_details.account_no ?? ''}` : '—', <StatusBadge key="s" status={s.status} />,
        <div key="a" className="flex gap-1">
          {s.status === 'registered' && <Button size="sm" onClick={() => run.mutate(() => inv.verifySupplier(s.id), { onSuccess: () => toast.success('Verified — portal user created'), onError: fail })}>Verify</Button>}
          {s.status !== 'blacklisted' && <Button size="sm" variant="ghost" onClick={() => { const r = window.prompt('Blacklist reason'); if (r) run.mutate(() => inv.blacklist(s.id, r), { onError: fail }); }}>Blacklist</Button>}
          <Button size="sm" variant="ghost" onClick={() => inv.statement(s.id).then((r: Any) => setStmt({ s, data: r.data })).catch(fail)}>Statement</Button>
        </div>,
      ])} />
      <Modal open={!!form} onOpenChange={(o) => !o && setForm(null)} title="Add supplier" footer={<Button disabled={!form?.name} onClick={() => run.mutate(() => inv.saveSupplier({ name: form.name, gstin: form.gstin || null, pan: form.pan || null, contact: { email: form.email || null }, supplier_type: form.supplier_type }), { onSuccess: () => { toast.success('Added'); setForm(null); }, onError: fail })}>Save</Button>}>
        {form && <div className="space-y-2 text-sm"><Input placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /><Input placeholder="GSTIN" value={form.gstin} onChange={(e) => setForm({ ...form, gstin: e.target.value.toUpperCase() })} /><Input placeholder="PAN" value={form.pan} onChange={(e) => setForm({ ...form, pan: e.target.value.toUpperCase() })} /><Input placeholder="Email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /><select className={`${sel} w-full`} value={form.supplier_type} onChange={(e) => setForm({ ...form, supplier_type: e.target.value })}>{['company', 'firm', 'individual', 'government'].map((t) => <option key={t}>{t}</option>)}</select></div>}
      </Modal>
      <Modal open={!!stmt} onOpenChange={(o) => !o && setStmt(null)} title={`Statement — ${stmt?.s.name ?? ''}`}>
        {stmt && <div className="space-y-2 text-sm"><p>Billed {rupees(stmt.data.billed_paise)} · paid {rupees(stmt.data.paid_paise)} · outstanding {rupees(stmt.data.outstanding_paise)}</p><SimpleTable head={['PO', 'Date', 'Total', 'Status']} rows={stmt.data.purchase_orders.map((p: Any) => [p.po_number, p.date, rupees(p.total_paise), p.status])} /></div>}
      </Modal>
    </div>
  );
}

// ---- /admin/inventory/indents --------------------------------------------------------------------------------------------------
function IndentForm({ onDone }: { onDone: () => void }) {
  const [b, setB] = useState<Any>({ purpose: '', priority: 'normal', items: [{ item_id: '', qty: 1, est_unit_cost_paise: 0 }] });
  const run = useRun();
  return (
    <div className="space-y-2 text-sm">
      <Input placeholder="Purpose" value={b.purpose} onChange={(e) => setB({ ...b, purpose: e.target.value })} />
      <select className={`${sel} w-full`} value={b.priority} onChange={(e) => setB({ ...b, priority: e.target.value })}>{['low', 'normal', 'high', 'emergency'].map((p) => <option key={p}>{p}</option>)}</select>
      {b.priority === 'emergency' && <Input placeholder="Principal approval reference" value={b.emergency_approval_ref ?? ''} onChange={(e) => setB({ ...b, emergency_approval_ref: e.target.value })} />}
      {b.items.map((ln: Any, i: number) => (
        <div key={i} className="grid grid-cols-[1fr_80px_32px] gap-1">
          {ln.free ? <Input placeholder="Describe the item" value={ln.free_text ?? ''} onChange={(e) => setB({ ...b, items: b.items.map((x: Any, j: number) => (j === i ? { ...x, free_text: e.target.value } : x)) })} /> : <ItemPicker value={ln.item_id} onChange={(v) => setB({ ...b, items: b.items.map((x: Any, j: number) => (j === i ? { ...x, item_id: v } : x)) })} />}
          <Input type="number" value={ln.qty} onChange={(e) => setB({ ...b, items: b.items.map((x: Any, j: number) => (j === i ? { ...x, qty: e.target.value } : x)) })} />
          <Button size="sm" variant="ghost" onClick={() => setB({ ...b, items: b.items.filter((_: Any, j: number) => j !== i) })}>×</Button>
        </div>
      ))}
      <div className="flex gap-1"><Button size="sm" variant="outline" onClick={() => setB({ ...b, items: [...b.items, { item_id: '', qty: 1 }] })}>+ Item</Button><Button size="sm" variant="outline" onClick={() => setB({ ...b, items: [...b.items, { free: true, free_text: '', qty: 1, est_unit_cost_paise: 0 }] })}>+ Free text</Button></div>
      <Button disabled={!b.purpose} onClick={() => run.mutate(() => inv.createIndent({ purpose: b.purpose, priority: b.priority, emergency_approval_ref: b.emergency_approval_ref || null, items: b.items.map((x: Any) => ({ item_id: x.free ? null : x.item_id || null, free_text: x.free ? x.free_text : null, qty: Number(x.qty), est_unit_cost_paise: Number(x.est_unit_cost_paise || 0) })) }).then((r: Any) => inv.submitIndent(r.data.id)), { onSuccess: () => { toast.success('Submitted for approval'); onDone(); }, onError: fail })}>Create & submit</Button>
    </div>
  );
}

export function IndentsPage() {
  useTitle('Indents');
  const [scope, setScope] = useState('');
  const [status, setStatus] = useState('');
  const q = useQ(['indents', scope, status], () => inv.indents({ scope: scope || undefined, status: status || undefined }));
  const [open, setOpen] = useState(false);
  const [cur, setCur] = useState<Any | null>(null);
  const [fulfil, setFulfil] = useState<Any | null>(null);
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Indents" description="Raise → HOD → inventory manager → accounts (budget check); fulfil from stock or convert to procurement." actions={<Button onClick={() => setOpen(true)}>New indent</Button>} />
      <div className="flex flex-wrap gap-2"><ScopeTabs data={q.data} value={scope || 'all'} onChange={setScope} /><select className={sel} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Any status</option>{['draft', 'submitted', 'hod_approved', 'approved', 'rejected', 'fulfilled', 'closed'].map((s) => <option key={s}>{s}</option>)}</select></div>
      <SimpleTable head={['Indent', 'Dept', 'Requester', 'Purpose', 'Estimate', 'Priority', 'Status', 'Done', '']} rows={list(q.data).map((r: Any) => [
        <button key="n" className="underline" onClick={() => setCur(r)}>{r.indent_number}</button>, r.department_code ?? '—', r.requester_name ?? '—', r.purpose, rupees(r.estimated_paise), r.priority, <span key="s"><StatusBadge status={r.status} />{r.workflow_step && <span className="ml-1 text-xs text-muted-foreground">{r.workflow_step}</span>}</span>, `${r.fulfilment_pct}%`,
        <div key="a" className="flex gap-1">
          {r.status === 'draft' && <Button size="sm" onClick={() => run.mutate(() => inv.submitIndent(r.id), { onError: fail })}>Submit</Button>}
          {r.status === 'approved' && <Button size="sm" variant="outline" onClick={() => setFulfil({ indent: r, store_id: r.store_id ?? '', qty: Object.fromEntries(r.items.map((_: Any, i: number) => [i, ''])) })}>Fulfil</Button>}
          {['approved', 'fulfilled'].includes(r.status) && <Button size="sm" variant="ghost" onClick={() => run.mutate(() => inv.closeIndent(r.id), { onError: fail })}>Close</Button>}
        </div>,
      ])} />
      <Modal open={open} onOpenChange={setOpen} title="New indent"><IndentForm onDone={() => setOpen(false)} /></Modal>
      <Modal open={!!cur} onOpenChange={(o) => !o && setCur(null)} title={cur ? `${cur.indent_number} · ${cur.status}` : ''}>
        {cur && <div className="space-y-2 text-sm"><p>{cur.purpose}</p><SimpleTable head={['Line', 'Qty', 'Est.', 'Issued', 'Procured']} rows={cur.items.map((x: Any) => [x.name ?? x.free_text, `${x.qty} ${x.unit ?? ''}`, rupees(x.est_unit_cost_paise), x.issued ?? 0, x.procured ?? 0])} /><p className="text-xs text-muted-foreground">{cur.quotations} quotation(s) · {cur.po_ids.length} PO(s){cur.workflow_step ? ` · workflow ${cur.workflow_step}` : ''}</p></div>}
      </Modal>
      <Modal open={!!fulfil} onOpenChange={(o) => !o && setFulfil(null)} title="Fulfil from stock" footer={<Button onClick={() => run.mutate(() => inv.fulfil(fulfil.indent.id, { store_id: fulfil.store_id || null, safety_ack: !!fulfil.safety_ack, items: Object.entries(fulfil.qty).filter(([, v]) => Number(v) > 0).map(([k, v]) => ({ line: Number(k), qty_from_stock: Number(v) })) }), { onSuccess: () => { toast.success('Issued'); setFulfil(null); }, onError: fail })}>Issue</Button>}>
        {fulfil && <div className="space-y-2 text-sm"><StorePicker value={fulfil.store_id} onChange={(v) => setFulfil({ ...fulfil, store_id: v })} />{fulfil.indent.items.map((x: Any, i: number) => x.item_id ? <div key={i} className="grid grid-cols-[1fr_100px] gap-2"><span>{x.name} (need {x.qty - (x.issued ?? 0) - (x.procured ?? 0)})</span><Input type="number" value={fulfil.qty[i]} onChange={(e) => setFulfil({ ...fulfil, qty: { ...fulfil.qty, [i]: e.target.value } })} /></div> : null)}<label className="flex items-center gap-2"><input type="checkbox" checked={!!fulfil.safety_ack} onChange={(e) => setFulfil({ ...fulfil, safety_ack: e.target.checked })} /> Safety acknowledged (hazardous lines)</label></div>}
      </Modal>
    </div>
  );
}

// ---- /admin/inventory/quotations ------------------------------------------------------------------------------------------------
export function QuotationsPage() {
  useTitle('Quotations');
  const approved = useQ(['indents', 'approved'], () => inv.indents({ status: 'approved' }));
  const sups = useQ(['suppliers', 'active'], () => inv.suppliers({ status: 'active' }));
  const [cur, setCur] = useState('');
  const cs = useQ(['cs', cur], () => inv.comparative(cur), !!cur);
  const [form, setForm] = useState<Any | null>(null);
  const run = useRun();
  const ind = list(approved.data).find((r: Any) => r.id === cur);
  const c = (cs.data as Any)?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Quotations & comparative statement" description="Three quotations (or a GeM / tender reference) above the threshold; L1 highlighted per line." />
      <select className={sel} value={cur} onChange={(e) => setCur(e.target.value)}><option value="">Approved indent…</option>{list(approved.data).map((r: Any) => <option key={r.id} value={r.id}>{r.indent_number} · {rupees(r.estimated_paise)}</option>)}</select>
      {c && <Section title={`${c.suppliers.length} quotation(s)`} action={<div className="flex gap-1"><Button size="sm" onClick={() => setForm({ supplier_id: '', reference: '', gem_ref: '', prices: Object.fromEntries(ind.items.map((_: Any, i: number) => [i, ''])) })}>Add quotation</Button><Button size="sm" variant="outline" disabled={!c.suppliers.some((s: Any) => s.is_selected)} onClick={() => { const s = c.suppliers.find((x: Any) => x.is_selected); run.mutate(() => inv.createPo({ supplier_id: s.supplier_id, indent_id: cur, quotation_id: s.quotation_id }), { onSuccess: () => toast.success('PO drafted'), onError: fail }); }}>Create PO from selected</Button></div>}>
        <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="text-left text-xs text-muted-foreground"><th className="p-2">Line</th><th>Qty</th>{c.suppliers.map((s: Any) => <th key={s.supplier_id} className="p-2">{s.name}{s.is_selected && ' ✓'}</th>)}</tr></thead>
          <tbody>{c.rows.map((r: Any) => <tr key={r.line} className="border-t"><td className="p-2">{r.item}</td><td>{r.qty}</td>{c.suppliers.map((s: Any) => { const v = r.per_supplier[s.supplier_id]; const l1 = c.lowest_by_item[String(r.line)] === s.supplier_id; return <td key={s.supplier_id} className={`p-2 ${l1 ? 'font-semibold text-emerald-600' : ''}`}>{v ? rupees(v.price) : '—'}{l1 ? ' L1' : ''}</td>; })}</tr>)}
            <tr className="border-t font-medium"><td className="p-2">Total</td><td />{c.suppliers.map((s: Any) => <td key={s.supplier_id} className="p-2">{rupees(s.total_paise)} <Button size="sm" variant="ghost" onClick={() => run.mutate(() => inv.selectQuotation(s.quotation_id), { onError: fail })}>Select</Button></td>)}</tr>
          </tbody></table></div>
      </Section>}
      <Modal open={!!form} onOpenChange={(o) => !o && setForm(null)} title="Record quotation" footer={<Button disabled={!form?.supplier_id} onClick={() => run.mutate(() => inv.addQuotation(cur, { supplier_id: form.supplier_id, reference: form.reference || null, gem_ref: form.gem_ref || null, items: ind.items.map((x: Any, i: number) => ({ line: i, qty: x.qty, unit_price_paise: Number(form.prices[i] || 0), tax_rate: 18 })).filter((x: Any) => x.unit_price_paise > 0) }), { onSuccess: () => { toast.success('Recorded'); setForm(null); }, onError: fail })}>Save</Button>}>
        {form && <div className="space-y-2 text-sm"><select className={`${sel} w-full`} value={form.supplier_id} onChange={(e) => setForm({ ...form, supplier_id: e.target.value })}><option value="">Supplier…</option>{list(sups.data).map((s: Any) => <option key={s.id} value={s.id}>{s.name}</option>)}</select><Input placeholder="Reference" value={form.reference} onChange={(e) => setForm({ ...form, reference: e.target.value })} /><Input placeholder="GeM / tender ref" value={form.gem_ref} onChange={(e) => setForm({ ...form, gem_ref: e.target.value })} />{ind.items.map((x: Any, i: number) => <div key={i} className="grid grid-cols-[1fr_120px] gap-2"><span>{x.name ?? x.free_text} × {x.qty}</span><Input type="number" placeholder="Unit price (paise)" value={form.prices[i]} onChange={(e) => setForm({ ...form, prices: { ...form.prices, [i]: e.target.value } })} /></div>)}</div>}
      </Modal>
    </div>
  );
}

// ---- /admin/inventory/purchase-orders ---------------------------------------------------------------------------------------------
export function PurchaseOrdersPage() {
  useTitle('Purchase orders');
  const [status, setStatus] = useState('');
  const q = useQ(['pos', status], () => inv.pos({ status: status || undefined }));
  const [cur, setCur] = useState<Any | null>(null);
  const run = useRun();
  const act = (id: string, a: string, b: Any = {}) => run.mutate(() => inv.poAction(id, a, b), { onSuccess: () => toast.success(a), onError: fail });
  return (
    <div className="space-y-4">
      <PageHeader title="Purchase orders" description="Draft → submit (workflow above the threshold, else direct approval) → send → receive; amend before receipt." />
      <select className={sel} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Any status</option>{['draft', 'submitted', 'approved', 'sent', 'partially_received', 'received', 'cancelled', 'closed'].map((s) => <option key={s}>{s}</option>)}</select>
      <SimpleTable head={['PO', 'Supplier', 'Date', 'Total', 'Version', 'Status', '']} rows={list(q.data).map((p: Any) => [
        <button key="n" className="underline" onClick={() => setCur(p)}>{p.po_number}</button>, p.supplier_name, p.order_date, rupees(p.total_paise), `v${p.version}`, <StatusBadge key="s" status={p.status} />,
        <div key="a" className="flex flex-wrap gap-1">
          {p.status === 'draft' && <Button size="sm" onClick={() => act(p.id, 'submit')}>Submit</Button>}
          {p.status === 'submitted' && !p.workflow_instance_id && <Button size="sm" onClick={() => run.mutate(() => inv.poAction(p.id, 'approve'), { onError: fail })}>Approve</Button>}
          {p.status === 'approved' && <Button size="sm" onClick={() => act(p.id, 'send')}>Send</Button>}
          {['approved', 'sent'].includes(p.status) && <Button size="sm" variant="outline" onClick={() => { const r = window.prompt('Amendment reason'); if (r) act(p.id, 'amend', { reason: r }); }}>Amend</Button>}
          {!['received', 'closed', 'cancelled', 'partially_received'].includes(p.status) && <Button size="sm" variant="ghost" onClick={() => { const r = window.prompt('Cancel reason'); if (r) act(p.id, 'cancel', { reason: r }); }}>Cancel</Button>}
          <Button size="sm" variant="ghost" onClick={() => inv.poPdf(p.id).then((b) => openBlob(b, `${p.po_number.split('/').join('-')}.pdf`)).catch(fail)}>PDF</Button>
        </div>,
      ])} />
      <Modal open={!!cur} onOpenChange={(o) => !o && setCur(null)} title={cur ? `${cur.po_number} · ${cur.supplier_name}` : ''}>
        {cur && <div className="space-y-2 text-sm"><SimpleTable head={['Item', 'Qty', 'Rate', 'Tax %', 'Received']} rows={cur.items.map((x: Any) => [x.item_name, x.quantity, rupees(x.unit_price_paise), x.tax_rate ?? 0, x.received_qty])} /><p>Subtotal {rupees(cur.subtotal_paise)} · tax {rupees(cur.tax_paise)} · total {rupees(cur.total_paise)}{cur.acknowledged_at ? ` · acknowledged ${dt(cur.acknowledged_at)}` : ''}</p><p className="text-xs text-muted-foreground">Receipts: {cur.receipts.map((r: Any) => r.grn_number).join(', ') || 'none'}</p></div>}
      </Modal>
    </div>
  );
}

// ---- /admin/inventory/goods-receipts ------------------------------------------------------------------------------------------------
export function GoodsReceiptsPage() {
  useTitle('Goods receipts');
  const q = useQ(['grns'], () => inv.grns());
  const open = useQ(['pos', 'open'], async () => ({ data: [...list(await inv.pos({ status: 'sent' })), ...list(await inv.pos({ status: 'partially_received' })), ...list(await inv.pos({ status: 'approved' }))] }));
  const [form, setForm] = useState<Any | null>(null);
  const [assets, setAssets] = useState<Any | null>(null);
  const run = useRun();
  const po = form ? list(open.data).find((p: Any) => p.id === form.po_id) : null;
  return (
    <div className="space-y-4">
      <PageHeader title="Goods receipts" description="Receive against a PO (partial allowed); accepted lines enter stock at the PO price." actions={<Button onClick={() => setForm({ po_id: '', store_id: '', received_on: today(), invoice_no: '', lines: {} })}>Receive goods</Button>} />
      <SimpleTable head={['GRN', 'PO', 'Received', 'Invoice', 'Lines', '']} rows={list(q.data).map((g: Any) => [g.grn_number, g.po_number, g.received_on, g.invoice_no ?? '—', g.items.length, <div key="a" className="flex gap-1"><Button size="sm" variant="ghost" onClick={() => inv.grnPdf(g.id).then((b) => openBlob(b, `${g.grn_number.split('/').join('-')}.pdf`)).catch(fail)}>PDF</Button>{g.asset_lines.length > 0 && <Button size="sm" variant="outline" onClick={() => setAssets({ grn: g, category: 'IT hardware' })}>Create assets</Button>}</div>])} />
      <Modal open={!!form} onOpenChange={(o) => !o && setForm(null)} title="Receive goods" footer={<Button disabled={!form?.po_id || !form?.store_id} onClick={() => run.mutate(() => inv.receive({ po_id: form.po_id, store_id: form.store_id, received_on: form.received_on, invoice_no: form.invoice_no || null, items: po.items.map((x: Any) => ({ po_item_id: x.id, qty_received: Number(form.lines[x.id]?.recv ?? 0), qty_rejected: Number(form.lines[x.id]?.rej ?? 0) })).filter((x: Any) => x.qty_received > 0) }), { onSuccess: (r: Any) => { toast.success(r?.data?.asset_lines?.length ? 'Received — create assets for the non-consumable lines' : 'Received'); setForm(null); }, onError: fail })}>Receive</Button>}>
        {form && <div className="space-y-2 text-sm">
          <select className={`${sel} w-full`} value={form.po_id} onChange={(e) => setForm({ ...form, po_id: e.target.value, lines: {} })}><option value="">PO…</option>{list(open.data).map((p: Any) => <option key={p.id} value={p.id}>{p.po_number} · {p.supplier_name} · {p.status}</option>)}</select>
          <StorePicker value={form.store_id} onChange={(v) => setForm({ ...form, store_id: v })} />
          <div className="grid grid-cols-2 gap-2"><Input type="date" value={form.received_on} onChange={(e) => setForm({ ...form, received_on: e.target.value })} /><Input placeholder="Supplier invoice no." value={form.invoice_no} onChange={(e) => setForm({ ...form, invoice_no: e.target.value })} /></div>
          {po?.items.map((x: Any) => <div key={x.id} className="grid grid-cols-[1fr_90px_90px] gap-2"><span>{x.item_name} ({x.received_qty}/{x.quantity})</span><Input type="number" placeholder="Received" value={form.lines[x.id]?.recv ?? ''} onChange={(e) => setForm({ ...form, lines: { ...form.lines, [x.id]: { ...form.lines[x.id], recv: e.target.value } } })} /><Input type="number" placeholder="Rejected" value={form.lines[x.id]?.rej ?? ''} onChange={(e) => setForm({ ...form, lines: { ...form.lines, [x.id]: { ...form.lines[x.id], rej: e.target.value } } })} /></div>)}
        </div>}
      </Modal>
      <Modal open={!!assets} onOpenChange={(o) => !o && setAssets(null)} title="Create assets from GRN" footer={<Button onClick={() => run.mutate(() => inv.assetsFromGrn({ grn_id: assets.grn.id, item_ids: assets.grn.asset_lines.map((x: Any) => x.item_id), category: assets.category }), { onSuccess: (r: Any) => { toast.success(`${list(r).length} asset(s) tagged`); setAssets(null); }, onError: fail })}>Create</Button>}>
        {assets && <div className="space-y-2 text-sm"><p>{assets.grn.asset_lines.map((x: Any) => `${x.item} × ${x.accepted}`).join(', ')}</p><Input placeholder="Category" value={assets.category} onChange={(e) => setAssets({ ...assets, category: e.target.value })} /></div>}
      </Modal>
    </div>
  );
}

// ---- /admin/inventory/assets ----------------------------------------------------------------------------------------------------------
export function AssetsPage() {
  useTitle('Assets');
  const [f, setF] = useState<Any>({ status: '', q: '' });
  const q = useQ(['assets', f], () => inv.assets({ status: f.status || undefined, q: f.q || undefined }));
  const [cur, setCur] = useState<Any | null>(null);
  const hist = useQ(['ahist', cur?.id], () => inv.assetHistory(cur.id), !!cur);
  const [fy, setFy] = useState(currentFy());
  const [dep, setDep] = useState<Any | null>(null);
  const run = useRun();
  const h = (hist.data as Any)?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Asset register" description="Tags, custody, location, depreciation, audits and disposal." actions={<div className="flex gap-1"><Button variant="outline" onClick={() => run.mutate(() => inv.qrLabels({ asset_ids: list(q.data).slice(0, 100).map((a: Any) => a.id) }), { onSuccess: () => toast.success('Label sheet queued — see Jobs'), onError: fail })}>QR labels (first 100)</Button><Input className="w-24" value={fy} onChange={(e) => setFy(e.target.value)} /><Button variant="outline" onClick={() => run.mutate(() => inv.depreciationPreview(fy).then((r: Any) => setDep(r.data)), { onError: fail })}>Depreciation preview</Button></div>} />
      <div className="flex flex-wrap gap-2"><Input className="w-64" placeholder="Search tag / name" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} /><select className={sel} value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="">Any status</option>{['in_use', 'idle', 'under_repair', 'condemned', 'disposed'].map((s) => <option key={s}>{s}</option>)}</select></div>
      <SimpleTable head={['Tag', 'Asset', 'Category', 'Dept', 'Custodian', 'Location', 'Value', 'Status']} rows={list(q.data).slice(0, 300).map((a: Any) => [<button key="t" className="underline" onClick={() => setCur(a)}>{a.asset_tag}</button>, a.name, a.category ?? '—', a.department_code ?? '—', <span key="c">{a.custodian_name ?? '—'}{a.pending_custodian_staff_id && <Badge variant="warning" className="ml-1">transfer pending</Badge>}</span>, a.location ?? '—', rupees(a.current_value_paise), <StatusBadge key="s" status={a.status} />])} />
      <Modal open={!!cur} onOpenChange={(o) => !o && setCur(null)} title={cur ? `${cur.asset_tag} — ${cur.name}` : ''}>
        {cur && <div className="space-y-3 text-sm">
          <p>Cost {rupees(cur.cost_paise)} · now {rupees(cur.current_value_paise)} · {cur.depreciation_method} {cur.depreciation_rate}% · warranty {cur.warranty_until ?? '—'}</p>
          <div className="flex flex-wrap gap-1">
            <Button size="sm" variant="outline" onClick={() => { const s = window.prompt('New custodian staff id'); if (s) run.mutate(() => inv.transferAsset(cur.id, { custodian_staff_id: s }), { onSuccess: () => toast.success('Awaiting acceptance'), onError: fail }); }}>Transfer custody</Button>
            {(['under_repair', 'idle', 'in_use', 'condemned', 'disposed'] as const).map((s) => <Button key={s} size="sm" variant="ghost" onClick={() => { const reason = window.prompt(`Reason (${s})`); if (!reason) return; const approval_ref = ['condemned', 'disposed'].includes(s) ? window.prompt('Approval / committee reference') : null; const sale = s === 'disposed' ? Number(window.prompt('Sale value (paise)') || 0) : null; run.mutate(() => inv.assetStatus(cur.id, { status: s, reason, approval_ref, sale_value_paise: sale }), { onSuccess: () => toast.success(s), onError: fail }); }}>{s}</Button>)}
          </div>
          {h && <>
            <h3 className="text-xs font-semibold uppercase text-muted-foreground">Depreciation schedule</h3>
            <SimpleTable head={['Year', 'Depreciation', 'Closing']} rows={h.schedule.map((r: Any) => [r.year, rupees(r.depreciation_paise), rupees(r.closing_paise)])} />
            <h3 className="text-xs font-semibold uppercase text-muted-foreground">Custody</h3>
            <SimpleTable head={['At', 'From', 'To']} rows={h.custody.map((c: Any) => [dt(c.at), c.from ?? '—', c.to])} />
            <h3 className="text-xs font-semibold uppercase text-muted-foreground">Audits</h3>
            <SimpleTable head={['On', 'Found', 'Condition']} rows={h.audits.map((x: Any) => [x.on, x.found ? 'yes' : 'missing', x.condition ?? '—'])} />
          </>}
        </div>}
      </Modal>
      <Modal open={!!dep} onOpenChange={(o) => !o && setDep(null)} title={`Depreciation ${dep?.financial_year ?? ''} (preview)`} footer={<Button onClick={() => run.mutate(() => inv.depreciationRun(dep.financial_year), { onSuccess: () => { toast.success('Run queued'); setDep(null); }, onError: fail })}>Run for the year</Button>}>
        {dep && <div className="space-y-2 text-sm"><p>{dep.assets} assets · {rupees(dep.depreciation_paise)}</p><SimpleTable head={['Tag', 'Method', 'Opening', 'Dep.', 'Closing']} rows={dep.rows.slice(0, 50).map((r: Any) => [r.tag, r.method, rupees(r.opening_paise), rupees(r.depreciation_paise), rupees(r.closing_paise)])} /></div>}
      </Modal>
    </div>
  );
}

// ---- /admin/inventory/audits ------------------------------------------------------------------------------------------------------------
export function AuditsPage() {
  useTitle('Asset audits');
  const q = useQ(['audits'], () => inv.audits());
  const depts = useQ(['depts'], () => inv.departments());
  const [dept, setDept] = useState('');
  const [cur, setCur] = useState<Any | null>(null);
  const [tags, setTags] = useState('');
  const rep = useQ(['arep', cur?.id], () => inv.auditReport(cur.id), !!cur);
  const run = useRun();
  const r = (rep.data as Any)?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Physical asset audits" description="Start a cycle for a scope, scan tags / QR labels, complete for found / missing / unexpected." />
      <div className="flex gap-2"><select className={sel} value={dept} onChange={(e) => setDept(e.target.value)}><option value="">All my assets</option>{list(depts.data).map((d: Any) => <option key={d.id} value={d.id}>{d.code}</option>)}</select><Button onClick={() => run.mutate(() => inv.startAudit({ department_id: dept || null }), { onSuccess: () => toast.success('Cycle started'), onError: fail })}>Start cycle</Button></div>
      <SimpleTable head={['Cycle', 'Started', 'Expected', 'Scanned', 'Status', '']} rows={list(q.data).map((c: Any) => [c.name, c.started_on, c.expected, c.scanned, <StatusBadge key="s" status={c.status} />, <Button key="o" size="sm" variant="outline" onClick={() => setCur(c)}>Open</Button>])} />
      {cur && <Section title={cur.name} action={cur.status === 'open' ? <Button size="sm" onClick={() => run.mutate(() => inv.completeAudit(cur.id), { onSuccess: () => toast.success('Completed'), onError: fail })}>Complete</Button> : undefined}>
        {cur.status === 'open' && <div className="flex gap-2"><textarea className="h-20 flex-1 rounded-md border bg-background p-2 font-mono text-xs" placeholder="Scan or paste asset tags (one per line)" value={tags} onChange={(e) => setTags(e.target.value)} /><Button onClick={() => run.mutate(() => inv.scan(cur.id, tags.split(/\s+/).filter(Boolean).map((t) => (t.length === 48 ? { qr: t } : { asset_tag: t }))), { onSuccess: (x: Any) => { toast.success(`${x?.data?.scanned} scanned`); setTags(''); }, onError: fail })}>Record scans</Button></div>}
        {r && <div className="space-y-2 text-sm"><div className="flex flex-wrap gap-2"><Badge variant="outline">expected {r.expected}</Badge><Badge variant="outline">found {r.found}</Badge><Badge variant="destructive">missing {r.missing}</Badge><Badge variant="warning">unexpected {r.unexpected}</Badge>{Object.entries(r.conditions).map(([k, v]) => <Badge key={k} variant="outline">{k}: {String(v)}</Badge>)}</div>
          {r.missing_assets.length > 0 && <p>Missing: {r.missing_assets.map((a: Any) => `${a.tag}${r.flagged.includes(a.id) ? ' (flagged)' : ''}`).join(', ')}</p>}
          {r.unexpected_assets.length > 0 && <p>Unexpected: {r.unexpected_assets.map((a: Any) => a.tag).join(', ')}</p>}</div>}
      </Section>}
    </div>
  );
}

// ---- /admin/inventory/bills ---------------------------------------------------------------------------------------------------------------
export function BillsPage() {
  useTitle('Vendor bills');
  const [status, setStatus] = useState('');
  const q = useQ(['bills', status], () => inv.bills({ status: status || undefined }));
  const ageing = useQ(['ageing'], () => inv.ageing());
  const sups = useQ(['suppliers', 'all'], () => inv.suppliers());
  const [form, setForm] = useState<Any | null>(null);
  const [match, setMatch] = useState<Any | null>(null);
  const run = useRun();
  const act = (fn: () => Promise<unknown>, okMsg: string) => run.mutate(fn, { onSuccess: () => toast.success(okMsg), onError: fail });
  const a = (ageing.data as Any)?.data?.buckets ?? {};
  return (
    <div className="space-y-4">
      <PageHeader title="Vendor bills" description="Three-way match (PO × GRN × bill), GST / TDS, verify → approve (workflow above the threshold) → pay." actions={<Button onClick={() => setForm({ supplier_id: '', po_id: '', bill_number: '', bill_date: today(), subtotal_paise: '' })}>Record bill</Button>} />
      <div className="flex flex-wrap gap-2">{Object.entries(a).map(([k, v]) => <Badge key={k} variant="outline">{k.replace('_', '–')}: {rupees(v as number)}</Badge>)}</div>
      <select className={sel} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Any status</option>{['received', 'verified', 'approved', 'paid', 'rejected', 'on_hold'].map((s) => <option key={s}>{s}</option>)}</select>
      <SimpleTable head={['Bill', 'Supplier', 'PO', 'Date', 'Due', 'Total', 'TDS', 'Net', 'Match', 'Status', '']} rows={list(q.data).map((b: Any) => [
        b.bill_number, b.supplier_name, b.po_number ?? '—', b.bill_date, b.due_date ?? '—', rupees(b.total_paise), rupees(b.tds_paise), rupees(b.net_payable_paise),
        b.match?.matched ? <button key="m" onClick={() => setMatch(b)}><Badge variant={b.match.flagged ? 'destructive' : 'outline'}>{b.match.flagged ? `Δ ${b.match.variance_pct}%` : 'matched'}</Badge></button> : '—',
        <span key="s"><StatusBadge status={b.status} />{b.hold_reason && <span className="ml-1 text-xs text-muted-foreground">{b.hold_reason}</span>}</span>,
        <div key="a" className="flex flex-wrap gap-1">
          {b.status === 'received' && <Button size="sm" onClick={() => act(() => inv.verifyBill(b.id), 'Verified')}>Verify</Button>}
          {b.status === 'verified' && <Button size="sm" onClick={() => act(() => inv.decideBill(b.id, { action: 'approve' }), 'Approved / sent to workflow')}>Approve</Button>}
          {b.status === 'approved' && <Button size="sm" onClick={() => { const ref = window.prompt('Payment reference (UTR / cheque)'); if (ref) act(() => inv.payBill(b.id, { payment_ref: ref, mode: 'neft' }), 'Paid'); }}>Pay</Button>}
          {!['paid', 'rejected', 'on_hold'].includes(b.status) && <Button size="sm" variant="ghost" onClick={() => { const r = window.prompt('Hold reason'); if (r) act(() => inv.decideBill(b.id, { action: 'hold', hold_reason: r }), 'On hold'); }}>Hold</Button>}
          {b.status === 'on_hold' && <Button size="sm" variant="ghost" onClick={() => act(() => inv.decideBill(b.id, { action: 'release' }), 'Released')}>Release</Button>}
          {!['paid', 'rejected'].includes(b.status) && <Button size="sm" variant="ghost" onClick={() => act(() => inv.decideBill(b.id, { action: 'reject' }), 'Rejected')}>Reject</Button>}
        </div>,
      ])} />
      <Modal open={!!form} onOpenChange={(o) => !o && setForm(null)} title="Record bill" footer={<Button disabled={!form?.supplier_id || !form?.bill_number} onClick={() => act(() => inv.createBill({ supplier_id: form.supplier_id, po_id: form.po_id || null, bill_number: form.bill_number, bill_date: form.bill_date, subtotal_paise: Number(form.subtotal_paise || 0) }).then(() => setForm(null)), 'Recorded')}>Save</Button>}>
        {form && <div className="space-y-2 text-sm"><select className={`${sel} w-full`} value={form.supplier_id} onChange={(e) => setForm({ ...form, supplier_id: e.target.value })}><option value="">Supplier…</option>{list(sups.data).map((s: Any) => <option key={s.id} value={s.id}>{s.name}</option>)}</select><Input placeholder="PO id (optional, for the three-way match)" value={form.po_id} onChange={(e) => setForm({ ...form, po_id: e.target.value.trim() })} /><Input placeholder="Bill number" value={form.bill_number} onChange={(e) => setForm({ ...form, bill_number: e.target.value })} /><Input type="date" value={form.bill_date} onChange={(e) => setForm({ ...form, bill_date: e.target.value })} /><Input type="number" placeholder="Subtotal (paise)" value={form.subtotal_paise} onChange={(e) => setForm({ ...form, subtotal_paise: e.target.value })} /></div>}
      </Modal>
      <Modal open={!!match} onOpenChange={(o) => !o && setMatch(null)} title="Three-way match">{match && <dl className="grid grid-cols-2 gap-1 text-sm">{Object.entries(match.match).map(([k, v]) => <div key={k} className="contents"><dt className="text-muted-foreground">{k}</dt><dd>{String(v)}</dd></div>)}</dl>}</Modal>
    </div>
  );
}

// ---- /admin/inventory/vendor-store ------------------------------------------------------------------------------------------------------------
export function VendorStorePage() {
  useTitle('Campus store');
  const [day, setDay] = useState(today());
  const rep = useQ(['vsr', day], () => inv.salesReport(day));
  const [sale, setSale] = useState<Any>({ store_id: '', item_id: '', quantity: 1, buyer_id: '' });
  const run = useRun();
  const r = (rep.data as Any)?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Campus store" description="Sales to students / staff — stock issue + a fee invoice for students." />
      <Section title="New sale"><div className="grid gap-2 md:grid-cols-5"><StorePicker value={sale.store_id} onChange={(v) => setSale({ ...sale, store_id: v })} /><ItemPicker value={sale.item_id} onChange={(v) => setSale({ ...sale, item_id: v })} /><Input type="number" value={sale.quantity} onChange={(e) => setSale({ ...sale, quantity: e.target.value })} /><Input placeholder="Student id" value={sale.buyer_id} onChange={(e) => setSale({ ...sale, buyer_id: e.target.value.trim() })} /><Button disabled={!sale.store_id || !sale.item_id || !sale.buyer_id} onClick={() => run.mutate(() => inv.sell({ store_id: sale.store_id, buyer_type: 'student', buyer_id: sale.buyer_id, items: [{ item_id: sale.item_id, quantity: Number(sale.quantity) }] }), { onSuccess: () => toast.success('Sold — invoice raised'), onError: fail })}>Sell</Button></div></Section>
      <Input type="date" className="w-44" value={day} onChange={(e) => setDay(e.target.value)} />
      {r && <Section title={`${r.sales} sale(s) · ${rupees(r.value_paise)}`}><SimpleTable head={['At', 'Item', 'Qty', 'Buyer']} rows={r.rows.map((x: Any) => [dt(x.at), x.item, x.quantity, x.buyer_type])} /></Section>}
    </div>
  );
}

// ---- /admin/inventory/reports + settings ------------------------------------------------------------------------------------------------------------
const KINDS = ['stock_ledger', 'valuation', 'consumption', 'indent_cycle', 'po_register', 'grn_register', 'supplier_performance', 'asset_register', 'depreciation', 'hazardous', 'audit'];
export function InventoryReportsPage() {
  useTitle('Inventory reports');
  const [kind, setKind] = useState('valuation');
  const q = useQ(['report', kind], () => inv.report(kind));
  const rep = (q.data as Any)?.data ?? { columns: [], rows: [] };
  return (
    <div className="space-y-4">
      <PageHeader title="Inventory reports" description="Registers and analyses for stores, procurement and assets." actions={<Button variant="outline" onClick={() => inv.exportReport(kind).then(() => toast.success('Export queued — see Jobs')).catch(fail)}>Export XLSX</Button>} />
      <div className="flex flex-wrap gap-1">{KINDS.map((k) => <Button key={k} size="sm" variant={kind === k ? 'default' : 'outline'} onClick={() => setKind(k)}>{k.split('_').join(' ')}</Button>)}</div>
      <SimpleTable head={rep.columns} rows={rep.rows.slice(0, 500).map((r: Any) => rep.columns.map((c: string) => (c.endsWith('_paise') ? rupees(r[c]) : typeof r[c] === 'object' && r[c] !== null ? JSON.stringify(r[c]) : String(r[c] ?? '—'))))} />
    </div>
  );
}

export function InventorySettingsPage() {
  useTitle('Inventory settings');
  return (
    <div className="space-y-4">
      <PageHeader title="Inventory settings" description="Thresholds, depreciation defaults, TDS rates and audit cycle live under Settings › inventory." />
      <Card><CardContent className="space-y-2 p-4 text-sm"><p>Keys: <code>po_approval_threshold_paise</code>, <code>bill_approval_threshold_paise</code>, <code>three_quotes_above_paise</code>, <code>write_off_approval_paise</code>, <code>depreciation_defaults</code>, <code>salvage_pct</code>, <code>audit_cycle_months</code>, <code>bill_variance_pct</code>, <code>tds_threshold_paise</code>, <code>tds_rates</code>.</p><Button variant="outline" onClick={() => (window.location.href = '/admin/settings?category=inventory')}>Open settings</Button></CardContent></Card>
    </div>
  );
}

// ---- /staff/indents (my indents + my custody) -------------------------------------------------------------------------------------------------------
export function StaffIndentsPage() {
  useTitle('My indents & assets');
  const mine = useQ(['myind'], () => inv.myIndents());
  const assets = useQ(['myassets'], () => inv.myAssets());
  const [open, setOpen] = useState(false);
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="My indents & assets" description="Raise and track indents; accept custody of assets assigned to you." actions={<Button onClick={() => setOpen(true)}>New indent</Button>} />
      <Section title="My indents"><SimpleTable head={['Indent', 'Purpose', 'Estimate', 'Status', 'Done']} rows={list(mine.data).map((r: Any) => [r.indent_number, r.purpose, rupees(r.estimated_paise), <span key="s"><StatusBadge status={r.status} />{r.workflow_step && <span className="ml-1 text-xs text-muted-foreground">{r.workflow_step}</span>}</span>, `${r.fulfilment_pct}%`])} /></Section>
      <Section title="Assets in my custody"><SimpleTable head={['Tag', 'Asset', 'Location', 'Status', '']} rows={list(assets.data).map((a: Any) => [a.asset_tag, a.name, a.location ?? '—', <StatusBadge key="s" status={a.status} />, <Button key="r" size="sm" variant="ghost" onClick={() => run.mutate(() => inv.acceptCustody(a.id), { onSuccess: () => toast.success('Custody accepted'), onError: fail })}>Accept custody</Button>])} /></Section>
      <Modal open={open} onOpenChange={setOpen} title="New indent"><IndentForm onDone={() => setOpen(false)} /></Modal>
    </div>
  );
}

// ---- vendor portal /vendor/* -----------------------------------------------------------------------------------------------------------------------
export function VendorHomePage() {
  useTitle('Supplier portal');
  const me = useQ(['vme'], () => inv.vendorMe());
  const rfqs = useQ(['rfqs'], () => inv.rfqs());
  const pos = useQ(['vpos'], () => inv.vendorPos());
  const bills = useQ(['vbills'], () => inv.vendorBills());
  const [quote, setQuote] = useState<Any | null>(null);
  const run = useRun();
  const m = (me.data as Any)?.data;
  return (
    <div className="space-y-4">
      <PageHeader title={m?.name ?? 'Supplier portal'} description={m ? `GSTIN ${m.gstin ?? '—'} · ${m.status}` : 'Requests for quotation, purchase orders and bills.'} />
      <Section title="Requests for quotation"><SimpleTable head={['Indent', 'Purpose', 'Lines', '']} rows={list(rfqs.data).map((r: Any) => [r.indent_number, r.purpose, r.items.map((x: Any) => `${x.name ?? x.free_text} × ${x.qty}`).join('; '), <Button key="q" size="sm" onClick={() => setQuote({ indent: r, prices: {}, reference: '' })}>Quote</Button>])} /></Section>
      <Section title="Purchase orders"><SimpleTable head={['PO', 'Date', 'Total', 'Status', '']} rows={list(pos.data).map((p: Any) => [p.po_number, p.order_date, rupees(p.total_paise), <StatusBadge key="s" status={p.status} />, p.acknowledged_at ? <Badge key="a" variant="outline">acknowledged</Badge> : <Button key="a" size="sm" variant="outline" onClick={() => run.mutate(() => inv.acknowledge(p.id), { onSuccess: () => toast.success('Acknowledged'), onError: fail })}>Acknowledge</Button>])} /></Section>
      <Section title="Bills"><SimpleTable head={['Bill', 'Date', 'Total', 'TDS', 'Status', 'Paid']} rows={list(bills.data).map((b: Any) => [b.bill_number, b.bill_date, rupees(b.total_paise), rupees(b.tds_paise), <StatusBadge key="s" status={b.status} />, b.payment_ref ?? '—'])} /></Section>
      <Modal open={!!quote} onOpenChange={(o) => !o && setQuote(null)} title={quote ? `Quote for ${quote.indent.indent_number}` : ''} footer={<Button onClick={() => run.mutate(() => inv.vendorQuote(quote.indent.id, { reference: quote.reference || null, items: quote.indent.items.map((x: Any, i: number) => ({ line: i, qty: x.qty, unit_price_paise: Number(quote.prices[i] || 0), tax_rate: 18 })).filter((x: Any) => x.unit_price_paise > 0) }), { onSuccess: () => { toast.success('Quotation submitted'); setQuote(null); }, onError: fail })}>Submit</Button>}>
        {quote && <div className="space-y-2 text-sm"><Input placeholder="Your reference" value={quote.reference} onChange={(e) => setQuote({ ...quote, reference: e.target.value })} />{quote.indent.items.map((x: Any, i: number) => <div key={i} className="grid grid-cols-[1fr_140px] gap-2"><span>{x.name ?? x.free_text} × {x.qty}</span><Input type="number" placeholder="Unit price (paise)" value={quote.prices[i] ?? ''} onChange={(e) => setQuote({ ...quote, prices: { ...quote.prices, [i]: e.target.value } })} /></div>)}</div>}
      </Modal>
    </div>
  );
}

export function VendorRegisterPage() {
  useTitle('Supplier registration');
  const [b, setB] = useState<Any>({ institution: new URLSearchParams(window.location.search).get('institution') ?? '', name: '', email: '', phone: '', gstin: '', pan: '', categories: '' });
  const [done, setDone] = useState(false);
  const run = useRun();
  if (done) return <Card className="mx-auto mt-10 max-w-lg"><CardContent className="p-6 text-sm">Thank you — the stores office will verify your details and email you when your portal account is ready.</CardContent></Card>;
  return (
    <div className="mx-auto mt-10 max-w-lg space-y-3 px-4">
      <PageHeader title="Supplier registration" description="Register to receive requests for quotation." />
      {(['institution', 'name', 'email', 'phone', 'gstin', 'pan', 'categories'] as const).map((k) => <Input key={k} placeholder={k === 'categories' ? 'Categories (comma separated)' : k} value={b[k]} onChange={(e) => setB({ ...b, [k]: ['gstin', 'pan'].includes(k) ? e.target.value.toUpperCase() : e.target.value })} />)}
      <Button disabled={!b.institution || !b.name || !b.email} onClick={() => run.mutate(() => inv.vendorRegister({ institution: b.institution, name: b.name, email: b.email, phone: b.phone || null, gstin: b.gstin || null, pan: b.pan || null, categories: b.categories.split(',').map((s: string) => s.trim()).filter(Boolean) }), { onSuccess: () => setDone(true), onError: fail })}>Register</Button>
    </div>
  );
}
