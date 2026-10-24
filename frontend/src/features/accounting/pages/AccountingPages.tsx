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
import { accountingApi as acc } from '../api';

// Phase 23 web screens (Prompts/23 §23.9). Rules and visibility live in the API.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));
const useQ = <T,>(key: unknown[], fn: () => Promise<T>, enabled = true) => useQuery({ queryKey: ['accounting', ...key], queryFn: fn, enabled, retry: false });
function useRun() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: () => qc.invalidateQueries({ queryKey: ['accounting'] }) });
}
const rupees = (p: number | null | undefined) => (p == null ? '—' : `₹${(p / 100).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`);
const list = (r: Any) => (Array.isArray(r?.data) ? r.data : r?.data?.items ?? []);
const today = () => new Date().toISOString().slice(0, 10);
const yearAgo = () => { const d = new Date(); d.setFullYear(d.getFullYear() - 1); return d.toISOString().slice(0, 10); };
const month = () => new Date().toISOString().slice(0, 7);
const sel = 'h-9 rounded-md border bg-background px-2 text-sm';
const openBlob = (b: Blob, name: string) => { const u = URL.createObjectURL(b); const a = document.createElement('a'); a.href = u; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(u), 30000); };

function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <Card><CardContent className="space-y-3 p-4"><div className="flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">{title}</h2>{action}</div>{children}</CardContent></Card>;
}
function AccountPicker({ value, onChange, types, label = 'Account…' }: { value: string; onChange: (v: string) => void; types?: string[]; label?: string }) {
  const q = useQ(['accounts'], () => acc.accounts());
  return <select className={`${sel} w-full`} value={value} onChange={(e) => onChange(e.target.value)}><option value="">{label}</option>{list(q.data).filter((a: Any) => a.is_active && (!types || types.includes(a.account_type))).map((a: Any) => <option key={a.id} value={a.id}>{a.code} · {a.name}</option>)}</select>;
}
function Bar({ pct }: { pct: number }) {
  return <div className="h-2 w-28 overflow-hidden rounded bg-muted"><div className={`h-2 ${pct >= 100 ? 'bg-destructive' : pct >= 80 ? 'bg-amber-500' : 'bg-primary'}`} style={{ width: `${Math.min(100, pct)}%` }} /></div>;
}
function Period({ v, onChange }: { v: Any; onChange: (x: Any) => void }) {
  return <div className="flex gap-2"><Input type="date" className="w-40" value={v.from} onChange={(e) => onChange({ ...v, from: e.target.value })} /><Input type="date" className="w-40" value={v.to} onChange={(e) => onChange({ ...v, to: e.target.value })} /></div>;
}

// ---- dashboard ---------------------------------------------------------------------------------------------------------
export function AccountingDashboardPage() {
  useTitle('Finance dashboard');
  const q = useQ(['dash'], () => acc.dashboard());
  const d = (q.data as Any)?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Finance dashboard" description="Cash position, receivables, budgets and pending work." />
      {d && <>
        <div className="grid gap-3 md:grid-cols-4">{[['Bank', d.bank_paise], ['Cash', d.cash_paise], ['Fees receivable', d.receivables_paise], ['Income this month', d.income_month_paise], ['Expenses this month', d.expense_month_paise]].map(([k, v]) => <Card key={String(k)}><CardContent className="p-3"><p className="text-xs text-muted-foreground">{k}</p><p className="text-lg font-semibold">{rupees(v as number)}</p></CardContent></Card>)}
          <Card><CardContent className="p-3 text-sm"><p>{d.pending_expenses} expense(s) awaiting approval</p><p>{d.open_reconciliations} open reconciliation(s)</p><p>{d.posting_gaps} posting gap(s)</p></CardContent></Card></div>
        <Section title="Budget alerts"><SimpleTable head={['Head', 'Dept', 'Used']} rows={d.budget_alerts.map((a: Any) => [a.head, a.department ?? '—', <span key="p" className="flex items-center gap-2"><Bar pct={a.pct} />{a.pct}%</span>])} /></Section>
      </>}
    </div>
  );
}

// ---- chart -----------------------------------------------------------------------------------------------------------------
function TreeRows({ nodes, depth, onPick }: { nodes: Any[]; depth: number; onPick: (n: Any) => void }) {
  return <>{nodes.map((n) => <div key={n.id}><button className="flex w-full items-center justify-between rounded px-2 py-1 text-left text-sm hover:bg-muted" style={{ paddingLeft: 8 + depth * 16 }} onClick={() => onPick(n)}><span>{n.code} · {n.name}{!n.is_active && <Badge variant="outline" className="ml-1">inactive</Badge>}</span><span className="tabular-nums">{rupees(n.balance_paise)}</span></button>{n.children?.length > 0 && <TreeRows nodes={n.children} depth={depth + 1} onPick={onPick} />}</div>)}</>;
}
export function ChartPage() {
  useTitle('Chart of accounts');
  const [tab, setTab] = useState<'tree' | 'mappings'>('tree');
  const q = useQ(['tree'], () => acc.tree());
  const maps = useQ(['maps'], () => acc.mappings(), tab === 'mappings');
  const [form, setForm] = useState<Any | null>(null);
  const run = useRun();
  const m = (maps.data as Any)?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Chart of accounts" description="Hierarchical ledger accounts with balances; mappings drive automatic postings." actions={<div className="flex gap-1"><Button onClick={() => setForm({ code: '', name: '', parent_id: '', external_ref: '' })}>New account</Button><Button variant="outline" onClick={() => run.mutate(() => acc.importChart({ template: 'IN' }), { onSuccess: (r: Any) => toast.success(`${r?.data?.added ?? 0} account(s) added`), onError: fail })}>Import IN template</Button></div>} />
      <div className="flex gap-1">{(['tree', 'mappings'] as const).map((t) => <Button key={t} size="sm" variant={tab === t ? 'default' : 'outline'} onClick={() => setTab(t)}>{t}</Button>)}</div>
      {tab === 'tree' && <Card><CardContent className="p-2"><TreeRows nodes={list(q.data)} depth={0} onPick={(n) => setForm({ ...n })} /></CardContent></Card>}
      {tab === 'mappings' && m && <div className="grid gap-4 lg:grid-cols-2">
        <Section title="System accounts"><SimpleTable head={['Key', 'Account code']} rows={Object.entries(m.system).filter(([, v]) => typeof v === 'string').map(([k, v]) => [k, <Input key={k} className="h-8 w-28" defaultValue={String(v)} onBlur={(e) => e.target.value !== v && run.mutate(() => acc.saveMappings({ system: { [k]: e.target.value } }), { onSuccess: () => toast.success('Saved'), onError: fail })} />])} /></Section>
        <Section title="Fee heads"><SimpleTable head={['Head', 'Account']} rows={m.fee_heads.map((h: Any) => [`${h.code} · ${h.name}`, <AccountPicker key={h.id} value={h.ledger_account_id ?? ''} types={['income', 'liability']} onChange={(v) => run.mutate(() => acc.saveMappings({ fee_heads: [{ id: h.id, ledger_account_id: v || null }] }), { onSuccess: () => toast.success('Mapped'), onError: fail })} />])} /></Section>
      </div>}
      <Modal open={!!form} onOpenChange={(o) => !o && setForm(null)} title={form?.id ? `${form.code} · ${form.name}` : 'New account'} footer={<Button onClick={() => run.mutate(() => (form.id ? acc.saveAccount({ name: form.name, external_ref: form.external_ref || null, is_active: form.is_active }, form.id) : acc.saveAccount({ code: form.code, name: form.name, parent_id: form.parent_id || null, external_ref: form.external_ref || null, account_type: form.account_type || null })), { onSuccess: () => { toast.success('Saved'); setForm(null); }, onError: fail })}>Save</Button>}>
        {form && <div className="space-y-2 text-sm">
          {!form.id && <Input placeholder="Code" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} />}
          <Input placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          {!form.id && <><AccountPicker value={form.parent_id} onChange={(v) => setForm({ ...form, parent_id: v })} label="Parent (type inherited)" /><select className={`${sel} w-full`} value={form.account_type ?? ''} onChange={(e) => setForm({ ...form, account_type: e.target.value })}><option value="">Type (top level only)</option>{['income', 'expense', 'asset', 'liability', 'equity'].map((t) => <option key={t}>{t}</option>)}</select></>}
          <Input placeholder="Tally / Zoho ledger name" value={form.external_ref ?? ''} onChange={(e) => setForm({ ...form, external_ref: e.target.value })} />
          {form.id && <label className="flex items-center gap-2"><input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} /> Active</label>}
        </div>}
      </Modal>
    </div>
  );
}

// ---- ledger + trial balance -------------------------------------------------------------------------------------------------
export function LedgerPage() {
  useTitle('Ledger');
  const [account, setAccount] = useState('');
  const [p, setP] = useState({ from: yearAgo(), to: today() });
  const led = useQ(['ledger', account, p], () => acc.ledger(account, p), !!account);
  const tb = useQ(['tb', p], () => acc.trialBalance(p));
  const t = (tb.data as Any)?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Ledger & trial balance" description="Account ledger with links to the source documents." />
      <div className="flex flex-wrap gap-2"><div className="w-80"><AccountPicker value={account} onChange={setAccount} /></div><Period v={p} onChange={setP} /></div>
      {account && <SimpleTable head={['Date', 'Description', 'Source', 'Debit', 'Credit', 'Balance']} rows={list(led.data).map((l: Any) => [l.on, l.description ?? '—', l.source_type ?? '—', l.debit_paise ? rupees(l.debit_paise) : '', l.credit_paise ? rupees(l.credit_paise) : '', rupees(l.balance_paise)])} />}
      {t && <Section title={`Trial balance ${t.balanced ? '✓ balanced' : '✗ not balanced'}`}><SimpleTable head={['Code', 'Account', 'Debit', 'Credit']} rows={[...t.rows.map((r: Any) => [r.code, r.name, r.debit_paise ? rupees(r.debit_paise) : '', r.credit_paise ? rupees(r.credit_paise) : '']), ['', 'Total', rupees(t.total_debit_paise), rupees(t.total_credit_paise)]]} /></Section>}
    </div>
  );
}

// ---- income -----------------------------------------------------------------------------------------------------------------
export function IncomePage() {
  useTitle('Income');
  const [p, setP] = useState({ from: yearAgo(), to: today() });
  const [source, setSource] = useState('');
  const q = useQ(['income', p, source], () => acc.income({ ...p, source_type: source || undefined }));
  const [form, setForm] = useState<Any | null>(null);
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Income" description="Automatic postings (fees, grants…) and manual income; reverse instead of editing." actions={<Button onClick={() => setForm({ ledger_account_id: '', amount: '', received_on: today(), description: '', payment_mode: 'bank' })}>Record income</Button>} />
      <div className="flex flex-wrap gap-2"><Period v={p} onChange={setP} /><select className={sel} value={source} onChange={(e) => setSource(e.target.value)}><option value="">All sources</option>{['manual', 'fee_payment', 'fee_payment_reversal', 'grant_receipt', 'vendor_bill', 'payroll', 'donation', 'asset_disposal'].map((s) => <option key={s}>{s}</option>)}</select></div>
      <SimpleTable head={['Date', 'Account', 'Description', 'Source', 'Mode', 'Amount', '']} rows={list(q.data).slice(0, 500).map((r: Any) => [r.received_on, r.account, r.description, r.source_type ?? '—', r.payment_mode ?? '—', rupees(r.amount_paise), r.source_type === 'manual' && !r.reversed ? <Button key="r" size="sm" variant="ghost" onClick={() => { const reason = window.prompt('Reversal reason'); if (reason) run.mutate(() => acc.reverseIncome(r.id, reason), { onError: fail }); }}>Reverse</Button> : r.reversed ? <Badge key="x" variant="outline">reversed</Badge> : null])} />
      <Modal open={!!form} onOpenChange={(o) => !o && setForm(null)} title="Record income" footer={<Button disabled={!form?.ledger_account_id || !form?.amount} onClick={() => run.mutate(() => acc.addIncome({ ledger_account_id: form.ledger_account_id, amount_paise: Math.round(Number(form.amount) * 100), received_on: form.received_on, description: form.description, payment_mode: form.payment_mode, reference_no: form.reference_no || null }), { onSuccess: () => { toast.success('Recorded'); setForm(null); }, onError: fail })}>Save</Button>}>
        {form && <div className="space-y-2 text-sm"><AccountPicker value={form.ledger_account_id} types={['income', 'liability']} onChange={(v) => setForm({ ...form, ledger_account_id: v })} /><Input type="number" placeholder="Amount ₹" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} /><Input type="date" value={form.received_on} onChange={(e) => setForm({ ...form, received_on: e.target.value })} /><Input placeholder="Description" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /><Input placeholder="Reference" value={form.reference_no ?? ''} onChange={(e) => setForm({ ...form, reference_no: e.target.value })} /><select className={`${sel} w-full`} value={form.payment_mode} onChange={(e) => setForm({ ...form, payment_mode: e.target.value })}>{['bank', 'cash', 'cheque', 'upi', 'neft', 'in_kind'].map((x) => <option key={x}>{x}</option>)}</select></div>}
      </Modal>
    </div>
  );
}

// ---- expenses ------------------------------------------------------------------------------------------------------------------
function ExpenseForm({ onDone, heads }: { onDone: () => void; heads: Any[] }) {
  const [f, setF] = useState<Any>({ ledger_account_id: '', budget_head_id: '', amount: '', spent_on: today(), payee: '', description: '', document_url: '' });
  const run = useRun();
  return (
    <div className="space-y-2 text-sm">
      <AccountPicker value={f.ledger_account_id} types={['expense', 'asset']} onChange={(v) => setF({ ...f, ledger_account_id: v })} />
      <select className={`${sel} w-full`} value={f.budget_head_id} onChange={(e) => setF({ ...f, budget_head_id: e.target.value })}><option value="">No budget head</option>{heads.filter((h: Any) => h.status === 'approved').map((h: Any) => <option key={h.id} value={h.id}>{h.name} — {rupees(h.available_paise)} left</option>)}</select>
      <Input type="number" placeholder="Amount ₹" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} />
      <Input type="date" value={f.spent_on} onChange={(e) => setF({ ...f, spent_on: e.target.value })} />
      <Input placeholder="Payee" value={f.payee} onChange={(e) => setF({ ...f, payee: e.target.value })} />
      <Input placeholder="Description" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />
      <Input placeholder="Attachment URL (bill / voucher)" value={f.document_url} onChange={(e) => setF({ ...f, document_url: e.target.value })} />
      <Button disabled={!f.ledger_account_id || !f.amount || !f.payee} onClick={() => run.mutate(() => acc.addExpense({ ledger_account_id: f.ledger_account_id, budget_head_id: f.budget_head_id || null, amount_paise: Math.round(Number(f.amount) * 100), spent_on: f.spent_on, payee: f.payee, description: f.description || f.payee, document_url: f.document_url || null }).then((r: Any) => acc.submitExpense(r.data.id).then(() => r)), { onSuccess: (r: Any) => { toast.success(r?.data?.warning ? `Submitted (${r.data.warning})` : 'Submitted for approval'); onDone(); }, onError: fail })}>Record & submit</Button>
    </div>
  );
}

export function ExpensesPage() {
  useTitle('Expenses');
  const [scope, setScope] = useState('');
  const [status, setStatus] = useState('');
  const q = useQ(['expenses', scope, status], () => acc.expenses({ scope: scope || undefined, status: status || undefined, manual_only: true }));
  const heads = useQ(['budgets'], () => acc.budgets());
  const [open, setOpen] = useState(false);
  const run = useRun();
  const scopes: string[] = (q.data as Any)?.meta?.visibility?.scopes ?? [];
  return (
    <div className="space-y-4">
      <PageHeader title="Expenses" description="Record → submit → approve (workflow above the threshold) → pay; budget utilisation updates on approval." actions={<Button onClick={() => setOpen(true)}>New expense</Button>} />
      <div className="flex flex-wrap gap-2">{scopes.length > 1 && scopes.map((s) => <Button key={s} size="sm" variant={scope === s ? 'default' : 'outline'} onClick={() => setScope(s)}>{s}</Button>)}<select className={sel} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Any status</option>{['recorded', 'submitted', 'approved', 'paid', 'rejected'].map((s) => <option key={s}>{s}</option>)}</select></div>
      <SimpleTable head={['Date', 'Payee', 'Account', 'Budget head', 'Dept', 'Amount', 'Status', '']} rows={list(q.data).slice(0, 500).map((e: Any) => [e.spent_on, e.payee, e.account, e.budget_head ?? '—', e.department_code ?? '—', rupees(e.amount_paise), <span key="s"><StatusBadge status={e.status} />{e.workflow_instance_id && <Badge variant="outline" className="ml-1">workflow</Badge>}</span>,
        <div key="a" className="flex gap-1">
          {e.status === 'recorded' && <Button size="sm" variant="outline" onClick={() => run.mutate(() => acc.submitExpense(e.id), { onError: fail })}>Submit</Button>}
          {e.status === 'submitted' && !e.workflow_instance_id && <><Button size="sm" onClick={() => run.mutate(() => acc.decideExpense(e.id, { action: 'approve' }), { onError: fail })}>Approve</Button><Button size="sm" variant="ghost" onClick={() => run.mutate(() => acc.decideExpense(e.id, { action: 'reject' }), { onError: fail })}>Reject</Button></>}
          {e.status === 'approved' && <Button size="sm" onClick={() => { const ref = window.prompt('Payment reference'); if (ref) run.mutate(() => acc.payExpense(e.id, { paid_on: today(), mode: 'neft', reference: ref }), { onError: fail }); }}>Pay</Button>}
        </div>])} />
      <Modal open={open} onOpenChange={setOpen} title="New expense"><ExpenseForm heads={list(heads.data)} onDone={() => setOpen(false)} /></Modal>
    </div>
  );
}

// ---- budgets ----------------------------------------------------------------------------------------------------------------------
export function BudgetsPage() {
  useTitle('Budgets');
  const years = useQ(['years'], () => acc.years());
  const depts = useQ(['depts'], () => acc.departments());
  const [year, setYear] = useState('');
  const q = useQ(['budgets', year], () => acc.budgets({ year: year || undefined }));
  const util = useQ(['util', year], () => acc.utilisation({ year: year || undefined }));
  const [form, setForm] = useState<Any | null>(null);
  const [revise, setRevise] = useState<Any | null>(null);
  const [xfer, setXfer] = useState<Any | null>(null);
  const run = useRun();
  const rows = list(q.data);
  const yid = year || list(years.data).find((y: Any) => y.is_current)?.id || list(years.data)[0]?.id || '';
  return (
    <div className="space-y-4">
      <PageHeader title="Budgets" description="Allocated · committed · utilised · available per head; approval via workflow; hard stop on overspend." actions={<div className="flex gap-1"><Button onClick={() => setForm({ name: '', department_id: '', allocated: '' })}>New head</Button><Button variant="outline" onClick={() => run.mutate(() => acc.submitAll(yid), { onSuccess: () => toast.success('Drafts submitted for approval'), onError: fail })}>Submit drafts</Button><Button variant="outline" onClick={() => setXfer({ from_head_id: '', to_head_id: '', amount: '', reason: '' })}>Transfer</Button></div>} />
      <select className={sel} value={year} onChange={(e) => setYear(e.target.value)}><option value="">Current year</option>{list(years.data).map((y: Any) => <option key={y.id} value={y.id}>{y.name ?? y.code}</option>)}</select>
      <SimpleTable head={['Head', 'Dept', 'Allocated', 'Committed', 'Utilised', 'Available', 'Used', 'Status', '']} rows={rows.map((h: Any) => [h.name, h.department_code ?? '—', rupees(h.allocated_paise), rupees(h.committed_paise), rupees(h.utilised_paise), rupees(h.available_paise), <span key="b" className="flex items-center gap-2"><Bar pct={h.pct} />{h.pct}%</span>, <StatusBadge key="s" status={h.status} />,
        <div key="a" className="flex gap-1">{h.status === 'draft' && <Button size="sm" variant="outline" onClick={() => run.mutate(() => acc.budgetAction(h.id, 'submit'), { onError: fail })}>Submit</Button>}{['draft', 'submitted'].includes(h.status) && <Button size="sm" onClick={() => run.mutate(() => acc.budgetAction(h.id, 'approve'), { onError: fail })}>Approve</Button>}{h.status === 'approved' && <><Button size="sm" variant="ghost" onClick={() => setRevise({ id: h.id, allocated: h.allocated_paise / 100, reason: '' })}>Revise</Button><Button size="sm" variant="ghost" onClick={() => run.mutate(() => acc.budgetAction(h.id, 'freeze'), { onError: fail })}>Freeze</Button></>}</div>])} />
      <Section title="Utilisation by department"><SimpleTable head={['Department', 'Allocated', 'Utilised', 'Committed', '%']} rows={list(util.data).map((u: Any) => [u.department, rupees(u.allocated_paise), rupees(u.utilised_paise), rupees(u.committed_paise), <span key="p" className="flex items-center gap-2"><Bar pct={u.pct} />{u.pct}%</span>])} /></Section>
      <Modal open={!!form} onOpenChange={(o) => !o && setForm(null)} title="New budget head" footer={<Button disabled={!form?.name || !yid} onClick={() => run.mutate(() => acc.addBudget({ academic_year_id: yid, name: form.name, department_id: form.department_id || null, ledger_account_id: form.ledger_account_id || null, allocated_paise: Math.round(Number(form.allocated || 0) * 100) }), { onSuccess: () => { toast.success('Draft created'); setForm(null); }, onError: fail })}>Create</Button>}>
        {form && <div className="space-y-2 text-sm"><Input placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /><select className={`${sel} w-full`} value={form.department_id} onChange={(e) => setForm({ ...form, department_id: e.target.value })}><option value="">Institution-level</option>{list(depts.data).map((d: Any) => <option key={d.id} value={d.id}>{d.code}</option>)}</select><AccountPicker value={form.ledger_account_id ?? ''} types={['expense', 'asset']} onChange={(v) => setForm({ ...form, ledger_account_id: v })} /><Input type="number" placeholder="Allocation ₹" value={form.allocated} onChange={(e) => setForm({ ...form, allocated: e.target.value })} /></div>}
      </Modal>
      <Modal open={!!revise} onOpenChange={(o) => !o && setRevise(null)} title="Revise allocation" footer={<Button disabled={!revise?.reason} onClick={() => run.mutate(() => acc.revise(revise.id, { allocated_paise: Math.round(Number(revise.allocated) * 100), reason: revise.reason }), { onSuccess: () => { toast.success('Revised'); setRevise(null); }, onError: fail })}>Save</Button>}>
        {revise && <div className="space-y-2 text-sm"><Input type="number" value={revise.allocated} onChange={(e) => setRevise({ ...revise, allocated: e.target.value })} /><Input placeholder="Reason" value={revise.reason} onChange={(e) => setRevise({ ...revise, reason: e.target.value })} /></div>}
      </Modal>
      <Modal open={!!xfer} onOpenChange={(o) => !o && setXfer(null)} title="Transfer between heads" footer={<Button disabled={!xfer?.from_head_id || !xfer?.to_head_id || !xfer?.reason} onClick={() => run.mutate(() => acc.transfer({ from_head_id: xfer.from_head_id, to_head_id: xfer.to_head_id, amount_paise: Math.round(Number(xfer.amount) * 100), reason: xfer.reason }), { onSuccess: () => { toast.success('Transferred'); setXfer(null); }, onError: fail })}>Transfer</Button>}>
        {xfer && <div className="space-y-2 text-sm">{(['from_head_id', 'to_head_id'] as const).map((k) => <select key={k} className={`${sel} w-full`} value={xfer[k]} onChange={(e) => setXfer({ ...xfer, [k]: e.target.value })}><option value="">{k === 'from_head_id' ? 'From…' : 'To…'}</option>{rows.filter((h: Any) => h.status === 'approved').map((h: Any) => <option key={h.id} value={h.id}>{h.name} ({rupees(h.available_paise)} free)</option>)}</select>)}<Input type="number" placeholder="Amount ₹" value={xfer.amount} onChange={(e) => setXfer({ ...xfer, amount: e.target.value })} /><Input placeholder="Reason" value={xfer.reason} onChange={(e) => setXfer({ ...xfer, reason: e.target.value })} /></div>}
      </Modal>
    </div>
  );
}

export function MyBudgetPage() {
  useTitle('Department budget');
  const q = useQ(['mybudgets'], () => acc.myBudgets());
  const mine = useQ(['myexp'], () => acc.expenses({ scope: 'department', manual_only: true }));
  const [open, setOpen] = useState(false);
  return (
    <div className="space-y-4">
      <PageHeader title="Department budget" description="Your department's heads and expenses." actions={<Button onClick={() => setOpen(true)}>Record expense</Button>} />
      <SimpleTable head={['Head', 'Allocated', 'Committed', 'Utilised', 'Available', 'Used']} rows={list(q.data).map((h: Any) => [h.name, rupees(h.allocated_paise), rupees(h.committed_paise), rupees(h.utilised_paise), rupees(h.available_paise), <span key="b" className="flex items-center gap-2"><Bar pct={h.pct} />{h.pct}%</span>])} />
      <Section title="Department expenses"><SimpleTable head={['Date', 'Payee', 'Head', 'Amount', 'Status']} rows={list(mine.data).slice(0, 200).map((e: Any) => [e.spent_on, e.payee, e.budget_head ?? '—', rupees(e.amount_paise), <StatusBadge key="s" status={e.status} />])} /></Section>
      <Modal open={open} onOpenChange={setOpen} title="Record expense"><ExpenseForm heads={list(q.data)} onDone={() => setOpen(false)} /></Modal>
    </div>
  );
}

// ---- grants ------------------------------------------------------------------------------------------------------------------------
export function GrantsPage() {
  useTitle('Grant ledgers');
  const q = useQ(['grants'], () => acc.grants());
  const [cur, setCur] = useState<Any | null>(null);
  const [dlg, setDlg] = useState<Any | null>(null);
  const [form, setForm] = useState<Any | null>(null);
  const run = useRun();
  const g = cur ? list(q.data).find((x: Any) => x.id === cur.id) ?? cur : null;
  return (
    <div className="space-y-4">
      <PageHeader title="Grant ledgers" description="Funded projects: head-wise receipts / expenses, reallocation, UC and statement of expenditure." actions={<Button onClick={() => setForm({ name: '', funding_agency: '', sanctioned: '', pi_staff_id: '', heads: 'manpower:35,equipment:30,consumables:12,travel:8,contingency:10,overheads:5' })}>New grant</Button>} />
      <div className="grid gap-3 md:grid-cols-3">{list(q.data).map((x: Any) => <Card key={x.id} className={g?.id === x.id ? 'ring-2 ring-primary' : ''}><CardContent className="cursor-pointer space-y-1 p-3 text-sm" onClick={() => setCur(x)}><p className="font-medium">{x.name} <StatusBadge status={x.status} /></p><p className="text-xs text-muted-foreground">{x.funding_agency} · PI {x.pi_name ?? '—'}</p><p>Sanctioned {rupees(x.sanctioned_paise)} · received {rupees(x.received_paise)} · used {rupees(x.utilised_paise)}</p></CardContent></Card>)}</div>
      {g && <Section title={g.name} action={<div className="flex flex-wrap gap-1"><Button size="sm" variant="outline" onClick={() => setDlg({ kind: 'receipt', amount: '', received_on: today() })}>Receipt</Button><Button size="sm" variant="outline" onClick={() => setDlg({ kind: 'expense', head: g.budget_heads[0]?.name, amount: '', spent_on: today(), description: '' })}>Expense</Button><Button size="sm" variant="outline" onClick={() => setDlg({ kind: 'reallocate', from_head: g.budget_heads[0]?.name, to_head: g.budget_heads[1]?.name, amount: '', remark: '' })}>Reallocate</Button><Button size="sm" variant="ghost" onClick={() => acc.uc(g.id).then((b) => openBlob(b, `UC-${g.name}.pdf`)).catch(fail)}>UC PDF</Button>{g.status === 'active' && <Button size="sm" variant="ghost" onClick={() => run.mutate(() => acc.closeGrant(g.id), { onSuccess: () => toast.success('Closed'), onError: fail })}>Close</Button>}</div>}>
        <SimpleTable head={['Head', 'Allocated', 'Utilised', 'Available']} rows={g.budget_heads.map((h: Any) => [h.name, rupees(h.allocated_paise), rupees(h.utilised_paise), rupees(h.available_paise)])} />
      </Section>}
      <Modal open={!!dlg} onOpenChange={(o) => !o && setDlg(null)} title={dlg?.kind ?? ''} footer={<Button onClick={() => {
        const amt = Math.round(Number(dlg.amount) * 100);
        const fn = dlg.kind === 'receipt' ? () => acc.grantReceipt(g.id, { amount_paise: amt, received_on: dlg.received_on }) : dlg.kind === 'expense' ? () => acc.grantExpense(g.id, { head: dlg.head, amount_paise: amt, spent_on: dlg.spent_on, description: dlg.description || dlg.head }) : () => acc.reallocate(g.id, { from_head: dlg.from_head, to_head: dlg.to_head, amount_paise: amt, remark: dlg.remark });
        run.mutate(fn, { onSuccess: () => { toast.success('Saved'); setDlg(null); }, onError: fail });
      }}>Save</Button>}>
        {dlg && g && <div className="space-y-2 text-sm">
          {dlg.kind === 'expense' && <select className={`${sel} w-full`} value={dlg.head} onChange={(e) => setDlg({ ...dlg, head: e.target.value })}>{g.budget_heads.map((h: Any) => <option key={h.name}>{h.name}</option>)}</select>}
          {dlg.kind === 'reallocate' && (['from_head', 'to_head'] as const).map((k) => <select key={k} className={`${sel} w-full`} value={dlg[k]} onChange={(e) => setDlg({ ...dlg, [k]: e.target.value })}>{g.budget_heads.map((h: Any) => <option key={h.name}>{h.name}</option>)}</select>)}
          <Input type="number" placeholder="Amount ₹" value={dlg.amount} onChange={(e) => setDlg({ ...dlg, amount: e.target.value })} />
          {dlg.kind !== 'reallocate' && <Input type="date" value={dlg.received_on ?? dlg.spent_on} onChange={(e) => setDlg({ ...dlg, [dlg.kind === 'receipt' ? 'received_on' : 'spent_on']: e.target.value })} />}
          {dlg.kind === 'expense' && <Input placeholder="Description" value={dlg.description} onChange={(e) => setDlg({ ...dlg, description: e.target.value })} />}
          {dlg.kind === 'reallocate' && <Input placeholder="Remark (agency approval)" value={dlg.remark} onChange={(e) => setDlg({ ...dlg, remark: e.target.value })} />}
        </div>}
      </Modal>
      <Modal open={!!form} onOpenChange={(o) => !o && setForm(null)} title="New grant ledger" footer={<Button disabled={!form?.name || !form?.sanctioned} onClick={() => { const total = Number(form.sanctioned) * 100; run.mutate(() => acc.addGrant({ name: form.name, funding_agency: form.funding_agency || null, sanctioned_paise: Math.round(total), pi_staff_id: form.pi_staff_id || null, budget_heads: form.heads.split(',').map((p: string) => { const [n, pct] = p.split(':'); return { name: n.trim(), allocated_paise: Math.round((total * Number(pct)) / 100) }; }) }), { onSuccess: () => { toast.success('Created'); setForm(null); }, onError: fail }); }}>Create</Button>}>
        {form && <div className="space-y-2 text-sm"><Input placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /><Input placeholder="Funding agency" value={form.funding_agency} onChange={(e) => setForm({ ...form, funding_agency: e.target.value })} /><Input type="number" placeholder="Sanctioned ₹" value={form.sanctioned} onChange={(e) => setForm({ ...form, sanctioned: e.target.value })} /><Input placeholder="PI staff id" value={form.pi_staff_id} onChange={(e) => setForm({ ...form, pi_staff_id: e.target.value.trim() })} /><Input placeholder="Heads name:% list" value={form.heads} onChange={(e) => setForm({ ...form, heads: e.target.value })} /></div>}
      </Modal>
    </div>
  );
}

// ---- reconciliation ---------------------------------------------------------------------------------------------------------------
export function ReconciliationPage() {
  useTitle('Bank reconciliation');
  const q = useQ(['recons'], () => acc.recons());
  const [cur, setCur] = useState('');
  const r = useQ(['recon', cur], () => acc.recon(cur), !!cur);
  const [form, setForm] = useState<Any | null>(null);
  const [csv, setCsv] = useState('');
  const run = useRun();
  const x = (r.data as Any)?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Bank reconciliation" description="Upload a statement, auto-match to receipts / payments, explain the rest, close." actions={<Button onClick={() => setForm({ bank_account: '', statement_date: today(), balance: '' })}>New reconciliation</Button>} />
      <SimpleTable head={['Bank', 'Statement date', 'Statement balance', 'Matched', 'Unmatched', 'Difference', 'Status', '']} rows={list(q.data).map((c: Any) => [c.bank_account, c.statement_date, rupees(c.statement_balance_paise), c.matched, c.unmatched, rupees(c.difference_paise), <StatusBadge key="s" status={c.status} />, <Button key="o" size="sm" variant="outline" onClick={() => setCur(c.id)}>Open</Button>])} />
      {x && <Section title={`${x.bank_account} · ${x.statement_date} · difference ${rupees(x.difference_paise)}`} action={x.status === 'open' ? <Button size="sm" onClick={() => run.mutate(() => acc.closeRecon(x.id), { onSuccess: () => toast.success('Reconciled'), onError: fail })}>Close</Button> : undefined}>
        {x.status === 'open' && <div className="flex gap-2"><textarea className="h-20 flex-1 rounded-md border bg-background p-2 font-mono text-xs" placeholder="date,description,reference,amount (₹; negative = debit)" value={csv} onChange={(e) => setCsv(e.target.value)} /><Button disabled={!csv} onClick={() => run.mutate(() => acc.importRecon(x.id, csv.startsWith('date') ? csv : `date,description,reference,amount\n${csv}`), { onSuccess: () => { toast.success('Imported & auto-matched'); setCsv(''); }, onError: fail })}>Import</Button></div>}
        <SimpleTable head={['Date', 'Description', 'Ref', 'Amount', 'Status', '']} rows={x.items.map((i: Any) => [i.row.date, i.row.description, i.row.reference ?? '—', rupees(i.row.amount_paise), <span key="s"><StatusBadge status={i.status} />{i.matched_type && <span className="ml-1 text-xs text-muted-foreground">{i.matched_type}</span>}{i.remark && <span className="ml-1 text-xs text-muted-foreground">{i.remark}</span>}</span>,
          x.status === 'open' ? <div key="a" className="flex gap-1">{i.status === 'unmatched' ? <>
            <Button size="sm" variant="ghost" onClick={() => run.mutate(() => acc.addReconRecord(x.id, { item_id: i.id, kind: i.row.amount_paise < 0 ? 'bank_charge' : 'interest' }), { onError: fail })}>{i.row.amount_paise < 0 ? 'Bank charge' : 'Interest'}</Button>
            <Button size="sm" variant="ghost" onClick={() => { const id = window.prompt('Match to record id (fee payment / income / expense)'); const type = id ? window.prompt('Type: fee_payment | income | expense', 'income') : null; if (id && type) run.mutate(() => acc.matchRecon(x.id, { item_id: i.id, matched_type: type, matched_id: id }), { onError: fail }); }}>Match</Button>
            <Button size="sm" variant="ghost" onClick={() => { const remark = window.prompt('Why does this row stay unexplained?'); if (remark) run.mutate(() => acc.matchRecon(x.id, { item_id: i.id, unexplained_remark: remark }), { onError: fail }); }}>Explain</Button>
          </> : <Button size="sm" variant="ghost" onClick={() => run.mutate(() => acc.unmatchRecon(x.id, i.id), { onError: fail })}>Undo</Button>}</div> : null])} />
      </Section>}
      <Modal open={!!form} onOpenChange={(o) => !o && setForm(null)} title="New reconciliation" footer={<Button disabled={!form?.bank_account} onClick={() => run.mutate(() => acc.openRecon({ bank_account: form.bank_account, statement_date: form.statement_date, statement_balance_paise: Math.round(Number(form.balance || 0) * 100) }).then((res: Any) => setCur(res.data.id)), { onSuccess: () => setForm(null), onError: fail })}>Open</Button>}>
        {form && <div className="space-y-2 text-sm"><Input placeholder="Bank account" value={form.bank_account} onChange={(e) => setForm({ ...form, bank_account: e.target.value })} /><Input type="date" value={form.statement_date} onChange={(e) => setForm({ ...form, statement_date: e.target.value })} /><Input type="number" placeholder="Statement balance ₹" value={form.balance} onChange={(e) => setForm({ ...form, balance: e.target.value })} /></div>}
      </Modal>
    </div>
  );
}

// ---- GST / exports / statements / periods -------------------------------------------------------------------------------------------
export function GstPage() {
  useTitle('GST');
  const [period, setPeriod] = useState(month());
  const q = useQ(['gst', period], () => acc.gst(period));
  const g = (q.data as Any)?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="GST summary" description="Output tax on taxable fee heads, input tax on vendor bills and expenses." actions={<Button variant="outline" onClick={() => acc.gstExport(period).then(() => toast.success('CSV export queued — see Jobs')).catch(fail)}>Export CSV</Button>} />
      <Input type="month" className="w-44" value={period} onChange={(e) => setPeriod(e.target.value)} />
      {g && <><div className="flex gap-2"><Badge variant="outline">output {rupees(g.output_total_paise)}</Badge><Badge variant="outline">input {rupees(g.input_total_paise)}</Badge><Badge>net {rupees(g.net_paise)}</Badge></div>
        <Section title="Output tax"><SimpleTable head={['Head', 'Taxable', 'Tax']} rows={g.output_tax.map((r: Any) => [r.head, rupees(r.taxable_paise), rupees(r.tax_paise)])} /></Section>
        <Section title="Input tax"><SimpleTable head={['Bill', 'Supplier', 'GSTIN', 'Taxable', 'Tax']} rows={g.input_tax.map((r: Any) => [r.bill ?? '—', r.supplier ?? '—', r.gstin ?? '—', rupees(r.taxable_paise), rupees(r.tax_paise)])} /></Section></>}
    </div>
  );
}

export function ExportsPage() {
  useTitle('Voucher exports');
  const q = useQ(['exports'], () => acc.exports());
  const [f, setF] = useState<Any>({ target: 'tally', period_from: yearAgo(), period_to: today(), include_exported: false });
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Voucher exports" description="Tally XML, Zoho Books CSV or generic CSV; exported rows are skipped next time." />
      <Section title="New export"><div className="flex flex-wrap items-center gap-2"><select className={sel} value={f.target} onChange={(e) => setF({ ...f, target: e.target.value })}>{['tally', 'zoho', 'csv'].map((t) => <option key={t}>{t}</option>)}</select><Input type="date" className="w-40" value={f.period_from} onChange={(e) => setF({ ...f, period_from: e.target.value })} /><Input type="date" className="w-40" value={f.period_to} onChange={(e) => setF({ ...f, period_to: e.target.value })} /><label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={f.include_exported} onChange={(e) => setF({ ...f, include_exported: e.target.checked })} /> include already exported</label><Button onClick={() => run.mutate(() => acc.createExport(f), { onSuccess: () => toast.success('Queued'), onError: fail })}>Export</Button></div></Section>
      <SimpleTable head={['Target', 'From', 'To', 'Status', 'Requested', '']} rows={list(q.data).map((e: Any) => [e.target, e.period_from, e.period_to, <StatusBadge key="s" status={e.status} />, new Date(e.created_at).toLocaleString(), e.file_url ? <a key="d" className="text-primary underline" href={e.file_url}>Download</a> : '—'])} />
    </div>
  );
}

export function StatementsPage() {
  useTitle('Financial statements');
  const [kind, setKind] = useState('receipts_payments');
  const [p, setP] = useState({ from: yearAgo(), to: today() });
  const q = useQ(['stmt', kind, p], () => acc.statement(kind, p));
  const s = (q.data as Any)?.data;
  const file = (format: 'pdf' | 'xlsx') => acc.statementFile(kind, { ...p, format }).then((b) => openBlob(b, `${kind}.${format}`)).catch(fail);
  return (
    <div className="space-y-4">
      <PageHeader title="Financial statements" description="Receipts & payments, income & expenditure and balance summary." actions={<div className="flex gap-1"><Button variant="outline" onClick={() => file('pdf')}>PDF</Button><Button variant="outline" onClick={() => file('xlsx')}>XLSX</Button></div>} />
      <div className="flex flex-wrap gap-2">{['receipts_payments', 'income_expenditure', 'balance_summary'].map((k) => <Button key={k} size="sm" variant={kind === k ? 'default' : 'outline'} onClick={() => setKind(k)}>{k.split('_').join(' ')}</Button>)}<Period v={p} onChange={setP} /></div>
      {s && <>{s.sections.map((sec: Any) => <Section key={sec.title} title={sec.title}><SimpleTable head={['', 'Amount']} rows={sec.rows.map((r: Any) => [r.label, rupees(r.amount_paise)])} /></Section>)}
        <div className="flex flex-wrap gap-2">{Object.entries(s.totals).map(([k, v]) => <Badge key={k} variant="outline">{k.replace('_paise', '').split('_').join(' ')}: {rupees(v as number)}</Badge>)}</div></>}
    </div>
  );
}

export function PeriodsPage() {
  useTitle('Periods');
  const years = useQ(['years'], () => acc.years());
  const gaps = useQ(['gaps'], () => acc.gaps());
  const [upto, setUpto] = useState(today());
  const [year, setYear] = useState('');
  const [cf, setCf] = useState('none');
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Periods & year close" description="Lock the books up to a date; close a year (budgets frozen, optional carry-forward)." />
      <Section title="Close the books"><div className="flex gap-2"><Input type="date" className="w-44" value={upto} onChange={(e) => setUpto(e.target.value)} /><Button onClick={() => run.mutate(() => acc.closePeriod(upto), { onSuccess: () => toast.success(`Closed up to ${upto}`), onError: fail })}>Close period</Button></div></Section>
      <Section title="Year close"><div className="flex flex-wrap gap-2"><select className={sel} value={year} onChange={(e) => setYear(e.target.value)}><option value="">Year…</option>{list(years.data).map((y: Any) => <option key={y.id} value={y.id}>{y.name ?? y.code}</option>)}</select><select className={sel} value={cf} onChange={(e) => setCf(e.target.value)}><option value="none">no carry-forward</option><option value="unspent">carry unspent forward</option></select><Button disabled={!year} onClick={() => run.mutate(() => acc.closeYear({ academic_year_id: year, carry_forward: cf }), { onSuccess: () => toast.success('Year close queued'), onError: fail })}>Close year</Button></div></Section>
      <Section title={`Posting gaps (${list(gaps.data).length})`} action={<Button size="sm" variant="outline" onClick={() => run.mutate(() => acc.replay({ from: yearAgo(), to: today() }), { onSuccess: () => toast.success('Replay queued'), onError: fail })}>Replay last 12 months</Button>}><SimpleTable head={['Source', 'Reference', 'Id']} rows={list(gaps.data).slice(0, 100).map((g: Any) => [g.source_type, g.ref, g.source_id])} /></Section>
    </div>
  );
}

// ---- faculty PI grant page ---------------------------------------------------------------------------------------------------------------
export function FacultyGrantsPage() {
  useTitle('My grants');
  const q = useQ(['grants'], () => acc.grants());
  const [exp, setExp] = useState<Any | null>(null);
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="My grants" description="Balance per head; record expenses with the receipt; download the utilisation certificate." />
      {list(q.data).map((g: Any) => (
        <Section key={g.id} title={`${g.name} · ${g.funding_agency ?? ''}`} action={<div className="flex gap-1"><Button size="sm" variant="outline" onClick={() => setExp({ g, head: g.budget_heads[0]?.name, amount: '', description: '', document_url: '' })}>Add expense</Button><Button size="sm" variant="ghost" onClick={() => acc.uc(g.id).then((b) => openBlob(b, `UC-${g.name}.pdf`)).catch(fail)}>UC</Button></div>}>
          <p className="text-sm">Received {rupees(g.received_paise)} · utilised {rupees(g.utilised_paise)} · balance {rupees(g.balance_paise)}</p>
          <SimpleTable head={['Head', 'Allocated', 'Available']} rows={g.budget_heads.map((h: Any) => [h.name, rupees(h.allocated_paise), rupees(h.available_paise)])} />
        </Section>
      ))}
      {list(q.data).length === 0 && <p className="text-sm text-muted-foreground">No grant ledgers name you as PI.</p>}
      <Modal open={!!exp} onOpenChange={(o) => !o && setExp(null)} title="Grant expense" footer={<Button disabled={!exp?.amount} onClick={() => run.mutate(() => acc.grantExpense(exp.g.id, { head: exp.head, amount_paise: Math.round(Number(exp.amount) * 100), spent_on: today(), description: exp.description || exp.head, document_url: exp.document_url || null }), { onSuccess: () => { toast.success('Recorded'); setExp(null); }, onError: fail })}>Save</Button>}>
        {exp && <div className="space-y-2 text-sm"><select className={`${sel} w-full`} value={exp.head} onChange={(e) => setExp({ ...exp, head: e.target.value })}>{exp.g.budget_heads.map((h: Any) => <option key={h.name}>{h.name}</option>)}</select><Input type="number" placeholder="Amount ₹" value={exp.amount} onChange={(e) => setExp({ ...exp, amount: e.target.value })} /><Input placeholder="Description" value={exp.description} onChange={(e) => setExp({ ...exp, description: e.target.value })} /><Input placeholder="Receipt URL" value={exp.document_url} onChange={(e) => setExp({ ...exp, document_url: e.target.value })} /></div>}
      </Modal>
    </div>
  );
}
